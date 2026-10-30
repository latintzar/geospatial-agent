"""
Leo Spatial Utilities - AOI Manager (Cloud-Native)
==================================================

Area of Interest (AOI) Manager for the Agentic Maps pipeline.
This is STEP 1 of the 5-Step Agentic Sandwich:

    1. Define AOI     ← THIS MODULE
    2. Gather Data
    3. Compute Analysis
    4. Visualization
    5. Storytelling

Every user request must first be converted into a geometry (AOI).
This module handles that conversion with smart defaults.

ARCHITECTURE:
-------------
Uses AWS Athena to query Overture Maps data directly. This provides:
- ROBUST: No rate limits, no flaky external APIs
- PRECISE: SQL-level filtering (subtype, hierarchy_level)
- SCALABLE: Works for "Tokyo" or rural village the same way
- FIXES "Tokyo Problem": Proper hierarchy ordering (city > prefecture)

UX PHILOSOPHY: "Focus + Context" (Google Earth Style)
------------------------------------------------------
Instead of hard-clipping data at AOI boundaries, we return TWO geometries:

    1. FOCUS: The exact boundary (e.g., Berlin city limits)
       - Data inside is shown at 100% opacity
       - This is what the user asked for
       
    2. CONTEXT: An expanded bounding box (1.5x larger)
       - Data outside focus but inside context is shown at 50% opacity
       - This provides "breathing room" and organic transitions

Classes:
    AOIManager: Core class for AOI operations
    
Functions:
    - get_aoi: Convert location query to focus polygon + context bbox
    - create_corridor: Create buffered route corridor ("Search Tunnel")
    - mask_layer_by_aoi: Mark data as inside/outside (NOT delete)

Dependencies:
    - shapely: Geometry operations
    - pyproj: Accurate meter-based buffering
    - tools.tools_athena: AWS Athena boundary fetching
    - tools.tools_routes: Route calculation
    - utils_h3: H3 hexagon utilities

Usage:
    from utils_spatial import AOIManager
    
    aoi = AOIManager()
    
    # Get AOI for a city (returns focus + context)
    result = aoi.get_aoi("Tokyo")
    focus = result['focus_geometry']   # Exact city boundary
    context = result['context_bbox']   # Expanded bbox for data fetching
    
    # Mask data (marks is_inside, doesn't delete)
    masked = aoi.mask_layer_by_aoi(h3_data, focus)
"""

import os
import json
import logging
from typing import Dict, List, Optional, Union, Any, Literal
from dataclasses import dataclass

from shapely.geometry import shape, mapping, Point, LineString, Polygon, MultiPolygon
from shapely.ops import transform
from shapely.prepared import prep
import pyproj
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# IMPORTS - Athena Engine (Cloud-Native)
# =============================================================================

try:
    from .tools.tools_athena import AthenaEngine, get_smart_boundary as athena_get_boundary
    from .tools.tools_routes import get_transport_route
    from .utils_h3 import h3_to_geojson, point_to_h3
except ImportError:
    from tools.tools_athena import AthenaEngine, get_smart_boundary as athena_get_boundary
    from tools.tools_routes import get_transport_route
    from utils_h3 import h3_to_geojson, point_to_h3

logger.info("🌐 AOI Manager: Cloud-Native (Athena) backend")

# =============================================================================
# CONSTANTS
# =============================================================================

# Default buffer distances (in meters)
BUFFER_POINT_M = 2000      # 2km for point locations
BUFFER_LINE_M = 200        # 200m for linear features
BUFFER_CORRIDOR_KM = 5     # 5km default for route corridors

# Context expansion factor (for "breathing room")
CONTEXT_EXPANSION_FACTOR = 1.5

# Geometry types
POLYGON_TYPES = ('Polygon', 'MultiPolygon')
LINE_TYPES = ('LineString', 'MultiLineString')
POINT_TYPES = ('Point', 'MultiPoint')

# =============================================================================
# COMPLEXITY THRESHOLDS
# =============================================================================

COMPLEXITY_HIGH_KM2 = 500       # > 500 km² = Large city/metro
COMPLEXITY_MASSIVE_KM2 = 10000  # > 10,000 km² = Region/Country

COMPLEXITY_LEVELS = {
    'low': 'Small area - all tools safe to use',
    'normal': 'Medium area - all tools generally safe',
    'high': 'Large area (>500 km²) - prefer aggregated data',
    'massive': 'Very large area (>10,000 km²) - use only lightweight tools',
}


# =============================================================================
# AOI MANAGER CLASS
# =============================================================================

class AOIManager:
    """
    Area of Interest Manager - Cloud-Native Edition.
    
    Uses AWS Athena to query Overture Maps for boundaries.
    Returns Focus + Context geometries (Google Earth style).
    
    Example:
        >>> aoi = AOIManager()
        >>> 
        >>> # Get Tokyo city (not prefecture!)
        >>> result = aoi.get_aoi("Tokyo", prefer_type="city")
        >>> print(result['focus_geometry']['type'])  # 'Polygon'
        >>> 
        >>> # Use context_bbox for data fetching
        >>> fetch_bbox = result['context_bbox']
    """
    
    def __init__(self):
        """Initialize AOI Manager with Athena engine."""
        self._athena_engine = None
        logger.info("🎯 AOIManager initialized (Athena backend)")
    
    @property
    def athena_engine(self) -> AthenaEngine:
        """Lazy-load the Athena engine."""
        if self._athena_engine is None:
            self._athena_engine = AthenaEngine()
        return self._athena_engine
    
    # =========================================================================
    # CORE METHOD: get_aoi
    # =========================================================================
    
    def get_aoi(
        self,
        query: str,
        prefer_type: Literal['auto', 'city', 'neighborhood', 'region'] = 'auto',
        country_filter: Optional[str] = None,
        context_expansion: float = CONTEXT_EXPANSION_FACTOR,
    ) -> Dict[str, Any]:
        """
        Get Area of Interest with Focus + Context (Google Earth style).
        
        Queries AWS Athena for Overture divisions, returns:
        1. FOCUS: The exact boundary (full opacity data)
        2. CONTEXT: Expanded bbox for "breathing room" (dimmed data)
        
        FIXES "Tokyo Problem":
        - prefer_type='city' excludes prefectures/regions
        - Hierarchy ordering: locality > neighborhood > region
        
        Args:
            query: Location name (e.g., "Tokyo", "Berlin", "Hackney")
            prefer_type: Boundary type preference:
                - 'auto': Algorithm decides (prefers locality/neighborhood)
                - 'city': Force city/locality (excludes regions)
                - 'neighborhood': Force neighborhood level
                - 'region': Force region/state level
            country_filter: Optional country name to disambiguate
            context_expansion: How much to expand context bbox (default 1.5x)
            
        Returns:
            dict with:
                # Focus (exact boundary - 100% opacity)
                - focus_geometry: GeoJSON Polygon/MultiPolygon
                - focus_bbox: [min_lon, min_lat, max_lon, max_lat]
                
                # Context (expanded - 50% opacity breathing room)
                - context_bbox: Expanded bounding box
                - context_geometry: GeoJSON Polygon of context
                
                # Backwards compatibility
                - geometry: Same as focus_geometry
                - bbox: Same as focus_bbox
                
                # Metadata
                - display_name: Location name
                - subtype: Division type (locality, neighborhood, etc.)
                - area_km2: Approximate area
                - complexity: Tool selection hint
                - shapely_geom: Shapely geometry for operations
                
        Example:
            >>> aoi = AOIManager()
            >>> 
            >>> # Get Tokyo city (not Tokyo Prefecture!)
            >>> result = aoi.get_aoi("Tokyo", prefer_type="city")
            >>> print(result['subtype'])  # "locality"
            >>> 
            >>> # Use context_bbox for data fetching
            >>> fetch_bbox = result['context_bbox']
            >>> cafes = athena.fetch_infrastructure_sql(fetch_bbox, "cafe")
            >>> 
            >>> # Mask data by focus boundary
            >>> masked = aoi.mask_layer_by_aoi(cafes, result['focus_geometry'])
        """
        logger.info(f"🎯 AOIManager.get_aoi: {query}")
        logger.info(f"   prefer_type={prefer_type}, country={country_filter}")
        
        # Query Athena for boundary
        # Map prefer_type to type_hint (get_smart_boundary uses 'type_hint' not 'prefer_type')
        type_hint_map = {
            'auto': 'city',  # Default to city when auto
            'city': 'city',
            'neighborhood': 'neighborhood',
            'region': 'region',
        }
        type_hint = type_hint_map.get(prefer_type, 'city')
        
        boundary = self.athena_engine.get_smart_boundary(
            query=query,
            type_hint=type_hint,
            country_filter=country_filter,
            context_expansion=context_expansion,
        )
        
        logger.info(f"   ✅ Found: {boundary.name} ({boundary.subtype})")
        logger.info(f"   📐 Area: {boundary.area_km2:.2f} km²")
        logger.info(f"   📐 Focus bbox: {[round(b, 4) for b in boundary.focus_bbox]}")
        logger.info(f"   📐 Context bbox: {[round(b, 4) for b in boundary.context_bbox]}")
        
        # Calculate complexity
        complexity = self._calculate_complexity(boundary.area_km2)
        logger.info(f"   🎚️ Complexity: {complexity.upper()}")
        
        # Create Shapely geometry for operations
        shapely_geom = shape(boundary.focus_geometry)
        
        # Create context_geometry from context_bbox if not provided
        # (BoundaryResult may not have context_geometry attribute)
        context_geometry = getattr(boundary, 'context_geometry', None)
        if context_geometry is None and boundary.context_bbox:
            # Create a polygon from the context bbox
            minx, miny, maxx, maxy = boundary.context_bbox
            context_geometry = {
                "type": "Polygon",
                "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]
            }
        
        return {
            # Focus (exact boundary)
            'focus_geometry': boundary.focus_geometry,
            'focus_bbox': boundary.focus_bbox,
            
            # Context (expanded bbox)
            'context_bbox': boundary.context_bbox,
            'context_geometry': context_geometry,
            'context_expansion': getattr(boundary, 'context_expansion', context_expansion),
            
            # Backwards compatibility
            'geometry': boundary.focus_geometry,
            'bbox': boundary.focus_bbox,
            
            # Metadata
            'display_name': boundary.name,
            'subtype': boundary.subtype,
            'hierarchy_level': getattr(boundary, 'hierarchy_level', None),  # May not exist
            'area_km2': boundary.area_km2,
            'complexity': complexity,
            'complexity_hint': COMPLEXITY_LEVELS.get(complexity, ''),
            'shapely_geom': shapely_geom,
            'source': getattr(boundary, 'source', 'athena'),
            'query_time_ms': getattr(boundary, 'query_time_ms', 0),
            
            # Additional metadata
            'id': getattr(boundary, 'id', 'unknown'),
            'was_buffered': False,  # Athena returns actual polygons
            'original_geometry_type': boundary.focus_geometry.get('type', 'Polygon'),
        }
    
    # =========================================================================
    # CORRIDOR METHOD: create_corridor
    # =========================================================================
    
    def create_corridor(
        self,
        start_location: str,
        end_location: str,
        buffer_km: float = BUFFER_CORRIDOR_KM,
        transport_mode: str = 'driving',
    ) -> Dict[str, Any]:
        """
        Create a buffered corridor along a route - the "Search Tunnel".
        
        Uses OSRM routing to get the actual road path, then buffers it
        to create a polygon search area along the route.
        
        Args:
            start_location: Starting point (e.g., "Madrid")
            end_location: Ending point (e.g., "Barcelona")
            buffer_km: Buffer distance in km (default 5km)
            transport_mode: 'driving', 'walking', or 'cycling'
            
        Returns:
            dict with:
                - geometry: GeoJSON Polygon (buffered corridor)
                - bbox: [min_lon, min_lat, max_lon, max_lat]
                - route_geometry: Original LineString
                - distance_km: Route distance
                - duration_hours: Estimated travel time
                - shapely_geom: Shapely polygon
                
        Example:
            >>> corridor = aoi.create_corridor("Kumasi", "Tema Port", buffer_km=10)
        """
        logger.info(f"🛤️ AOIManager.create_corridor")
        logger.info(f"   From: {start_location}")
        logger.info(f"   To: {end_location}")
        logger.info(f"   Buffer: {buffer_km}km")
        
        # Geocode start and end using Athena
        start_result = self.athena_engine.get_smart_boundary(start_location)
        start_geom = shape(start_result.focus_geometry)
        start_centroid = start_geom.centroid
        start_coords = (start_centroid.y, start_centroid.x)  # (lat, lon)
        logger.info(f"   Start: {start_result.name} ({start_coords[0]:.4f}, {start_coords[1]:.4f})")
        
        end_result = self.athena_engine.get_smart_boundary(end_location)
        end_geom = shape(end_result.focus_geometry)
        end_centroid = end_geom.centroid
        end_coords = (end_centroid.y, end_centroid.x)
        logger.info(f"   End: {end_result.name} ({end_coords[0]:.4f}, {end_coords[1]:.4f})")
        
        # Get route from OSRM
        route_json = get_transport_route(
            start_lat=start_coords[0],
            start_lon=start_coords[1],
            end_lat=end_coords[0],
            end_lon=end_coords[1],
            transport_mode=transport_mode
        )
        
        route_data = json.loads(route_json)
        
        if route_data.get('error'):
            raise ValueError(f"Route error: {route_data.get('message', 'Unknown')}")
        
        route_geometry = route_data['geometry']
        route_props = route_data['properties']
        logger.info(f"   Route: {route_props['distance_km']}km, {route_props['duration_hours']}h")
        
        # Buffer the route
        route_line = shape(route_geometry)
        buffer_meters = buffer_km * 1000
        corridor_polygon = self._buffer_geometry_meters(route_line, buffer_meters)
        
        # Calculate bounds and area
        bounds = corridor_polygon.bounds
        bbox = [bounds[0], bounds[1], bounds[2], bounds[3]]
        area_km2 = self._calculate_area_km2(corridor_polygon)
        complexity = self._calculate_complexity(area_km2)
        
        logger.info(f"   ✅ Corridor: {area_km2:.2f} km², complexity={complexity}")
        
        return {
            'geometry': mapping(corridor_polygon),
            'bbox': bbox,
            'route_geometry': route_geometry,
            'distance_km': route_props['distance_km'],
            'duration_hours': route_props['duration_hours'],
            'duration_minutes': route_props['duration_minutes'],
            'buffer_km': buffer_km,
            'shapely_geom': corridor_polygon,
            'area_km2': area_km2,
            'complexity': complexity,
            'complexity_hint': COMPLEXITY_LEVELS.get(complexity, ''),
            'start_point': [start_coords[1], start_coords[0]],
            'end_point': [end_coords[1], end_coords[0]],
            'start_name': start_result.name,
            'end_name': end_result.name,
            'transport_mode': transport_mode,
        }
    
    # =========================================================================
    # MASKING METHOD: mask_layer_by_aoi
    # =========================================================================
    
    def mask_layer_by_aoi(
        self,
        layer_data: Union[List[Dict], Dict],
        aoi_polygon: Union[Dict, Polygon, MultiPolygon],
    ) -> Union[List[Dict], Dict]:
        """
        Mark spatial data as inside/outside AOI - the "Spotlight" effect.
        
        Adds 'is_inside' property to each feature. Frontend can then:
        - Show is_inside=True at 100% opacity (Focus)
        - Show is_inside=False at 50% opacity (Context)
        
        Works with:
        - H3 hexagon data: [{'hex': 'abc...', 'value': 100}, ...]
        - Point data: [{'lat': 40.7, 'lon': -74.0, ...}, ...]
        - GeoJSON FeatureCollection
        
        Args:
            layer_data: Data to mask
            aoi_polygon: Focus AOI (GeoJSON dict or Shapely geometry)
                
        Returns:
            Same format as input, with 'is_inside' added.
            Data is NOT deleted - just marked.
            
        Example:
            >>> result = aoi.get_aoi("Berlin")
            >>> h3_data = fetch_h3_data(result['context_bbox'])
            >>> masked = aoi.mask_layer_by_aoi(h3_data, result['focus_geometry'])
            >>> inside_count = sum(1 for d in masked if d['is_inside'])
        """
        logger.info(f"🎯 AOIManager.mask_layer_by_aoi")
        
        # Convert AOI to Shapely if needed
        if isinstance(aoi_polygon, dict):
            aoi_geom = shape(aoi_polygon)
        else:
            aoi_geom = aoi_polygon
        
        # Prepare for fast intersection tests
        prepared_aoi = prep(aoi_geom)
        
        # Detect format and process
        if isinstance(layer_data, dict) and layer_data.get('type') == 'FeatureCollection':
            return self._mask_feature_collection(layer_data, prepared_aoi, aoi_geom)
        elif isinstance(layer_data, list):
            if not layer_data:
                return []
            
            first_item = layer_data[0]
            
            if 'hex' in first_item:
                return self._mask_h3_data(layer_data, prepared_aoi, aoi_geom)
            elif 'lat' in first_item or 'latitude' in first_item:
                return self._mask_point_list(layer_data, prepared_aoi)
            elif 'geometry' in first_item:
                return self._mask_feature_list(layer_data, prepared_aoi, aoi_geom)
            else:
                return [{**item, 'is_inside': True} for item in layer_data]
        else:
            return layer_data
    
    def _mask_h3_data(self, h3_data: List[Dict], prepared_aoi, aoi_geom) -> List[Dict]:
        """Mark H3 hexagons with is_inside."""
        masked = []
        inside_count = 0
        
        for item in h3_data:
            hex_id = item.get('hex')
            if not hex_id:
                masked.append({**item, 'is_inside': False})
                continue
            
            try:
                hex_geojson = h3_to_geojson(hex_id)
                hex_polygon = shape(hex_geojson)
                is_inside = prepared_aoi.intersects(hex_polygon)
                masked.append({**item, 'is_inside': is_inside})
                if is_inside:
                    inside_count += 1
            except Exception:
                masked.append({**item, 'is_inside': False})
        
        logger.info(f"   H3: {len(h3_data)} total, {inside_count} focus")
        return masked
    
    def _mask_point_list(self, point_data: List[Dict], prepared_aoi) -> List[Dict]:
        """Mark points with is_inside."""
        masked = []
        inside_count = 0
        
        for item in point_data:
            lat = item.get('lat') or item.get('latitude')
            lon = item.get('lon') or item.get('lng') or item.get('longitude')
            
            if lat is None or lon is None:
                masked.append({**item, 'is_inside': False})
                continue
            
            point = Point(lon, lat)
            is_inside = prepared_aoi.contains(point)
            masked.append({**item, 'is_inside': is_inside})
            if is_inside:
                inside_count += 1
        
        logger.info(f"   Points: {len(point_data)} total, {inside_count} focus")
        return masked
    
    def _mask_feature_collection(self, fc: Dict, prepared_aoi, aoi_geom) -> Dict:
        """Mark FeatureCollection features with is_inside."""
        features = fc.get('features', [])
        masked_features = []
        inside_count = 0
        
        for feature in features:
            geom = feature.get('geometry')
            is_inside = False
            
            if geom:
                try:
                    shapely_geom = shape(geom)
                    is_inside = prepared_aoi.intersects(shapely_geom)
                except Exception:
                    pass
            
            masked_features.append({
                **feature,
                'properties': {**feature.get('properties', {}), 'is_inside': is_inside}
            })
            if is_inside:
                inside_count += 1
        
        logger.info(f"   Features: {len(features)} total, {inside_count} focus")
        return {'type': 'FeatureCollection', 'features': masked_features}
    
    def _mask_feature_list(self, features: List[Dict], prepared_aoi, aoi_geom) -> List[Dict]:
        """Mark feature list with is_inside."""
        masked = []
        inside_count = 0
        
        for feature in features:
            geom = feature.get('geometry')
            is_inside = False
            
            if geom:
                try:
                    shapely_geom = shape(geom)
                    is_inside = prepared_aoi.intersects(shapely_geom)
                except Exception:
                    pass
            
            masked.append({
                **feature,
                'properties': {**feature.get('properties', {}), 'is_inside': is_inside}
            })
            if is_inside:
                inside_count += 1
        
        logger.info(f"   Features: {len(features)} total, {inside_count} focus")
        return masked
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _buffer_geometry_meters(self, geom, buffer_meters: float):
        """Buffer geometry by meters using UTM projection."""
        centroid = geom.centroid
        utm_zone = int((centroid.x + 180) / 6) + 1
        hemisphere = 'north' if centroid.y >= 0 else 'south'
        
        wgs84 = pyproj.CRS('EPSG:4326')
        utm = pyproj.CRS(f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84')
        
        project_to_utm = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
        project_to_wgs84 = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True).transform
        
        geom_utm = transform(project_to_utm, geom)
        buffered_utm = geom_utm.buffer(buffer_meters)
        return transform(project_to_wgs84, buffered_utm)
    
    def _calculate_area_km2(self, geom) -> float:
        """Calculate area in km² using UTM projection."""
        try:
            centroid = geom.centroid
            utm_zone = int((centroid.x + 180) / 6) + 1
            hemisphere = 'north' if centroid.y >= 0 else 'south'
            
            wgs84 = pyproj.CRS('EPSG:4326')
            utm = pyproj.CRS(f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84')
            
            project_to_utm = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform
            geom_utm = transform(project_to_utm, geom)
            
            return round(geom_utm.area / 1_000_000, 2)
        except Exception as e:
            logger.warning(f"Could not calculate area: {e}")
            return 0.0
    
    def _calculate_complexity(self, area_km2: float) -> str:
        """Calculate complexity level for tool selection hints."""
        if area_km2 > COMPLEXITY_MASSIVE_KM2:
            return 'massive'
        elif area_km2 > COMPLEXITY_HIGH_KM2:
            return 'high'
        elif area_km2 > 10:
            return 'normal'
        else:
            return 'low'
    
    def close(self):
        """Close connections."""
        self._athena_engine = None
        logger.info("AOIManager closed")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_aoi(
    query: str,
    prefer_type: str = 'auto',
    country_filter: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Convenience function to get AOI.
    
    Returns focus_geometry (exact boundary) and context_bbox 
    (expanded for breathing room).
    """
    manager = AOIManager()
    try:
        return manager.get_aoi(query, prefer_type, country_filter, **kwargs)
    finally:
        manager.close()


def create_corridor(
    start_location: str,
    end_location: str,
    buffer_km: float = BUFFER_CORRIDOR_KM,
    **kwargs
) -> Dict[str, Any]:
    """Convenience function to create corridor."""
    manager = AOIManager()
    try:
        return manager.create_corridor(start_location, end_location, buffer_km, **kwargs)
    finally:
        manager.close()


def mask_layer_by_aoi(
    layer_data: Union[List[Dict], Dict],
    aoi_polygon: Union[Dict, Polygon, MultiPolygon],
) -> Union[List[Dict], Dict]:
    """
    Convenience function to mask data with is_inside property.
    
    Focus data (is_inside=True) → 100% opacity
    Context data (is_inside=False) → 50% opacity
    """
    manager = AOIManager()
    return manager.mask_layer_by_aoi(layer_data, aoi_polygon)


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🎯 AOI Manager - Cloud-Native Test Suite")
    print("=" * 70)
    
    # Check for AWS credentials
    if not os.getenv('AWS_ACCESS_KEY_ID'):
        print("\n⚠️ AWS credentials not found in environment.")
        print("   Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        print("=" * 70)
        exit(0)
    
    manager = AOIManager()
    
    # Test 1: Tokyo (city, not prefecture)
    print("\n🏙️ Test 1: Tokyo City (not Prefecture)")
    print("-" * 50)
    try:
        result = manager.get_aoi("Tokyo", prefer_type="city")
        print(f"   Name: {result['display_name']}")
        print(f"   Subtype: {result['subtype']}")
        print(f"   Area: {result['area_km2']} km²")
        print(f"   Focus bbox: {[round(b, 3) for b in result['focus_bbox']]}")
        print(f"   Context bbox: {[round(b, 3) for b in result['context_bbox']]}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Berlin
    print("\n🏙️ Test 2: Berlin")
    print("-" * 50)
    try:
        result = manager.get_aoi("Berlin")
        print(f"   Name: {result['display_name']}")
        print(f"   Area: {result['area_km2']} km²")
        print(f"   Complexity: {result['complexity']}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Hackney neighborhood
    print("\n🏘️ Test 3: Hackney (Neighborhood)")
    print("-" * 50)
    try:
        result = manager.get_aoi("Hackney", prefer_type="neighborhood", country_filter="United Kingdom")
        print(f"   Name: {result['display_name']}")
        print(f"   Subtype: {result['subtype']}")
        print(f"   Area: {result['area_km2']} km²")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    manager.close()
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)
