# app.py
import re
import requests
import streamlit as st
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from geopy.geocoders import Nominatim

SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["soc", "phh2o", "sand", "silt", "clay", "bdod", "ocs"]
PREFERRED_DEPTHS = [(0.0, 5.0), (0.0, 30.0), (0.0, 15.0)]

_depth_label_re = re.compile(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)")

# Default values if SoilGrids returns null (example realistic defaults)
DEFAULT_VALUES = {
    "soc": 15.0,      # g/kg
    "phh2o": 6.5,     # -
    "sand": 30.0,     # %
    "silt": 40.0,     # %
    "clay": 30.0,     # %
    "bdod": 1.3,      # kg/dm³
    "ocs": 4.0        # kg/m²
}

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

def fetch_property_for_point(lat: float, lon: float, prop: str) -> Tuple[Optional[float], Optional[str]]:
    # Try primary point
    val, unit = _fetch_value(lat, lon, prop)
    if val is not None:
        return val, unit
    # Option A: try nearby points with small delta
    delta = [0.01, -0.01, 0.02, -0.02]
    for dlat in delta:
        for dlon in delta:
            val, unit = _fetch_value(lat + dlat, lon + dlon, prop)
            if val is not None:
                return val, unit
    # Option B: fallback to default
    return DEFAULT_VALUES[prop], ""

def _fetch_value(lat: float, lon: float, prop: str) -> Tuple[Optional[float], Optional[str]]:
    params = {"lat": lat, "lon": lon, "property": prop}
    try:
        r = requests.get(SOILGRIDS_API, params=params, timeout=25)
    except requests.RequestException:
        return None, None

    if r.status_code != 200:
        return None, None

    try:
        data = r.json()
    except Exception:
        return None, None

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
        return None, None

    depths = layer_obj.get("depths") or []
    unit = _extract_unit(layer_obj)
    d_factor = layer_obj.get("unit_measure", {}).get("d_factor", 1)

    for d in depths:
        vals = d.get("values") or {}
        numeric = _extract_numeric_from_values(vals, d_factor=d_factor)
        if numeric is not None:
            return numeric, unit
    return None, unit

def fetch_soil_data_all(lat: float, lon: float) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in PROPERTIES:
        val, unit = fetch_property_for_point(lat, lon, p)
        out[p] = {"value": val, "unit": unit}
    return out

def get_location_name(lat: float, lon: float) -> str:
    try:
        geolocator = Nominatim(user_agent="soil_app")
        location = geolocator.reverse((lat, lon), language="en")
        if location:
            return location.address
        return "Unknown Location"
    except:
        return "Unknown Location"

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="SoilGrids Explorer", layout="centered", initial_sidebar_state="collapsed")
st.title("SoilGrids Explorer — lat/lon → soil properties")
st.markdown(
    "Enter latitude & longitude and the app will query ISRIC SoilGrids for common soil properties "
    "(SOC, pH, sand/silt/clay, bulk density, OCS)."
)

with st.expander("Which properties are requested?"):
    st.write(", ".join(PROPERTIES))
    st.caption("We attempt all available depths and return the first non-NULL value, scaled if needed. If data is missing, nearby points or defaults are used.")

col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude", value=31.1471, format="%.6f")  # Default = Mumbai
with col2:
    lon = st.number_input("Longitude", value=75.3412, format="%.6f")

if st.button("Get Soil Data"):
    with st.spinner("Querying SoilGrids..."):
        out = fetch_soil_data_all(lat, lon)
        location_name = get_location_name(lat, lon)

    rows = []
    for prop in PROPERTIES:
        rec = out.get(prop, {})
        val = rec.get("value")
        unit = rec.get("unit") or ""
        display_val = f"{val:.4g}" if val is not None else "No data"
        rows.append({"Property": prop.upper(), "Value": display_val, "Unit": unit})

    df = pd.DataFrame(rows)
    st.subheader(f"Soil Data for {location_name}")
    st.table(df.set_index("Property"))

    try:
        st.subheader("Location preview")
        st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
    except Exception:
        pass

    st.caption("⚠️ Some values are defaults or estimated because SoilGrids data is missing in this region.")

# Permanent footer
st.markdown("---")
st.markdown("💡 Made with ❤️ by **Mayank Kumar Sharma**")
