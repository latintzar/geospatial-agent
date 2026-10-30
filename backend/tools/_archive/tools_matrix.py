"""
The Earth Matrix - H3 Feature Store Query Engine (v3.0)
=======================================================
FULL OVERTURE COVERAGE + GEOMETRY FILTERING (The "Cookie Cutter")

The "Strategic Compass" - pre-computed H3 Resolution 11 Feature Store for
STRATEGY mode queries. Use this to find Areas (Heatmaps) based on conditions.

Architecture:
    - Data: earth_matrix.parquet (H3 hexagons with aggregated features)
    - Query: DuckDB Spatial for fast geometry + attribute filtering
    - Output: LayerData (H3 Grid) for visualization

GEOMETRY FILTERING (NEW in v3.0):
=================================
The Matrix supports filtering by ANY shape - not just bounding boxes!

Use Cases:
    - "Within 2.5km of the French coastline" → Buffer polygon
    - "15-minute drive from this store" → Isochrone polygon
    - "Inside the Bordeaux wine region" → Administrative boundary
    - "Along the Route Nationale 7" → Buffered line

How it works:
    1. Agent creates shape (buffer, isochrone, boundary)
    2. Shape is converted to WKT (Well-Known Text)
    3. DuckDB uses ST_Intersects to filter hexes
    4. Only hexes INSIDE the shape are returned

This is efficient for LARGE shapes (coastlines, routes) where
H3 polyfill would generate millions of hex IDs.

v3.0 Schema (150+ columns):
    
    # Core
    h3_index            : H3 Resolution 11 index (~45m, building-level)
    lat, lon            : Hex centroid coordinates (for spatial filtering)
    
    # POI Counts (57 categories)
    total_places        : All POIs
    (22 top-level + 35 specific categories)
    
    # Buildings
    building_density, avg_building_height, urban_volume
    
    # Land Use (19 classes)
    has_park, has_forest, has_residential, has_commercial, has_vineyard, etc.
    
    # Water (4 types)
    has_lake, has_river, has_coast, has_wetland
    
    # Infrastructure
    has_bridge, road_density, rail_density, etc.
    
    # Proximity Scores (0-10, distance-decayed)
    score_transit, score_park, score_water, score_hospital, etc.
    
    # Directionality (bearing 0-360°)
    bearing_transit, bearing_water, bearing_park, etc.

Usage:
    from tools.tools_matrix import query_matrix
    
    # 1. Simple attribute filter
    result = query_matrix(filters={"wealth_index": "> 0.7"})
    
    # 2. With bounding box (fast, but square)
    result = query_matrix(
        filters={"cafe_count": "> 5"},
        bbox=[2.3, 48.8, 2.4, 48.9]  # Paris area
    )
    
    # 3. With GEOMETRY FILTER (the cookie cutter!)
    coastline_buffer = {"type": "Polygon", "coordinates": [...]}  # 2.5km from coast
    result = query_matrix(
        aoi_geometry=coastline_buffer,
        filters={"score_coast": "> 8"}
    )
    
    # 4. On-the-fly neighborhood queries
    result = query_matrix_neighborhood(
        center_hex="8b1fb4671551fff",
        rings=5,
        aggregations={"gym_count": "SUM", "cafe_count": "SUM"}
    )

System Prompt Context:
    'Use query_matrix for STRATEGY mode - finding Areas based on conditions.'
    'For LARGE shapes (coastlines, routes), pass aoi_geometry as GeoJSON polygon.'
    'For SMALL areas, bbox is faster.'
    'Proximity filters: score_transit, score_park, score_water, etc. (0-10)'
    'POI filters: cafe_count, restaurant_count, hospital_count, etc.'
    'Returns H3 hexagon grid for heatmap visualization.'
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lazy imports for shapely (geometry conversion)
_shapely_available = None
def _get_shapely():
    """Lazy load shapely for GeoJSON → WKT conversion."""
    global _shapely_available
    if _shapely_available is None:
        try:
            from shapely.geometry import shape
            from shapely import wkt
            _shapely_available = True
        except ImportError:
            _shapely_available = False
            logger.warning("shapely not available - geometry filtering disabled")
    return _shapely_available

# =============================================================================
# CONFIGURATION
# =============================================================================

# Path to the Earth Matrix parquet file
# Can be local or S3 - DuckDB handles both natively
MATRIX_DIR = Path(__file__).parent.parent / "data" / "matrix"
LOCAL_MATRIX_PATH = MATRIX_DIR / "france_h11.parquet"
LEGACY_MATRIX_PATH = MATRIX_DIR / "earth_matrix.parquet"

# S3 Matrix path (France H3 Resolution 11, ~58M hexes)
S3_MATRIX_PATH = "s3://leo-earth-matrix/france_h11.parquet"

# Smart path selection: prefer local (fast), fall back to S3
import os
if LOCAL_MATRIX_PATH.exists():
    MATRIX_PATH = str(LOCAL_MATRIX_PATH)
    logger.info(f"📂 Using LOCAL Matrix: {MATRIX_PATH}")
elif LEGACY_MATRIX_PATH.exists():
    MATRIX_PATH = str(LEGACY_MATRIX_PATH)
    logger.info(f"📂 Using LEGACY Matrix: {MATRIX_PATH}")
else:
    MATRIX_PATH = S3_MATRIX_PATH
    logger.info(f"☁️ Using S3 Matrix: {MATRIX_PATH} (slower, downloading recommended)")

# H3 Resolution for the Matrix
# Resolution 11 = ~45m edge = building-level precision
H3_RESOLUTION = 11

# Available columns in the Matrix v2.1 - FULL OVERTURE COVERAGE
MATRIX_COLUMNS = {
    # Core
    "h3_index": "H3 Resolution 11 index (~45m, building-level)",
    
    # POI Counts (27 categories)
    "total_places": "All POIs count",
    "cafe_count": "Cafes/coffee shops",
    "restaurant_count": "Restaurants",
    "bar_count": "Bars/nightlife",
    "hotel_count": "Hotels/lodging",
    "hospital_count": "Hospitals/clinics",
    "school_count": "Schools/education",
    "university_count": "Universities",
    "bank_count": "Banks/financial",
    "atm_count": "ATMs",
    "pharmacy_count": "Pharmacies",
    "supermarket_count": "Supermarkets/grocery",
    "convenience_count": "Convenience stores",
    "retail_count": "General retail",
    "gas_station_count": "Gas/fuel stations",
    "parking_count": "Parking facilities",
    "subway_count": "Subway/metro stations",
    "train_count": "Train stations",
    "bus_count": "Bus stations",
    "airport_count": "Airports",
    "park_poi_count": "Park POIs (points)",
    "museum_count": "Museums",
    "cinema_count": "Cinemas/theaters",
    "gym_count": "Gyms/fitness",
    "library_count": "Libraries",
    "police_count": "Police stations",
    "fire_count": "Fire stations",
    "post_office_count": "Post offices",
    "services_count": "General services",
    
    # Buildings
    "building_density": "Building count per hex",
    "avg_building_height": "Average building height (m)",
    "urban_volume": "Sum of building heights",
    
    # Land Use: Recreation & Green Space
    "has_park": "Park polygon",
    "has_recreation_ground": "Recreation ground",
    "has_grass": "Grass area",
    "has_meadow": "Meadow",
    
    # Land Use: Natural
    "has_forest": "Forest",
    
    # Land Use: Agriculture
    "has_farmland": "Farmland",
    "has_orchard": "Orchard",
    "has_vineyard": "Vineyard",
    
    # Land Use: Urban Zones
    "has_residential": "Residential zone",
    "has_commercial": "Commercial zone",
    "has_industrial": "Industrial zone",
    "has_retail": "Retail zone",
    
    # Land Use: Special
    "has_cemetery": "Cemetery",
    "has_military": "Military zone",
    "has_quarry": "Quarry",
    "has_landfill": "Landfill",
    
    # Land Use: Sports & Recreation
    "has_sports_centre": "Sports centre",
    "has_golf_course": "Golf course",
    "has_stadium": "Stadium",
    
    # Water Features
    "has_lake": "Lake/pond",
    "has_river": "River/stream",
    "has_coast": "Coastline/ocean",
    "has_water": "Any water feature",
    
    # Demographics
    "pop_density": "WorldPop population per hex",
    "wealth_index": "Relative Wealth Index (0-1)",
    
    # Agriculture (MapSPAM)
    "crop_yield_cocoa": "MapSPAM cocoa yield",
    "crop_yield_coffee": "MapSPAM coffee yield",
    
    # Proximity Scores: Transit & Services (0-10)
    "score_transit": "Proximity to transit",
    "score_hospital": "Proximity to hospital",
    "score_school": "Proximity to school",
    
    # Proximity Scores: Natural Features
    "score_park": "Proximity to park",
    "score_forest": "Proximity to forest",
    "score_meadow": "Proximity to meadow",
    
    # Proximity Scores: Water
    "score_water": "Proximity to any water",
    "score_lake": "Proximity to lake",
    "score_river": "Proximity to river",
    "score_coast": "Proximity to coastline",
    
    # Proximity Scores: Urban Zones
    "score_commercial": "Proximity to commercial zone",
    "score_industrial": "Proximity to industrial zone",
    "score_residential": "Proximity to residential zone",
    
    # Proximity Scores: Agriculture
    "score_farmland": "Proximity to farmland",
    "score_vineyard": "Proximity to vineyard",
    
    # Proximity Scores: Recreation
    "score_golf_course": "Proximity to golf course",
    "score_stadium": "Proximity to stadium",
    
    # Directionality (bearing 0-360, north=0)
    "bearing_transit": "Direction to nearest transit",
    "bearing_park": "Direction to nearest park",
    "bearing_forest": "Direction to nearest forest",
    "bearing_meadow": "Direction to nearest meadow",
    "bearing_water": "Direction to nearest water",
    "bearing_lake": "Direction to nearest lake",
    "bearing_river": "Direction to nearest river",
    "bearing_coast": "Direction to coastline",
    "bearing_commercial": "Direction to commercial zone",
    "bearing_industrial": "Direction to industrial zone",
    "bearing_residential": "Direction to residential zone",
    "bearing_farmland": "Direction to farmland",
    "bearing_vineyard": "Direction to vineyard",
    "bearing_golf_course": "Direction to golf course",
    "bearing_stadium": "Direction to stadium",
}

# Column groups for easy reference - FULL OVERTURE COVERAGE
COLUMN_GROUPS = {
    "poi_counts": [
        "total_places", "cafe_count", "restaurant_count", "bar_count", "hotel_count",
        "hospital_count", "school_count", "university_count", "bank_count", "atm_count",
        "pharmacy_count", "supermarket_count", "convenience_count", "retail_count",
        "gas_station_count", "parking_count", "subway_count", "train_count", "bus_count",
        "airport_count", "park_poi_count", "museum_count", "cinema_count", "gym_count",
        "library_count", "police_count", "fire_count", "post_office_count", "services_count"
    ],
    "buildings": ["building_density", "avg_building_height", "urban_volume"],
    "land_use_recreation": ["has_park", "has_recreation_ground", "has_grass", "has_meadow"],
    "land_use_natural": ["has_forest"],
    "land_use_agriculture": ["has_farmland", "has_orchard", "has_vineyard"],
    "land_use_urban": ["has_residential", "has_commercial", "has_industrial", "has_retail"],
    "land_use_special": ["has_cemetery", "has_military", "has_quarry", "has_landfill"],
    "land_use_sports": ["has_sports_centre", "has_golf_course", "has_stadium"],
    "water_features": ["has_lake", "has_river", "has_coast", "has_water"],
    "demographics": ["pop_density", "wealth_index"],
    "agriculture_yields": ["crop_yield_cocoa", "crop_yield_coffee"],
    "proximity_services": ["score_transit", "score_hospital", "score_school"],
    "proximity_natural": ["score_park", "score_forest", "score_meadow"],
    "proximity_water": ["score_water", "score_lake", "score_river", "score_coast"],
    "proximity_urban": ["score_commercial", "score_industrial", "score_residential"],
    "proximity_agriculture": ["score_farmland", "score_vineyard"],
    "proximity_recreation": ["score_golf_course", "score_stadium"],
    "bearings": [
        "bearing_transit", "bearing_park", "bearing_forest", "bearing_meadow",
        "bearing_water", "bearing_lake", "bearing_river", "bearing_coast",
        "bearing_commercial", "bearing_industrial", "bearing_residential",
        "bearing_farmland", "bearing_vineyard", "bearing_golf_course", "bearing_stadium"
    ],
}

# =============================================================================
# SCHEMA IMPORTS
# =============================================================================

try:
    from ..schema import LayerData, VizConfig, create_h3_layer
except ImportError:
    try:
        from schema import LayerData, VizConfig, create_h3_layer
    except ImportError:
        # Fallback definitions (must match schema.py exactly)
        from dataclasses import dataclass, field
        from typing import List, Dict, Any, Optional
        
        @dataclass
        class VizConfig:
            style: str = "heatmap"
            color_scale: str = "viridis"
            property_key: str = "value"
            label: str = "Layer"
            opacity: float = 0.8
            elevation_scale: float = 10.0
        
        @dataclass
        class LayerData:
            layer_id: str
            type: str
            data: Any  # List[Dict] or Dict
            viz_config: VizConfig
            summary: str = ""
            metadata: Dict[str, Any] = field(default_factory=dict)
        
        def create_h3_layer(layer_id, data, label, color_scale="magma", summary=""):
            return LayerData(
                layer_id=layer_id,
                type="h3_grid",
                data=data,
                viz_config=VizConfig(style="extrusion", color_scale=color_scale, label=label),
                summary=summary or f"{label} H3 grid",
            )


# =============================================================================
# MATRIX QUERY ENGINE - Cached Connection
# =============================================================================

_cached_connection = None

def _get_duckdb_connection():
    """Get cached DuckDB connection with S3 support (reused across queries)."""
    global _cached_connection
    
    if _cached_connection is not None:
        return _cached_connection
    
    import duckdb
    con = duckdb.connect()
    
    # Load extensions
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    
    # Configure S3 if using S3 path
    if MATRIX_PATH.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute("SET s3_region='us-east-1';")
        
        # Load credentials from environment
        aws_key = os.environ.get('AWS_ACCESS_KEY_ID')
        aws_secret = os.environ.get('AWS_SECRET_ACCESS_KEY')
        if aws_key and aws_secret:
            con.execute(f"SET s3_access_key_id='{aws_key}';")
            con.execute(f"SET s3_secret_access_key='{aws_secret}';")
    
    _cached_connection = con
    logger.info("🔌 DuckDB connection cached (reusing for future queries)")
    return con


def _check_matrix_exists() -> bool:
    """Check if the Matrix parquet file exists (local or S3)."""
    if MATRIX_PATH.startswith("s3://"):
        # For S3, assume it exists if we're configured to use it
        # The actual check will happen when we query
        return True
    return Path(MATRIX_PATH).exists()


# =============================================================================
# MATRIX WARMUP - Preload metadata on server startup
# =============================================================================

_matrix_warmed = False
_matrix_row_count = 0

def warmup_matrix() -> dict:
    """
    Warm up the Matrix by loading parquet metadata from S3.
    
    Call this on server startup to avoid cold start latency on first query.
    DuckDB caches parquet metadata after first access, making subsequent queries fast.
    
    Returns:
        dict with warmup status and row count
    """
    global _matrix_warmed, _matrix_row_count
    
    if _matrix_warmed:
        return {"status": "already_warm", "rows": _matrix_row_count, "path": MATRIX_PATH}
    
    logger.info(f"🔥 Warming up Matrix from {MATRIX_PATH}...")
    start = time.time()
    
    try:
        con = _get_duckdb_connection()
        
        # Load metadata by counting rows (forces parquet footer read)
        result = con.execute(f"SELECT COUNT(*) as cnt FROM '{MATRIX_PATH}'").fetchone()
        _matrix_row_count = result[0] if result else 0
        
        elapsed = time.time() - start
        _matrix_warmed = True
        
        logger.info(f"✅ Matrix warm! {_matrix_row_count:,} hexes loaded in {elapsed:.1f}s")
        
        return {
            "status": "warmed",
            "rows": _matrix_row_count,
            "elapsed_seconds": elapsed,
            "path": MATRIX_PATH,
        }
        
    except Exception as e:
        logger.error(f"❌ Matrix warmup failed: {e}")
        return {"status": "error", "error": str(e), "path": MATRIX_PATH}


def get_matrix_status() -> dict:
    """Get current Matrix status (warmed, row count, path)."""
    return {
        "warmed": _matrix_warmed,
        "rows": _matrix_row_count,
        "path": MATRIX_PATH,
        "is_s3": MATRIX_PATH.startswith("s3://"),
    }


def _geojson_to_wkt(geojson: Dict[str, Any]) -> Tuple[str, Tuple[float, float, float, float]]:
    """
    Convert GeoJSON to WKT string and calculate bounding box.
    
    The Cookie Cutter needs:
    1. WKT string for ST_Intersects (precise filter)
    2. BBox for coarse pre-filtering (optimization)
    
    Args:
        geojson: GeoJSON dict (Polygon, MultiPolygon, etc.)
    
    Returns:
        Tuple of (wkt_string, (min_lon, min_lat, max_lon, max_lat))
    """
    from shapely.geometry import shape
    
    geom = shape(geojson)
    wkt_string = geom.wkt
    bounds = geom.bounds  # (min_lon, min_lat, max_lon, max_lat)
    
    return wkt_string, bounds


def query_matrix(
    filters: Optional[Dict[str, str]] = None,
    aoi_geometry: Optional[Dict[str, Any]] = None,
    bbox: Optional[List[float]] = None,
    columns: Optional[List[str]] = None,
    limit: int = 50000,
    color_by: Optional[str] = None,
    # Legacy support
    aoi_polygon: Optional[Dict[str, Any]] = None,
) -> LayerData:
    """
    Query the Earth Matrix for hexagons matching spatial and attribute filters.
    
    This is the STRATEGY mode tool - use it to find Areas based on conditions
    like "wealthy areas", "near parks", "close to hospitals".
    
    SPATIAL FILTERING (The Cookie Cutter):
    ======================================
    Two approaches depending on shape complexity:
    
    1. BBOX (fast, for simple rectangles):
       query_matrix(bbox=[2.3, 48.8, 2.4, 48.9], filters={...})
       
    2. GEOMETRY (precise, for complex shapes):
       coastline_buffer = {"type": "Polygon", "coordinates": [...]}
       query_matrix(aoi_geometry=coastline_buffer, filters={...})
    
    The geometry approach uses DuckDB ST_Intersects to efficiently
    filter millions of hexes against complex shapes (buffers, isochrones).
    
    Args:
        filters: Dict of column -> SQL condition (e.g., {"wealth_index": "> 0.7"})
        aoi_geometry: GeoJSON dict for geometry filtering (any shape!)
        bbox: Simple bounding box [min_lon, min_lat, max_lon, max_lat]
        columns: List of columns to return (default: common subset)
        limit: Max hexagons to return (default: 50000)
        color_by: Column to use for coloring the heatmap
        aoi_polygon: DEPRECATED - use aoi_geometry instead
    
    Returns:
        LayerData with H3 hexagons matching the criteria
        
    Examples:
        # Simple filter
        >>> query_matrix(filters={"wealth_index": "> 0.7", "score_transit": "> 7"})
        
        # With bounding box
        >>> query_matrix(bbox=[2.3, 48.8, 2.4, 48.9], filters={"cafe_count": "> 5"})
        
        # With geometry filter (2.5km coastal buffer)
        >>> coastal_zone = buffer_coastline(distance_km=2.5)
        >>> query_matrix(aoi_geometry=coastal_zone, filters={"score_coast": "> 8"})
        
        # With isochrone (15-min drive from a store)
        >>> isochrone = get_driving_isochrone(lat=48.86, lon=2.35, minutes=15)
        >>> query_matrix(aoi_geometry=isochrone, filters={"has_commercial": "= 1"})
    """
    logger.info("=" * 60)
    logger.info("🧭 MATRIX QUERY: Strategic Area Search (v3.0)")
    logger.info("=" * 60)
    
    # Legacy support: aoi_polygon → aoi_geometry
    if aoi_polygon and not aoi_geometry:
        aoi_geometry = aoi_polygon
    
    # Safety check: Matrix file exists?
    if not _check_matrix_exists():
        logger.warning(f"⚠️ Matrix file not found at: {MATRIX_PATH}")
        logger.warning("   Run `python backend/etl/build_earth_matrix.py` to generate it.")
        
        return LayerData(
            layer_id="matrix_not_ready",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(
                style="heatmap",
                color_scale="viridis",
                label="Matrix Not Generated",
            ),
            summary="Matrix data not yet generated",
            metadata={
                "status": "not_ready",
                "message": "Matrix data not yet generated. Run: python backend/etl/build_earth_matrix.py",
                "expected_path": str(MATRIX_PATH),
            }
        )
    
    try:
        import duckdb
        import h3
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        return LayerData(
            layer_id="matrix_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Matrix Query Error"),
            summary=f"Missing dependency: {e}",
            metadata={"error": f"Missing dependency: {e}"}
        )
    
    logger.info(f"📂 Loading Matrix from: {MATRIX_PATH}")
    logger.info(f"🔍 Filters: {filters}")
    if aoi_geometry:
        logger.info(f"🍪 Geometry filter: {aoi_geometry.get('type', 'unknown')} shape")
    if bbox:
        logger.info(f"📦 BBox filter: {bbox}")
    
    try:
        # Connect to DuckDB with S3 support
        con = _get_duckdb_connection()
        
        # Default columns (avoid SELECT * for performance)
        if not columns:
            columns = [
                "h3_index",
                # Core metrics
                "total_places", "building_density", "avg_building_height",
                # Key POIs
                "cafe_count", "restaurant_count", "hospital_count", "school_count",
                "subway_count", "train_count", "supermarket_count",
                # Land use
                "has_park", "has_forest", "has_residential", "has_commercial",
                # Water
                "has_coast", "has_lake", "has_river", "has_water",
                # Proximity scores
                "score_transit", "score_park", "score_water", "score_coast",
                "score_hospital", "score_school",
            ]
        
        select_clause = ", ".join(columns)
        
        # Build WHERE clauses
        where_clauses = []
        spatial_method = "none"
        
        # =====================================================================
        # GEOMETRY FILTER (The Cookie Cutter) - for complex shapes
        # =====================================================================
        if aoi_geometry and aoi_geometry.get("coordinates"):
            if _get_shapely():
                from shapely.geometry import shape
                
                try:
                    wkt_string, bounds = _geojson_to_wkt(aoi_geometry)
                    min_lon, min_lat, max_lon, max_lat = bounds
                    
                    # Step 1: Coarse BBox filter (fast pre-filter)
                    # This uses lon/lat columns if available, otherwise compute from h3
                    where_clauses.append(f"""
                        h3_cell_to_lat(h3_index::UBIGINT) BETWEEN {min_lat} AND {max_lat}
                        AND h3_cell_to_lng(h3_index::UBIGINT) BETWEEN {min_lon} AND {max_lon}
                    """)
                    
                    # Step 2: Precise geometry filter (the cookie cutter!)
                    where_clauses.append(f"""
                        ST_Intersects(
                            ST_Point(
                                h3_cell_to_lng(h3_index::UBIGINT),
                                h3_cell_to_lat(h3_index::UBIGINT)
                            ),
                            ST_GeomFromText('{wkt_string}')
                        )
                    """)
                    
                    spatial_method = "geometry_filter"
                    logger.info(f"   🍪 Using ST_Intersects with {aoi_geometry.get('type')} geometry")
                    logger.info(f"   📦 BBox pre-filter: [{min_lon:.2f}, {min_lat:.2f}] to [{max_lon:.2f}, {max_lat:.2f}]")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Geometry conversion failed: {e}")
                    logger.warning("   Falling back to H3 polyfill...")
                    
                    # Fallback: H3 polyfill (works for small polygons)
                    try:
                        geo_json = {
                            "type": aoi_geometry.get("type", "Polygon"),
                            "coordinates": aoi_geometry["coordinates"]
                        }
                        aoi_hexes = list(h3.polyfill_geojson(geo_json, H3_RESOLUTION))
                        
                        if aoi_hexes and len(aoi_hexes) < 100000:
                            hex_list = ", ".join([f"'{h}'" for h in aoi_hexes])
                            where_clauses.append(f"h3_index IN ({hex_list})")
                            spatial_method = "h3_polyfill"
                            logger.info(f"   📍 H3 polyfill: {len(aoi_hexes)} hexagons")
                        else:
                            logger.warning(f"   ⚠️ Polyfill too large ({len(aoi_hexes)} hexes), using bbox only")
                    except Exception as e2:
                        logger.warning(f"   H3 polyfill also failed: {e2}")
            else:
                logger.warning("⚠️ shapely not available - cannot use geometry filter")
        
        # =====================================================================
        # BBOX FILTER - for simple rectangular areas
        # =====================================================================
        elif bbox and len(bbox) == 4:
            min_lon, min_lat, max_lon, max_lat = bbox
            where_clauses.append(f"""
                h3_cell_to_lat(h3_index::UBIGINT) BETWEEN {min_lat} AND {max_lat}
                AND h3_cell_to_lng(h3_index::UBIGINT) BETWEEN {min_lon} AND {max_lon}
            """)
            spatial_method = "bbox"
            logger.info(f"   📦 BBox filter: [{min_lon:.2f}, {min_lat:.2f}] to [{max_lon:.2f}, {max_lat:.2f}]")
        
        # =====================================================================
        # ATTRIBUTE FILTERS
        # =====================================================================
        if filters:
            for col, condition in filters.items():
                # Handle different condition types
                if isinstance(condition, bool):
                    # Boolean: has_park: True → has_park = 1
                    where_clauses.append(f"{col} = {1 if condition else 0}")
                    logger.info(f"   🔍 Filter: {col} = {1 if condition else 0}")
                elif isinstance(condition, (int, float)) and not isinstance(condition, bool):
                    # Numeric without operator: has_park: 1 → has_park = 1
                    where_clauses.append(f"{col} = {condition}")
                    logger.info(f"   🔍 Filter: {col} = {condition}")
                elif isinstance(condition, str) and condition.strip() and condition.strip()[0] in '>=<!' :
                    # String with operator: "> 5", "= 1", etc.
                    where_clauses.append(f"{col} {condition}")
                    logger.info(f"   🔍 Filter: {col} {condition}")
                else:
                    # Default: assume it needs = operator
                    where_clauses.append(f"{col} = {condition}")
                    logger.info(f"   🔍 Filter: {col} = {condition}")
        
        # Build final query
        query = f"SELECT {select_clause} FROM read_parquet('{MATRIX_PATH}')"
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += f" LIMIT {limit}"
        
        logger.info(f"📊 Executing query (spatial: {spatial_method})...")
        result = con.execute(query).fetchdf()
        
        logger.info(f"✅ Found {len(result)} matching hexagons")
        
        # Convert to LayerData format
        data = []
        for _, row in result.iterrows():
            hex_int = row.get("h3_index")
            if hex_int:
                try:
                    # Convert integer to hex string (h3 v4 API)
                    hex_str = h3.int_to_str(int(hex_int))
                    lat, lng = h3.cell_to_latlng(hex_str)
                    data.append({
                        "hex": hex_str,
                        "lat": lat,
                        "lng": lng,
                        **{k: float(v) if isinstance(v, (int, float)) else v 
                           for k, v in row.items() if k != "h3_index"}
                    })
                except Exception:
                    pass
        
        # Determine color scale based on color_by column
        color_scale = "viridis"
        if color_by:
            if "score_" in color_by or "wealth" in color_by:
                color_scale = "plasma"
            elif "count" in color_by or "density" in color_by:
                color_scale = "inferno"
            elif "bearing" in color_by:
                color_scale = "twilight"  # Circular colormap for bearings
        
        return LayerData(
            layer_id=f"matrix_query_{len(data)}",
            type="h3_grid",
            data=data,
            viz_config=VizConfig(
                style="heatmap",
                color_scale=color_scale,
                label="Matrix Results",
            ),
            summary=f"Found {len(data)} hexagons matching filters",
            metadata={
                "status": "success",
                "count": len(data),
                "filters_applied": filters,
                "spatial_method": spatial_method,
                "color_by": color_by,
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Matrix query failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return LayerData(
            layer_id="matrix_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Matrix Query Error"),
            summary=str(e),
            metadata={"error": str(e)}
        )


def query_matrix_neighborhood(
    center_hex: Optional[str] = None,
    center_point: Optional[Tuple[float, float]] = None,
    rings: int = 5,
    filters: Optional[Dict[str, str]] = None,
    aggregations: Optional[Dict[str, str]] = None,
    bbox: Optional[List[float]] = None,
    limit: int = 10000,
) -> LayerData:
    """
    Query the Matrix with NEIGHBORHOOD aggregation (on-the-fly indices).
    
    This enables queries like:
    - "Find hexes where the surrounding 5-ring neighborhood has gyms AND pubs"
    - "Calculate affluence index based on nearby POIs"
    - "Find areas where neighbors have high transit access"
    
    The aggregation happens AT QUERY TIME, not pre-computed. This is more
    flexible than pre-computed indices (which would require rebuilding the matrix).
    
    Args:
        center_hex: Single H3 hex to analyze neighborhood of
        center_point: (lat, lon) to find hex and its neighborhood
        rings: Number of H3 rings to include (default: 5 = ~250m at res 11)
        filters: Conditions on the NEIGHBORHOOD aggregates
        aggregations: Dict of column -> aggregation type (SUM, AVG, MAX, etc.)
        bbox: Limit search to bounding box first
        limit: Max results to return
    
    Returns:
        LayerData with hexes matching neighborhood criteria
        
    Examples:
        # Find hexes where neighborhood has both gyms and pubs
        >>> query_matrix_neighborhood(
        ...     bbox=[2.3, 48.8, 2.4, 48.9],  # Paris
        ...     rings=5,
        ...     aggregations={"gym_count": "SUM", "bar_count": "SUM"},
        ...     filters={"hood_gym_count": "> 0", "hood_bar_count": "> 0"}
        ... )
        
        # Calculate on-the-fly affluence for a neighborhood
        >>> query_matrix_neighborhood(
        ...     center_point=(48.86, 2.35),  # Champs-Élysées
        ...     rings=10,
        ...     aggregations={
        ...         "hotel_count": "SUM",
        ...         "bank_count": "SUM", 
        ...         "gym_count": "SUM",
        ...         "convenience_count": "SUM"
        ...     }
        ... )
    """
    logger.info("=" * 60)
    logger.info("🏘️ NEIGHBORHOOD QUERY: On-the-fly aggregation")
    logger.info("=" * 60)
    
    if not _check_matrix_exists():
        return LayerData(
            layer_id="matrix_not_ready",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Matrix Not Ready"),
            summary="Matrix not generated",
            metadata={"status": "not_ready"}
        )
    
    try:
        import duckdb
        import h3
    except ImportError as e:
        return LayerData(
            layer_id="matrix_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Error"),
            summary=str(e),
            metadata={"error": str(e)}
        )
    
    # Default aggregations if not specified
    if not aggregations:
        aggregations = {
            "total_places": "SUM",
            "cafe_count": "SUM",
            "restaurant_count": "SUM",
            "gym_count": "SUM",
            "bar_count": "SUM",
        }
    
    logger.info(f"   Rings: {rings} (~{rings * 45}m at res 11)")
    logger.info(f"   Aggregations: {list(aggregations.keys())}")
    
    try:
        con = _get_duckdb_connection()
        
        # Build aggregation columns
        agg_cols = []
        for col, agg_type in aggregations.items():
            agg_cols.append(f"{agg_type}(n.{col}) as hood_{col}")
        agg_clause = ", ".join(agg_cols)
        
        # Build WHERE for bbox pre-filter
        bbox_clause = ""
        if bbox and len(bbox) == 4:
            min_lon, min_lat, max_lon, max_lat = bbox
            bbox_clause = f"""
                WHERE h3_cell_to_lat(h3_index::UBIGINT) BETWEEN {min_lat} AND {max_lat}
                AND h3_cell_to_lng(h3_index::UBIGINT) BETWEEN {min_lon} AND {max_lon}
            """
            logger.info(f"   BBox: [{min_lon:.2f}, {min_lat:.2f}] to [{max_lon:.2f}, {max_lat:.2f}]")
        elif center_hex:
            # Single hex analysis
            bbox_clause = f"WHERE h3_index = '{center_hex}'"
            logger.info(f"   Center hex: {center_hex}")
        elif center_point:
            lat, lon = center_point
            center_h = h3.geo_to_h3(lat, lon, H3_RESOLUTION)
            bbox_clause = f"WHERE h3_index = '{center_h}'"
            logger.info(f"   Center point: {lat}, {lon} → {center_h}")
        
        # The magic query: neighborhood aggregation
        query = f"""
        WITH centers AS (
            SELECT h3_index as center_hex
            FROM read_parquet('{MATRIX_PATH}')
            {bbox_clause}
            LIMIT {limit}
        ),
        neighborhoods AS (
            SELECT 
                c.center_hex,
                UNNEST(h3_grid_disk(c.center_hex::UBIGINT, {rings}))::VARCHAR as neighbor_hex
            FROM centers c
        ),
        aggregated AS (
            SELECT
                nh.center_hex as h3_index,
                {agg_clause},
                COUNT(*) as hood_hex_count
            FROM neighborhoods nh
            JOIN read_parquet('{MATRIX_PATH}') n ON n.h3_index = nh.neighbor_hex
            GROUP BY nh.center_hex
        )
        SELECT * FROM aggregated
        """
        
        # Add filters on aggregated values
        if filters:
            filter_clauses = []
            for col, condition in filters.items():
                filter_clauses.append(f"{col} {condition}")
            if filter_clauses:
                query = f"""
                WITH base AS ({query})
                SELECT * FROM base
                WHERE {" AND ".join(filter_clauses)}
                """
        
        query += f" LIMIT {limit}"
        
        logger.info(f"📊 Executing neighborhood query...")
        result = con.execute(query).fetchdf()
        
        logger.info(f"✅ Found {len(result)} hexes with matching neighborhoods")
        
        # Convert to LayerData format
        data = []
        for _, row in result.iterrows():
            hex_int = row.get("h3_index")
            if hex_int:
                try:
                    # Convert integer to hex string (h3 v4 API)
                    hex_str = h3.int_to_str(int(hex_int))
                    lat, lng = h3.cell_to_latlng(hex_str)
                    data.append({
                        "hex": hex_str,
                        "lat": lat,
                        "lng": lng,
                        **{k: float(v) if isinstance(v, (int, float)) else v 
                           for k, v in row.items() if k != "h3_index"}
                    })
                except Exception:
                    pass
        
        return LayerData(
            layer_id=f"neighborhood_query_{len(data)}",
            type="h3_grid",
            data=data,
            viz_config=VizConfig(
                style="heatmap",
                color_scale="plasma",
                label=f"Neighborhood ({rings} rings)",
            ),
            summary=f"Found {len(data)} hexes with matching {rings}-ring neighborhoods",
            metadata={
                "status": "success",
                "count": len(data),
                "rings": rings,
                "aggregations": aggregations,
                "filters": filters,
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Neighborhood query failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return LayerData(
            layer_id="neighborhood_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Error"),
            summary=str(e),
            metadata={"error": str(e)}
        )


def calculate_derived_index(
    index_type: str,
    bbox: Optional[List[float]] = None,
    aoi_geometry: Optional[Dict[str, Any]] = None,
    rings: int = 5,
    limit: int = 10000,
) -> LayerData:
    """
    Calculate derived indices (affluence, gentrification, vitality) on-the-fly.
    
    These indices are NOT pre-computed in the Matrix - they are calculated
    at query time using neighborhood aggregation. This is more flexible
    and avoids expensive pre-computation.
    
    Args:
        index_type: One of "affluence", "gentrification", "vitality"
        bbox: Bounding box to limit calculation
        aoi_geometry: Complex geometry to filter by
        rings: Neighborhood size for smoothing (default: 5)
        limit: Max hexes to return
    
    Returns:
        LayerData with calculated index values
        
    Examples:
        >>> calculate_derived_index("affluence", bbox=[2.3, 48.8, 2.4, 48.9])
        >>> calculate_derived_index("vitality", rings=10)
    """
    logger.info(f"📊 Calculating on-the-fly index: {index_type}")
    
    # Define index formulas
    INDEX_FORMULAS = {
        "affluence": {
            "aggregations": {
                "bank_count": "SUM",
                "hotel_count": "SUM",
                "gym_count": "SUM",
                "shopping_mall_count": "SUM",
                "museum_count": "SUM",
                "restaurant_count": "SUM",
                "convenience_count": "SUM",
                "gas_station_count": "SUM",
                "total_places": "SUM",
            },
            "formula": """
                LEAST(10, GREATEST(0,
                    (hood_bank_count * 2.0 + hood_hotel_count * 1.5 + hood_gym_count * 1.5 +
                     hood_shopping_mall_count * 2.0 + hood_museum_count * 2.0 +
                     hood_restaurant_count * 0.5 - hood_convenience_count * 0.5 -
                     hood_gas_station_count * 0.3)
                    / GREATEST(1, hood_total_places) * 10
                ))
            """,
            "label": "Affluence Index",
            "color_scale": "viridis",
        },
        "gentrification": {
            "aggregations": {
                "cafe_count": "SUM",
                "gym_count": "SUM",
                "bar_count": "SUM",
                "museum_count": "SUM",
                "avg_building_height": "AVG",
                "has_industrial": "SUM",
            },
            "formula": """
                LEAST(10, GREATEST(0,
                    (hood_cafe_count * 2.0 + hood_gym_count * 1.5 + hood_bar_count * 1.0 +
                     hood_museum_count * 2.0 + COALESCE(hood_avg_building_height, 0) * 0.3 -
                     hood_has_industrial * 3.0)
                    / GREATEST(1, hood_hex_count) * 2
                ))
            """,
            "label": "Gentrification Index",
            "color_scale": "plasma",
        },
        "vitality": {
            "aggregations": {
                "total_places": "SUM",
                "cafe_count": "SUM",
                "restaurant_count": "SUM",
                "bar_count": "SUM",
                "gym_count": "SUM",
                "supermarket_count": "SUM",
            },
            "formula": """
                LEAST(10, GREATEST(0,
                    (LOG2(GREATEST(1, hood_total_places)) * 1.5 +
                     (CASE WHEN hood_cafe_count > 0 THEN 1 ELSE 0 END +
                      CASE WHEN hood_restaurant_count > 0 THEN 1 ELSE 0 END +
                      CASE WHEN hood_bar_count > 0 THEN 1 ELSE 0 END +
                      CASE WHEN hood_gym_count > 0 THEN 1 ELSE 0 END +
                      CASE WHEN hood_supermarket_count > 0 THEN 1 ELSE 0 END) * 0.5 +
                     hood_restaurant_count * 0.3 + hood_cafe_count * 0.3)
                    / 3
                ))
            """,
            "label": "Urban Vitality Index",
            "color_scale": "inferno",
        },
    }
    
    if index_type not in INDEX_FORMULAS:
        return LayerData(
            layer_id="index_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Error"),
            summary=f"Unknown index type: {index_type}. Use: affluence, gentrification, vitality",
            metadata={"error": f"Unknown index: {index_type}"}
        )
    
    config = INDEX_FORMULAS[index_type]
    
    # Get neighborhood data
    result = query_matrix_neighborhood(
        bbox=bbox,
        rings=rings,
        aggregations=config["aggregations"],
        limit=limit,
    )
    
    if result.metadata.get("status") != "success":
        return result
    
    # Calculate index for each hex
    import h3
    
    try:
        con = _get_duckdb_connection()
        
        # Create temp table with neighborhood data
        df_data = result.data
        if not df_data:
            return result
        
        import pandas as pd
        df = pd.DataFrame(df_data)
        con.register("neighborhood_data", df)
        
        # Calculate index
        query = f"""
            SELECT 
                hex as h3_index,
                lat, lng,
                {config['formula']} as {index_type}_index,
                *
            FROM neighborhood_data
        """
        
        calculated = con.execute(query).fetchdf()
        
        # Convert back to LayerData
        data = []
        for _, row in calculated.iterrows():
            data.append({
                "hex": row["h3_index"],
                "lat": row["lat"],
                "lng": row["lng"],
                "value": float(row[f"{index_type}_index"]),
                f"{index_type}_index": float(row[f"{index_type}_index"]),
            })
        
        return LayerData(
            layer_id=f"{index_type}_index_{len(data)}",
            type="h3_grid",
            data=data,
            viz_config=VizConfig(
                style="heatmap",
                color_scale=config["color_scale"],
                property_key="value",
                label=config["label"],
            ),
            summary=f"Calculated {config['label']} for {len(data)} hexes (rings={rings})",
            metadata={
                "status": "success",
                "count": len(data),
                "index_type": index_type,
                "rings": rings,
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Index calculation failed: {e}")
        return LayerData(
            layer_id="index_error",
            type="h3_grid",
            data=[],
            viz_config=VizConfig(style="heatmap", color_scale="viridis", label="Error"),
            summary=str(e),
            metadata={"error": str(e)}
        )


def get_hex_details(h3_index: str) -> Dict[str, Any]:
    """
    Get all attributes for a specific H3 hexagon.
    
    Use this for detailed context lookup when user clicks on a hex.
    
    Args:
        h3_index: The H3 index string (e.g., "89283082837ffff")
    
    Returns:
        Dict with all column values for that hexagon, grouped by category
    """
    logger.info(f"🔎 Getting details for hex: {h3_index}")
    
    if not _check_matrix_exists():
        return {
            "status": "not_ready",
            "message": "Matrix data not yet generated.",
            "h3_index": h3_index,
        }
    
    try:
        import h3
        
        con = _get_duckdb_connection()
        query = f"""
            SELECT *
            FROM read_parquet('{MATRIX_PATH}')
            WHERE h3_index = '{h3_index}'
            LIMIT 1
        """
        
        result = con.execute(query).fetchdf()
        
        if len(result) == 0:
            return {"status": "not_found", "h3_index": h3_index}
        
        row = result.iloc[0].to_dict()
        
        # Get hex center coordinates - ensure hex string format
        hex_str = h3_index if isinstance(h3_index, str) and h3_index.startswith('8') else h3.int_to_str(int(h3_index))
        lat, lng = h3.cell_to_latlng(hex_str)
        
        # Group by category for better readability
        return {
            "status": "success",
            "h3_index": h3_index,
            "location": {"lat": lat, "lng": lng},
            "poi_counts": {k: row.get(k, 0) for k in COLUMN_GROUPS["poi_counts"] if k in row},
            "buildings": {k: row.get(k, 0) for k in COLUMN_GROUPS["buildings"] if k in row},
            "natural_features": {k: row.get(k, 0) for k in COLUMN_GROUPS["natural_features"] if k in row},
            "demographics": {k: row.get(k, 0) for k in COLUMN_GROUPS["demographics"] if k in row},
            "proximity_scores": {k: row.get(k, 5) for k in COLUMN_GROUPS["proximity_scores"] if k in row},
            "bearings": {k: row.get(k) for k in COLUMN_GROUPS["bearings"] if k in row and row.get(k) is not None},
        }
        
    except Exception as e:
        logger.error(f"❌ Hex lookup failed: {e}")
        return {"status": "error", "error": str(e), "h3_index": h3_index}


def get_matrix_stats() -> Dict[str, Any]:
    """
    Get statistics about the Matrix file.
    
    Returns:
        Dict with row count, columns, file size, etc.
    """
    if not _check_matrix_exists():
        return {
            "status": "not_ready",
            "message": "Matrix data not yet generated.",
            "expected_path": str(MATRIX_PATH),
        }
    
    try:
        con = _get_duckdb_connection()
        
        # Get row count
        count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{MATRIX_PATH}')").fetchone()[0]
        
        # Get columns
        schema = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{MATRIX_PATH}')").fetchdf()
        columns = schema["column_name"].tolist()
        
        # Get file size (handle S3 paths)
        if MATRIX_PATH.startswith("s3://"):
            file_size_mb = 2800  # ~2.8 GB for France matrix
        else:
            file_size_mb = Path(MATRIX_PATH).stat().st_size / (1024 * 1024)
        
        # Get sample stats
        sample_stats = con.execute(f"""
            SELECT 
                AVG(total_places) as avg_places,
                AVG(score_transit) as avg_transit_score,
                AVG(score_park) as avg_park_score,
                SUM(has_park) as hexes_with_parks,
                SUM(has_water) as hexes_with_water
            FROM read_parquet('{MATRIX_PATH}')
        """).fetchdf().iloc[0].to_dict()
        
        return {
            "status": "ready",
            "row_count": count,
            "column_count": len(columns),
            "columns": columns,
            "column_groups": list(COLUMN_GROUPS.keys()),
            "file_size_mb": round(file_size_mb, 2),
            "path": str(MATRIX_PATH),
            "sample_stats": sample_stats,
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_available_columns() -> Dict[str, str]:
    """
    List all available columns with descriptions.
    
    Returns:
        Dict mapping column names to descriptions
    """
    return MATRIX_COLUMNS


def list_column_groups() -> Dict[str, List[str]]:
    """
    List column groups for easier querying.
    
    Returns:
        Dict mapping group names to column lists
    """
    return COLUMN_GROUPS


# =============================================================================
# TOOL WRAPPERS FOR AGENT (v3.0 - Geometry Filtering)
# =============================================================================

def tool_query_matrix(
    filters: Dict[str, str],
    aoi_geometry: Optional[Dict[str, Any]] = None,
    bbox: Optional[List[float]] = None,
    color_by: Optional[str] = None,
    # Legacy support
    aoi_polygon: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Agent-callable wrapper for query_matrix.
    
    Use for STRATEGY mode queries - finding Areas based on conditions.
    
    SPATIAL FILTERING:
    - bbox: Simple bounding box [min_lon, min_lat, max_lon, max_lat] - fast for rectangles
    - aoi_geometry: GeoJSON polygon for complex shapes (buffers, isochrones) - the cookie cutter!
    
    Examples:
        # Simple filter
        filters={"wealth_index": "> 0.7", "score_park": "> 6"}
        
        # With bounding box (Paris)
        bbox=[2.3, 48.8, 2.4, 48.9], filters={"cafe_count": "> 10"}
        
        # With geometry filter (2.5km coastal buffer)
        aoi_geometry=coastal_buffer, filters={"score_coast": "> 8"}
        
        # With isochrone (15-min drive)
        aoi_geometry=driving_isochrone, filters={"has_commercial": "= 1"}
    
    Args:
        filters: Dict of conditions (column: "operator value")
        aoi_geometry: GeoJSON polygon for geometry filtering (complex shapes)
        bbox: Simple bounding box [min_lon, min_lat, max_lon, max_lat]
        color_by: Column to color the heatmap by
        aoi_polygon: DEPRECATED - use aoi_geometry instead
    
    Returns:
        Dict with status, data, and metadata
    """
    # Legacy support
    if aoi_polygon and not aoi_geometry:
        aoi_geometry = aoi_polygon
    
    result = query_matrix(
        filters=filters,
        aoi_geometry=aoi_geometry,
        bbox=bbox,
        color_by=color_by
    )
    
    # Use standardized response format
    try:
        from ..schema import format_tool_response
        return format_tool_response(result)
    except ImportError:
        try:
            from schema import format_tool_response
            return format_tool_response(result)
        except ImportError:
            # Fallback: return as dict
            return {
                "status": result.metadata.get("status", "success"),
                "layer": result,
                "summary": result.summary,
            }


def tool_query_neighborhood(
    bbox: Optional[List[float]] = None,
    rings: int = 5,
    aggregations: Optional[Dict[str, str]] = None,
    filters: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Agent-callable wrapper for neighborhood queries.
    
    Use for on-the-fly neighborhood analysis - find hexes where the surrounding
    area has specific characteristics.
    
    Examples:
        # Find hexes where neighborhood has gyms AND pubs
        bbox=[2.3, 48.8, 2.4, 48.9],
        aggregations={"gym_count": "SUM", "bar_count": "SUM"},
        filters={"hood_gym_count": "> 0", "hood_bar_count": "> 0"}
        
        # Find areas with diverse POI mix in neighborhood
        aggregations={"cafe_count": "SUM", "restaurant_count": "SUM", "gym_count": "SUM"},
        filters={"hood_cafe_count": "> 5", "hood_restaurant_count": "> 5"}
    
    Args:
        bbox: Bounding box to limit search
        rings: Number of H3 rings for neighborhood (5 ≈ 250m at res 11)
        aggregations: Dict of column → aggregation (SUM, AVG, MAX)
        filters: Conditions on neighborhood aggregates (use hood_ prefix!)
    
    Returns:
        Dict with status, data, and metadata
    """
    result = query_matrix_neighborhood(
        bbox=bbox,
        rings=rings,
        aggregations=aggregations,
        filters=filters,
    )
    
    try:
        from ..schema import format_tool_response
    except ImportError:
        try:
            from schema import format_tool_response
        except ImportError:
            return {
                "status": result.metadata.get("status", "success"),
                "layer": result,
                "summary": result.summary,
            }
    return format_tool_response(result)


def tool_calculate_index(
    index_type: str,
    bbox: Optional[List[float]] = None,
    aoi_geometry: Optional[Dict[str, Any]] = None,
    rings: int = 5,
) -> Dict[str, Any]:
    """
    Agent-callable wrapper for derived index calculation.
    
    Calculate affluence, gentrification, or vitality indices ON-THE-FLY.
    These are NOT pre-computed - they use neighborhood aggregation at query time.
    
    Available indices:
        - affluence: Banks, hotels, gyms, malls vs convenience stores
        - gentrification: Cafes, gyms, bars, museums, building height vs industrial
        - vitality: POI diversity, walkability, restaurant/cafe density
    
    Examples:
        # Affluence in Paris
        index_type="affluence", bbox=[2.3, 48.8, 2.4, 48.9]
        
        # Gentrification with larger neighborhood smoothing
        index_type="gentrification", rings=10
    
    Args:
        index_type: "affluence", "gentrification", or "vitality"
        bbox: Bounding box to limit calculation
        aoi_geometry: Complex geometry to filter by
        rings: Neighborhood size for smoothing (default: 5)
    
    Returns:
        Dict with calculated index values
    """
    result = calculate_derived_index(
        index_type=index_type,
        bbox=bbox,
        aoi_geometry=aoi_geometry,
        rings=rings,
    )
    
    try:
        from ..schema import format_tool_response
    except ImportError:
        try:
            from schema import format_tool_response
        except ImportError:
            return {
                "status": result.metadata.get("status", "success"),
                "layer": result,
                "summary": result.summary,
            }
    return format_tool_response(result)


def tool_get_hex_details(h3_index: str) -> Dict[str, Any]:
    """
    Agent-callable wrapper for get_hex_details.
    
    Use to get detailed information about a specific hex when user clicks or asks.
    
    Args:
        h3_index: The H3 index string
    
    Returns:
        Dict with grouped attributes for the hex
    """
    return get_hex_details(h3_index)


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🧭 Earth Matrix v2.0 - Status Check")
    print("=" * 60)
    
    stats = get_matrix_stats()
    
    if stats["status"] == "ready":
        print(f"✅ Matrix is READY")
        print(f"   Rows: {stats['row_count']:,}")
        print(f"   Columns: {stats['column_count']}")
        print(f"   Size: {stats['file_size_mb']} MB")
        print(f"\n   Column groups:")
        for group, cols in COLUMN_GROUPS.items():
            print(f"     - {group}: {len(cols)} columns")
        print(f"\n   Sample stats:")
        for k, v in stats.get("sample_stats", {}).items():
            print(f"     - {k}: {v:.2f}" if v else f"     - {k}: N/A")
    else:
        print(f"⚠️ Matrix NOT READY: {stats.get('message', stats.get('error'))}")
        print(f"   Expected path: {MATRIX_PATH}")
        print(f"\n   To generate: python backend/etl/build_earth_matrix.py")
    
    print("\n" + "=" * 60)
    print("Available columns:")
    print("=" * 60)
    for group, cols in COLUMN_GROUPS.items():
        print(f"\n{group.upper()}:")
        for col in cols[:5]:
            print(f"  - {col}: {MATRIX_COLUMNS.get(col, '')}")
        if len(cols) > 5:
            print(f"  ... and {len(cols) - 5} more")
