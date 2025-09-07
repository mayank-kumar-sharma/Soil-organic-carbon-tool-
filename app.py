import streamlit as st
import requests
import pandas as pd

# --------------------------
# SoilGrids API endpoint
# --------------------------
SOILGRIDS_API = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# --------------------------
# Function to fetch soil data
# --------------------------
def fetch_soil_data(lat: float, lon: float):
    try:
        params = {
            "lat": lat,
            "lon": lon,
            "property": ["soc", "phh2o", "sand", "silt", "clay", "bdod"]
        }
        response = requests.get(SOILGRIDS_API, params=params, timeout=20)

        if response.status_code != 200:
            return None, f"Error {response.status_code}: {response.text}"

        data = response.json()
        results = {}

        # Extract topsoil layer (0-5 cm) values
        for prop in params["property"]:
            try:
                values = data["properties"]["layers"][prop]["depths"][0]["values"]
                results[prop] = values.get("mean", None)
            except Exception:
                results[prop] = None

        return results, None

    except Exception as e:
        return None, str(e)

# --------------------------
# Streamlit App
# --------------------------
st.set_page_config(page_title="Soil Data Explorer", layout="centered")

st.title("🌍 Soil Data Explorer (Powered by SoilGrids API)")
st.write("Enter a latitude and longitude to get soil properties (SOC, pH, Sand, Silt, Clay, Bulk Density).")

# User inputs
lat = st.number_input("Latitude", value=12.9716, format="%.6f")
lon = st.number_input("Longitude", value=77.5946, format="%.6f")

if st.button("Get Soil Data"):
    with st.spinner("Fetching soil data..."):
        results, error = fetch_soil_data(lat, lon)

        if error:
            st.error(f"Failed to fetch data: {error}")
        elif results:
            st.success(f"Soil data for location ({lat}, {lon}):")

            df = pd.DataFrame.from_dict(results, orient="index", columns=["Value"])
            df.index = df.index.str.upper()
            st.table(df)

            with st.expander("See raw JSON response"):
                st.json(results)
        else:
            st.warning("No data found for this location.")
