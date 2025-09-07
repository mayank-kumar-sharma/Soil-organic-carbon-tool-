# app.py
import re
import requests
import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"
# Properties we care about
PROPERTIES = ["soc", "phh2o", "sand", "silt", "clay", "bdod", "ocs"]  # include ocs/ocd if present
# Preferred depth targets (topsoil first, then fallback)
PREFERRED_DEPTHS = [(0.0, 5.0), (0.0, 30.0), (0.0, 15.0)]

# Utility: parse numeric from label like "0-5cm" or "0–5 cm"
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
    # range may have keys like 'top'/'bottom' or 'top_depth'/'bottom_depth'
    rng = d.get("range") or {}
    top = rng.get("top")
    bottom = rng.get("bottom")
    if top is None or bottom is None:
        top = rng.get("top_depth") if rng.get("top_depth") is not None else top
        bottom = rng.get("bottom_depth") if rng.get("bottom_depth") is not None else bottom
    try:
        if top is not None and bottom is not None:
            return (float(top), float(bottom))
    except Exception:
        return None
    return None


def _pick_depth_entry(depths: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Given the 'depths' list from a layer, pick the entry that best matches preferred depths.
    If none match exactly, return the first entry as fallback.
    """
    if not depths:
        return None

    # Try to match any preferred depth pair
    for pref_top, pref_bottom in PREFERRED_DEPTHS:
        for d in depths:
            # 1) try range keys
            tb = _get_top_bottom_from_range(d)
            if tb and abs(tb[0] - pref_top) < 1e-6 and abs(tb[1] - pref_bottom) < 1e-6:
                return d
            # 2) try label parsing
            lbl = d.get("label") or d.get("depth_label") or ""
            tb2 = _try_parse_depth_from_label(lbl)
            if tb2 and abs(tb2[0] - pref_top) < 1e-6 and abs(tb2[1] - pref_bottom) < 1e-6:
                return d

    # If no exact preferred match, try to return the topmost depth (where top is smallest)
    try:
        sorted_depths = sorted(depths, key=lambda x: _get_top_bottom_from_range(x)[0] if _get_top_bottom_from_range(x) else 9999.0)
        return sorted_depths[0]
    except Exception:
        return depths[0]


def _extract_numeric_from_values(values: Dict[str, Any]) -> Optional[float]:
    """Given 'values' dict, try to return a numeric (prefer 'mean', then common quantiles)."""
    if not isinstance(values, dict):
        return None
    # prefer keys in this order
    prefer = ["mean", "Q0.5", "median", "Q0.05", "Q0.95"]
    for k in prefer:
        v = values.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                continue
    # fallback: first numeric entry
    for k, v in values.items():
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _extract_unit(layer: Dict[str, Any]) -> Optional[str]:
    um = layer.get("unit_measure") or {}
    # unit_measure often contains 'mapped_units' or 'target_units'
    unit = um.get("mapped_units") or um.get("target_units") or um.get("unit")
    return unit


def fetch_property_for_point(lat: float, lon: float, prop: str) -> Tuple[Optional[float], Optional[str], Optional[Dict[str, Any]]]:
    """
    Query SoilGrids for a single property at lat/lon.
    Returns (value, unit, raw_layer_dict_or_none)
    """
    params = {
        "lat": lat,
        "lon": lon,
        "property": prop,
        # depth_intervals parameter sometimes accepted; we still parse returned depths robustly
        "depth_intervals": "0-5",
        # requesting 'value' isn't always necessary; safe to include
        "value": "mean",
    }

    try:
        r = requests.get(SOILGRIDS_API, params=params, timeout=25)
    except requests.RequestException as e:
        return None, None, {"error": str(e)}

    if r.status_code != 200:
        # return None but include raw text for debugging
        return None, None, {"error": f"status {r.status_code}", "text": r.text}

    try:
        data = r.json()
    except Exception as e:
        return None, None, {"error": f"invalid json: {e}"}

    # Layers can be dict or list. Normalize to dict keyed by name.
    layers = data.get("properties", {}).get("layers")
    layer_obj = None
    if isinstance(layers, dict):
        layer_obj = layers.get(prop)
    elif isinstance(layers, list):
        for item in layers:
            if isinstance(item, dict) and item.get("name") == prop:
                layer_obj = item
                break
    else:
        # unexpected structure
        layer_obj = None

    if not layer_obj:
        # no layer found, return raw for debugging
        return None, None, data

    depths = layer_obj.get("depths", []) or []
    if not depths:
        return None, _extract_unit(layer_obj) if isinstance(layer_obj, dict) else None, layer_obj

    chosen = _pick_depth_entry(depths)
    if not chosen:
        return None, _extract_unit(layer_obj) if isinstance(layer_obj, dict) else None, layer_obj

    values = chosen.get("values", {}) or {}
    numeric = _extract_numeric_from_values(values)
    unit = _extract_unit(layer_obj)
    return numeric, unit, layer_obj


def fetch_soil_data_all(lat: float, lon: float) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """
    Fetch all requested properties for a point.
    Returns a dict: {prop: {"value": float|None, "unit": str|None, "raw": {...}}}
    """
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
    "(SOC, pH, sand/silt/clay, bulk density). If a property is missing it will show 'No data'."
)

with st.expander("Which properties are requested?"):
    st.write(", ".join(PROPERTIES))
    st.caption("We attempt the 0–5 cm topsoil layer first and fall back to other top layers if needed.")

col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude", value=12.971600, format="%.6f")
with col2:
    lon = st.number_input("Longitude", value=77.594600, format="%.6f")

if st.button("Get Soil Data"):
    with st.spinner("Querying SoilGrids (one request per property)..."):
        out, err = fetch_soil_data_all(lat, lon)

    # Build pandas DataFrame for display
    rows = []
    for prop in PROPERTIES:
        rec = out.get(prop, {})
        val = rec.get("value")
        unit = rec.get("unit") or ""
        if val is None:
            display_val = "No data"
        else:
            # Format numeric with reasonable precision
            display_val = f"{val:.4g} {unit}".strip()
        rows.append({"Property": prop.upper(), "Value": display_val, "Unit": unit})

    df = pd.DataFrame(rows)
    st.subheader("Results (topmost available / preferred topsoil depth)")
    st.table(df.set_index("Property"))

    # Map preview
    try:
        st.subheader("Location preview")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
    except Exception:
        pass

    with st.expander("Raw property JSON (per property) — useful for debugging"):
        # show raw JSON for each property
        for prop in PROPERTIES:
            st.markdown(f"**{prop.upper()}**")
            st.json(out[prop].get("raw"))
