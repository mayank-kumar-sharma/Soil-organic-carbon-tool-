# app.py
import streamlit as st
import requests
import pandas as pd
from typing import Dict, Any, Tuple, Optional

SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["soc", "phh2o", "sand", "silt", "clay", "bdod"]
DEPTH_INTERVAL = "0-5"
VALUE_STAT = "mean"


def _extract_mean_from_layer(layer: Dict[str, Any]) -> Optional[float]:
    """Extract mean value for depth 0-5cm if available."""
    if not layer:
        return None
    depths = layer.get("depths", [])
    if not depths:
        return None

    target_depth = None
    for d in depths:
        rng = d.get("range") or {}
        if str(rng.get("top")) in ["0", "0.0"] and str(rng.get("bottom")) in ["5", "5.0"]:
            target_depth = d
            break
    if target_depth is None:
        target_depth = depths[0]

    values = target_depth.get("values", {})
    if isinstance(values, dict):
        if "mean" in values and values["mean"] is not None:
            return float(values["mean"])
        for v in values.values():
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
    return None


def fetch_soil_data(lat: float, lon: float) -> Tuple[Dict[str, Optional[float]], Optional[Dict[str, Any]], Optional[str]]:
    results: Dict[str, Optional[float]] = {p: None for p in PROPERTIES}

    params_multi = {
        "lat": lat,
        "lon": lon,
        "properties": ",".join(PROPERTIES),
        "depth_intervals": DEPTH_INTERVAL,
        "value": VALUE_STAT,
    }

    try:
        r = requests.get(SOILGRIDS_API, params=params_multi, timeout=25)
    except requests.RequestException as e:
        return results, None, f"Request failed: {e}"

    if r.status_code != 200:
        return results, None, f"Error {r.status_code}: {r.text}"

    try:
        data = r.json()
    except ValueError:
        return results, None, "Invalid JSON returned."

    # Handle both dict and list cases for "layers"
    layers = data.get("properties", {}).get("layers", {})
    if isinstance(layers, list):
        # Convert list → dict {name: layer}
        layers_dict = {}
        for item in layers:
            if isinstance(item, dict) and "name" in item:
                layers_dict[item["name"]] = item
        layers = layers_dict

    for prop in PROPERTIES:
        layer = layers.get(prop) if isinstance(layers, dict) else None
        val = _extract_mean_from_layer(layer)
        results[prop] = val

    return results, data, None


# --------------------------
# Streamlit UI
# --------------------------
st.set_page_config(page_title="Soil Data Explorer", layout="centered")

st.title("🌍 Soil Data Explorer (SoilGrids)")
st.write("Enter a latitude and longitude to get soil properties (SOC, pH, Sand, Silt, Clay, Bulk Density).")

lat = st.number_input("Latitude", value=12.9716, format="%.6f")
lon = st.number_input("Longitude", value=77.5946, format="%.6f")

if st.button("Get Soil Data"):
    with st.spinner("Fetching soil data..."):
        results, raw_json, error = fetch_soil_data(lat, lon)

    if error:
        st.error(f"Failed to fetch data: {error}")
    else:
        df = pd.DataFrame.from_dict(results, orient="index", columns=["Value"])
        df.index = df.index.str.upper()
        st.table(df.fillna("No data"))

        with st.expander("See raw JSON response"):
            st.json(raw_json)
