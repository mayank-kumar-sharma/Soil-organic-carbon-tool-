# app.py
import re
import requests
import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["soc", "phh2o", "sand", "silt", "clay", "bdod", "ocs"]
PREFERRED_DEPTHS = [(0.0, 5.0), (0.0, 30.0), (0.0, 15.0)]

_depth_label_re = re.compile(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)")

def _try_parse_depth_from_label(label: str) -> Optional[Tuple[float, float]]:
    if not label or not isinstance(label, str):
        return None
    m = _depth_label_re.search(label)
    if m:
        try:
            top = float(m.group(1))
            bottom = float(m.group(2))
            return (top, bottom)
        except Exception:
            return None
    return None

def _get_top_bottom_from_range(d: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    rng = d.get("range") or {}
    top = rng.get("top") or rng.get("top_depth")
    bottom = rng.get("bottom") or rng.get("bottom_depth")
    try:
        if top is not None and bottom is not None:
            return (float(top), float(bottom))
    except Exception:
        return None
    return None

def _extract_numeric_from_values(values: Dict[str, Any], d_factor: float = 1) -> Optional[float]:
    if not isinstance(values, dict):
        return None
    prefer = ["mean", "Q0.5", "median", "Q0.05", "Q0.95"]
    for k in prefer:
        v = values.get(k)
        if v is not None:
            try:
                return float(v) / d_factor
            except Exception:
                continue
    for k, v in values.items():
        if v is None:
            continue
        try:
            return float(v) / d_factor
        except Exception:
            continue
    return None

def _extract_unit(layer: Dict[str, Any]) -> Optional[str]:
    um = layer.get("unit_measure") or {}
    unit = um.get("target_units") or um.get("mapped_units") or um.get("unit")
    return unit

def fetch_property_for_point(lat: float, lon: float, prop: str) -> Tuple[Optional[float], Optional[str], Optional[Dict[str, Any]]]:
    params = {"lat": lat, "lon": lon, "property": prop}
    try:
        r = requests.get(SOILGRIDS_API, params=params, timeout=25)
    except requests.RequestException as e:
        return None, None, {"error": str(e)}

    if r.status_code != 200:
        return None, None, {"error": f"status {r.status_code}", "text": r.text}

    try:
        data = r.json()
    except Exception as e:
        return None, None, {"error": f"invalid json: {e}"}

    layers = data.get("properties", {}).get("layers")
    layer_obj = None
    if isinstance(layers, dict):
        layer_obj = layers.get(prop)
    elif isinstance(layers, list):
        for item in layers:
            if isinstance(item, dict) and item.get("name") == prop:
                layer_obj = item
                break

    if not layer_obj:
        return None, None, data

    depths = layer_obj.get("depths") or []
    unit = _extract_unit(layer_obj)
    d_factor = layer_obj.get("unit_measure", {}).get("d_factor", 1)

    # Return first non-null numeric value across all depths with proper scaling
    for d in depths:
        vals = d.get("values") or {}
        numeric = _extract_numeric_from_values(vals, d_factor=d_factor)
        if numeric is not None:
            return numeric, unit, layer_obj

    return None, unit, layer_obj

def fetch_soil_data_all(lat: float, lon: float) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in PROPERTIES:
        val, unit, raw = fetch_property_for_point(lat, lon, p)
        out[p] = {"value": val, "unit": unit, "raw": raw}
    return out, None

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="SoilGrids Explorer", layout="centered", initial_sidebar_state="collapsed")
st.title("SoilGrids Explorer — lat/lon → soil properties")
st.markdown(
    "Enter latitude & longitude and the app will query ISRIC SoilGrids for common soil properties "
    "(SOC, pH, sand/silt/clay, bulk density, OCS). If a property is missing it will show 'No data'."
)

with st.expander("Which properties are requested?"):
    st.write(", ".join(PROPERTIES))
    st.caption("We attempt all available depths and return the first non-NULL value, applying unit scaling if needed.")

col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude", value=12.971600, format="%.6f")
with col2:
    lon = st.number_input("Longitude", value=77.594600, format="%.6f")

if st.button("Get Soil Data"):
    with st.spinner("Querying SoilGrids (one request per property)..."):
        out, err = fetch_soil_data_all(lat, lon)

    rows = []
    for prop in PROPERTIES:
        rec = out.get(prop, {})
        val = rec.get("value")
        unit = rec.get("unit") or ""
        display_val = f"{val:.4g}" if val is not None else "No data"
        rows.append({"Property": prop.upper(), "Value": display_val, "Unit": unit})

    df = pd.DataFrame(rows)
    st.subheader("Results (first available value across all depths, scaled)")
    st.table(df.set_index("Property"))

    try:
        st.subheader("Location preview")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
    except Exception:
        pass

    with st.expander("Raw property JSON (per property) — useful for debugging"):
        for prop in PROPERTIES:
            st.markdown(f"**{prop.upper()}**")
            st.json(out[prop].get("raw"))

