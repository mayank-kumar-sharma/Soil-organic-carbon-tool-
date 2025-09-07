# app.py
import streamlit as st
import requests
import pandas as pd
from typing import Dict, Any, Tuple, Optional

# --------------------------
# Config / constants
# --------------------------
SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"
# properties we want (common SoilGrids codes)
PROPERTIES = ["soc", "phh2o", "sand", "silt", "clay", "bdod"]
# depth interval to query (0-5 cm surface layer)
DEPTH_INTERVAL = "0-5"
# which statistic / value to request (mean is most common)
VALUE_STAT = "mean"


# --------------------------
# Helper functions
# --------------------------
def _extract_mean_from_layer(layer: Dict[str, Any]) -> Optional[float]:
    """
    Given a 'layer' object from SoilGrids JSON, try to find the requested depth (0-5)
    and return the 'mean' or the first non-null numeric value in values{}.
    """
    if not layer:
        return None

    depths = layer.get("depths", [])
    if not depths:
        return None

    # Try to find an exact match for 0-5 depth by range if available
    target_depth = None
    for d in depths:
        rng = d.get("range") or {}
        top = rng.get("top")
        bottom = rng.get("bottom")
        # Accept integers or floats
        if top is not None and bottom is not None:
            try:
                if float(top) == 0.0 and float(bottom) == 5.0:
                    target_depth = d
                    break
            except Exception:
                pass

    # If exact match not found, use the first depth entry
    if target_depth is None:
        target_depth = depths[0]

    values = target_depth.get("values", {}) if target_depth else {}
    # Prefer 'mean' if present
    if isinstance(values, dict):
        if "mean" in values and values["mean"] is not None:
            return float(values["mean"])
        # otherwise pick first non-null numeric value
        for k, v in values.items():
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
    return None


def fetch_soil_data(lat: float, lon: float) -> Tuple[Dict[str, Optional[float]], Optional[Dict[str, Any]], Optional[str]]:
    """
    Try to fetch multiple properties in a single SoilGrids request first.
    If that fails or returns partial data, fall back to one-by-one requests.
    Returns: (results_dict, raw_json_if_available, error_message_if_any)
    """
    # Prepare results dict with None defaults
    results: Dict[str, Optional[float]] = {p: None for p in PROPERTIES}

    # First try a multi-property request (properties param)
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
        # If multi-property request failed, we'll fall back to per-property calls
        # but keep the error message to report if everything fails
        multi_error = f"Multi-property request failed with status {r.status_code}"
        # continue to fallback below
    else:
        try:
            data = r.json()
        except ValueError:
            return results, None, "Invalid JSON from SoilGrids (multi-property request)."

        layers = data.get("properties", {}).get("layers", {})
        if layers:
            # Attempt to parse each requested property
            for prop in PROPERTIES:
                layer = layers.get(prop)
                val = _extract_mean_from_layer(layer)
                results[prop] = val
            return results, data, None
        else:
            # No layers returned — fall back to per-property requests below
            multi_error = "Multi-property request returned no layers."

    # Fallback: query each property individually
    raw = {"properties": {"layers": {}}}
    for prop in PROPERTIES:
        params_single = {
            "lat": lat,
            "lon": lon,
            "property": prop,
            "depth_intervals": DEPTH_INTERVAL,
            "value": VALUE_STAT,
        }
        try:
            r2 = requests.get(SOILGRIDS_API, params=params_single, timeout=20)
        except requests.RequestException as e:
            return results, None, f"Request failed for property {prop}: {e}"

        if r2.status_code != 200:
            # leave this property as None but continue
            raw["properties"]["layers"][prop] = {}
            continue

        try:
            d2 = r2.json()
        except ValueError:
            raw["properties"]["layers"][prop] = {}
            continue

        # Attempt to extract
        layer = d2.get("properties", {}).get("layers", {}).get(prop)
        val = _extract_mean_from_layer(layer)
        results[prop] = val
        # store raw for debugging
        raw["properties"]["layers"][prop] = layer or {}

    return results, raw, None


# --------------------------
# Streamlit UI
# --------------------------
st.set_page_config(page_title="Soil Data Explorer", layout="centered", initial_sidebar_state="auto")

st.title("🌍 Soil Data Explorer (SoilGrids)")
st.markdown(
    "Enter a latitude and longitude (anywhere in the world). The app will query SoilGrids "
    "and return soil properties for the 0–5 cm top layer where available."
)

with st.sidebar:
    st.write("Query settings")
    st.write(f"Depth interval: {DEPTH_INTERVAL} cm (topsoil)")
    st.write(f"Requested properties: {', '.join(PROPERTIES)}")
    st.write("Data source: ISRIC SoilGrids (rest.isric.org)")

# Inputs
col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude", value=12.971600, format="%.6f")
with col2:
    lon = st.number_input("Longitude", value=77.594600, format="%.6f")

st.markdown("Click **Get Soil Data** to query SoilGrids for this point.")
if st.button("Get Soil Data"):
    with st.spinner("Querying SoilGrids..."):
        results, raw_json, error = fetch_soil_data(lat, lon)

    if error:
        st.error(f"Error: {error}")
    else:
        # If all values are None, show a helpful message
        if all(v is None for v in results.values()):
            st.warning(
                "SoilGrids returned no data for these properties at this exact coordinate. "
                "This can happen for water bodies, certain urban locations, or if the grid cell is unmapped. "
                "Try a nearby coordinate or check the raw JSON below."
            )

        # Prepare display dataframe (replace None with 'No data')
        df = pd.DataFrame.from_dict(results, orient="index", columns=["Value"])
        df.index = df.index.str.upper()
        display_df = df.fillna("No data")
        st.subheader("Soil properties (0–5 cm)")
        st.table(display_df)

        # Show map with point
        try:
            st.subheader("Location preview")
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
        except Exception:
            pass

        with st.expander("Raw API response (for debugging)"):
            if raw_json:
                st.json(raw_json)
            else:
                st.write("No raw JSON available for this query.")
