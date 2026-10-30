"""
Leo Tools - Schema-Aware AWS Athena Engine for Overture Maps (v3.0)
===================================================================

Cloud-Native Geospatial Architecture with full schema awareness.

This module provides:
1. AthenaEngine - Core SQL execution with proper error handling
2. get_smart_boundary - Population-aware city/region lookup
3. fetch_features_sql - Dynamic SQL with bbox and filters
4. spatial_join_sql - Proximity queries (e.g., "cafes near tube stations")
5. fetch_features_geometry - GEOMETRY FILTERING (The Cookie Cutter) ← NEW!
6. fetch_coastline / buffer_geometry - Helpers for complex shapes

GEOMETRY FILTERING (The Cookie Cutter) - NEW in v3.0:
=====================================================
Filter features by ANY shape, not just bounding boxes!

Use Cases:
    - "Cafes within 2.5km of the French coast" → Buffered coastline
    - "Parks within 15-minute drive" → Isochrone polygon  
    - "Shops along Route 66" → Buffered route

Workflow:
    1. Get base geometry: coast = fetch_coastline("FR")
    2. Create buffer: zone = buffer_geometry(coast, 2500)  # 2.5km
    3. Query with cookie cutter: 
       cafes = fetch_features_geometry(zone, "places", "place", {...})
    
    OR use with Matrix:
       from tools.tools_matrix import query_matrix
       wealthy_coastal = query_matrix(aoi_geometry=zone, filters={"wealth_index": "> 0.7"})

Reference: 
- https://docs.overturemaps.org/schema
- https://docs.overturemaps.org/getting-data/athena-aws/
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any, Union, Literal, Tuple
from dataclasses import dataclass, field
from dotenv import load_dotenv

import boto3
import pandas as pd
from shapely.geometry import shape, mapping, box
from shapely.ops import transform
from shapely import wkt
import pyproj

# Import schema context
from .overture_schema import (
    OVERTURE_SCHEMA_CONTEXT,
    OVERTURE_THEMES,
    DIVISION_SUBTYPE_PRIORITY,
    CATEGORY_ALIASES,
    ROAD_CLASS_HIERARCHY,
    get_theme_type_for_query,
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# AWS/Athena configuration
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
ATHENA_WORKGROUP = os.getenv("ATHENA_WORKGROUP", "primary")
ATHENA_OUTPUT_LOCATION = os.getenv(
    "ATHENA_OUTPUT_LOCATION",
    "s3://puedo-casa-athena-results/queries/"
)

# Overture Maps cross-account Glue catalog
OVERTURE_CATALOG = "overture"
OVERTURE_DATABASE = "release"
OVERTURE_RELEASE = os.getenv("OVERTURE_RELEASE", "v2025_12_17_0")
OVERTURE_TABLE = f"{OVERTURE_CATALOG}.{OVERTURE_DATABASE}.{OVERTURE_RELEASE}"

# Query settings
ATHENA_QUERY_TIMEOUT_SECONDS = 300
ATHENA_POLL_INTERVAL_SECONDS = 1.0

# Approximate meters per degree at equator (for area/distance calculations)
METERS_PER_DEGREE = 111319


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BoundaryResult:
    """Result from get_smart_boundary()"""
    id: str
    name: str
    subtype: str
    country: str
    population: Optional[int]
    focus_geometry: Dict  # GeoJSON geometry
    focus_bbox: List[float]  # [minx, miny, maxx, maxy]
    context_bbox: List[float]  # Expanded bbox for data fetching
    area_km2: float
    source: str = "athena"
    query_time_ms: int = 0


@dataclass
class QueryResult:
    """Result from run_query()"""
    data: pd.DataFrame
    query_execution_id: str
    state: str
    duration_ms: int
    scanned_bytes: int
    row_count: int = 0


# =============================================================================
# ATHENA ENGINE CLASS
# =============================================================================

class AthenaEngine:
    """
    Schema-Aware AWS Athena Engine for Overture Maps.
    
    This engine understands the Overture schema and can translate
    natural language queries into correct SQL.
    
    Example:
        >>> engine = AthenaEngine()
        >>> 
        >>> # Get London boundary (the city, not the state!)
        >>> london = engine.get_smart_boundary("London", type_hint="city")
        >>> 
        >>> # Get parks over 20,000m² in London
        >>> parks = engine.fetch_features_sql(
        ...     bbox=london.focus_bbox,
        ...     theme="base",
        ...     feature_type="land_use",
        ...     filters={"class": "park"},
        ...     min_area_m2=20000
        ... )
        >>> 
        >>> # Get cafes within 50m of tube stations
        >>> cafes = engine.spatial_join_sql(
        ...     target_theme="places", target_type="place",
        ...     target_filter="categories.primary = 'cafe'",
        ...     ref_theme="places", ref_type="place", 
        ...     ref_filter="categories.primary = 'subway_station'",
        ...     distance_meters=50,
        ...     bbox=london.focus_bbox
        ... )
    """
    
    def __init__(self):
        """Initialize the Athena Engine with AWS credentials."""
        self._athena_client = None
        self._s3_client = None
        
        # Verify AWS credentials
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        
        if not self.aws_access_key or not self.aws_secret_key:
            logger.warning("⚠️ AWS credentials not found in environment")
        
        logger.info(f"🏛️ AthenaEngine initialized")
        logger.info(f"   Table: {OVERTURE_TABLE}")
        logger.info(f"   Region: {AWS_REGION}")
        logger.info(f"   Workgroup: {ATHENA_WORKGROUP}")
    
    @property
    def athena_client(self):
        """Lazy-load Athena client."""
        if self._athena_client is None:
            self._athena_client = boto3.client(
                'athena',
                region_name=AWS_REGION,
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
            )
        return self._athena_client
    
    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client(
                's3',
                region_name=AWS_REGION,
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
            )
        return self._s3_client
    
    # =========================================================================
    # CORE METHOD: run_query
    # =========================================================================
    
    def run_query(
        self,
        sql: str,
        timeout_seconds: int = ATHENA_QUERY_TIMEOUT_SECONDS,
    ) -> QueryResult:
        """
        Execute a SQL query on Athena and return results as Pandas DataFrame.
        
        Args:
            sql: SQL query string
            timeout_seconds: Maximum time to wait for results
            
        Returns:
            QueryResult with data as Pandas DataFrame
            
        Raises:
            TimeoutError: If query exceeds timeout
            RuntimeError: If query fails
        """
        logger.info(f"🔍 Executing Athena query...")
        logger.debug(f"   SQL: {sql[:300]}...")
        
        start_time = time.time()
        
        # Start query execution
        try:
            response = self.athena_client.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={'Catalog': OVERTURE_CATALOG},
                WorkGroup=ATHENA_WORKGROUP,
                ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_LOCATION},
            )
        except Exception as e:
            logger.error(f"   ❌ Failed to start query: {e}")
            raise RuntimeError(f"Failed to start Athena query: {e}")
        
        query_execution_id = response['QueryExecutionId']
        logger.info(f"   Query ID: {query_execution_id}")
        
        # Poll for completion
        state = 'QUEUED'
        elapsed = 0
        
        while state in ('QUEUED', 'RUNNING') and elapsed < timeout_seconds:
            time.sleep(ATHENA_POLL_INTERVAL_SECONDS)
            elapsed = time.time() - start_time
            
            status_response = self.athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )
            state = status_response['QueryExecution']['Status']['State']
            
            if elapsed > 10 and int(elapsed) % 10 == 0:
                logger.info(f"   Still running... ({int(elapsed)}s)")
        
        # Check final state
        if state == 'FAILED':
            error_msg = status_response['QueryExecution']['Status'].get(
                'StateChangeReason', 'Unknown error'
            )
            logger.error(f"   ❌ Query failed: {error_msg}")
            raise RuntimeError(f"Athena query failed: {error_msg}")
        
        if state == 'CANCELLED':
            raise RuntimeError("Athena query was cancelled")
        
        if state not in ('SUCCEEDED',):
            if elapsed >= timeout_seconds:
                raise TimeoutError(f"Athena query timed out after {timeout_seconds}s")
            raise RuntimeError(f"Unexpected query state: {state}")
        
        # Get execution stats
        stats = status_response['QueryExecution'].get('Statistics', {})
        duration_ms = int(stats.get('TotalExecutionTimeInMillis', 0))
        scanned_bytes = int(stats.get('DataScannedInBytes', 0))
        
        logger.info(f"   ✅ Query completed in {duration_ms}ms, scanned {scanned_bytes / 1024 / 1024:.2f}MB")
        
        # Fetch results
        data = self._fetch_query_results(query_execution_id)
        
        return QueryResult(
            data=data,
            query_execution_id=query_execution_id,
            state=state,
            duration_ms=duration_ms,
            scanned_bytes=scanned_bytes,
            row_count=len(data),
        )
    
    def _fetch_query_results(self, query_execution_id: str) -> pd.DataFrame:
        """Fetch query results and convert to Pandas DataFrame."""
        rows = []
        columns = []
        next_token = None
        
        while True:
            if next_token:
                response = self.athena_client.get_query_results(
                    QueryExecutionId=query_execution_id,
                    NextToken=next_token,
                    MaxResults=1000,
                )
            else:
                response = self.athena_client.get_query_results(
                    QueryExecutionId=query_execution_id,
                    MaxResults=1000,
                )
            
            result_set = response['ResultSet']
            
            # Get columns from first page
            if not columns and 'ResultSetMetadata' in result_set:
                columns = [col['Name'] for col in result_set['ResultSetMetadata']['ColumnInfo']]
            
            # Process rows
            for i, row in enumerate(result_set['Rows']):
                # Skip header row on first page
                if i == 0 and not rows:
                    continue
                
                row_data = []
                for cell in row['Data']:
                    row_data.append(cell.get('VarCharValue'))
                rows.append(row_data)
            
            # Check for more pages
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        logger.info(f"   Fetched {len(rows)} rows, {len(columns)} columns")
        
        if not rows:
            return pd.DataFrame(columns=columns)
        
        return pd.DataFrame(rows, columns=columns)
    
    # =========================================================================
    # get_smart_boundary - Population-aware city/region lookup
    # =========================================================================
    
    def get_smart_boundary(
        self,
        query: str,
        type_hint: Literal["city", "neighborhood", "region", "country"] = "city",
        country_filter: Optional[str] = None,
        context_expansion: float = 1.5,
    ) -> BoundaryResult:
        """
        Get administrative boundary with smart disambiguation.
        
        Uses population data to find the "famous" city, not a tiny village.
        
        Args:
            query: Place name (e.g., "London", "Paris", "Tokyo")
            type_hint: Expected type - "city", "neighborhood", "region", "country"
            country_filter: Optional ISO country code filter (e.g., "GB", "US")
            context_expansion: Factor to expand bbox for context data
            
        Returns:
            BoundaryResult with geometry, bbox, and metadata
            
        Example:
            >>> engine.get_smart_boundary("London", type_hint="city")
            # Returns London, GB (pop=8.9M) not London, Texas
        """
        logger.info(f"🎯 get_smart_boundary: {query}")
        logger.info(f"   type_hint={type_hint}, country_filter={country_filter}")
        
        start_time = time.time()
        
        # Map type_hint to subtype filter
        subtype_filter = {
            "city": "subtype IN ('locality', 'localadmin')",
            "neighborhood": "subtype IN ('neighborhood', 'macrohood', 'locality')",
            "region": "subtype IN ('region', 'macroregion')",
            "country": "subtype = 'country'",
        }.get(type_hint, "subtype IN ('locality', 'localadmin')")
        
        # Step 1: Find the most populous match (Point with population data)
        point_sql = f"""
        SELECT 
            id,
            names.primary AS name,
            subtype,
            population,
            country,
            bbox.xmin AS bbox_xmin,
            bbox.ymin AS bbox_ymin,
            bbox.xmax AS bbox_xmax,
            bbox.ymax AS bbox_ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(query)}')
          AND {subtype_filter}
        """
        
        if country_filter:
            point_sql += f" AND UPPER(country) = UPPER('{self._escape_sql(country_filter)}')"
        
        point_sql += """
        ORDER BY population DESC NULLS LAST
        LIMIT 5
        """
        
        point_result = self.run_query(point_sql)
        
        if point_result.data.empty:
            raise ValueError(f"Location not found: {query}")
        
        # Get best match (highest population)
        best = point_result.data.iloc[0].to_dict()
        target_country = best.get('country')
        target_pop = best.get('population')
        
        logger.info(f"   📍 Found: {best['name']} ({best['subtype']}, pop={target_pop}, country={target_country})")
        
        # Step 2: Try to find polygon boundary (division_area)
        area_sql = f"""
        SELECT 
            id,
            names.primary AS name,
            subtype,
            country,
            ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt,
            bbox.xmin AS bbox_xmin,
            bbox.ymin AS bbox_ymin,
            bbox.xmax AS bbox_xmax,
            bbox.ymax AS bbox_ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(query)}')
          AND country = '{self._escape_sql(target_country)}'
        ORDER BY (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) DESC
        LIMIT 1
        """
        
        area_result = self.run_query(area_sql)
        
        # Determine geometry source
        if not area_result.data.empty:
            # Use polygon from division_area
            area_data = area_result.data.iloc[0].to_dict()
            geometry = wkt.loads(area_data['geometry_wkt'])
            geometry_geojson = mapping(geometry)
            focus_bbox = [
                float(area_data['bbox_xmin']),
                float(area_data['bbox_ymin']),
                float(area_data['bbox_xmax']),
                float(area_data['bbox_ymax']),
            ]
            area_km2 = self._calculate_area_km2(geometry)
            logger.info(f"   📐 Using polygon from division_area ({area_km2:.2f} km²)")
        else:
            # Fall back to generated bbox from point
            logger.info(f"   ⚠️ No polygon found, generating bbox from point...")
            
            # Scale bbox based on population
            pop_num = int(target_pop) if target_pop else 100000
            import math
            scale = 0.05 + 0.25 * math.log10(max(pop_num, 1000)) / 6
            scale = min(scale, 0.5)
            
            center_lon = (float(best['bbox_xmin']) + float(best['bbox_xmax'])) / 2
            center_lat = (float(best['bbox_ymin']) + float(best['bbox_ymax'])) / 2
            
            focus_bbox = [
                center_lon - scale,
                center_lat - scale,
                center_lon + scale,
                center_lat + scale,
            ]
            
            geometry = box(*focus_bbox)
            geometry_geojson = mapping(geometry)
            area_km2 = self._calculate_area_km2(geometry)
            logger.info(f"   📍 Generated bbox: {[round(b, 4) for b in focus_bbox]} (scale={scale:.3f})")
        
        # Expand bbox for context
        context_bbox = self._expand_bbox(focus_bbox, context_expansion)
        
        query_time_ms = int((time.time() - start_time) * 1000)
        
        logger.info(f"   📐 Focus bbox: {[round(b, 4) for b in focus_bbox]}")
        logger.info(f"   📐 Context bbox: {[round(b, 4) for b in context_bbox]} ({context_expansion}x)")
        
        return BoundaryResult(
            id=best['id'],
            name=best['name'],
            subtype=best['subtype'],
            country=target_country,
            population=int(target_pop) if target_pop else None,
            focus_geometry=geometry_geojson,
            focus_bbox=focus_bbox,
            context_bbox=context_bbox,
            area_km2=area_km2,
            query_time_ms=query_time_ms,
        )
    
    # =========================================================================
    # discover_location - SMART universal discovery (hierarchy + bbox fallback)
    # =========================================================================
    
    def discover_location(
        self,
        location_name: str,
        country_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Smart universal location discovery.
        
        Tries hierarchy first, falls back to bbox if no children found.
        Returns a menu of what's available for visualization.
        
        This is the PRIMARY discovery function for the agent.
        
        Args:
            location_name: Place name (e.g., "Paris", "London", "Tokyo")
            country_filter: Optional ISO code for disambiguation
            
        Returns:
            {
                "location": {"name": "Paris", "country": "FR", "subtype": "locality", "population": ...},
                "bbox": [min_lon, min_lat, max_lon, max_lat],
                "children_menu": {...} or None if no hierarchy,
                "boundaries_menu": {...} from bbox discovery,
                "discovery_method": "hierarchy" or "bbox"
            }
        """
        logger.info(f"🔍 discover_location: {location_name}")
        
        # Step 1: Find the location
        country_clause = f"AND country = '{country_filter}'" if country_filter else ""
        
        loc_sql = f"""
        SELECT id, names.primary AS name, subtype, country, population,
               bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(location_name)}')
          {country_clause}
        ORDER BY population DESC NULLS LAST
        LIMIT 1
        """
        
        loc_result = self.run_query(loc_sql)
        
        if loc_result.data.empty:
            raise ValueError(f"Location not found: {location_name}")
        
        loc = loc_result.data.iloc[0]
        loc_id = loc['id']
        loc_country = loc['country']
        loc_subtype = loc['subtype']
        
        logger.info(f"   📍 Found: {loc['name']} ({loc_subtype}, {loc_country})")
        
        # Get bbox from division_area
        bbox_sql = f"""
        SELECT bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND country = '{loc_country}'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(location_name)}')
          AND subtype = '{loc_subtype}'
        LIMIT 1
        """
        
        bbox_result = self.run_query(bbox_sql)
        
        if not bbox_result.data.empty:
            b = bbox_result.data.iloc[0]
            bbox = [float(b['xmin']), float(b['ymin']), float(b['xmax']), float(b['ymax'])]
        else:
            # Fallback to point bbox with margin
            margin = 0.1
            bbox = [
                float(loc['xmin']) - margin,
                float(loc['ymin']) - margin,
                float(loc['xmax']) + margin,
                float(loc['ymax']) + margin,
            ]
        
        logger.info(f"   📐 Bbox: {[round(b, 3) for b in bbox]}")
        
        # Step 2: Try hierarchy first
        children_sql = f"""
        SELECT subtype, COUNT(*) as count, ARRAY_AGG(names.primary ORDER BY names.primary) as examples
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND parent_division_id = '{loc_id}'
        GROUP BY subtype
        ORDER BY count DESC
        """
        
        children_result = self.run_query(children_sql)
        
        children_menu = None
        discovery_method = "bbox"
        
        # Convert count to int for comparison
        total_children = 0
        if not children_result.data.empty:
            try:
                total_children = sum(int(c) for c in children_result.data['count'])
            except:
                total_children = 0
        
        if total_children > 0:
            # Hierarchy exists
            children_menu = {}
            for _, row in children_result.data.iterrows():
                examples = row.get('examples', [])
                if isinstance(examples, str):
                    examples = [examples]
                examples = [e for e in (examples or []) if e][:10]
                children_menu[row['subtype']] = {
                    "count": int(row['count']),
                    "examples": examples
                }
            discovery_method = "hierarchy"
            logger.info(f"   ✅ Hierarchy found: {sum(c['count'] for c in children_menu.values())} children")
        else:
            logger.info(f"   ⚠️ No hierarchy children, using bbox discovery")
        
        # Step 3: Also get bbox-based discovery (always useful for map features)
        boundaries_menu = self.discover_boundaries(bbox, country_filter=loc_country)
        
        return {
            "location": {
                "id": loc_id,
                "name": loc['name'],
                "country": loc_country,
                "subtype": loc_subtype,
                "population": loc.get('population'),
            },
            "bbox": bbox,
            "children_menu": children_menu,
            "boundaries_menu": boundaries_menu["menu"],
            "discovery_method": discovery_method,
        }
    
    # =========================================================================
    # get_division_children - TRUE hierarchy discovery (no bbox interpretation)
    # =========================================================================
    
    def get_division_children(
        self,
        parent_name: str,
        parent_subtype: Literal["country", "region", "county", "localadmin", "locality"] = "locality",
        country_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all child divisions of a named parent using TRUE hierarchy.
        
        This is the DISCOVERY-DRIVEN approach:
        1. Find parent by name → get its division ID
        2. Query children WHERE parent_division_id = parent_id
        3. Return menu of child subtypes with counts
        
        Args:
            parent_name: Name of parent division (e.g., "Paris", "London")
            parent_subtype: Type of parent (locality=city, region=state, etc.)
            country_filter: Optional ISO code for disambiguation
            
        Returns:
            {
                "parent": {"id": "...", "name": "Paris", "subtype": "locality"},
                "children_menu": {
                    "macrohood": {"count": 52, "examples": ["Le Marais", ...]},
                    "neighborhood": {"count": 76, "examples": [...]},
                },
                "total_children": 129
            }
        """
        logger.info(f"🌳 get_division_children: {parent_name} ({parent_subtype})")
        
        # Step 1: Find parent division ID
        country_clause = f"AND country = '{country_filter}'" if country_filter else ""
        
        parent_sql = f"""
        SELECT id, names.primary AS name, subtype, country, population
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(parent_name)}')
          AND subtype = '{parent_subtype}'
          {country_clause}
        ORDER BY population DESC NULLS LAST
        LIMIT 1
        """
        
        parent_result = self.run_query(parent_sql)
        
        if parent_result.data.empty:
            raise ValueError(f"Parent division not found: {parent_name} ({parent_subtype})")
        
        parent = parent_result.data.iloc[0]
        parent_id = parent['id']
        parent_country = parent['country']
        
        logger.info(f"   📍 Found: {parent['name']} (id={parent_id[:8]}..., country={parent_country})")
        
        # Step 2: Get children counts by subtype
        children_sql = f"""
        SELECT 
            subtype,
            COUNT(*) as count,
            ARRAY_AGG(names.primary ORDER BY names.primary) as examples
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND parent_division_id = '{parent_id}'
        GROUP BY subtype
        ORDER BY 
            CASE subtype
                WHEN 'macrohood' THEN 1
                WHEN 'neighborhood' THEN 2
                WHEN 'microhood' THEN 3
                ELSE 4
            END
        """
        
        children_result = self.run_query(children_sql)
        
        children_menu = {}
        total = 0
        for _, row in children_result.data.iterrows():
            subtype = row['subtype']
            count = int(row['count'])
            examples = row.get('examples', [])
            if isinstance(examples, str):
                examples = [examples]
            examples = [e for e in (examples or []) if e][:10]
            
            children_menu[subtype] = {
                "count": count,
                "examples": examples
            }
            total += count
            logger.info(f"   {subtype}: {count} children")
        
        return {
            "parent": {
                "id": parent_id,
                "name": parent['name'],
                "subtype": parent['subtype'],
                "country": parent_country,
                "population": parent.get('population'),
            },
            "children_menu": children_menu,
            "total_children": total,
        }
    
    # =========================================================================
    # fetch_division_children - Get actual child boundaries with polygons
    # =========================================================================
    
    def fetch_division_children(
        self,
        parent_name: str,
        child_subtype: str,
        parent_subtype: Literal["country", "region", "county", "localadmin", "locality"] = "locality",
        country_filter: Optional[str] = None,
        include_geometry: bool = True,
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Fetch child boundaries of a parent division with polygons.
        
        Args:
            parent_name: Name of parent (e.g., "Paris")
            child_subtype: Subtype of children to fetch (e.g., "macrohood")
            parent_subtype: Type of parent
            country_filter: Optional ISO code
            include_geometry: Include WKT geometry
            limit: Max results
            
        Returns:
            DataFrame with: name, subtype, geometry_wkt, bbox
        """
        logger.info(f"📍 fetch_division_children: {parent_name} → {child_subtype}")
        
        # Get parent info first
        parent_info = self.get_division_children(parent_name, parent_subtype, country_filter)
        parent_id = parent_info["parent"]["id"]
        parent_country = parent_info["parent"]["country"]
        
        # Get child names from hierarchy
        child_names_sql = f"""
        SELECT names.primary AS name
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division'
          AND parent_division_id = '{parent_id}'
          AND subtype = '{child_subtype}'
        """
        
        child_names_result = self.run_query(child_names_sql)
        child_names = child_names_result.data['name'].tolist()
        
        if not child_names:
            logger.warning(f"   No {child_subtype} children found for {parent_name}")
            return pd.DataFrame()
        
        logger.info(f"   Found {len(child_names)} {child_subtype} children")
        
        # Get parent bbox for spatial filtering
        parent_bbox_sql = f"""
        SELECT bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND country = '{parent_country}'
          AND LOWER(names.primary) = LOWER('{self._escape_sql(parent_name)}')
          AND subtype = '{parent_subtype}'
        LIMIT 1
        """
        
        parent_bbox_result = self.run_query(parent_bbox_sql)
        
        if parent_bbox_result.data.empty:
            logger.warning(f"   No polygon found for parent {parent_name}")
            return pd.DataFrame()
        
        row = parent_bbox_result.data.iloc[0]
        bbox = [float(row['xmin']), float(row['ymin']), float(row['xmax']), float(row['ymax'])]
        bbox_margin = 0.05  # ~5km margin
        
        # Get polygons matching child names WITHIN parent bbox
        geom_select = ", ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt" if include_geometry else ""
        
        # Build name filter - escape single quotes
        escaped_names = [self._escape_sql(n) for n in child_names[:100]]  # Limit for SQL length
        names_filter = " OR ".join([f"names.primary = '{n}'" for n in escaped_names])
        
        polygons_sql = f"""
        SELECT 
            id,
            names.primary AS name,
            subtype,
            country,
            bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
            {geom_select}
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND country = '{parent_country}'
          AND subtype = '{child_subtype}'
          AND ({names_filter})
          AND bbox.xmin >= {bbox[0] - bbox_margin}
          AND bbox.xmax <= {bbox[2] + bbox_margin}
          AND bbox.ymin >= {bbox[1] - bbox_margin}
          AND bbox.ymax <= {bbox[3] + bbox_margin}
        LIMIT {limit}
        """
        
        polygons_result = self.run_query(polygons_sql)
        logger.info(f"   ✅ Fetched {len(polygons_result.data)} {child_subtype} polygons")
        
        return polygons_result.data
    
    # =========================================================================
    # discover_boundaries - Get ALL boundary types in a bbox (fallback)
    # =========================================================================
    
    def discover_boundaries(
        self,
        bbox: List[float],
        country_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Discover what administrative boundaries exist in a bbox.
        
        Use this as a FALLBACK when you don't have a named parent.
        Prefer get_division_children() when you have a parent name.
        
        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]
            country_filter: Optional ISO country code
            
        Returns:
            {"menu": {...}, "total_boundaries": N, "bbox": [...]}
        """
        logger.info(f"🔍 discover_boundaries in bbox: {[round(b, 2) for b in bbox]}")
        
        country_clause = f"AND country = '{country_filter}'" if country_filter else ""
        
        sql = f"""
        SELECT 
            subtype,
            COUNT(*) as count,
            ARRAY_AGG(names.primary ORDER BY names.primary) as examples
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND bbox.xmin >= {bbox[0]}
          AND bbox.xmax <= {bbox[2]}
          AND bbox.ymin >= {bbox[1]}
          AND bbox.ymax <= {bbox[3]}
          {country_clause}
        GROUP BY subtype
        ORDER BY 
            CASE subtype
                WHEN 'country' THEN 1
                WHEN 'region' THEN 2
                WHEN 'county' THEN 3
                WHEN 'localadmin' THEN 4
                WHEN 'locality' THEN 5
                WHEN 'macrohood' THEN 6
                WHEN 'neighborhood' THEN 7
                WHEN 'microhood' THEN 8
                ELSE 9
            END
        """
        
        result = self.run_query(sql)
        
        menu = {}
        total = 0
        for _, row in result.data.iterrows():
            subtype = row['subtype']
            count = int(row['count'])
            examples = row.get('examples', [])
            if isinstance(examples, str):
                examples = [examples]
            examples = [e for e in (examples or []) if e][:5]
            
            menu[subtype] = {"count": count, "examples": examples}
            total += count
            logger.info(f"   {subtype}: {count}")
        
        return {"menu": menu, "total_boundaries": total, "bbox": bbox}
    
    # =========================================================================
    # fetch_boundaries - Get actual boundaries by subtype (agent's choice)
    # =========================================================================
    
    def fetch_boundaries(
        self,
        bbox: List[float],
        subtype: str,
        country_filter: Optional[str] = None,
        include_geometry: bool = True,
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Fetch boundaries of a specific subtype within bbox.
        
        The agent uses discover_boundaries() first to see the menu,
        then calls this with the chosen subtype.
        
        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]
            subtype: One of: country, region, county, localadmin, locality, 
                     macrohood, neighborhood, microhood
            country_filter: Optional ISO country code
            include_geometry: Include WKT geometry (default True for mapping)
            limit: Max boundaries to return
            
        Returns:
            DataFrame with: id, name, subtype, population, bbox coords, geometry_wkt
        """
        logger.info(f"📍 fetch_boundaries: {subtype} in bbox {[round(b, 2) for b in bbox]}")
        
        country_clause = f"AND country = '{country_filter}'" if country_filter else ""
        geom_select = ", ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt" if include_geometry else ""
        
        sql = f"""
        SELECT 
            id,
            names.primary AS name,
            subtype,
            country,
            population,
            bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
            {geom_select}
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND subtype = '{subtype}'
          AND bbox.xmin >= {bbox[0]}
          AND bbox.xmax <= {bbox[2]}
          AND bbox.ymin >= {bbox[1]}
          AND bbox.ymax <= {bbox[3]}
          {country_clause}
        ORDER BY population DESC NULLS LAST, names.primary
        LIMIT {limit}
        """
        
        result = self.run_query(sql)
        logger.info(f"   ✅ Fetched {len(result.data)} {subtype} boundaries")
        return result.data
    
    # =========================================================================
    # fetch_by_country - Simple country-level queries
    # =========================================================================
    
    def fetch_by_country(
        self,
        country_code: str,
        theme: str,
        feature_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch features by country code.
        
        Note: Places don't have a 'country' field populated, so this method
        first gets the country's bbox and then queries within that area.
        For divisions/addresses, it uses the direct country filter.
        
        Args:
            country_code: ISO 2-letter code (GB, US, FR, DE, JP, etc.)
            theme: Overture theme
            feature_type: Feature type
            filters: Additional filters
            limit: Max rows
            
        Example:
            >>> # Train stations in UK
            >>> stations = engine.fetch_by_country(
            ...     country_code="GB",
            ...     theme="places", feature_type="place",
            ...     filters={"categories.primary": "train_station"}
            ... )
        """
        logger.info(f"🌍 fetch_by_country: {country_code} {theme}/{feature_type}")
        
        # For divisions/addresses, country field is populated
        if theme in ("divisions", "addresses"):
            if theme == "divisions":
                select = "id, names.primary AS name, subtype, country, population"
            else:
                select = "id, street, number, postcode, country"
            
            sql = f"""
            SELECT {select}
            FROM {OVERTURE_TABLE}
            WHERE theme = '{theme}'
              AND type = '{feature_type}'
              AND country = '{country_code.upper()}'
            """
            
            if filters:
                for col, val in filters.items():
                    if isinstance(val, str):
                        sql += f" AND {col} = '{self._escape_sql(val)}'"
            
            sql += f" LIMIT {limit}"
            result = self.run_query(sql)
            logger.info(f"   ✅ Found {len(result.data)} features in {country_code}")
            return result.data
        
        # For places/base/buildings/transportation, get country bbox first
        logger.info(f"   Getting {country_code} boundary...")
        
        # Get country boundary
        country_sql = f"""
        SELECT bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
        FROM {OVERTURE_TABLE}
        WHERE theme = 'divisions'
          AND type = 'division_area'
          AND subtype = 'country'
          AND country = '{country_code.upper()}'
        ORDER BY (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) DESC
        LIMIT 1
        """
        
        country_result = self.run_query(country_sql)
        
        if country_result.data.empty:
            raise ValueError(f"Country not found: {country_code}")
        
        row = country_result.data.iloc[0]
        country_bbox = [
            float(row['xmin']),
            float(row['ymin']),
            float(row['xmax']),
            float(row['ymax']),
        ]
        
        logger.info(f"   Country bbox: {[round(b, 2) for b in country_bbox]}")
        
        # Now query within country bbox
        return self.fetch_features_sql(
            bbox=country_bbox,
            theme=theme,
            feature_type=feature_type,
            filters=filters,
            limit=limit,
        )
    
    # =========================================================================
    # fetch_by_location - Smart location-based queries
    # =========================================================================
    
    def fetch_by_location(
        self,
        location: str,
        theme: str,
        feature_type: str,
        filters: Optional[Dict[str, Any]] = None,
        location_type: Literal["city", "region", "country"] = "city",
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch features within a named location using spatial containment.
        
        This is the DISCOVERY-DRIVEN approach:
        1. Resolve location name to polygon (using population for disambiguation)
        2. Query features that fall within that polygon
        
        Args:
            location: Place name (e.g., "London", "California", "Germany")
            theme: Overture theme
            feature_type: Feature type
            filters: Additional filters
            location_type: Hint for disambiguation
            limit: Max rows
            
        Example:
            >>> # Cafes in London (the city, not the state)
            >>> cafes = engine.fetch_by_location(
            ...     location="London",
            ...     theme="places", feature_type="place",
            ...     filters={"categories.primary": "cafe"},
            ...     location_type="city"
            ... )
        """
        logger.info(f"📍 fetch_by_location: '{location}' ({location_type}) {theme}/{feature_type}")
        
        # Step 1: Get location boundary
        boundary = self.get_smart_boundary(location, type_hint=location_type)
        logger.info(f"   Resolved to: {boundary.name}, {boundary.country} (pop={boundary.population})")
        
        # Step 2: Use bbox for now (polygon containment is expensive)
        # For better precision, we could use ST_Contains with the actual polygon
        return self.fetch_features_sql(
            bbox=boundary.focus_bbox,
            theme=theme,
            feature_type=feature_type,
            filters=filters,
            limit=limit,
        )
    
    # =========================================================================
    # fetch_by_radius - Point + radius queries
    # =========================================================================
    
    def fetch_by_radius(
        self,
        center_lat: float,
        center_lon: float,
        radius_meters: float,
        theme: str,
        feature_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch features within a radius of a point.
        
        Args:
            center_lat: Latitude of center point
            center_lon: Longitude of center point
            radius_meters: Search radius in meters
            theme: Overture theme
            feature_type: Feature type
            filters: Additional filters
            limit: Max rows
            
        Example:
            >>> # Restaurants within 500m of Big Ben
            >>> restaurants = engine.fetch_by_radius(
            ...     center_lat=51.5007, center_lon=-0.1246,
            ...     radius_meters=500,
            ...     theme="places", feature_type="place",
            ...     filters={"categories.primary": "restaurant"}
            ... )
        """
        logger.info(f"📍 fetch_by_radius: ({center_lat}, {center_lon}) r={radius_meters}m")
        
        # Convert meters to degrees (approximate)
        radius_degrees = radius_meters / (METERS_PER_DEGREE * abs(center_lat / 90 + 0.5))
        
        # Build bbox for initial filter (performance)
        bbox = [
            center_lon - radius_degrees,
            center_lat - radius_degrees,
            center_lon + radius_degrees,
            center_lat + radius_degrees,
        ]
        
        # Build SELECT based on type
        if theme == "places":
            select = """
                id, names.primary AS name, categories.primary AS category,
                ST_X(ST_GeomFromBinary(geometry)) AS lon,
                ST_Y(ST_GeomFromBinary(geometry)) AS lat
            """
        else:
            select = """
                id, names.primary AS name, subtype,
                ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt
            """
        
        sql = f"""
        SELECT {select},
               ST_Distance(
                   ST_GeomFromBinary(geometry), 
                   ST_Point({center_lon}, {center_lat})
               ) * {METERS_PER_DEGREE} * COS(RADIANS({center_lat})) AS distance_m
        FROM {OVERTURE_TABLE}
        WHERE theme = '{theme}'
          AND type = '{feature_type}'
          AND bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
          AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
          AND ST_Distance(
                  ST_GeomFromBinary(geometry),
                  ST_Point({center_lon}, {center_lat})
              ) < {radius_degrees}
        """
        
        if filters:
            for col, val in filters.items():
                if isinstance(val, str):
                    sql += f" AND {col} = '{self._escape_sql(val)}'"
                elif isinstance(val, (list, tuple)):
                    vals = ", ".join(f"'{self._escape_sql(v)}'" for v in val)
                    sql += f" AND {col} IN ({vals})"
        
        sql += f" ORDER BY distance_m LIMIT {limit}"
        
        result = self.run_query(sql)
        logger.info(f"   ✅ Found {len(result.data)} features within {radius_meters}m")
        return result.data
    
    # =========================================================================
    # fetch_features_sql - Bbox-based queries (for map viewport)
    # =========================================================================
    
    def fetch_features_sql(
        self,
        bbox: List[float],
        theme: str,
        feature_type: str,
        filters: Optional[Dict[str, Any]] = None,
        select_columns: Optional[List[str]] = None,
        min_area_m2: Optional[float] = None,
        limit: int = 10000,
    ) -> pd.DataFrame:
        """
        Fetch features with dynamic SQL filters.
        
        Args:
            bbox: [min_lon, min_lat, max_lon, max_lat]
            theme: Overture theme (base, places, buildings, transportation, divisions)
            feature_type: Feature type within theme (land_use, place, building, segment)
            filters: Dict of column -> value filters (e.g., {"class": "park"})
            select_columns: Optional list of columns to select
            min_area_m2: Optional minimum area filter (for polygons)
            limit: Maximum rows to return
            
        Returns:
            Pandas DataFrame with features
            
        Example:
            >>> # Parks over 20,000m² in London
            >>> parks = engine.fetch_features_sql(
            ...     bbox=[-0.5, 51.2, 0.3, 51.7],
            ...     theme="base",
            ...     feature_type="land_use",
            ...     filters={"class": "park"},
            ...     min_area_m2=20000
            ... )
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        center_lat = (min_lat + max_lat) / 2
        
        logger.info(f"🗃️ fetch_features_sql: {theme}/{feature_type}")
        logger.info(f"   bbox: {bbox}, filters: {filters}")
        
        # Build SELECT clause
        if select_columns:
            select_clause = ", ".join(select_columns)
        else:
            # Default columns based on type
            select_clause = """
                id,
                names.primary AS name,
                subtype,
                ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt,
                bbox.xmin AS bbox_xmin,
                bbox.ymin AS bbox_ymin,
                bbox.xmax AS bbox_xmax,
                bbox.ymax AS bbox_ymax
            """
            
            # Add type-specific columns
            if theme == "base" and feature_type == "land_use":
                select_clause += ", class, surface"
            elif theme == "places" and feature_type == "place":
                select_clause = """
                    id,
                    names.primary AS name,
                    categories.primary AS category,
                    ST_X(ST_GeomFromBinary(geometry)) AS lon,
                    ST_Y(ST_GeomFromBinary(geometry)) AS lat,
                    confidence
                """
            elif theme == "buildings":
                select_clause += ", height, num_floors"
            elif theme == "transportation" and feature_type == "segment":
                select_clause += ", class, subclass, surface"
        
        # Build SQL
        sql = f"""
        SELECT {select_clause}
        FROM {OVERTURE_TABLE}
        WHERE theme = '{theme}'
          AND type = '{feature_type}'
          AND bbox.xmin >= {min_lon}
          AND bbox.xmax <= {max_lon}
          AND bbox.ymin >= {min_lat}
          AND bbox.ymax <= {max_lat}
        """
        
        # Add dynamic filters
        if filters:
            for col, val in filters.items():
                if isinstance(val, str):
                    sql += f" AND {col} = '{self._escape_sql(val)}'"
                elif isinstance(val, (list, tuple)):
                    vals = ", ".join(f"'{self._escape_sql(v)}'" for v in val)
                    sql += f" AND {col} IN ({vals})"
                elif isinstance(val, bool):
                    sql += f" AND {col} = {str(val).lower()}"
                else:
                    sql += f" AND {col} = {val}"
        
        # Add area filter for polygons
        if min_area_m2 and theme in ("base", "buildings", "divisions"):
            # Approximate area calculation for lat/lon
            sql += f"""
              AND ST_Area(ST_GeomFromBinary(geometry)) * {METERS_PER_DEGREE} * {METERS_PER_DEGREE} * COS(RADIANS({center_lat})) > {min_area_m2}
            """
        
        sql += f" LIMIT {limit}"
        
        result = self.run_query(sql)
        
        logger.info(f"   ✅ Returned {len(result.data)} features")
        
        return result.data
    
    # =========================================================================
    # spatial_join_sql - Proximity queries
    # =========================================================================
    
    def spatial_join_sql(
        self,
        target_theme: str,
        target_type: str,
        target_filter: str,
        ref_theme: str,
        ref_type: str,
        ref_filter: str,
        distance_meters: float,
        bbox: List[float],
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Spatial join to find features within distance of reference features.
        
        Args:
            target_theme: Theme of features to find (e.g., "places")
            target_type: Type of features to find (e.g., "place")
            target_filter: SQL filter for target (e.g., "categories.primary = 'cafe'")
            ref_theme: Theme of reference features (e.g., "places")
            ref_type: Type of reference features (e.g., "place")
            ref_filter: SQL filter for reference (e.g., "categories.primary = 'subway_station'")
            distance_meters: Maximum distance in meters
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            limit: Maximum rows to return
            
        Returns:
            DataFrame with target features and their nearest reference
            
        Example:
            >>> # Cafes within 50m of tube stations in London
            >>> cafes = engine.spatial_join_sql(
            ...     target_theme="places", target_type="place",
            ...     target_filter="categories.primary = 'cafe'",
            ...     ref_theme="places", ref_type="place",
            ...     ref_filter="categories.primary = 'subway_station'",
            ...     distance_meters=50,
            ...     bbox=[-0.2, 51.4, 0.0, 51.6]
            ... )
        """
        min_lon, min_lat, max_lon, max_lat = bbox
        center_lat = (min_lat + max_lat) / 2
        
        # Convert meters to approximate degrees
        distance_degrees = distance_meters / (METERS_PER_DEGREE * abs(center_lat / 90 + 0.5))
        
        logger.info(f"📍 spatial_join_sql")
        logger.info(f"   Target: {target_theme}/{target_type} WHERE {target_filter}")
        logger.info(f"   Reference: {ref_theme}/{ref_type} WHERE {ref_filter}")
        logger.info(f"   Distance: {distance_meters}m (~{distance_degrees:.6f}°)")
        
        # Fix table aliases for filter expressions
        target_filter_aliased = target_filter.replace("categories.", "t.categories.").replace("names.", "t.names.")
        ref_filter_aliased = ref_filter.replace("categories.", "r.categories.").replace("names.", "r.names.")
        
        sql = f"""
        SELECT 
            t.id AS target_id,
            t.names.primary AS target_name,
            r.id AS ref_id,
            r.names.primary AS ref_name,
            ST_X(ST_GeomFromBinary(t.geometry)) AS target_lon,
            ST_Y(ST_GeomFromBinary(t.geometry)) AS target_lat,
            ST_Distance(ST_GeomFromBinary(t.geometry), ST_GeomFromBinary(r.geometry)) * {METERS_PER_DEGREE} * COS(RADIANS({center_lat})) AS distance_m
        FROM {OVERTURE_TABLE} t
        JOIN {OVERTURE_TABLE} r
          ON ST_Distance(ST_GeomFromBinary(t.geometry), ST_GeomFromBinary(r.geometry)) < {distance_degrees}
        WHERE t.theme = '{target_theme}'
          AND t.type = '{target_type}'
          AND {target_filter_aliased}
          AND r.theme = '{ref_theme}'
          AND r.type = '{ref_type}'
          AND {ref_filter_aliased}
          AND t.bbox.xmin >= {min_lon} AND t.bbox.xmax <= {max_lon}
          AND t.bbox.ymin >= {min_lat} AND t.bbox.ymax <= {max_lat}
          AND r.bbox.xmin >= {min_lon - distance_degrees}
          AND r.bbox.xmax <= {max_lon + distance_degrees}
          AND r.bbox.ymin >= {min_lat - distance_degrees}
          AND r.bbox.ymax <= {max_lat + distance_degrees}
        ORDER BY distance_m
        LIMIT {limit}
        """
        
        result = self.run_query(sql)
        
        logger.info(f"   ✅ Found {len(result.data)} matches")
        
        return result.data
    
    # =========================================================================
    # GEOMETRY FILTERING (The Cookie Cutter) - NEW in v3.0
    # =========================================================================
    
    def fetch_features_geometry(
        self,
        geometry: Dict[str, Any],
        theme: str,
        feature_type: str,
        filters: Optional[Dict[str, Any]] = None,
        select_columns: Optional[List[str]] = None,
        limit: int = 10000,
    ) -> pd.DataFrame:
        """
        Fetch features that intersect with ANY geometry shape (The Cookie Cutter).
        
        This is the most powerful spatial filter - works with complex shapes:
        - Buffered coastlines
        - Isochrones (driving/walking time zones)
        - Administrative boundaries
        - Buffered routes/roads
        - Custom polygons
        
        The method:
        1. Converts GeoJSON to WKT
        2. Calculates bbox for coarse pre-filtering (performance)
        3. Uses ST_Intersects for precise geometry filtering
        
        Args:
            geometry: GeoJSON dict (Polygon, MultiPolygon, etc.)
            theme: Overture theme (places, base, buildings, etc.)
            feature_type: Feature type (place, land_use, building, etc.)
            filters: Additional attribute filters
            select_columns: Optional columns to select
            limit: Max rows
            
        Returns:
            DataFrame with features inside the geometry
            
        Examples:
            >>> # Get cafes within 2.5km of French coast
            >>> coast = engine.fetch_coastline("FR")  # LineString
            >>> buffer = shapely.buffer(coast, 2500)   # Polygon
            >>> cafes = engine.fetch_features_geometry(
            ...     geometry=buffer.__geo_interface__,
            ...     theme="places", feature_type="place",
            ...     filters={"categories.primary": "cafe"}
            ... )
            
            >>> # Get parks inside an isochrone
            >>> isochrone = get_driving_isochrone(lat, lon, 15)  # 15 min drive
            >>> parks = engine.fetch_features_geometry(
            ...     geometry=isochrone,
            ...     theme="base", feature_type="land_use",
            ...     filters={"class": "park"}
            ... )
        """
        logger.info(f"🍪 fetch_features_geometry (Cookie Cutter): {theme}/{feature_type}")
        logger.info(f"   Geometry type: {geometry.get('type', 'unknown')}")
        
        # Step 1: Convert GeoJSON to WKT and get bbox
        geom_shape = shape(geometry)
        wkt_string = geom_shape.wkt
        bounds = geom_shape.bounds  # (min_lon, min_lat, max_lon, max_lat)
        min_lon, min_lat, max_lon, max_lat = bounds
        
        logger.info(f"   BBox (pre-filter): [{min_lon:.3f}, {min_lat:.3f}] to [{max_lon:.3f}, {max_lat:.3f}]")
        
        # Step 2: Build SELECT clause
        if select_columns:
            select_clause = ", ".join(select_columns)
        else:
            # Default columns based on type
            if theme == "places" and feature_type == "place":
                select_clause = """
                    id,
                    names.primary AS name,
                    categories.primary AS category,
                    ST_X(ST_GeomFromBinary(geometry)) AS lon,
                    ST_Y(ST_GeomFromBinary(geometry)) AS lat,
                    confidence
                """
            elif theme == "base" and feature_type == "water":
                select_clause = """
                    id,
                    names.primary AS name,
                    subtype,
                    class,
                    ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt,
                    bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
                """
            elif theme == "base" and feature_type == "land_use":
                select_clause = """
                    id,
                    names.primary AS name,
                    subtype,
                    class,
                    surface,
                    ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt,
                    bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
                """
            else:
                select_clause = """
                    id,
                    names.primary AS name,
                    subtype,
                    ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt,
                    bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
                """
        
        # Step 3: Build SQL with geometry filter
        sql = f"""
        SELECT {select_clause}
        FROM {OVERTURE_TABLE}
        WHERE theme = '{theme}'
          AND type = '{feature_type}'
          -- Coarse bbox filter (fast pre-filter using partition pruning)
          AND bbox.xmin >= {min_lon}
          AND bbox.xmax <= {max_lon}
          AND bbox.ymin >= {min_lat}
          AND bbox.ymax <= {max_lat}
          -- Precise geometry filter (the cookie cutter!)
          AND ST_Intersects(
              ST_GeomFromBinary(geometry),
              ST_GeomFromText('{wkt_string}')
          )
        """
        
        # Add attribute filters
        if filters:
            for col, val in filters.items():
                if isinstance(val, str):
                    sql += f" AND {col} = '{self._escape_sql(val)}'"
                elif isinstance(val, (list, tuple)):
                    vals = ", ".join(f"'{self._escape_sql(v)}'" for v in val)
                    sql += f" AND {col} IN ({vals})"
                elif isinstance(val, bool):
                    sql += f" AND {col} = {str(val).lower()}"
                else:
                    sql += f" AND {col} = {val}"
        
        sql += f" LIMIT {limit}"
        
        result = self.run_query(sql)
        
        logger.info(f"   ✅ Found {len(result.data)} features inside geometry")
        
        return result.data
    
    def fetch_coastline(
        self,
        country_code: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        simplify_tolerance: float = 0.001,
    ) -> Dict[str, Any]:
        """
        Fetch coastline geometry from Overture water features.
        
        Returns a GeoJSON geometry (LineString or MultiLineString) of coastlines.
        
        Args:
            country_code: Optional ISO code to filter by country bbox
            bbox: Optional custom bbox [min_lon, min_lat, max_lon, max_lat]
            simplify_tolerance: Simplification tolerance in degrees (default ~100m)
            
        Returns:
            GeoJSON geometry dict
            
        Example:
            >>> coast = engine.fetch_coastline("FR")
            >>> buffer = shapely.buffer(shapely.shape(coast), 0.025)  # ~2.5km
        """
        logger.info(f"🌊 fetch_coastline: country={country_code}, bbox={bbox}")
        
        # Get bbox from country if not provided
        if not bbox and country_code:
            country_sql = f"""
            SELECT bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
            FROM {OVERTURE_TABLE}
            WHERE theme = 'divisions'
              AND type = 'division_area'
              AND subtype = 'country'
              AND country = '{country_code.upper()}'
            ORDER BY (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) DESC
            LIMIT 1
            """
            country_result = self.run_query(country_sql)
            
            if country_result.data.empty:
                raise ValueError(f"Country not found: {country_code}")
            
            row = country_result.data.iloc[0]
            bbox = [float(row['xmin']), float(row['ymin']), 
                    float(row['xmax']), float(row['ymax'])]
        
        if not bbox:
            raise ValueError("Must provide bbox or country_code")
        
        min_lon, min_lat, max_lon, max_lat = bbox
        logger.info(f"   Using bbox: {[round(b, 2) for b in bbox]}")
        
        # Fetch coastline (water features with subtype 'ocean', 'sea', 'bay' or class 'ocean')
        sql = f"""
        SELECT 
            ST_AsText(ST_SimplifyPreserveTopology(
                ST_GeomFromBinary(geometry), 
                {simplify_tolerance}
            )) AS geometry_wkt
        FROM {OVERTURE_TABLE}
        WHERE theme = 'base'
          AND type = 'water'
          AND (subtype IN ('ocean', 'sea', 'bay') OR class IN ('ocean', 'sea'))
          AND bbox.xmin >= {min_lon - 0.5}
          AND bbox.xmax <= {max_lon + 0.5}
          AND bbox.ymin >= {min_lat - 0.5}
          AND bbox.ymax <= {max_lat + 0.5}
        LIMIT 1000
        """
        
        result = self.run_query(sql)
        
        if result.data.empty:
            logger.warning("   No coastline found in area")
            return {"type": "GeometryCollection", "geometries": []}
        
        # Combine all coastline geometries
        from shapely.ops import unary_union
        geometries = []
        for _, row in result.data.iterrows():
            try:
                geom = wkt.loads(row['geometry_wkt'])
                geometries.append(geom)
            except Exception as e:
                logger.warning(f"   Could not parse geometry: {e}")
        
        if not geometries:
            return {"type": "GeometryCollection", "geometries": []}
        
        # Union all geometries
        combined = unary_union(geometries)
        
        # Extract boundary (coastline is the edge of water polygons)
        coastline = combined.boundary
        
        logger.info(f"   ✅ Fetched coastline ({coastline.geom_type}, {coastline.length:.2f}° length)")
        
        return mapping(coastline)
    
    def fetch_water_features(
        self,
        bbox: Optional[List[float]] = None,
        geometry: Optional[Dict[str, Any]] = None,
        water_types: Optional[List[str]] = None,
        min_area_m2: Optional[float] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch water features (lakes, rivers, coastlines, etc.).
        
        Args:
            bbox: Bounding box filter
            geometry: GeoJSON geometry filter (cookie cutter)
            water_types: Filter by type ('lake', 'river', 'ocean', 'stream', etc.)
            min_area_m2: Minimum area filter
            limit: Max results
            
        Returns:
            DataFrame with water features
        """
        logger.info(f"🌊 fetch_water_features: types={water_types}")
        
        if geometry:
            return self.fetch_features_geometry(
                geometry=geometry,
                theme="base",
                feature_type="water",
                filters={"subtype": water_types} if water_types else None,
                limit=limit,
            )
        elif bbox:
            return self.fetch_features_sql(
                bbox=bbox,
                theme="base",
                feature_type="water",
                filters={"subtype": water_types} if water_types else None,
                min_area_m2=min_area_m2,
                limit=limit,
            )
        else:
            raise ValueError("Must provide bbox or geometry")
    
    def buffer_geometry(
        self,
        geometry: Dict[str, Any],
        distance_meters: float,
        cap_style: str = "round",
    ) -> Dict[str, Any]:
        """
        Create a buffer around a geometry.
        
        This is a helper to create the "cookie cutter" shape from a feature.
        
        Args:
            geometry: GeoJSON geometry to buffer
            distance_meters: Buffer distance in meters
            cap_style: 'round', 'flat', or 'square'
            
        Returns:
            GeoJSON Polygon of the buffered geometry
            
        Example:
            >>> coast = engine.fetch_coastline("FR")
            >>> buffer = engine.buffer_geometry(coast, 2500)  # 2.5km buffer
            >>> cafes = engine.fetch_features_geometry(buffer, "places", "place", ...)
        """
        logger.info(f"📐 buffer_geometry: {distance_meters}m buffer")
        
        geom_shape = shape(geometry)
        centroid = geom_shape.centroid
        
        # Convert meters to degrees (approximate at centroid latitude)
        lat = centroid.y
        meters_per_degree_lon = METERS_PER_DEGREE * abs(lat / 90 + 0.5)
        meters_per_degree_lat = METERS_PER_DEGREE
        
        # Use average for buffer (simplification)
        avg_meters_per_degree = (meters_per_degree_lon + meters_per_degree_lat) / 2
        distance_degrees = distance_meters / avg_meters_per_degree
        
        logger.info(f"   Distance: {distance_meters}m ≈ {distance_degrees:.5f}°")
        
        cap_style_map = {"round": 1, "flat": 2, "square": 3}
        cap = cap_style_map.get(cap_style, 1)
        
        buffered = geom_shape.buffer(distance_degrees, cap_style=cap)
        
        logger.info(f"   ✅ Buffered {geom_shape.geom_type} → {buffered.geom_type}")
        
        return mapping(buffered)
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _escape_sql(self, value: str) -> str:
        """Escape single quotes in SQL values."""
        if value is None:
            return ''
        return str(value).replace("'", "''")
    
    def _expand_bbox(self, bbox: List[float], factor: float) -> List[float]:
        """Expand a bounding box by a factor."""
        min_lon, min_lat, max_lon, max_lat = bbox
        width = max_lon - min_lon
        height = max_lat - min_lat
        
        expand_w = width * (factor - 1) / 2
        expand_h = height * (factor - 1) / 2
        
        return [
            min_lon - expand_w,
            min_lat - expand_h,
            max_lon + expand_w,
            max_lat + expand_h,
        ]
    
    def _calculate_area_km2(self, geometry) -> float:
        """Calculate area in km² for a geometry."""
        try:
            # Project to equal-area for accurate measurement
            centroid = geometry.centroid
            proj_string = f"+proj=aea +lat_1={centroid.y - 1} +lat_2={centroid.y + 1} +lat_0={centroid.y} +lon_0={centroid.x}"
            
            project = pyproj.Transformer.from_crs(
                "EPSG:4326", proj_string, always_xy=True
            ).transform
            
            projected = transform(project, geometry)
            return projected.area / 1_000_000  # m² to km²
        except Exception:
            return 0.0
    
    def _bbox_to_polygon(self, bbox: List[float]) -> Dict:
        """Convert bbox to GeoJSON polygon."""
        return mapping(box(*bbox))


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Singleton engine instance
_engine_instance = None

def get_athena_engine() -> AthenaEngine:
    """Get or create singleton AthenaEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AthenaEngine()
    return _engine_instance


def get_smart_boundary(
    query: str,
    type_hint: str = "city",
    country_filter: Optional[str] = None,
) -> BoundaryResult:
    """Convenience function for get_smart_boundary."""
    return get_athena_engine().get_smart_boundary(query, type_hint, country_filter)


def fetch_features_sql(
    bbox: List[float],
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    **kwargs,
) -> pd.DataFrame:
    """Convenience function for fetch_features_sql."""
    return get_athena_engine().fetch_features_sql(bbox, theme, feature_type, filters, **kwargs)


def fetch_by_country(
    country_code: str,
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    **kwargs,
) -> pd.DataFrame:
    """Convenience function for fetch_by_country."""
    return get_athena_engine().fetch_by_country(country_code, theme, feature_type, filters, **kwargs)


def fetch_by_location(
    location: str,
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    **kwargs,
) -> pd.DataFrame:
    """Convenience function for fetch_by_location."""
    return get_athena_engine().fetch_by_location(location, theme, feature_type, filters, **kwargs)


def fetch_by_radius(
    center_lat: float,
    center_lon: float,
    radius_meters: float,
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    **kwargs,
) -> pd.DataFrame:
    """Convenience function for fetch_by_radius."""
    return get_athena_engine().fetch_by_radius(
        center_lat, center_lon, radius_meters, theme, feature_type, filters, **kwargs
    )


def discover_location(
    location_name: str,
    country_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """SMART universal discovery - tries hierarchy first, bbox fallback. PRIMARY discovery function."""
    return get_athena_engine().discover_location(location_name, country_filter)


def get_division_children(
    parent_name: str,
    parent_subtype: Literal["country", "region", "county", "localadmin", "locality"] = "locality",
    country_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Discover children of a named division - TRUE hierarchy discovery."""
    return get_athena_engine().get_division_children(parent_name, parent_subtype, country_filter)


def fetch_division_children(
    parent_name: str,
    child_subtype: str,
    parent_subtype: Literal["country", "region", "county", "localadmin", "locality"] = "locality",
    country_filter: Optional[str] = None,
    include_geometry: bool = True,
    limit: int = 500,
) -> pd.DataFrame:
    """Fetch child boundaries with polygons - agent picks from discovery menu."""
    return get_athena_engine().fetch_division_children(
        parent_name, child_subtype, parent_subtype, country_filter, include_geometry, limit
    )


def discover_boundaries(
    bbox: List[float],
    country_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Fallback: Discover boundaries in a bbox (use get_division_children when you have a name)."""
    return get_athena_engine().discover_boundaries(bbox, country_filter)


def fetch_boundaries(
    bbox: List[float],
    subtype: str,
    country_filter: Optional[str] = None,
    include_geometry: bool = True,
    limit: int = 500,
) -> pd.DataFrame:
    """Fallback: Fetch boundaries by bbox (use fetch_division_children when you have a parent)."""
    return get_athena_engine().fetch_boundaries(bbox, subtype, country_filter, include_geometry, limit)


def spatial_join_sql(
    target_theme: str,
    target_type: str,
    target_filter: str,
    ref_theme: str,
    ref_type: str,
    ref_filter: str,
    distance_meters: float,
    bbox: List[float],
    **kwargs,
) -> pd.DataFrame:
    """Convenience function for spatial_join_sql."""
    return get_athena_engine().spatial_join_sql(
        target_theme, target_type, target_filter,
        ref_theme, ref_type, ref_filter,
        distance_meters, bbox, **kwargs
    )


# =============================================================================
# GEOMETRY FILTERING CONVENIENCE FUNCTIONS (The Cookie Cutter)
# =============================================================================

def fetch_features_geometry(
    geometry: Dict[str, Any],
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch features that intersect with ANY geometry (The Cookie Cutter).
    
    Use this for complex shapes like:
    - Buffered coastlines ("cafes within 2.5km of French coast")
    - Isochrones ("parks within 15-minute drive")
    - Custom polygons
    
    Example:
        >>> coast = fetch_coastline("FR")
        >>> buffer = buffer_geometry(coast, 2500)  # 2.5km
        >>> cafes = fetch_features_geometry(
        ...     geometry=buffer,
        ...     theme="places", feature_type="place",
        ...     filters={"categories.primary": "cafe"}
        ... )
    """
    return get_athena_engine().fetch_features_geometry(
        geometry, theme, feature_type, filters, **kwargs
    )


def fetch_coastline(
    country_code: Optional[str] = None,
    bbox: Optional[List[float]] = None,
    simplify_tolerance: float = 0.001,
) -> Dict[str, Any]:
    """
    Fetch coastline geometry from Overture water features.
    
    Returns GeoJSON geometry (LineString/MultiLineString) for buffering.
    
    Example:
        >>> coast = fetch_coastline("FR")
        >>> coastal_buffer = buffer_geometry(coast, 2500)  # 2.5km buffer
    """
    return get_athena_engine().fetch_coastline(country_code, bbox, simplify_tolerance)


def fetch_water_features(
    bbox: Optional[List[float]] = None,
    geometry: Optional[Dict[str, Any]] = None,
    water_types: Optional[List[str]] = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch water features (lakes, rivers, coastlines).
    
    Can filter by bbox OR geometry (cookie cutter).
    """
    return get_athena_engine().fetch_water_features(bbox, geometry, water_types, **kwargs)


def buffer_geometry(
    geometry: Dict[str, Any],
    distance_meters: float,
    cap_style: str = "round",
) -> Dict[str, Any]:
    """
    Create a buffer around a geometry (for cookie cutter).
    
    Example:
        >>> coast = fetch_coastline("FR")
        >>> coastal_zone = buffer_geometry(coast, 2500)  # 2.5km buffer
        >>> # Now use coastal_zone with fetch_features_geometry() or query_matrix()
    """
    return get_athena_engine().buffer_geometry(geometry, distance_meters, cap_style)


# =============================================================================
# SCHEMA CONTEXT EXPORT (for Agent System Prompt)
# =============================================================================

def get_schema_context() -> str:
    """Get the full Overture schema context for the Agent system prompt."""
    return OVERTURE_SCHEMA_CONTEXT
