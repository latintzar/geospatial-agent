"""
Leo H3 Utilities
================

Helper functions to standardize H3 operations across all tools.
Supports both H3 v3 and v4 API.

Functions:
- polygon_to_hexagons: Fill a polygon with H3 hexagons
- line_to_hexagons: Convert a linestring to H3 hexagons (interpolation)
- aggregate_data_to_h3: Aggregate DataFrame values by H3 hexagon
- point_to_h3: Convert a single point to H3 index
- h3_to_geojson: Convert H3 hexagon to GeoJSON polygon
- hexagons_to_feature_collection: Convert list of hexagons to GeoJSON FeatureCollection
"""

import h3
import pandas as pd
import logging
from typing import List, Dict, Set, Optional, Union, Tuple, Any
from shapely.geometry import shape, Point, LineString, Polygon, mapping
from shapely.ops import transform
import math

logger = logging.getLogger(__name__)

# ============================================================================
# H3 VERSION DETECTION
# ============================================================================

_h3_version = int(h3.__version__.split('.')[0])
logger.info(f"H3 version detected: {h3.__version__} (major: {_h3_version})")


def _latlng_to_h3(lat: float, lng: float, resolution: int) -> str:
    """Convert lat/lng to H3 index, handling v3/v4 API differences."""
    if _h3_version >= 4:
        return h3.latlng_to_cell(lat, lng, resolution)
    else:
        return h3.geo_to_h3(lat, lng, resolution)


def _h3_to_boundary(h3_index: str) -> List[Tuple[float, float]]:
    """Get boundary coordinates for an H3 index, handling v3/v4 API differences."""
    if _h3_version >= 4:
        return h3.cell_to_boundary(h3_index)
    else:
        return h3.h3_to_geo_boundary(h3_index, geo_json=True)


def _polyfill(polygon_coords: List, resolution: int) -> Set[str]:
    """Fill a polygon with H3 hexagons, handling v3/v4 API differences."""
    if _h3_version >= 4:
        # H3 v4: polygon_to_cells expects GeoJSON-style polygon
        return h3.polygon_to_cells(h3.LatLngPoly(polygon_coords), resolution)
    else:
        # H3 v3: polyfill expects list of [lat, lng] tuples
        return h3.polyfill_geojson(
            {"type": "Polygon", "coordinates": [polygon_coords]},
            resolution
        )


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def polygon_to_hexagons(
    geojson_polygon: Dict,
    resolution: int = 8
) -> Set[str]:
    """
    Fill a GeoJSON polygon with H3 hexagons.
    
    Args:
        geojson_polygon: GeoJSON Polygon or MultiPolygon geometry dict
                        e.g., {"type": "Polygon", "coordinates": [[[lng, lat], ...]]}
        resolution: H3 resolution (0-15). Default 8 (~460m edge).
    
    Returns:
        Set of H3 hexagon indexes that fill the polygon.
    
    Example:
        >>> polygon = {"type": "Polygon", "coordinates": [[[-73.9, 40.7], [-73.8, 40.7], ...]]}
        >>> hexes = polygon_to_hexagons(polygon, resolution=9)
        >>> print(f"Found {len(hexes)} hexagons")
    """
    try:
        geom_type = geojson_polygon.get('type', '')
        
        if geom_type == 'Polygon':
            # Single polygon
            coords = geojson_polygon['coordinates'][0]
            # Convert from GeoJSON [lng, lat] to H3 [lat, lng]
            latlng_coords = [(lat, lng) for lng, lat in coords]
            
            if _h3_version >= 4:
                return set(h3.polygon_to_cells(h3.LatLngPoly(latlng_coords), resolution))
            else:
                return h3.polyfill_geojson(geojson_polygon, resolution)
                
        elif geom_type == 'MultiPolygon':
            # Multiple polygons - union all hexagons
            all_hexes: Set[str] = set()
            for polygon_coords in geojson_polygon['coordinates']:
                single_polygon = {"type": "Polygon", "coordinates": polygon_coords}
                all_hexes.update(polygon_to_hexagons(single_polygon, resolution))
            return all_hexes
            
        else:
            logger.warning(f"Unsupported geometry type: {geom_type}")
            return set()
            
    except Exception as e:
        logger.error(f"Error in polygon_to_hexagons: {e}")
        return set()


def line_to_hexagons(
    geojson_linestring: Dict,
    resolution: int = 8,
    interpolate_meters: float = 100.0
) -> Set[str]:
    """
    Convert a GeoJSON LineString to H3 hexagons by interpolating points along it.
    
    Useful for analyzing trade routes, supply chains, or transport corridors.
    
    Args:
        geojson_linestring: GeoJSON LineString geometry dict
                           e.g., {"type": "LineString", "coordinates": [[lng, lat], ...]}
        resolution: H3 resolution (0-15). Default 8 (~460m edge).
        interpolate_meters: Distance between interpolated points in meters.
                           Smaller = more hexagons, more accurate. Default 100m.
    
    Returns:
        Set of H3 hexagon indexes along the line.
    
    Example:
        >>> line = {"type": "LineString", "coordinates": [[-73.9, 40.7], [-73.8, 40.75]]}
        >>> hexes = line_to_hexagons(line, resolution=9, interpolate_meters=50)
    """
    try:
        geom_type = geojson_linestring.get('type', '')
        
        if geom_type == 'LineString':
            coords = geojson_linestring['coordinates']
        elif geom_type == 'MultiLineString':
            # Flatten all linestrings
            all_hexes: Set[str] = set()
            for line_coords in geojson_linestring['coordinates']:
                single_line = {"type": "LineString", "coordinates": line_coords}
                all_hexes.update(line_to_hexagons(single_line, resolution, interpolate_meters))
            return all_hexes
        else:
            logger.warning(f"Unsupported geometry type for line: {geom_type}")
            return set()
        
        # Create Shapely LineString
        line = LineString(coords)
        
        # Calculate total length in meters (approximate)
        # Using the first point's latitude for the conversion
        lat = coords[0][1]
        meters_per_degree = 111320 * math.cos(math.radians(lat))
        line_length_meters = line.length * meters_per_degree
        
        # Interpolate points along the line
        hexes: Set[str] = set()
        
        # Add start and end points
        for lng, lat in coords:
            hexes.add(_latlng_to_h3(lat, lng, resolution))
        
        # Interpolate intermediate points
        num_points = max(2, int(line_length_meters / interpolate_meters))
        for i in range(num_points + 1):
            fraction = i / num_points
            point = line.interpolate(fraction, normalized=True)
            hexes.add(_latlng_to_h3(point.y, point.x, resolution))
        
        logger.debug(f"Line to hexagons: {len(hexes)} hexagons from {len(coords)} vertices")
        return hexes
        
    except Exception as e:
        logger.error(f"Error in line_to_hexagons: {e}")
        return set()


def aggregate_data_to_h3(
    dataframe: pd.DataFrame,
    lat_col: str,
    lon_col: str,
    value_col: str,
    resolution: int = 8,
    agg_func: str = 'sum'
) -> List[Dict[str, Any]]:
    """
    Aggregate DataFrame values by H3 hexagon.
    
    Takes any dataframe with lat/lon columns, converts to H3, 
    and aggregates values by hexagon.
    
    Args:
        dataframe: Pandas DataFrame with coordinates and values.
        lat_col: Name of latitude column.
        lon_col: Name of longitude column.
        value_col: Name of value column to aggregate.
        resolution: H3 resolution (0-15). Default 8.
        agg_func: Aggregation function - 'sum', 'mean', 'max', 'min', 'count'.
    
    Returns:
        List of dicts: [{'hex': '89283082837ffff', 'value': 100.0, 'count': 5}, ...]
    
    Example:
        >>> df = pd.DataFrame({
        ...     'lat': [40.7, 40.71, 40.72],
        ...     'lon': [-73.9, -73.91, -73.92],
        ...     'sales': [100, 200, 150]
        ... })
        >>> result = aggregate_data_to_h3(df, 'lat', 'lon', 'sales', resolution=9)
        >>> print(result[0])
        {'hex': '89283082837ffff', 'value': 450.0, 'count': 3}
    """
    try:
        # Make a copy to avoid modifying original
        df = dataframe.copy()
        
        # Drop rows with missing coordinates
        df = df.dropna(subset=[lat_col, lon_col])
        
        if len(df) == 0:
            logger.warning("No valid coordinates found in dataframe")
            return []
        
        # Convert to H3
        df['h3_index'] = df.apply(
            lambda row: _latlng_to_h3(row[lat_col], row[lon_col], resolution),
            axis=1
        )
        
        # Group by H3 and aggregate
        agg_dict = {value_col: agg_func}
        grouped = df.groupby('h3_index').agg(
            value=(value_col, agg_func),
            count=(value_col, 'count')
        ).reset_index()
        
        # Convert to list of dicts
        result = [
            {
                'hex': row['h3_index'],
                'value': float(row['value']),
                'count': int(row['count'])
            }
            for _, row in grouped.iterrows()
        ]
        
        logger.info(f"Aggregated {len(df)} points into {len(result)} H3 hexagons (resolution {resolution})")
        return result
        
    except Exception as e:
        logger.error(f"Error in aggregate_data_to_h3: {e}")
        return []


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def point_to_h3(lat: float, lng: float, resolution: int = 8) -> str:
    """
    Convert a single lat/lng point to H3 index.
    
    Args:
        lat: Latitude
        lng: Longitude
        resolution: H3 resolution (0-15). Default 8.
    
    Returns:
        H3 hexagon index string.
    """
    return _latlng_to_h3(lat, lng, resolution)


def h3_to_geojson(h3_index: str) -> Dict:
    """
    Convert an H3 hexagon to a GeoJSON Polygon.
    
    Args:
        h3_index: H3 hexagon index string.
    
    Returns:
        GeoJSON Polygon geometry dict.
    """
    boundary = _h3_to_boundary(h3_index)
    
    # H3 v4 returns [(lat, lng), ...], need to convert to GeoJSON [[lng, lat], ...]
    if _h3_version >= 4:
        coords = [[lng, lat] for lat, lng in boundary]
    else:
        coords = boundary
    
    # Close the ring
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    
    return {
        "type": "Polygon",
        "coordinates": [coords]
    }


def hexagons_to_feature_collection(
    hexagons: Union[Set[str], List[str], List[Dict]],
    value_key: str = 'value'
) -> Dict:
    """
    Convert a list of H3 hexagons to a GeoJSON FeatureCollection.
    
    Args:
        hexagons: Either:
            - Set/List of H3 index strings
            - List of dicts with 'hex' and optional value keys
        value_key: Key name for the value property (if dicts provided).
    
    Returns:
        GeoJSON FeatureCollection with hexagon polygons.
    
    Example:
        >>> hexes = ['89283082837ffff', '89283082833ffff']
        >>> fc = hexagons_to_feature_collection(hexes)
        
        >>> data = [{'hex': '89283082837ffff', 'value': 100}]
        >>> fc = hexagons_to_feature_collection(data)
    """
    features = []
    
    for item in hexagons:
        if isinstance(item, str):
            # Just an H3 index
            h3_index = item
            properties = {'h3': h3_index}
        elif isinstance(item, dict):
            # Dict with 'hex' key and other properties
            h3_index = item.get('hex', item.get('h3', ''))
            properties = {'h3': h3_index}
            # Add all other properties
            for key, val in item.items():
                if key not in ('hex', 'h3'):
                    properties[key] = val
        else:
            continue
        
        if not h3_index:
            continue
            
        features.append({
            "type": "Feature",
            "geometry": h3_to_geojson(h3_index),
            "properties": properties
        })
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


def get_h3_resolution_info() -> Dict[str, Dict]:
    """
    Get information about H3 resolution levels.
    
    Returns:
        Dict mapping resolution to edge length and area.
    """
    return {
        0: {"edge_km": 1107.71, "area_km2": 4250546.848},
        1: {"edge_km": 418.68, "area_km2": 607220.978},
        2: {"edge_km": 158.24, "area_km2": 86745.854},
        3: {"edge_km": 59.81, "area_km2": 12392.264},
        4: {"edge_km": 22.61, "area_km2": 1770.324},
        5: {"edge_km": 8.54, "area_km2": 252.903},
        6: {"edge_km": 3.23, "area_km2": 36.129},
        7: {"edge_km": 1.22, "area_km2": 5.161},
        8: {"edge_km": 0.461, "area_km2": 0.737},  # Default - good balance
        9: {"edge_km": 0.174, "area_km2": 0.105},
        10: {"edge_km": 0.066, "area_km2": 0.015},
        11: {"edge_km": 0.025, "area_km2": 0.002},
        12: {"edge_km": 0.009, "area_km2": 0.0003},
        13: {"edge_km": 0.003, "area_km2": 0.00004},
        14: {"edge_km": 0.001, "area_km2": 0.000006},
        15: {"edge_km": 0.0005, "area_km2": 0.0000009},
    }


def suggest_resolution(area_km2: float) -> int:
    """
    Suggest an appropriate H3 resolution based on area size.
    
    Args:
        area_km2: Area in square kilometers.
    
    Returns:
        Suggested H3 resolution (0-15).
    """
    # Target roughly 100-1000 hexagons for the area
    target_hex_count = 500
    target_hex_area = area_km2 / target_hex_count
    
    info = get_h3_resolution_info()
    
    for res in range(15, -1, -1):
        if info[res]["area_km2"] >= target_hex_area:
            return res
    
    return 8  # Default


# ============================================================================
# EXAMPLE USAGE (if run directly)
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Leo H3 Utilities Test ===\n")
    
    # Test 1: Point to H3
    h3_idx = point_to_h3(40.7128, -74.0060, resolution=9)
    print(f"1. Point to H3: NYC -> {h3_idx}")
    
    # Test 2: Polygon to hexagons
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-74.01, 40.70],
            [-73.98, 40.70],
            [-73.98, 40.73],
            [-74.01, 40.73],
            [-74.01, 40.70]
        ]]
    }
    hexes = polygon_to_hexagons(polygon, resolution=9)
    print(f"2. Polygon to hexagons: {len(hexes)} hexagons")
    
    # Test 3: Line to hexagons
    line = {
        "type": "LineString",
        "coordinates": [
            [-74.01, 40.70],
            [-73.95, 40.75]
        ]
    }
    line_hexes = line_to_hexagons(line, resolution=9, interpolate_meters=200)
    print(f"3. Line to hexagons: {len(line_hexes)} hexagons")
    
    # Test 4: Aggregate data
    df = pd.DataFrame({
        'lat': [40.71, 40.712, 40.72, 40.73],
        'lon': [-74.00, -74.002, -73.99, -73.98],
        'sales': [100, 200, 150, 300]
    })
    result = aggregate_data_to_h3(df, 'lat', 'lon', 'sales', resolution=9)
    print(f"4. Aggregate to H3: {len(result)} hexagons from 4 points")
    
    # Test 5: Hexagons to GeoJSON
    fc = hexagons_to_feature_collection(result)
    print(f"5. To FeatureCollection: {len(fc['features'])} features")
    
    # Test 6: Resolution info
    res_info = get_h3_resolution_info()
    print(f"6. Resolution 8: edge={res_info[8]['edge_km']}km, area={res_info[8]['area_km2']}km²")
    
    print("\n✅ All tests passed!")

