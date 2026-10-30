"""
Leo Formatting Utilities - LayerData Helper
============================================

Helper functions to wrap tool outputs into the standardized LayerData schema.
Ensures consistent output format across all tools in the pipeline.

Usage:
    from utils_formatting import format_layer, format_h3_layer, format_error
    
    # Format GeoJSON point data
    layer = format_layer(
        id='schools_kenya',
        type='geojson_point',
        data=geojson,
        label='Schools',
        style='symbol'
    )
    
    # Format H3 hexagon data
    layer = format_h3_layer(
        id='population_density',
        data=h3_data,
        label='Population',
        color_scale='magma'
    )
    
    # Format error
    error = format_error('No data found', 'schools_kenya')
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Literal

logger = logging.getLogger(__name__)

# Import schema models - handle both package and direct imports
try:
    from .schema import LayerData, VizConfig
except ImportError:
    from schema import LayerData, VizConfig


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

LayerType = Literal["h3_grid", "geojson_point", "geojson_line", "geojson_poly", "geojson_collection", "weighted_points"]
VizStyle = Literal["heatmap", "heatmap_blur", "contour", "choropleth", "symbol", "line", "extrusion", "fill", "circle", "arc", "icon"]

# Data categories for the Unified Visual Design System
# HONEST CARTOGRAPHY: Statistical data uses heatmap_blur, actual geometry stays sharp
DataCategory = Literal[
    "demographics",    # Population data -> Blurred heatmap (statistical estimate)
    "agriculture",     # Crop production -> Blurred heatmap (10km grid estimate)
    "wealth",          # RWI/Affluence -> Blurred heatmap (statistical model)
    "retail",          # Retail gravity -> Blurred heatmap (aggregated from POIs)
    "places",          # POIs -> Sharp dots (actual locations)
    "risk",            # News/Risk events -> Sharp symbols (actual events)
    "development",     # Construction signals -> Sharp symbols (actual locations)
    "routes",          # Transport routes -> Sharp lines (actual geometry)
    "trade",           # Trade flows -> Arcs (stylized, not claiming precision)
    "climate",         # Weather risk -> Blurred heatmap (statistical estimate)
    "boundaries",      # AOI boundaries -> Sharp outlines (actual borders)
    "buildings",       # Building footprints -> Sharp polygons (actual geometry)
    "hdx",             # Humanitarian data -> Sharp symbols (actual locations)
]


# =============================================================================
# 🎨 LAYER STYLES REGISTRY - Unified Visual Design System
# =============================================================================
# 
# HONEST CARTOGRAPHY PRINCIPLE:
# =============================
# SHARP = Actual geometry (buildings, POIs, routes, boundaries)
# BLUR  = Statistical estimates (population, wealth, crop production)
#
# If you don't have building-level precision, DON'T render as sharp hexagons.
# Use heatmap_blur to honestly show "more here, less there" without implying
# false precision.
#
# Design Philosophy:
# - Statistical Data: Gaussian blur heatmap ("Honest Uncertainty")
# - POIs/Places: Sharp dots ("Actual Locations")  
# - Routes: Sharp glowing lines ("Actual Paths")
# - Buildings: Sharp polygons ("Actual Footprints")
# - Boundaries: Sharp outlines ("Actual Borders")
# - Trade: Stylized arcs ("Flow Visualization")
# =============================================================================

LAYER_STYLES: Dict[str, Dict[str, Any]] = {
    # Demographics: Blurred heatmap - population is an ESTIMATE, not precise
    "demographics": {
        "style": "heatmap_blur",
        "color_scale": "magma",
        "opacity": 0.8,
        "value_key": "weight",
        "radius_pixels": 30,
        "intensity": 1.0,
        "threshold": 0.05,
    },
    
    # Agriculture: Blurred heatmap - 10km grid is NOT precise
    "agriculture": {
        "style": "heatmap_blur",
        "color_scale": "ylgn",
        "opacity": 0.75,
        "value_key": "weight",
        "radius_pixels": 40,  # Larger blur for coarser data
        "intensity": 1.0,
        "threshold": 0.03,
    },
    
    # Wealth: Blurred heatmap - RWI is a statistical MODEL
    "wealth": {
        "style": "heatmap_blur",
        "color_scale": "viridis",
        "opacity": 0.7,
        "value_key": "weight",
        "radius_pixels": 35,
        "intensity": 1.0,
        "threshold": 0.05,
    },
    
    # Retail Gravity: Blurred heatmap - aggregated score, not precise
    "retail": {
        "style": "heatmap_blur",
        "color_scale": "inferno",
        "opacity": 0.8,
        "value_key": "weight",
        "radius_pixels": 25,
        "intensity": 1.2,
        "threshold": 0.05,
    },
    
    # Places/POIs: SHARP dots - these are ACTUAL locations
    "places": {
        "style": "symbol",
        "color_scale": "plasma",
        "opacity": 0.9,
        "radius": 6,
        "stroke_width": 2,
        "stroke_color": "#FFFFFF",
        "value_key": "name",
    },
    
    # Risk/News: SHARP symbols - these are ACTUAL reported events
    "risk": {
        "style": "symbol",
        "color_scale": "categorical_risk",
        "opacity": 0.95,
        "radius": 8,
        "stroke_width": 2,
        "stroke_color": "#FFFFFF",
        "value_key": "tone",
    },
    
    # Development Signals: SHARP symbols - ACTUAL construction locations
    "development": {
        "style": "symbol",
        "color_scale": "ylgn",
        "opacity": 0.9,
        "radius": 7,
        "stroke_width": 2,
        "stroke_color": "#FFFFFF",
        "value_key": "type",
    },
    
    # Routes: SHARP lines - ACTUAL road geometry
    "routes": {
        "style": "line",
        "color_scale": "neon_blue",
        "opacity": 0.9,
        "stroke_width": 4,
        "value_key": "distance_km",
    },
    
    # Trade Flows: Stylized arcs - visualization, not claiming precision
    "trade": {
        "style": "arc",
        "color_scale": "neon_magenta",
        "opacity": 0.85,
        "arc_width": 3,
        "value_key": "trade_value",
    },
    
    # Climate: Blurred heatmap - weather risk is an ESTIMATE
    "climate": {
        "style": "heatmap_blur",
        "color_scale": "rdbu",
        "opacity": 0.6,
        "value_key": "weight",
        "radius_pixels": 50,  # Large blur for coarse climate data
        "intensity": 0.8,
        "threshold": 0.05,
    },
    
    # Boundaries: SHARP lines - ACTUAL administrative borders
    "boundaries": {
        "style": "line",
        "color_scale": "neon_blue",
        "opacity": 1.0,
        "stroke_width": 3,
        "stroke_color": "#00FFFF",
        "value_key": "name",
    },
    
    # Buildings: SHARP polygons - ACTUAL building footprints
    "buildings": {
        "style": "fill",
        "color_scale": "magma",
        "opacity": 0.8,
        "stroke_width": 1,
        "stroke_color": "#333333",
        "value_key": "volume",
    },
    
    # HDX Humanitarian: SHARP symbols - ACTUAL facility locations
    "hdx": {
        "style": "symbol",
        "color_scale": "plasma",
        "opacity": 0.9,
        "radius": 5,
        "stroke_width": 1,
        "stroke_color": "#FFFFFF",
        "value_key": "name",
    },
    
    # Building Density: Blurred heatmap - aggregated metric, not precise
    "building_density": {
        "style": "heatmap_blur",
        "color_scale": "magma",
        "opacity": 0.75,
        "value_key": "weight",
        "radius_pixels": 25,
        "intensity": 1.0,
        "threshold": 0.05,
    },
    
    # Affluence Score: Blurred heatmap - aggregated POI score, not precise
    "affluence": {
        "style": "heatmap_blur",
        "color_scale": "viridis",
        "opacity": 0.75,
        "value_key": "weight",
        "radius_pixels": 30,
        "intensity": 1.0,
        "threshold": 0.05,
    },
}


# Legacy defaults (fallback when no category specified)
DEFAULT_COLOR_SCALES = {
    "h3_grid": "viridis",
    "geojson_point": "plasma",
    "geojson_line": "neon_blue",
    "geojson_poly": "viridis",
    "geojson_collection": "viridis",
    "weighted_points": "magma",  # Heatmap blur default
}

DEFAULT_VIZ_STYLES = {
    "h3_grid": "heatmap_blur",  # Changed: statistical data should be blurred
    "geojson_point": "symbol",
    "geojson_line": "line",
    "geojson_poly": "fill",
    "geojson_collection": "fill",
    "weighted_points": "heatmap_blur",  # New: for honest statistical viz
}


# =============================================================================
# MAIN HELPER: format_layer
# =============================================================================

def format_layer(
    id: str,
    type: LayerType,
    data: Union[List[Dict], Dict],
    label: str,
    data_category: Optional[str] = None,
    style: Optional[VizStyle] = None,
    color_scale: Optional[str] = None,
    property_key: Optional[str] = None,
    summary: Optional[str] = None,
    source: Optional[str] = None,
    **metadata
) -> Dict[str, Any]:
    """
    Wrap tool output into a standardized LayerData dictionary.
    
    Uses the Unified Visual Design System when data_category is provided.
    
    Args:
        id: Unique layer identifier (e.g., 'schools_kenya', 'population_bcn')
        type: Data type - one of:
            - 'h3_grid': H3 hexagon data [{'hex': '...', 'value': ...}, ...]
            - 'geojson_point': Point features
            - 'geojson_line': Line features (routes, boundaries)
            - 'geojson_poly': Polygon features
            - 'geojson_collection': Mixed geometry types
        data: The spatial data (H3 list or GeoJSON dict)
        label: Human-readable label for the legend
        data_category: Category for Unified Visual Design System lookup.
            Options: demographics, agriculture, wealth, retail, places,
            risk, development, routes, trade, climate, boundaries, buildings, hdx
        style: Visualization style (overrides category default if provided)
        color_scale: Color scale name (overrides category default if provided)
        property_key: Property to use for coloring (overrides category default)
        summary: Text summary (auto-generated if not provided)
        source: Data source name (for metadata)
        **metadata: Additional metadata fields
        
    Returns:
        Dictionary with LayerData structure including full viz_config
        
    Example:
        >>> # Using Unified Visual Design System (recommended)
        >>> result = format_layer(
        ...     id='population_tokyo',
        ...     type='h3_grid',
        ...     data=h3_data,
        ...     label='Population Density',
        ...     data_category='demographics',  # Auto-applies 3D Magma style
        ...     source='WorldPop'
        ... )
        
        >>> # Manual override
        >>> result = format_layer(
        ...     id='schools_kenya',
        ...     type='geojson_point',
        ...     data=geojson,
        ...     label='Schools',
        ...     style='symbol',
        ...     color_scale='plasma'
        ... )
    """
    # Get defaults from LAYER_STYLES registry if category provided
    category_style = LAYER_STYLES.get(data_category, {}) if data_category else {}
    
    # Resolve style (explicit > category > type default)
    resolved_style = style or category_style.get("style") or DEFAULT_VIZ_STYLES.get(type, "fill")
    
    # Resolve color scale (explicit > category > type default)
    resolved_color = color_scale or category_style.get("color_scale") or DEFAULT_COLOR_SCALES.get(type, "viridis")
    
    # Resolve property key (explicit > category > default)
    resolved_key = property_key or category_style.get("value_key", "value")
    
    # Count features for summary
    feature_count = _count_features(data, type)
    
    # Auto-generate summary if not provided
    if summary is None:
        summary = f"{label}: {feature_count} features"
    
    # Build metadata
    meta = {
        "source": source or "unknown",
        "timestamp": datetime.now().isoformat(),
        "feature_count": feature_count,
        "data_category": data_category,
    }
    meta.update(metadata)
    
    # Build viz config - start with category defaults, then override
    viz_config = {
        "style": resolved_style,
        "color_scale": resolved_color,
        "value_key": resolved_key,
        "label": label,
        "opacity": category_style.get("opacity", 0.8),
        "elevation_scale": category_style.get("elevation_scale", 10.0),
        "coverage": category_style.get("coverage", 0.9),
    }
    
    # Add optional style properties from category
    if category_style.get("radius"):
        viz_config["radius"] = category_style["radius"]
    if category_style.get("stroke_width"):
        viz_config["stroke_width"] = category_style["stroke_width"]
    if category_style.get("stroke_color"):
        viz_config["stroke_color"] = category_style["stroke_color"]
    if category_style.get("arc_width"):
        viz_config["arc_width"] = category_style["arc_width"]
    
    return {
        "layer_id": id,
        "type": type,
        "data": data,
        "viz_config": viz_config,
        "summary": summary,
        "metadata": meta,
    }


def get_category_style(category: str) -> Dict[str, Any]:
    """
    Get the default style configuration for a data category.
    
    Args:
        category: Data category (demographics, agriculture, etc.)
        
    Returns:
        Style dictionary from LAYER_STYLES or empty dict
    """
    return LAYER_STYLES.get(category, {})


def format_h3_layer(
    id: str,
    data: List[Dict],
    label: str,
    color_scale: str = "viridis",
    property_key: str = "value",
    style: VizStyle = "heatmap_blur",
    summary: Optional[str] = None,
    **metadata
) -> Dict[str, Any]:
    """
    Convenience function for formatting H3 hexagon data.
    
    NOTE: For HONEST CARTOGRAPHY, consider using format_weighted_points_layer
    instead, which renders as a blurred heatmap. Only use H3 hexagons when
    you have building-level precision data.
    
    Args:
        id: Layer identifier
        data: H3 data as [{'hex': '...', 'value': ...}, ...]
        label: Display label
        color_scale: Color scale (default: viridis)
        property_key: Value property key (default: 'value')
        style: Viz style (default: heatmap_blur)
        summary: Optional text summary
        **metadata: Additional metadata
        
    Returns:
        LayerData dictionary
        
    Example:
        >>> layer = format_h3_layer(
        ...     id='population_density',
        ...     data=[{'hex': '89...', 'value': 1500}],
        ...     label='Population Density',
        ...     color_scale='magma'
        ... )
    """
    return format_layer(
        id=id,
        type="h3_grid",
        data=data,
        label=label,
        style=style,
        color_scale=color_scale,
        property_key=property_key,
        summary=summary,
        **metadata
    )


def format_weighted_points_layer(
    id: str,
    data: List[Dict],
    label: str,
    color_scale: str = "magma",
    weight_key: str = "weight",
    radius_pixels: int = 30,
    intensity: float = 1.0,
    summary: Optional[str] = None,
    source_resolution_m: Optional[int] = None,
    **metadata
) -> Dict[str, Any]:
    """
    Format weighted point data for heatmap blur visualization.
    
    HONEST CARTOGRAPHY: Use this for ALL statistical/aggregated data.
    This renders as a Gaussian blur heatmap, honestly showing uncertainty
    instead of implying false precision with sharp hexagons.
    
    Args:
        id: Layer identifier
        data: Weighted points as [{'lat': ..., 'lng': ..., 'weight': ...}, ...]
        label: Display label
        color_scale: Color scale (default: magma)
        weight_key: Key for weight value (default: 'weight')
        radius_pixels: Blur radius in screen pixels (default: 30)
        intensity: Heatmap intensity multiplier (default: 1.0)
        summary: Optional text summary
        source_resolution_m: Original data resolution in meters (for metadata)
        **metadata: Additional metadata
        
    Returns:
        LayerData dictionary configured for heatmap_blur visualization
        
    Example:
        >>> # Population data (100m resolution - still use blur!)
        >>> layer = format_weighted_points_layer(
        ...     id='population_barcelona',
        ...     data=[{'lat': 41.39, 'lng': 2.16, 'weight': 15000}, ...],
        ...     label='Population Density',
        ...     color_scale='magma',
        ...     source_resolution_m=100
        ... )
        
        >>> # Crop production (10km resolution - definitely blur!)
        >>> layer = format_weighted_points_layer(
        ...     id='cocoa_ghana',
        ...     data=[{'lat': 6.5, 'lng': -1.2, 'weight': 5000}, ...],
        ...     label='Cocoa Production',
        ...     color_scale='ylgn',
        ...     radius_pixels=40,  # Larger blur for coarser data
        ...     source_resolution_m=10000
        ... )
    """
    feature_count = len(data) if data else 0
    
    if summary is None:
        summary = f"{label}: {feature_count} data points"
    
    meta = {
        "timestamp": datetime.now().isoformat(),
        "feature_count": feature_count,
        "source_resolution_m": source_resolution_m,
        "visualization_note": "Rendered as heatmap blur for honest uncertainty representation",
    }
    meta.update(metadata)
    
    return {
        "layer_id": id,
        "type": "weighted_points",
        "data": data,
        "viz_config": {
            "style": "heatmap_blur",
            "color_scale": color_scale,
            "value_key": weight_key,
            "label": label,
            "opacity": 0.8,
            "radius_pixels": radius_pixels,
            "intensity": intensity,
            "threshold": 0.05,
        },
        "summary": summary,
        "metadata": meta,
    }


def format_geojson_layer(
    id: str,
    data: Dict,
    label: str,
    style: Optional[VizStyle] = None,
    color_scale: str = "blues",
    summary: Optional[str] = None,
    **metadata
) -> Dict[str, Any]:
    """
    Convenience function for formatting GeoJSON data.
    
    Auto-detects geometry type from the GeoJSON.
    
    Args:
        id: Layer identifier
        data: GeoJSON FeatureCollection
        label: Display label
        style: Viz style (auto-detected if not provided)
        color_scale: Color scale
        summary: Optional text summary
        **metadata: Additional metadata
        
    Returns:
        LayerData dictionary
    """
    # Detect geometry type
    layer_type = _detect_geojson_type(data)
    
    # Auto-detect style based on geometry type
    if style is None:
        style = DEFAULT_VIZ_STYLES.get(layer_type, "fill")
    
    return format_layer(
        id=id,
        type=layer_type,
        data=data,
        label=label,
        style=style,
        color_scale=color_scale,
        summary=summary,
        **metadata
    )


def format_error(
    message: str,
    layer_id: str = "error",
    details: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Format an error response.
    
    Returns a dictionary that can be used as an error layer or response.
    
    Args:
        message: Error message
        layer_id: Identifier for the failed operation
        details: Additional error details
        
    Returns:
        Error dictionary with consistent format
    """
    return {
        "error": True,
        "layer_id": layer_id,
        "message": message,
        "details": details or {},
        "timestamp": datetime.now().isoformat(),
    }


# =============================================================================
# CONVERSION HELPERS
# =============================================================================

def h3_to_geojson(h3_data: List[Dict], value_key: str = "value") -> Dict:
    """
    Convert H3 hexagon data to GeoJSON FeatureCollection.
    
    Args:
        h3_data: List of {'hex': '...', 'value': ...} dicts
        value_key: Key for the value property
        
    Returns:
        GeoJSON FeatureCollection with hexagon polygons
    """
    try:
        from utils_h3 import hexagons_to_feature_collection
        return hexagons_to_feature_collection(h3_data, value_key)
    except ImportError:
        from .utils_h3 import hexagons_to_feature_collection
        return hexagons_to_feature_collection(h3_data, value_key)


def points_to_geojson(
    points: List[Dict],
    lat_key: str = "lat",
    lon_key: str = "lon"
) -> Dict:
    """
    Convert list of point dicts to GeoJSON FeatureCollection.
    
    Args:
        points: List of dicts with lat/lon
        lat_key: Key for latitude (also checks 'latitude')
        lon_key: Key for longitude (also checks 'longitude', 'lng')
        
    Returns:
        GeoJSON FeatureCollection
    """
    features = []
    
    for point in points:
        # Extract coordinates (handle different key names)
        lat = point.get(lat_key) or point.get("latitude")
        lon = (point.get(lon_key) or point.get("longitude") or 
               point.get("lng") or point.get("long"))
        
        if lat is None or lon is None:
            continue
        
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue
        
        # Build properties (exclude lat/lon keys)
        exclude_keys = {lat_key, lon_key, "latitude", "longitude", "lng", "long"}
        properties = {k: v for k, v in point.items() if k not in exclude_keys}
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "properties": properties
        })
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


def dataframe_to_geojson(
    df,
    lat_col: str = "lat",
    lon_col: str = "lon",
    properties: Optional[List[str]] = None
) -> Dict:
    """
    Convert pandas DataFrame to GeoJSON FeatureCollection.
    
    Args:
        df: Pandas DataFrame with lat/lon columns
        lat_col: Name of latitude column
        lon_col: Name of longitude column
        properties: List of column names to include as properties (all if None)
        
    Returns:
        GeoJSON FeatureCollection
    """
    features = []
    
    prop_cols = properties if properties else [c for c in df.columns if c not in (lat_col, lon_col)]
    
    for _, row in df.iterrows():
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
        except (ValueError, TypeError, KeyError):
            continue
        
        props = {}
        for col in prop_cols:
            val = row.get(col)
            if val is not None and str(val) != "nan":
                props[col] = val
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "properties": props
        })
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _count_features(data: Union[List, Dict], data_type: str) -> int:
    """Count the number of features in the data."""
    if data is None:
        return 0
    
    if isinstance(data, list):
        return len(data)
    
    if isinstance(data, dict):
        if data.get("type") == "FeatureCollection":
            return len(data.get("features", []))
        elif "features" in data:
            return len(data["features"])
        elif data.get("type") == "Feature":
            return 1
        else:
            return len(data)
    
    return 0


def _detect_geojson_type(geojson: Dict) -> LayerType:
    """Detect the layer type from GeoJSON structure."""
    if not isinstance(geojson, dict):
        return "geojson_collection"
    
    # Check for FeatureCollection
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        
        if not features:
            return "geojson_collection"
        
        # Check geometry types
        geom_types = set()
        for feature in features[:10]:  # Sample first 10
            geom = feature.get("geometry", {})
            geom_type = geom.get("type", "")
            geom_types.add(geom_type)
        
        if geom_types == {"Point"} or geom_types == {"MultiPoint"}:
            return "geojson_point"
        elif geom_types <= {"LineString", "MultiLineString"}:
            return "geojson_line"
        elif geom_types <= {"Polygon", "MultiPolygon"}:
            return "geojson_poly"
        else:
            return "geojson_collection"
    
    # Single Feature
    elif geojson.get("type") == "Feature":
        geom_type = geojson.get("geometry", {}).get("type", "")
        if geom_type in ("Point", "MultiPoint"):
            return "geojson_point"
        elif geom_type in ("LineString", "MultiLineString"):
            return "geojson_line"
        elif geom_type in ("Polygon", "MultiPolygon"):
            return "geojson_poly"
    
    return "geojson_collection"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Main formatters
    "format_layer",
    "format_h3_layer",
    "format_weighted_points_layer",  # NEW: For honest cartography
    "format_geojson_layer",
    "format_error",
    "get_category_style",
    
    # Style registry
    "LAYER_STYLES",
    
    # Converters
    "h3_to_geojson",
    "points_to_geojson",
    "dataframe_to_geojson",
]


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🎨 Formatting Utilities - Test Suite")
    print("=" * 60)
    
    # Test format_layer with GeoJSON
    print("\n📍 Test 1: Format GeoJSON point layer")
    geojson_data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.17, 41.38]}, "properties": {"name": "School A"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.18, 41.39]}, "properties": {"name": "School B"}},
        ]
    }
    layer = format_layer(
        id="schools_barcelona",
        type="geojson_point",
        data=geojson_data,
        label="Schools",
        style="symbol",
        source="HDX"
    )
    print(f"   Layer ID: {layer['layer_id']}")
    print(f"   Type: {layer['type']}")
    print(f"   Viz: {layer['viz_config']['style']}")
    print(f"   Summary: {layer['summary']}")
    
    # Test format_h3_layer
    print("\n🔷 Test 2: Format H3 layer")
    h3_data = [
        {"hex": "89283082837ffff", "value": 1500},
        {"hex": "89283082833ffff", "value": 2200},
        {"hex": "89283082831ffff", "value": 800},
    ]
    layer = format_h3_layer(
        id="population_density",
        data=h3_data,
        label="Population Density",
        color_scale="magma"
    )
    print(f"   Layer ID: {layer['layer_id']}")
    print(f"   Type: {layer['type']}")
    print(f"   Color scale: {layer['viz_config']['color_scale']}")
    print(f"   Summary: {layer['summary']}")
    
    # Test format_geojson_layer with auto-detection
    print("\n🔲 Test 3: Format polygon layer (auto-detect)")
    polygon_data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, "properties": {"name": "Zone A"}}
        ]
    }
    layer = format_geojson_layer(
        id="zones",
        data=polygon_data,
        label="Zones"
    )
    print(f"   Auto-detected type: {layer['type']}")
    print(f"   Auto-detected style: {layer['viz_config']['style']}")
    
    # Test points_to_geojson
    print("\n📌 Test 4: Points to GeoJSON")
    points = [
        {"lat": 41.38, "lon": 2.17, "name": "Point A"},
        {"latitude": 41.39, "longitude": 2.18, "name": "Point B"},
    ]
    geojson = points_to_geojson(points)
    print(f"   Features created: {len(geojson['features'])}")
    
    # Test format_error
    print("\n❌ Test 5: Format error")
    error = format_error("No data found for Kenya", "schools_kenya")
    print(f"   Error: {error['error']}")
    print(f"   Message: {error['message']}")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
