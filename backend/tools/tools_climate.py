"""
Climate Risk Tools - Assess environmental risks for specific coordinates

Uses Open-Meteo APIs (free, no API key required):
- Historical weather archive for heat/flood risk analysis
- Elevation API for terrain data

Usage:
    from tools_climate import fetch_weather_risk, fetch_elevation
    
    # Get climate risk scores for a location
    risk = fetch_weather_risk(lat=41.38, lon=2.17)  # Barcelona
    print(risk)
    # {'heat_risk_score': 2.5, 'flood_risk_score': 0.8, 'avg_temp': 18.2}
    
    # Get elevation
    elevation = fetch_elevation(lat=41.38, lon=2.17)
    print(elevation)  # 12 meters

System Prompt Context:
    Use these tools to assess environmental risks for specific coordinates.
    Heat risk indicates percentage of days exceeding 35°C over 3 years.
    Flood risk indicates percentage of days with heavy precipitation (>50mm).
"""

import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API endpoints
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

# Risk thresholds
HEAT_THRESHOLD_CELSIUS = 35.0  # Days above this are "heat risk" days
HEAVY_RAIN_THRESHOLD_MM = 50.0  # Days above this are "flood risk" days


def fetch_weather_risk(lat: float, lon: float, years: int = 3) -> dict:
    """
    Fetch historical weather data and calculate heat/flood risk scores.
    
    Uses Open-Meteo Archive API to analyze the last N years of weather data.
    
    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)
        years: Number of years of historical data to analyze (default 3)
        
    Returns:
        Dictionary with risk scores:
        {
            'heat_risk_score': float,    # % of days > 35°C
            'flood_risk_score': float,   # % of days with > 50mm rain
            'avg_temp': float,           # Average daily max temperature
            'max_temp': float,           # Highest recorded temperature
            'total_heavy_rain_days': int,# Count of heavy rain days
            'total_heat_days': int,      # Count of extreme heat days
            'analysis_days': int,        # Total days analyzed
            'period_start': str,         # Analysis start date
            'period_end': str,           # Analysis end date
        }
        
    Raises:
        requests.RequestException: If API request fails
        ValueError: If coordinates are invalid
    """
    # Validate coordinates
    if not (-90 <= lat <= 90):
        raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90.")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180.")
    
    # Calculate date range (last N years)
    end_date = datetime.now() - timedelta(days=5)  # API has ~5 day delay
    start_date = end_date - timedelta(days=365 * years)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    logger.info(f"Fetching weather data for ({lat}, {lon}) from {start_str} to {end_str}")
    
    # Query Open-Meteo Archive API
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_str,
        "end_date": end_str,
        "daily": "temperature_2m_max,precipitation_sum",
        "timezone": "auto"
    }
    
    response = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    
    # Check for API errors
    if "error" in data:
        raise ValueError(f"API error: {data.get('reason', 'Unknown error')}")
    
    # Extract daily data
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    temps = daily.get("temperature_2m_max", [])
    precip = daily.get("precipitation_sum", [])
    
    if not dates:
        raise ValueError("No weather data returned for this location")
    
    logger.info(f"Received {len(dates)} days of data")
    
    # Create DataFrame for analysis
    df = pd.DataFrame({
        "date": pd.to_datetime(dates),
        "temp_max": temps,
        "precipitation": precip
    })
    
    # Handle missing values
    df["temp_max"] = pd.to_numeric(df["temp_max"], errors="coerce")
    df["precipitation"] = pd.to_numeric(df["precipitation"], errors="coerce")
    
    # Calculate statistics
    total_days = len(df)
    valid_temp_days = df["temp_max"].notna().sum()
    valid_precip_days = df["precipitation"].notna().sum()
    
    # Heat risk: days above threshold
    heat_days = (df["temp_max"] > HEAT_THRESHOLD_CELSIUS).sum()
    heat_risk_score = (heat_days / valid_temp_days * 100) if valid_temp_days > 0 else 0.0
    
    # Flood risk: days with heavy precipitation
    heavy_rain_days = (df["precipitation"] > HEAVY_RAIN_THRESHOLD_MM).sum()
    flood_risk_score = (heavy_rain_days / valid_precip_days * 100) if valid_precip_days > 0 else 0.0
    
    # Average and max temperature
    avg_temp = df["temp_max"].mean()
    max_temp = df["temp_max"].max()
    
    # Total precipitation
    total_precip = df["precipitation"].sum()
    
    result = {
        "heat_risk_score": round(heat_risk_score, 2),
        "flood_risk_score": round(flood_risk_score, 2),
        "avg_temp": round(avg_temp, 1) if pd.notna(avg_temp) else None,
        "max_temp": round(max_temp, 1) if pd.notna(max_temp) else None,
        "total_precipitation_mm": round(total_precip, 1) if pd.notna(total_precip) else None,
        "total_heat_days": int(heat_days),
        "total_heavy_rain_days": int(heavy_rain_days),
        "analysis_days": total_days,
        "period_start": start_str,
        "period_end": end_str,
        "thresholds": {
            "heat_celsius": HEAT_THRESHOLD_CELSIUS,
            "heavy_rain_mm": HEAVY_RAIN_THRESHOLD_MM
        }
    }
    
    logger.info(f"Heat risk: {heat_risk_score:.2f}% ({heat_days} days > {HEAT_THRESHOLD_CELSIUS}°C)")
    logger.info(f"Flood risk: {flood_risk_score:.2f}% ({heavy_rain_days} days > {HEAVY_RAIN_THRESHOLD_MM}mm)")
    
    return result


def fetch_elevation(lat: float, lon: float) -> Optional[float]:
    """
    Fetch elevation for a coordinate using Open-Meteo Elevation API.
    
    Args:
        lat: Latitude (-90 to 90)
        lon: Longitude (-180 to 180)
        
    Returns:
        Elevation in meters above sea level, or None if unavailable
        
    Raises:
        requests.RequestException: If API request fails
        ValueError: If coordinates are invalid
    """
    # Validate coordinates
    if not (-90 <= lat <= 90):
        raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90.")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180.")
    
    logger.info(f"Fetching elevation for ({lat}, {lon})")
    
    params = {
        "latitude": lat,
        "longitude": lon
    }
    
    response = requests.get(OPEN_METEO_ELEVATION_URL, params=params, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    
    # Extract elevation (returns array, we want first value)
    elevations = data.get("elevation", [])
    
    if elevations and len(elevations) > 0:
        elevation = elevations[0]
        logger.info(f"Elevation: {elevation}m")
        return elevation
    
    logger.warning("No elevation data returned")
    return None


def fetch_complete_climate_profile(lat: float, lon: float) -> dict:
    """
    Fetch a complete climate risk profile for a location.
    
    Combines weather risk analysis and elevation data.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        Complete climate profile dictionary
    """
    logger.info(f"Building complete climate profile for ({lat}, {lon})")
    
    profile = {
        "coordinates": {"lat": lat, "lon": lon},
        "weather_risk": None,
        "elevation_m": None,
        "risk_summary": None
    }
    
    # Fetch weather risk
    try:
        profile["weather_risk"] = fetch_weather_risk(lat, lon)
    except Exception as e:
        logger.error(f"Weather risk fetch failed: {e}")
        profile["weather_risk"] = {"error": str(e)}
    
    # Fetch elevation
    try:
        profile["elevation_m"] = fetch_elevation(lat, lon)
    except Exception as e:
        logger.error(f"Elevation fetch failed: {e}")
        profile["elevation_m"] = None
    
    # Generate risk summary
    weather = profile["weather_risk"]
    elevation = profile["elevation_m"]
    
    if weather and not weather.get("error"):
        heat_score = weather.get("heat_risk_score", 0)
        flood_score = weather.get("flood_risk_score", 0)
        
        # Risk level categorization
        def categorize_risk(score):
            if score < 1:
                return "Low"
            elif score < 5:
                return "Moderate"
            elif score < 10:
                return "High"
            else:
                return "Very High"
        
        profile["risk_summary"] = {
            "heat_risk_level": categorize_risk(heat_score),
            "flood_risk_level": categorize_risk(flood_score),
            "elevation_risk": "Low" if elevation and elevation > 50 else "Elevated" if elevation else "Unknown"
        }
    
    return profile


# =============================================================================
# Quick test when run directly
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🌡️  Climate Risk Tools - Test Suite")
    print("=" * 70)
    
    test_locations = [
        (41.38, 2.17, "Barcelona, Spain"),
        (25.27, 55.30, "Dubai, UAE (hot climate)"),
        (1.29, 103.85, "Singapore (tropical)"),
        (51.51, -0.13, "London, UK (temperate)"),
    ]
    
    for lat, lon, name in test_locations:
        print(f"\n📍 {name} ({lat}, {lon})")
        print("-" * 50)
        
        # Test weather risk
        try:
            risk = fetch_weather_risk(lat, lon, years=3)
            print(f"   🌡️  Heat Risk: {risk['heat_risk_score']}% ({risk['total_heat_days']} days > 35°C)")
            print(f"   🌧️  Flood Risk: {risk['flood_risk_score']}% ({risk['total_heavy_rain_days']} days > 50mm)")
            print(f"   📊 Avg Temp: {risk['avg_temp']}°C | Max: {risk['max_temp']}°C")
        except Exception as e:
            print(f"   ❌ Weather error: {e}")
        
        # Test elevation
        try:
            elevation = fetch_elevation(lat, lon)
            print(f"   ⛰️  Elevation: {elevation}m")
        except Exception as e:
            print(f"   ❌ Elevation error: {e}")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)

