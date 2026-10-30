"""
Entity Search Engine - Unified Discrete Object Search
======================================================

The "Inspector" - finds discrete objects (Things you can name/touch) regardless
of their geometry type. Returns Points, Polygons, or Lines as appropriate.

Architecture:
    Routes to appropriate backend based on `source` parameter:
    - athena: Static objects from Overture (Buildings, Shops, POIs) - FREE
    - news: Live events from GDELT (Protests, Floods, Fires) - FREE
    - hdx: Humanitarian infra from HDX (Camps, Hospitals, Ports) - FREE
    - google: Reviews/Ratings from ScrapingDog - PAID

The Geometry Normalizer:
    Inspects results and returns appropriate LayerData type:
    - Point geometry → geojson_point + symbol style
    - Polygon geometry → geojson_poly + fill style
    - LineString → geojson_line + line style

Usage:
    from tools.tools_search import search_entities
    
    # Search for coffee shops (FREE)
    result = search_entities(bbox, "coffee shops", source="athena")
    
    # Search for protests (FREE)
    result = search_entities(bbox, "protests", source="news")
    
    # Search with reviews (PAID)
    result = search_entities(bbox, "best rated cafes", source="google", city="Tokyo")
"""

import logging
from typing import List, Dict, Any, Literal, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Schema imports
try:
    from ..schema import LayerData, VizConfig
except ImportError:
    from schema import LayerData, VizConfig

# Backend imports
try:
    from .tools_athena import fetch_features_sql, get_athena_engine
except ImportError:
    fetch_features_sql = None
    get_athena_engine = None

try:
    from .tools_news import fetch_visual_risk
except ImportError:
    fetch_visual_risk = None

try:
    from .tools_hdx import fetch_hdx_spatial_data
except ImportError:
    fetch_hdx_spatial_data = None

try:
    from .tools_scraper import search_places as google_search
except ImportError:
    google_search = None


# =============================================================================
# GEOMETRY DETECTION
# =============================================================================

def _detect_geometry_type(features: List[Dict]) -> str:
    """Detect dominant geometry type from features."""
    if not features:
        return "Point"
    
    type_counts = {"Point": 0, "Polygon": 0, "LineString": 0, "MultiPolygon": 0}
    
    for f in features[:20]:  # Sample first 20
        geom = f.get("geometry", {})
        gtype = geom.get("type", "Point")
        if gtype in type_counts:
            type_counts[gtype] += 1
        elif gtype == "MultiPolygon":
            type_counts["Polygon"] += 1
    
    # Return dominant type
    if type_counts["Polygon"] > type_counts["Point"]:
        return "Polygon"
    if type_counts["LineString"] > type_counts["Point"]:
        return "LineString"
    return "Point"


def _get_layer_type(geom_type: str) -> str:
    """Map geometry type to LayerData type."""
    return {
        "Point": "geojson_point",
        "Polygon": "geojson_poly",
        "MultiPolygon": "geojson_poly",
        "LineString": "geojson_line",
    }.get(geom_type, "geojson_point")


def _get_viz_config(geom_type: str, source: str) -> VizConfig:
    """Get appropriate viz config based on geometry and source."""
    if geom_type in ("Polygon", "MultiPolygon"):
        return VizConfig(
            style="fill",
            color_scale="categorical_risk" if source == "hdx" else "viridis",
            label=f"Areas ({source})",
            opacity=0.6,
        )
    elif geom_type == "LineString":
        return VizConfig(
            style="line",
            color_scale="neon_blue",
            label=f"Routes ({source})",
            opacity=0.8,
        )
    else:  # Point
        color = {
            "athena": "plasma",
            "news": "categorical_risk",
            "hdx": "rdylgn",
            "google": "viridis",
        }.get(source, "plasma")
        return VizConfig(
            style="symbol",
            color_scale=color,
            label=f"Entities ({source})",
            opacity=0.9,
        )


# =============================================================================
# BACKEND HANDLERS
# =============================================================================

def _search_athena(bbox: List[float], query: str, limit: int) -> Dict:
    """Search Overture via Athena (FREE)."""
    if not fetch_features_sql:
        raise RuntimeError("tools_athena not available")
    
    # Map query to category
    category = _query_to_category(query)
    
    df = fetch_features_sql(
        bbox=bbox,
        theme="places",
        feature_type="place",
        filters={"categories.primary": category} if category else None,
        limit=limit,
    )
    
    features = []
    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row.get("lon", 0), row.get("lat", 0)]},
            "properties": {
                "name": row.get("name", "Unknown"),
                "category": row.get("category", category),
                "source": "overture",
            }
        })
    
    return {"type": "FeatureCollection", "features": features}


def _search_news(bbox: List[float], query: str) -> Dict:
    """Search GDELT for events (FREE)."""
    if not fetch_visual_risk:
        raise RuntimeError("tools_news not available")
    
    # Detect risk type
    risk_type = "general"
    for rtype in ["flood", "fire", "protest", "conflict", "disaster"]:
        if rtype in query.lower():
            risk_type = rtype
            break
    
    result = fetch_visual_risk(tuple(bbox), risk_type)
    
    if isinstance(result, dict) and "features" in result:
        return result
    return {"type": "FeatureCollection", "features": []}


def _search_hdx(bbox: List[float], query: str) -> Dict:
    """Search HDX for humanitarian data (FREE)."""
    if not fetch_hdx_spatial_data:
        raise RuntimeError("tools_hdx not available")
    
    import json
    
    # Extract keyword from query
    keyword = query.split()[0] if query else "hospitals"
    
    result = fetch_hdx_spatial_data(country_iso3="GLOBAL", keyword=keyword)
    
    if isinstance(result, str):
        result = json.loads(result)
    
    if isinstance(result, dict) and "features" in result:
        return result
    return {"type": "FeatureCollection", "features": []}


def _search_google(query: str, city: str, limit: int) -> Dict:
    """Search Google Maps via ScrapingDog (PAID)."""
    if not google_search:
        raise RuntimeError("tools_scraper not available")
    
    result = google_search(query, city, limit=limit)
    
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Google search failed"))
    
    features = []
    for place in result.get("places", []):
        if place.get("lat") and place.get("lon"):
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [place["lon"], place["lat"]]},
                "properties": {
                    "name": place.get("name", "Unknown"),
                    "rating": place.get("rating"),
                    "reviews_count": place.get("reviews_count"),
                    "address": place.get("address"),
                    "source": "google_maps",
                }
            })
    
    return {"type": "FeatureCollection", "features": features}


def _query_to_category(query: str) -> Optional[str]:
    """Map natural language to Overture category."""
    q = query.lower()
    mapping = {
        "coffee": "coffee_shop", "cafe": "cafe", "restaurant": "restaurant",
        "gym": "fitness_center", "hotel": "hotel", "bank": "bank",
        "pharmacy": "pharmacy", "hospital": "hospital", "school": "school",
        "bar": "bar", "supermarket": "supermarket", "gas": "gas_station",
        "parking": "parking", "park": "park", "museum": "museum",
    }
    for keyword, category in mapping.items():
        if keyword in q:
            return category
    return None


# =============================================================================
# MAIN SEARCH FUNCTION
# =============================================================================

SourceType = Literal["athena", "google", "news", "hdx"]

def search_entities(
    aoi_bbox: List[float],
    query: str,
    source: SourceType,  # REQUIRED - no auto
    limit: int = 100,
    city: Optional[str] = None,
) -> LayerData:
    """
    Search for discrete entities (Things) in the AOI.
    
    Args:
        aoi_bbox: [min_lon, min_lat, max_lon, max_lat]
        query: What to search for
        source: Backend to use (REQUIRED):
            - "athena": Static objects (FREE)
            - "news": Live events (FREE)
            - "hdx": Humanitarian infra (FREE)
            - "google": Reviews/ratings (PAID)
        limit: Max results
        city: City name (required for google source)
    
    Returns:
        LayerData with appropriate geometry type
    """
    logger.info(f"🔍 SEARCH: '{query}' via {source}")
    
    # Route to backend
    if source == "athena":
        geojson = _search_athena(aoi_bbox, query, limit)
    elif source == "news":
        geojson = _search_news(aoi_bbox, query)
    elif source == "hdx":
        geojson = _search_hdx(aoi_bbox, query)
    elif source == "google":
        if not city:
            # Try to infer city from bbox center
            city = f"near {(aoi_bbox[1]+aoi_bbox[3])/2:.2f}, {(aoi_bbox[0]+aoi_bbox[2])/2:.2f}"
        geojson = _search_google(query, city, limit)
    else:
        raise ValueError(f"Unknown source: {source}. Use: athena, news, hdx, google")
    
    features = geojson.get("features", [])
    logger.info(f"   Found {len(features)} entities")
    
    # Detect geometry type
    geom_type = _detect_geometry_type(features)
    layer_type = _get_layer_type(geom_type)
    viz_config = _get_viz_config(geom_type, source)
    
    return LayerData(
        layer_id=f"search_{source}_{query.replace(' ', '_')[:20]}",
        type=layer_type,
        data=geojson,
        viz_config=viz_config,
        summary=f"Found {len(features)} {query} via {source}",
        metadata={"source": source, "query": query, "geometry_type": geom_type},
    )


# =============================================================================
# TOOL WRAPPER FOR AGENT
# =============================================================================

def tool_search_entities(
    query: str,
    source: SourceType,
    aoi_bbox: Optional[List[float]] = None,
    limit: int = 100,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search for entities (Things) - Buildings, Events, Facilities.
    
    Args:
        query: What to search for (e.g., "coffee shops", "protests", "hospitals")
        source: Backend (REQUIRED):
            - "athena" (FREE) - Static objects from Overture
            - "news" (FREE) - Live events from GDELT
            - "hdx" (FREE) - Humanitarian data
            - "google" (PAID) - Reviews/ratings - use sparingly!
        aoi_bbox: Bounding box (uses session AOI if not provided)
        limit: Max results
        city: City name (required for google)
    
    Returns:
        GeoJSON entities (Points, Polygons, or Lines depending on data)
    """
    bbox = aoi_bbox or [-180, -90, 180, 90]
    
    result = search_entities(
        aoi_bbox=bbox,
        query=query,
        source=source,
        limit=limit,
        city=city,
    )
    
    # Use standardized response format
    from ..schema import format_tool_response
    return format_tool_response(result)
