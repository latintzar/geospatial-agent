"""
Fast Population Queries - Pre-computed H3 Population Data
=========================================================

NOTE (Dec 2024): For most use cases, use tools_demographics.py instead!
    - Default: Kontur (H3 res 8, ~460m) - fast & global
    - Fallback: GHS-POP (flexible res) - higher detail if needed

This module is for FUTURE use if you need:
- Higher resolution than Kontur (H3 res 10, ~66m)
- Instant queries (<1 sec) for pre-computed data
- Offline/cached population data

To use this module, you must first pre-compute the data:
    1. Run: python scripts/precompute_population_h3.py --region japan
    2. Upload: python scripts/precompute_population_h3.py --upload
    3. Query: Uses S3 automatically

Speed Comparison:
- Kontur (recommended): 5-15 seconds (download + filter)
- GHS-POP (fallback):   10-30 seconds (download tiles + process)
- Pre-computed S3:      1-3 seconds (DuckDB query)

Data Resolution:
- Kontur:       H3 res 8 = ~460m edge = neighborhood level
- Pre-computed: H3 res 10 = ~66m edge = building level detail
"""

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

import duckdb
import h3

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# S3 bucket for pre-computed population data
S3_BUCKET = os.getenv("POPULATION_S3_BUCKET", "puedo-casa-population")
S3_REGION = os.getenv("POPULATION_S3_REGION", "us-west-2")

# Local cache directory (fallback if S3 not available)
LOCAL_CACHE_DIR = Path(__file__).parent.parent / "data" / "population_h3"

# H3 resolution of pre-computed data
H3_RESOLUTION = 10  # ~66m edge, building level


# =============================================================================
# FAST POPULATION QUERY
# =============================================================================

def get_population_fast(
    bbox: List[float],
    resolution: int = H3_RESOLUTION,
    source: str = "auto"
) -> Optional[List[Dict[str, Any]]]:
    """
    Get population data FAST from pre-computed H3 parquet files.
    
    This is the recommended function for production use. Returns
    building-level population data in 1-3 seconds.
    
    Args:
        bbox: [west, south, east, north] bounding box
        resolution: H3 resolution (default 10 for building level)
        source: "s3", "local", or "auto" (tries S3 first, falls back to local)
        
    Returns:
        List of dicts [{'hex': 'h3_index', 'count': population}, ...]
        Returns None if data not available
        
    Example:
        >>> pop = get_population_fast([139.7, 35.65, 139.75, 35.7])
        >>> len(pop)
        1234
        >>> pop[0]
        {'hex': '8a2f59a4c1c7fff', 'count': 87}
    """
    west, south, east, north = bbox
    
    logger.info(f"🚀 Fast population query for bbox: {bbox}")
    
    # Try S3 first if auto or s3
    if source in ("auto", "s3"):
        result = _query_s3(west, south, east, north, resolution)
        if result is not None:
            return result
        if source == "s3":
            logger.warning("S3 query failed and source='s3' specified")
            return None
    
    # Fall back to local
    if source in ("auto", "local"):
        result = _query_local(west, south, east, north, resolution)
        if result is not None:
            return result
    
    logger.warning("No pre-computed population data available")
    logger.info("Run: python scripts/precompute_population_h3.py --help")
    return None


def _query_s3(
    west: float, south: float, east: float, north: float,
    resolution: int
) -> Optional[List[Dict[str, Any]]]:
    """Query population from S3 parquet files."""
    try:
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(f"SET s3_region='{S3_REGION}';")
        
        # Build S3 path
        s3_path = f"s3://{S3_BUCKET}/h3_res{resolution}/*/*.parquet"
        
        # Query with bbox filter (DuckDB will push down predicates)
        query = f"""
        SELECT hex, population as count
        FROM read_parquet('{s3_path}')
        WHERE lat >= {south} AND lat <= {north}
          AND lng >= {west} AND lng <= {east}
        """
        
        logger.debug(f"Querying S3: {s3_path}")
        result = conn.execute(query).fetchdf()
        conn.close()
        
        if result.empty:
            logger.info("No population data in this bbox (might be ocean/unpopulated)")
            return []
        
        records = result.to_dict('records')
        total_pop = sum(r['count'] for r in records)
        logger.info(f"✅ S3 query returned {len(records)} hexagons, total pop: {total_pop:,}")
        
        return records
        
    except Exception as e:
        logger.debug(f"S3 query failed: {e}")
        return None


def _query_local(
    west: float, south: float, east: float, north: float,
    resolution: int
) -> Optional[List[Dict[str, Any]]]:
    """Query population from local parquet files."""
    local_path = LOCAL_CACHE_DIR / f"h3_res{resolution}"
    
    if not local_path.exists():
        logger.debug(f"Local cache not found: {local_path}")
        return None
    
    parquet_files = list(local_path.glob("**/*.parquet"))
    if not parquet_files:
        logger.debug(f"No parquet files in {local_path}")
        return None
    
    try:
        conn = duckdb.connect()
        
        # Query local files
        query = f"""
        SELECT hex, population as count
        FROM read_parquet('{local_path}/*/*.parquet')
        WHERE lat >= {south} AND lat <= {north}
          AND lng >= {west} AND lng <= {east}
        """
        
        logger.debug(f"Querying local: {local_path}")
        result = conn.execute(query).fetchdf()
        conn.close()
        
        if result.empty:
            return []
        
        records = result.to_dict('records')
        total_pop = sum(r['count'] for r in records)
        logger.info(f"✅ Local query returned {len(records)} hexagons, total pop: {total_pop:,}")
        
        return records
        
    except Exception as e:
        logger.warning(f"Local query failed: {e}")
        return None


# =============================================================================
# POPULATION FOR LOCATION (High-level wrapper)
# =============================================================================

def get_population_for_location_fast(
    location_query: str,
    resolution: int = H3_RESOLUTION
) -> Optional[Dict[str, Any]]:
    """
    Get population for a named location using FAST pre-computed data.
    
    This is the fast version of tools_demographics.get_population_for_location().
    
    Args:
        location_query: Location name (e.g., "Shibuya, Tokyo, Japan")
        resolution: H3 resolution (default 10)
        
    Returns:
        Dict with boundary, population, and metadata
    """
    from .tools_athena import get_athena_engine
    from .tools_demographics import detect_country_from_boundary
    from shapely.geometry import shape
    
    logger.info(f"🚀 Fast population for: {location_query}")
    
    # Get boundary using Athena engine (replaces deprecated OvertureEngine)
    engine = get_athena_engine()
    try:
        boundary = engine.get_smart_boundary(location_query)
    except Exception as e:
        logger.error(f"Failed to get boundary: {e}")
        return None
    
    if not boundary or not boundary.get('geometry'):
        return None
    
    # Get bbox
    bbox = boundary.get('bbox')
    if not bbox:
        return None
    
    # Query fast population
    population = get_population_fast(bbox, resolution)
    
    if population is None:
        # Fall back to slow method
        logger.info("Fast data not available, falling back to GHS-POP...")
        from .tools_demographics import get_population_for_location
        return get_population_for_location(location_query, resolution)
    
    country_iso3 = detect_country_from_boundary(boundary) or 'WORLD'
    
    return {
        'boundary': boundary,
        'population': population,
        'country_iso3': country_iso3,
        'metadata': {
            'bbox': bbox,
            'resolution': resolution,
            'hex_count': len(population),
            'total_population': sum(p.get('count', 0) for p in population),
            'data_source': 'pre-computed H3 (fast)',
        }
    }


# =============================================================================
# CHECK DATA AVAILABILITY
# =============================================================================

def check_population_data_status() -> Dict[str, Any]:
    """
    Check what pre-computed population data is available.
    
    Returns:
        Dict with status info for S3 and local data
    """
    status = {
        's3_available': False,
        's3_bucket': S3_BUCKET,
        'local_available': False,
        'local_path': str(LOCAL_CACHE_DIR),
        'regions_processed': [],
        'total_parquet_files': 0,
    }
    
    # Check local
    if LOCAL_CACHE_DIR.exists():
        parquet_files = list(LOCAL_CACHE_DIR.glob("**/*.parquet"))
        if parquet_files:
            status['local_available'] = True
            status['total_parquet_files'] = len(parquet_files)
            
            # Detect regions from tile names
            regions = set()
            for pq in parquet_files:
                if 'R' in pq.stem and 'C' in pq.stem:
                    regions.add(pq.stem)
            status['regions_processed'] = list(regions)[:10]
    
    # Check S3 (quick test)
    try:
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(f"SET s3_region='{S3_REGION}';")
        
        # Try to list files
        result = conn.execute(f"""
            SELECT COUNT(*) FROM glob('s3://{S3_BUCKET}/h3_res10/*/*.parquet')
        """).fetchone()
        
        if result and result[0] > 0:
            status['s3_available'] = True
            status['s3_file_count'] = result[0]
        
        conn.close()
    except:
        pass
    
    return status


# =============================================================================
# CLI / TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🚀 Fast Population Query Test")
    print("=" * 60)
    
    # Check status
    print("\n📊 Data Status:")
    status = check_population_data_status()
    print(f"   S3 available: {status['s3_available']}")
    print(f"   Local available: {status['local_available']}")
    print(f"   Local parquet files: {status['total_parquet_files']}")
    
    if not status['s3_available'] and not status['local_available']:
        print("\n⚠️  No pre-computed data available!")
        print("   Run: python scripts/precompute_population_h3.py --tile R5_C19")
        print("   (This processes Tokyo area)")
        sys.exit(1)
    
    # Test query
    print("\n🧪 Testing query (Tokyo bbox):")
    bbox = [139.7, 35.65, 139.75, 35.7]  # Small area in Tokyo
    
    import time
    start = time.time()
    result = get_population_fast(bbox)
    elapsed = time.time() - start
    
    if result:
        print(f"   ✅ Got {len(result)} hexagons in {elapsed:.2f}s")
        total_pop = sum(r['count'] for r in result)
        print(f"   Total population: {total_pop:,}")
    else:
        print(f"   ❌ No data returned")
    
    print("\n" + "=" * 60)

