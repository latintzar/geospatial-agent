#!/usr/bin/env python3
"""
Global Earth Matrix Builder (ULTRA-MAXED Schema)
=================================================

Build the entire planet with ALL 1,081 Level-3 POI categories in ~8 hours for ~$165.

Instance: m8i.96xlarge (384 vCPU, 1.5TB RAM, 100Gbps, ~$20/hr on-demand)

Why m8i.96xlarge?
    - 384 vCPUs = process POI categories efficiently  
    - 100 Gbps network = 2× faster S3 reads
    - 1.5 TB RAM = plenty of headroom for batched processing

Extended K-Rings (for better walk coverage):
    - Res 8:  k=20, decay_knee=15 → ~90 min walk coverage
    - Res 10: k=25, decay_knee=20 → ~20 min walk coverage

Architecture:
    Phase 1: DuckDB Hex Fill (50 parallel instances) - ~2 hr
             SQL operations: h3_polygon_to_cells, ST_Area_Spheroid, h3_latlng_to_cell
             POI confidence filter: Only POIs with >= 75% confidence are included
    
    Phase 2: Python Propagation (memory-safe batched) - ~4 hr
             K-ring propagation from 1,081 POI categories → travel times + scores
             Edge detection + propagation from polygons → travel times
             Extended k-rings: k=25 for Res 10, k=20 for Res 8
             
             MEMORY-SAFE BATCHING:
             - Process categories in batches of 100
             - Write each batch to temp parquet (chunk_X_batch_N.parquet)
             - Clear RAM between batches
             - Final merge with DuckDB join at end
    
    Phase 3: Aggregate & Merge (DuckDB) - ~2 hr
             Aggregate Res 8 → Res 5
             UNION ALL chunks per resolution

Output:
    - earth_matrix_ultra_res5.parquet   (~50 MB,  ~500K hexes, 5,745 cols)
    - earth_matrix_ultra_res8.parquet   (~500 GB, ~180M hexes, 5,745 cols)
    - earth_matrix_ultra_res10.parquet  (~2.5 TB, ~9B hexes, 5,745 cols)

Total: ~3 TB, ~$100 on-demand cost

Usage:
    # On m8i.96xlarge instance
    python3 build_global_matrix.py
    
    # With custom settings
    python3 build_global_matrix.py --duckdb-workers 50 --python-workers 380

Author: Leo ETL System
Date: December 2024
"""

import argparse
import logging
import multiprocessing as mp
from multiprocessing import shared_memory
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import json

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))  # For utils_benchmark

# Benchmarking (optional - gracefully degrade if not available)
try:
    from utils_benchmark import (
        BenchmarkContext,
        measure_task,
        log_metric,
        s3_tracker,
        estimate_s3_read_size,
    )
    BENCHMARKING_AVAILABLE = True
except ImportError:
    BENCHMARKING_AVAILABLE = False
    # Stub implementations for when benchmarking isn't available
    class BenchmarkContext:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def measure_task(name):
        from contextlib import contextmanager
        @contextmanager
        def noop(): yield
        return noop()
    def log_metric(*args, **kwargs): pass
    class S3TrackerStub:
        def log_query(self, *args): pass
    s3_tracker = S3TrackerStub()
    def estimate_s3_read_size(*args): return 0

from geographic_chunks import generate_processing_queue, COUNTRY_CHUNKS, TEST_MODE, TEST_REGION
from retail_intelligence_config import (
    POI_CATEGORIES_L3,
    TOTAL_L3_POIS,
    LAND_USE_CLASSES as MAXED_LAND_USE_CLASSES,
    WATER_TYPES,
    GREEN_FEATURES,
    BLUE_FEATURES,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Overture Maps release (latest as of Dec 2024)
OVERTURE_RELEASE = "2025-12-17.0"
OVERTURE_S3 = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"

# H3 resolutions to process (res11 removed - too granular, diminishing returns)
RESOLUTIONS = [10, 8]  # Res 5 is aggregated from Res 8

# Base resolution for polygon hex fill (highest precision)
# Changed from 12 to 11 - res12 is too granular, diminishing returns
BASE_RESOLUTION = 11

# Output directories (local for testing, /data for production)
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "output" / "earth_matrix_temp"
FINAL_OUTPUT = Path(__file__).parent.parent.parent.parent / "output" / "earth_matrix"
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.json"

# Parallelism settings (for m8i.96xlarge with 384 vCPU)
DEFAULT_DUCKDB_WORKERS = int(os.environ.get('DUCKDB_THREADS', 50))
DEFAULT_PYTHON_WORKERS = int(os.environ.get('PYTHON_WORKERS', 380))

# Category batch size for memory-safe processing
# With 1,081 categories: 11 batches of ~100 categories each
# Each batch writes to temp parquet, preventing dict bloat
CATEGORY_BATCH_SIZE = int(os.environ.get('CATEGORY_BATCH_SIZE', 100))

# Minimum confidence threshold for POIs (0.0 to 1.0)
# Overture POIs below this confidence are excluded from counts and propagation
# 0.75 = 75% confidence, filters out low-quality/uncertain POI entries
POI_CONFIDENCE_THRESHOLD = float(os.environ.get('POI_CONFIDENCE_THRESHOLD', 0.75))

# =============================================================================
# BOUNDED PARALLELISM (for m8i.96xlarge optimization)
# =============================================================================
# 
# Problem: Sequential chunks waste CPU. All-at-once risks OOM.
# Solution: Process 10 chunks concurrently (91% CPU, 20% RAM)
#
# Math for m8i.96xlarge (384 vCPU, 1.5TB RAM):
#   - Per chunk: ~30GB RAM, ~35 threads for category propagation
#   - 10 chunks: 300GB RAM (safe), 350 threads (91% CPU utilization)
#
MAX_CONCURRENT_CHUNKS = int(os.environ.get('MAX_CONCURRENT_CHUNKS', 10))
THREADS_PER_CHUNK = int(os.environ.get('THREADS_PER_CHUNK', 35))

# Merge timeout per step (seconds) - increased for large files
MERGE_TIMEOUT_SECONDS = int(os.environ.get('MERGE_TIMEOUT', 600))

# =============================================================================
# CHECKPOINT MANAGEMENT (Resume on interruption)
# =============================================================================

def load_checkpoint() -> Dict:
    """Load checkpoint state or return empty state."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {"completed_chunks": [], "completed_propagations": [], "phase": 0}


def save_checkpoint(state: Dict):
    """Save checkpoint state."""
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def is_chunk_done(chunk_id: str, state: Dict) -> bool:
    """Check if a chunk has been completed."""
    return chunk_id in state.get("completed_chunks", [])


def mark_chunk_done(chunk_id: str, state: Dict):
    """Mark a chunk as completed."""
    if chunk_id not in state["completed_chunks"]:
        state["completed_chunks"].append(chunk_id)
        save_checkpoint(state)

# H3 edge lengths in meters (for travel time calculation)
H3_EDGE_LENGTHS = {
    5: 8000,   # ~8 km
    8: 461,    # ~460 m
    10: 66,    # ~66 m
    11: 25,    # ~25 m
    12: 9,     # ~9 m
}

# Travel speeds (meters per minute)
TRAVEL_SPEEDS = {
    'walk': 83,    # 5 km/h
    'cycle': 250,  # 15 km/h
    'drive': 833,  # 50 km/h
}

# K-ring configuration per resolution
# max_k: how many rings to propagate
# decay_knee: where score drops to 1 (then decays to 0 at max_k)
K_RING_CONFIG = {
    5:  {'max_k': 10, 'decay_knee': 7},   # k=10, decay 7→10 (default)
    8:  {'max_k': 20, 'decay_knee': 15},  # k=20, decay 15→20 (~90 min walk coverage)
    10: {'max_k': 25, 'decay_knee': 20},  # k=25, decay 20→25 (~20 min walk coverage)
    11: {'max_k': 10, 'decay_knee': 7},   # k=10, decay 7→10 (default)
    12: {'max_k': 10, 'decay_knee': 7},   # k=10, decay 7→10 (base layer)
}

# Convenience function to get max_k
def get_max_k(resolution: int) -> int:
    return K_RING_CONFIG.get(resolution, {'max_k': 10})['max_k']

# Land use classes to process (from MAXED config)
LAND_USE_CLASSES = MAXED_LAND_USE_CLASSES

# POI categories with their Overture primary category matches
# ULTRA-MAXED schema: ALL 1,081 Level-3 categories (individual POI types)
# Structure: {category_name: [matching_values]} - flat dict, each category maps to itself
POI_CATEGORIES = POI_CATEGORIES_L3

# Total: ~1,081 Level-3 POI categories
log_msg = f"Loaded {TOTAL_L3_POIS} POI categories from ULTRA-MAXED config"

# =============================================================================
# LOGGING SETUP
# =============================================================================

LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / 'earth_matrix.log'),
    ]
)
log = logging.getLogger(__name__)

# =============================================================================
# PHASE 1: DUCKDB HEX FILL
# =============================================================================

def run_hex_fill(chunk: Dict) -> str:
    """
    Execute DuckDB hex fill for one geographic chunk.
    
    Reads from Overture S3, performs polygon hex fill, outputs to local parquet.
    
    Args:
        chunk: Dictionary with 'chunk_id', 'bbox', and other metadata
        
    Returns:
        chunk_id on success
    """
    chunk_id = chunk['chunk_id']
    bbox = chunk['bbox']
    
    if bbox is None:
        log.warning(f"Skipping {chunk_id}: no bbox defined")
        return chunk_id
    
    log.info(f"[HEX FILL] Starting {chunk_id}")
    start = time.time()
    
    # Build land use class filter
    land_use_filter = "', '".join(LAND_USE_CLASSES)
    
    sql = f"""
    -- Install extensions
    INSTALL httpfs; LOAD httpfs;
    INSTALL spatial; LOAD spatial;
    INSTALL h3 FROM community; LOAD h3;
    
    SET s3_region='us-west-2';
    SET threads=7;  -- 384 vCPU / 50 chunks = ~7 threads per DuckDB instance
    
    -- =========================================================================
    -- LAND USE HEX FILL
    -- Handle both Polygon and MultiPolygon geometries
    -- =========================================================================
    COPY (
        WITH raw_polygons AS (
            SELECT 
                id as polygon_id,
                class,
                subtype,
                geometry,
                ST_Area_Spheroid(geometry) as polygon_area_m2
            FROM read_parquet('{OVERTURE_S3}/theme=base/type=land_use/*')
            WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
              AND class IN ('{land_use_filter}')
              AND geometry IS NOT NULL
        ),
        -- Convert centroid to hex for all geometry types (simpler, works universally)
        hex_fill AS (
            SELECT 
                h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {BASE_RESOLUTION}) as h3_index,
                polygon_id,
                class,
                subtype,
                polygon_area_m2
            FROM raw_polygons
        )
        SELECT 
            h3_index::VARCHAR as h3_index,
            polygon_id,
            class,
            subtype,
            polygon_area_m2
        FROM hex_fill
        WHERE h3_index IS NOT NULL
    ) TO '{OUTPUT_DIR}/hex_fill/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- WATER HEX FILL
    -- Handle both Polygon and MultiPolygon geometries
    -- =========================================================================
    COPY (
        WITH raw_water AS (
            SELECT 
                id as polygon_id,
                class,
                geometry,
                ST_Area_Spheroid(geometry) as polygon_area_m2
            FROM read_parquet('{OVERTURE_S3}/theme=base/type=water/*')
            WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
              AND class IN ('lake', 'river', 'pond', 'reservoir', 'sea', 'ocean')
              AND geometry IS NOT NULL
        ),
        -- Convert centroid to hex for all geometry types
        hex_fill AS (
            SELECT 
                h3_latlng_to_cell(ST_Y(ST_Centroid(geometry)), ST_X(ST_Centroid(geometry)), {BASE_RESOLUTION}) as h3_index,
                polygon_id,
                class,
                polygon_area_m2
            FROM raw_water
        )
        SELECT 
            h3_index::VARCHAR as h3_index,
            polygon_id,
            class,
            polygon_area_m2
        FROM hex_fill
        WHERE h3_index IS NOT NULL
    ) TO '{OUTPUT_DIR}/water/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- POIs (Point features) - CONFIDENCE FILTERED
    -- Only includes POIs with confidence >= {POI_CONFIDENCE_THRESHOLD} (default 75%)
    -- Removes low-quality, uncertain, or outdated entries
    -- =========================================================================
    COPY (
        SELECT 
            h3_latlng_to_cell(ST_Y(geometry), ST_X(geometry), {BASE_RESOLUTION})::VARCHAR as h3_index,
            id as poi_id,
            categories.primary as category,
            names.primary as name,
            confidence
        FROM read_parquet('{OVERTURE_S3}/theme=places/type=place/*')
        WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
              AND confidence >= {POI_CONFIDENCE_THRESHOLD}
    ) TO '{OUTPUT_DIR}/pois/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- BUILDINGS
    -- =========================================================================
    COPY (
        SELECT 
            h3_latlng_to_cell(
                ST_Y(ST_Centroid(geometry)), 
                ST_X(ST_Centroid(geometry)), 
                {BASE_RESOLUTION}
            )::VARCHAR as h3_index,
            id as building_id,
            height,
            num_floors,
            ST_Area_Spheroid(geometry) as footprint_m2
        FROM read_parquet('{OVERTURE_S3}/theme=buildings/type=building/*')
        WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
    ) TO '{OUTPUT_DIR}/buildings/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- COASTLINES (LINE features - extract raw geometry for Python processing)
    -- Phase 2 will convert to edge hexes and run propagation
    -- =========================================================================
    COPY (
            SELECT 
                id as line_id,
            class,
            ST_AsWKB(geometry) as geometry_wkb,
                ST_Length_Spheroid(geometry) as length_m
            FROM read_parquet('{OVERTURE_S3}/theme=base/type=water/*')
        WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
                  AND class = 'coastline'
              AND geometry IS NOT NULL
    ) TO '{OUTPUT_DIR}/coastlines/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- TRANSIT STATIONS (Point features from places theme)
    -- Subway, train, bus, tram, light rail, ferry, airport
    -- =========================================================================
    COPY (
        SELECT 
            h3_latlng_to_cell(ST_Y(geometry), ST_X(geometry), {BASE_RESOLUTION})::VARCHAR as h3_index,
            id as station_id,
            categories.primary as station_type,
            names.primary as name
        FROM read_parquet('{OVERTURE_S3}/theme=places/type=place/*')
        WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
              AND categories.primary IN (
                  'subway_station', 'metro_station', 'underground_station',
                  'train_station', 'railway_station',
                  'bus_station', 'bus_stop',
                  'tram_stop', 'tram_station',
                  'light_rail_station',
                  'ferry_terminal', 'ferry_stop',
                  'airport'
              )
    ) TO '{OUTPUT_DIR}/transit/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    
    -- =========================================================================
    -- ROADS (LINE features - extract raw geometry for Python processing)
    -- Phase 2 will convert to hexes along the road line
    -- =========================================================================
    COPY (
            SELECT 
                id as road_id,
                class as road_class,
            ST_AsWKB(geometry) as geometry_wkb,
            ST_Length_Spheroid(geometry) as length_m
            FROM read_parquet('{OVERTURE_S3}/theme=transportation/type=segment/*')
        WHERE bbox.xmin >= {bbox[0]} AND bbox.xmax <= {bbox[2]}
              AND bbox.ymin >= {bbox[1]} AND bbox.ymax <= {bbox[3]}
                  AND subtype = 'road'
                  AND class IN (
                      'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
                      'residential', 'pedestrian', 'cycleway', 'footway', 'living_street'
                  )
              AND geometry IS NOT NULL
    ) TO '{OUTPUT_DIR}/roads/{chunk_id}.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
    """
    
    try:
        result = subprocess.run(
            ['duckdb', '-c', sql],
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )
        elapsed = time.time() - start
        
        # Track output file sizes for S3 egress estimation
        # DuckDB scans more data than it outputs, so we multiply by a factor
        total_output_bytes = 0
        for subdir in ['hex_fill', 'water', 'coastlines', 'transit', 'roads']:
            output_file = OUTPUT_DIR / subdir / f"{chunk_id}.parquet"
            if output_file.exists():
                total_output_bytes += output_file.stat().st_size
        
        # Estimate S3 bytes read (output × ~10x for typical scan selectivity)
        estimated_s3_bytes = total_output_bytes * 10
        s3_tracker.log_query(f"hex_fill_{chunk_id}", estimated_s3_bytes)
        
        log.info(f"[HEX FILL] Completed {chunk_id} in {elapsed:.1f}s, S3 est: {estimated_s3_bytes / (1024**2):.1f} MB")
        return chunk_id
    except subprocess.CalledProcessError as e:
        log.error(f"[HEX FILL] Failed {chunk_id}: {e.stderr}")
        raise
    except subprocess.TimeoutExpired:
        log.error(f"[HEX FILL] Timeout {chunk_id}")
        raise


# =============================================================================
# PHASE 2: PYTHON PROPAGATION
# =============================================================================

def get_decay_score(k: int, resolution: int = 11) -> float:
    """
    Calculate two-phase linear decay score, parameterized by resolution.
    
    The decay curve is:
        k=0          → 10 (at the source)
        k=decay_knee → 1  (linear decay)
        k=max_k      → 0  (edge of influence)
    
    Resolution-specific settings:
        Res 5:  decay_knee=7,  max_k=10  (default)
        Res 8:  decay_knee=15, max_k=20  (extended for city-level)
        Res 10: decay_knee=20, max_k=25  (extended for neighborhood)
        Res 11: decay_knee=7,  max_k=10  (default)
    
    Args:
        k: Ring distance from source
        resolution: H3 resolution (affects decay curve)
        
    Returns:
        Score between 0 and 10
    """
    config = K_RING_CONFIG.get(resolution, {'max_k': 10, 'decay_knee': 7})
    decay_knee = config['decay_knee']
    max_k = config['max_k']
    
    if k <= 0:
        return 10.0
    elif k <= decay_knee:
        # Linear decay from 10 to 1 over [0, decay_knee]
        return 10.0 - (9.0 * k / decay_knee)
    elif k <= max_k:
        # Linear decay from 1 to 0 over [decay_knee, max_k]
        remaining = max_k - decay_knee
        return max(0.0, 1.0 - (k - decay_knee) / remaining)
    else:
        return 0.0


def find_edge_hexes(polygon_hexes: Set[str]) -> Set[str]:
    """
    Find hexes on the boundary of a polygon.
    
    An edge hex is one where at least one k=1 neighbor is NOT in the polygon.
    
    Args:
        polygon_hexes: Set of H3 hex IDs filling the polygon
        
    Returns:
        Set of edge hex IDs
    """
    import h3
    
    edges = set()
    for h in polygon_hexes:
        try:
            neighbors = set(h3.grid_ring(h, 1))
            if not neighbors.issubset(polygon_hexes):
                edges.add(h)
        except Exception:
            pass  # Invalid hex, skip
    return edges


def propagate_single_category(args: Tuple[str, str, int, Dict]) -> Tuple[str, Dict]:
    """
    Propagate a single POI category for a chunk (worker function).
    
    This is the unit of parallelism - we run 380+ of these simultaneously.
    Memory-safe because each worker only handles one category's k-rings.
    
    Args:
        args: (chunk_id, category_name, resolution, poi_hexes_for_category)
        
    Returns:
        (category_name, {hex: {travel_times}})
    """
    import h3
    
    chunk_id, cat_name, resolution, poi_hex_list = args
    edge_m = H3_EDGE_LENGTHS[resolution]
    poi_hexes = set(poi_hex_list)
    results = {}
    
    # k=0: POI hexes themselves
    for poi_hex in poi_hexes:
        results[poi_hex] = {
            f'{cat_name}_walk_min': 0.0,
            f'{cat_name}_cycle_min': 0.0,
            f'{cat_name}_drive_min': 0.0,
            f'{cat_name}_score': 10.0,
        }
    
    # k=1 to max_k: expanding rings (k=25 for Res 10, k=10 for others)
    max_k = get_max_k(resolution)
    for k in range(1, max_k + 1):
        distance_m = k * edge_m
        walk_min = distance_m / TRAVEL_SPEEDS['walk']
        cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
        drive_min = distance_m / TRAVEL_SPEEDS['drive']
        score = get_decay_score(k, resolution)
        
        for poi_hex in poi_hexes:
            try:
                for neighbor in h3.grid_ring(poi_hex, k):
                    if neighbor not in results:
                        results[neighbor] = {}
                    
                    # Keep minimum travel time
                    results[neighbor][f'{cat_name}_walk_min'] = min(
                        results[neighbor].get(f'{cat_name}_walk_min', 999), walk_min
                    )
                    results[neighbor][f'{cat_name}_cycle_min'] = min(
                        results[neighbor].get(f'{cat_name}_cycle_min', 999), cycle_min
                    )
                    results[neighbor][f'{cat_name}_drive_min'] = min(
                        results[neighbor].get(f'{cat_name}_drive_min', 999), drive_min
                    )
                    # Keep max score
                    results[neighbor][f'{cat_name}_score'] = max(
                        results[neighbor].get(f'{cat_name}_score', 0), score
                    )
            except Exception:
                pass
    
    return (cat_name, results)


def run_propagation(args: Tuple[str, int]) -> str:
    """
    Execute K-ring and edge propagation for one chunk at one resolution.
    
    MEMORY-SAFE BATCHED STRATEGY:
    =============================
    Instead of building one massive dictionary with 1,000+ keys per hexagon:
    
    1. Load chunk data ONCE
    2. Process categories in batches of CATEGORY_BATCH_SIZE (default: 100)
    3. Each batch writes to temp parquet: chunk_X_batch_N.parquet
    4. Clear dictionary RAM between batches
    5. Final: DuckDB joins all batch parquets into single output
    
    Why: Python dicts have overhead. A dict with 1,000 keys for 1M hexes
    can bloat RAM unexpectedly. Writing intermediate batches is safer.
    
    Args:
        args: Tuple of (chunk_id, resolution)
        
    Returns:
        Identifier string "{chunk_id}_res{resolution}"
    """
    import h3
    import pandas as pd
    import numpy as np
    import gc
    
    chunk_id, resolution = args
    log.info(f"[PROPAGATE] Starting {chunk_id} @ res{resolution}")
    start = time.time()
    
    # Create batch output directory
    batch_dir = OUTPUT_DIR / 'batch' / f'{chunk_id}_res{resolution}'
    batch_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data files
    hex_fill_path = OUTPUT_DIR / 'hex_fill' / f'{chunk_id}.parquet'
    water_path = OUTPUT_DIR / 'water' / f'{chunk_id}.parquet'
    pois_path = OUTPUT_DIR / 'pois' / f'{chunk_id}.parquet'
    buildings_path = OUTPUT_DIR / 'buildings' / f'{chunk_id}.parquet'
    
    # Read available data
    hex_fill = pd.read_parquet(hex_fill_path) if hex_fill_path.exists() else pd.DataFrame()
    water = pd.read_parquet(water_path) if water_path.exists() else pd.DataFrame()
    pois = pd.read_parquet(pois_path) if pois_path.exists() else pd.DataFrame()
    buildings = pd.read_parquet(buildings_path) if buildings_path.exists() else pd.DataFrame()
    
    # Convert h3 from decimal string to hex string (DuckDB outputs decimal, h3 lib expects hex)
    def to_hex_string(val):
        try:
            # If it's a numeric string, convert to hex format
            if isinstance(val, str) and val.isdigit():
                return h3.int_to_str(int(val))
            elif isinstance(val, (int, np.int64)):
                return h3.int_to_str(int(val))
            return val  # Already hex format
        except:
            return None
    
    for df in [hex_fill, water, pois, buildings]:
        if not df.empty and 'h3_index' in df.columns:
            df['h3_index'] = df['h3_index'].apply(to_hex_string)
            df.dropna(subset=['h3_index'], inplace=True)
    
    # Convert to target resolution (from base resolution 12)
    def to_resolution(hex_id: str) -> str:
        try:
            return h3.cell_to_parent(hex_id, resolution)
        except Exception:
            return None
    
    if resolution < BASE_RESOLUTION:
        if not hex_fill.empty:
            hex_fill['h3_index'] = hex_fill['h3_index'].apply(to_resolution)
            hex_fill = hex_fill.dropna(subset=['h3_index'])
        if not water.empty:
            water['h3_index'] = water['h3_index'].apply(to_resolution)
            water = water.dropna(subset=['h3_index'])
        if not pois.empty:
            pois['h3_index'] = pois['h3_index'].apply(to_resolution)
            pois = pois.dropna(subset=['h3_index'])
        if not buildings.empty:
            buildings['h3_index'] = buildings['h3_index'].apply(to_resolution)
            buildings = buildings.dropna(subset=['h3_index'])
    
    # Collect all unique hexes
    all_hexes = set()
    if not hex_fill.empty:
        all_hexes.update(hex_fill['h3_index'].unique())
    if not water.empty:
        all_hexes.update(water['h3_index'].unique())
    if not pois.empty:
        all_hexes.update(pois['h3_index'].unique())
    if not buildings.empty:
        all_hexes.update(buildings['h3_index'].unique())
    
    if not all_hexes:
        log.warning(f"[PROPAGATE] No hexes found for {chunk_id}")
        return f"{chunk_id}_res{resolution}"
    
    edge_m = H3_EDGE_LENGTHS[resolution]
    all_hexes_list = list(all_hexes)  # For DataFrame creation
    batch_files = []
    
    # =========================================================================
    # BATCH 0: IN-HEX METRICS (Base features - not POI propagation)
    # This batch contains: land use, water, buildings, POI counts
    # =========================================================================
    
    log.info(f"[PROPAGATE] {chunk_id}: Processing base metrics (batch 0)")
    base_matrix = {h: {'h3_index': h} for h in all_hexes}
    
    # Land use counts and areas
    if not hex_fill.empty:
        for class_name in LAND_USE_CLASSES:
            class_data = hex_fill[hex_fill['class'] == class_name]
            if class_data.empty:
                continue
            
            for h3_idx, group in class_data.groupby('h3_index'):
                if h3_idx in base_matrix:
                    base_matrix[h3_idx][f'{class_name}_count'] = group['polygon_id'].nunique()
                    base_matrix[h3_idx][f'{class_name}_in_hex_m2'] = group['polygon_area_m2'].sum()
                    base_matrix[h3_idx][f'{class_name}_avg_area_m2'] = group['polygon_area_m2'].mean()
    
    # Water counts and areas
    if not water.empty:
        for class_name in ['lake', 'river', 'pond', 'sea']:
            class_data = water[water['class'] == class_name]
            if class_data.empty:
                continue
            
            for h3_idx, group in class_data.groupby('h3_index'):
                if h3_idx in base_matrix:
                    base_matrix[h3_idx][f'{class_name}_count'] = group['polygon_id'].nunique()
                    base_matrix[h3_idx][f'{class_name}_in_hex_m2'] = group['polygon_area_m2'].sum()
    
    # POI counts (not travel times - those come in category batches)
    if not pois.empty:
        for cat_name, cat_values in POI_CATEGORIES.items():
            cat_pois = pois[pois['category'].isin(cat_values)]
            if cat_pois.empty:
                continue
            
            for h3_idx, count in cat_pois.groupby('h3_index').size().items():
                if h3_idx in base_matrix:
                    base_matrix[h3_idx][f'{cat_name}_count'] = count
    
    # Building metrics
    if not buildings.empty:
        for h3_idx, group in buildings.groupby('h3_index'):
            if h3_idx in base_matrix:
                base_matrix[h3_idx]['building_count'] = len(group)
                base_matrix[h3_idx]['avg_building_height'] = group['height'].mean() if 'height' in group else None
                base_matrix[h3_idx]['avg_floors'] = group['num_floors'].mean() if 'num_floors' in group else None
                base_matrix[h3_idx]['building_density'] = group['footprint_m2'].sum() if 'footprint_m2' in group else None
    
    # =========================================================================
    # EDGE PROPAGATION: GREEN FEATURES (from land use hex fill)
    # Parks (4 size tiers), beaches, forests, nature_reserve
    # =========================================================================
    
    log.info(f"[PROPAGATE] {chunk_id}: Processing GREEN features edge propagation")
    
    for feature_name, feature_config in GREEN_FEATURES.items():
        if hex_fill.empty:
            continue
        
        # Handle nature_reserve which might be stored with different class names
        if feature_name == 'nature_reserve':
            class_data = hex_fill[hex_fill['class'].isin(['nature_reserve', 'protected_area', 'national_park'])]
        else:
            class_data = hex_fill[hex_fill['class'] == feature_name]
        
        if class_data.empty:
            continue
        
        size_tiers = feature_config.get('size_tiers', {'any': 0})
        
        for poly_id, group in class_data.groupby('polygon_id'):
            poly_hexes = set(group['h3_index'])
            poly_area = group['polygon_area_m2'].iloc[0] if len(group) > 0 else 0
            
            # Find edge hexes
            edges = find_edge_hexes(poly_hexes)
            if not edges:
                continue
            
            # Determine which size tiers this polygon qualifies for
            qualifying_tiers = []
            for tier_name, threshold in size_tiers.items():
                if tier_name == 'any':
                    qualifying_tiers.append('any')
                elif tier_name == 'small' and threshold < 0:
                    # "small" tier: polygon area ≤ abs(threshold)
                    if poly_area <= abs(threshold):
                        qualifying_tiers.append('small')
                elif threshold > 0 and poly_area >= threshold:
                    # Regular tier: polygon area ≥ threshold
                    qualifying_tiers.append(tier_name)
            
            # k=0: edge hexes (inside the feature)
            for edge_hex in edges:
                if edge_hex in base_matrix:
                    for tier in qualifying_tiers:
                        col_suffix = '' if tier == 'any' else f'_{tier}'
                        base_matrix[edge_hex][f'{feature_name}{col_suffix}_walk_min'] = 0.0
                        base_matrix[edge_hex][f'{feature_name}{col_suffix}_cycle_min'] = 0.0
            
            # k=1 to max_k: expanding from edges
            max_k = get_max_k(resolution)
            for k in range(1, max_k + 1):
                distance_m = k * edge_m
                walk_min = distance_m / TRAVEL_SPEEDS['walk']
                cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
                
                for edge_hex in edges:
                    try:
                        ring = h3.grid_ring(edge_hex, k)
                        for neighbor in ring:
                            if neighbor in base_matrix and neighbor not in poly_hexes:
                                for tier in qualifying_tiers:
                                    col_suffix = '' if tier == 'any' else f'_{tier}'
                                    walk_col = f'{feature_name}{col_suffix}_walk_min'
                                    cycle_col = f'{feature_name}{col_suffix}_cycle_min'
                                    
                                    old_walk = base_matrix[neighbor].get(walk_col, 999)
                                    base_matrix[neighbor][walk_col] = min(old_walk, walk_min)
                                    
                                    old_cycle = base_matrix[neighbor].get(cycle_col, 999)
                                    base_matrix[neighbor][cycle_col] = min(old_cycle, cycle_min)
                    except Exception:
                        pass
    
    # =========================================================================
    # EDGE PROPAGATION: BLUE FEATURES (from water hex fill)
    # Lakes, rivers (polygons from water theme)
    # =========================================================================
    
    log.info(f"[PROPAGATE] {chunk_id}: Processing BLUE features edge propagation")
    
    for feature_name, feature_config in BLUE_FEATURES.items():
        # Skip coastlines - handled separately as line features
        if feature_name == 'coastline':
            continue
        
        if water.empty:
            continue
        
        class_data = water[water['class'] == feature_name]
        if class_data.empty:
            continue
        
        size_tiers = feature_config.get('size_tiers', {'any': 0})
        
        for poly_id, group in class_data.groupby('polygon_id'):
            poly_hexes = set(group['h3_index'])
            poly_area = group['polygon_area_m2'].iloc[0] if len(group) > 0 else 0
            
            # Find edge hexes
            edges = find_edge_hexes(poly_hexes)
            if not edges:
                continue
            
            # Determine qualifying tiers
            qualifying_tiers = []
            for tier_name, threshold in size_tiers.items():
                if tier_name == 'any':
                    qualifying_tiers.append('any')
                elif threshold > 0 and poly_area >= threshold:
                    qualifying_tiers.append(tier_name)
            
            # k=0: edge hexes
            for edge_hex in edges:
                if edge_hex in base_matrix:
                    for tier in qualifying_tiers:
                        col_suffix = '' if tier == 'any' else f'_{tier}'
                        base_matrix[edge_hex][f'{feature_name}{col_suffix}_walk_min'] = 0.0
                        base_matrix[edge_hex][f'{feature_name}{col_suffix}_cycle_min'] = 0.0
            
            # k=1 to max_k: expanding from edges
            max_k = get_max_k(resolution)
            for k in range(1, max_k + 1):
                distance_m = k * edge_m
                walk_min = distance_m / TRAVEL_SPEEDS['walk']
                cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
                
                for edge_hex in edges:
                    try:
                        ring = h3.grid_ring(edge_hex, k)
                        for neighbor in ring:
                            if neighbor in base_matrix and neighbor not in poly_hexes:
                                for tier in qualifying_tiers:
                                    col_suffix = '' if tier == 'any' else f'_{tier}'
                                    walk_col = f'{feature_name}{col_suffix}_walk_min'
                                    cycle_col = f'{feature_name}{col_suffix}_cycle_min'
                                    
                                    old_walk = base_matrix[neighbor].get(walk_col, 999)
                                    base_matrix[neighbor][walk_col] = min(old_walk, walk_min)
                                    
                                    old_cycle = base_matrix[neighbor].get(cycle_col, 999)
                                    base_matrix[neighbor][cycle_col] = min(old_cycle, cycle_min)
                    except Exception:
                        pass
    
    # =========================================================================
    # COASTLINE PROPAGATION (LINE features - different handling)
    # Coastlines are lines, not polygons - we propagate from sampled points
    # =========================================================================
    
    coastlines_path = OUTPUT_DIR / 'coastlines' / f'{chunk_id}.parquet'
    if coastlines_path.exists():
        log.info(f"[PROPAGATE] {chunk_id}: Processing coastline edge propagation")
        coastlines = pd.read_parquet(coastlines_path)
        
        # If coastlines have raw geometry (no h3_index), convert using shapely + h3
        if 'geometry_wkb' in coastlines.columns and 'h3_index' not in coastlines.columns:
            from shapely import wkb
            def line_to_hexes(geom_wkb, res):
                """Sample points along line and convert to hexes."""
                try:
                    geom = wkb.loads(geom_wkb)
                    # Sample at ~100m intervals
                    num_points = max(int(geom.length * 111000 / 100), 2)  # rough deg->m
                    hexes = set()
                    for i in range(num_points):
                        pt = geom.interpolate(i / num_points, normalized=True)
                        hexes.add(h3.latlng_to_cell(pt.y, pt.x, res))
                    return list(hexes)
                except:
                    return []
            
            # Expand each geometry into multiple hex rows
            all_rows = []
            for _, row in coastlines.iterrows():
                hexes = line_to_hexes(row['geometry_wkb'], resolution)
                for hex_id in hexes:
                    all_rows.append({'h3_index': hex_id, 'line_id': row['line_id'], 'length_m': row['length_m']})
            coastlines = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
        elif resolution < BASE_RESOLUTION and not coastlines.empty and 'h3_index' in coastlines.columns:
            coastlines['h3_index'] = coastlines['h3_index'].apply(to_resolution)
            coastlines = coastlines.dropna(subset=['h3_index'])
        
        if not coastlines.empty:
            # Get unique coastline hexes (these are the "edges" - points on the coast)
            coast_hexes = set(coastlines['h3_index'].unique())
            
            # k=0: coastline hexes themselves
            for coast_hex in coast_hexes:
                if coast_hex in base_matrix:
                    base_matrix[coast_hex]['coastline_walk_min'] = 0.0
                    base_matrix[coast_hex]['coastline_cycle_min'] = 0.0
            
            # k=1 to max_k: expanding from coastline
            max_k = get_max_k(resolution)
            for k in range(1, max_k + 1):
                distance_m = k * edge_m
                walk_min = distance_m / TRAVEL_SPEEDS['walk']
                cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
                
                for coast_hex in coast_hexes:
                    try:
                        ring = h3.grid_ring(coast_hex, k)
                        for neighbor in ring:
                            if neighbor in base_matrix and neighbor not in coast_hexes:
                                old_walk = base_matrix[neighbor].get('coastline_walk_min', 999)
                                base_matrix[neighbor]['coastline_walk_min'] = min(old_walk, walk_min)
                                
                                old_cycle = base_matrix[neighbor].get('coastline_cycle_min', 999)
                                base_matrix[neighbor]['coastline_cycle_min'] = min(old_cycle, cycle_min)
                    except Exception:
                        pass
    
    # =========================================================================
    # TRANSIT PROPAGATION (Point features - subway, train, bus, tram, etc.)
    # Calculate walk time to nearest station of each type
    # =========================================================================
    
    transit_path = OUTPUT_DIR / 'transit' / f'{chunk_id}.parquet'
    if transit_path.exists():
        log.info(f"[PROPAGATE] {chunk_id}: Processing transit station propagation")
        transit = pd.read_parquet(transit_path)
        
        if resolution < BASE_RESOLUTION and not transit.empty:
            transit['h3_index'] = transit['h3_index'].apply(to_resolution)
            transit = transit.dropna(subset=['h3_index'])
        
        if not transit.empty:
            # Transit types to process
            transit_types = {
                'subway': ['subway_station', 'metro_station', 'underground_station'],
                'train': ['train_station', 'railway_station'],
                'bus': ['bus_station', 'bus_stop'],
                'tram': ['tram_stop', 'tram_station'],
                'light_rail': ['light_rail_station'],
                'ferry': ['ferry_terminal', 'ferry_stop'],
                'airport': ['airport'],
            }
            
            for transit_name, transit_categories in transit_types.items():
                station_data = transit[transit['station_type'].isin(transit_categories)]
                if station_data.empty:
                    continue
                
                station_hexes = set(station_data['h3_index'].unique())
                
                # k=0: station hexes themselves
                for station_hex in station_hexes:
                    if station_hex in base_matrix:
                        base_matrix[station_hex][f'{transit_name}_walk_min'] = 0.0
                        base_matrix[station_hex][f'{transit_name}_cycle_min'] = 0.0
                
                # k=1 to max_k: expanding from stations
                max_k = get_max_k(resolution)
                for k in range(1, max_k + 1):
                    distance_m = k * edge_m
                    walk_min = distance_m / TRAVEL_SPEEDS['walk']
                    cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
                    
                    for station_hex in station_hexes:
                        try:
                            ring = h3.grid_ring(station_hex, k)
                            for neighbor in ring:
                                if neighbor in base_matrix:
                                    old_walk = base_matrix[neighbor].get(f'{transit_name}_walk_min', 999)
                                    base_matrix[neighbor][f'{transit_name}_walk_min'] = min(old_walk, walk_min)
                                    
                                    old_cycle = base_matrix[neighbor].get(f'{transit_name}_cycle_min', 999)
                                    base_matrix[neighbor][f'{transit_name}_cycle_min'] = min(old_cycle, cycle_min)
                        except Exception:
                            pass
    
    # =========================================================================
    # ROAD NETWORK FEATURES (LINE features - pedestrian, cycleway, etc.)
    # Identify road types present in each hex + proximity to major roads
    # =========================================================================
    
    roads_path = OUTPUT_DIR / 'roads' / f'{chunk_id}.parquet'
    if roads_path.exists():
        log.info(f"[PROPAGATE] {chunk_id}: Processing road network features")
        roads = pd.read_parquet(roads_path)
        
        # If roads have raw geometry (no h3_index), convert using shapely + h3
        if 'geometry_wkb' in roads.columns and 'h3_index' not in roads.columns:
            from shapely import wkb
            def wkb_to_hex(geom_wkb, res):
                try:
                    geom = wkb.loads(geom_wkb)
                    centroid = geom.centroid
                    return h3.latlng_to_cell(centroid.y, centroid.x, res)
                except:
                    return None
            roads['h3_index'] = roads['geometry_wkb'].apply(lambda g: wkb_to_hex(g, resolution))
            roads = roads.dropna(subset=['h3_index'])
        elif resolution < BASE_RESOLUTION and not roads.empty and 'h3_index' in roads.columns:
            roads['h3_index'] = roads['h3_index'].apply(to_resolution)
            roads = roads.dropna(subset=['h3_index'])
        
        if not roads.empty:
            # Road classes for in-hex presence (binary)
            presence_classes = ['pedestrian', 'cycleway', 'footway', 'living_street']
            
            # Road classes for proximity calculation
            proximity_classes = ['motorway', 'trunk', 'primary', 'secondary']
            
            # In-hex presence: is there a pedestrian/cycleway in this hex?
            for road_class in presence_classes:
                class_hexes = set(roads[roads['road_class'] == road_class]['h3_index'].unique())
                for hex_id in class_hexes:
                    if hex_id in base_matrix:
                        base_matrix[hex_id][f'{road_class}_in_hex'] = 1
            
            # Proximity to major roads (motorway, trunk, primary, secondary)
            for road_class in proximity_classes:
                class_hexes = set(roads[roads['road_class'] == road_class]['h3_index'].unique())
                if not class_hexes:
                    continue
                
                # k=0: road hexes themselves
                for road_hex in class_hexes:
                    if road_hex in base_matrix:
                        base_matrix[road_hex][f'{road_class}_road_walk_min'] = 0.0
                
                # k=1 to max_k: expanding from roads
                max_k = get_max_k(resolution)
                for k in range(1, max_k + 1):
                    distance_m = k * edge_m
                    walk_min = distance_m / TRAVEL_SPEEDS['walk']
                    
                    for road_hex in class_hexes:
                        try:
                            ring = h3.grid_ring(road_hex, k)
                            for neighbor in ring:
                                if neighbor in base_matrix:
                                    old_walk = base_matrix[neighbor].get(f'{road_class}_road_walk_min', 999)
                                    base_matrix[neighbor][f'{road_class}_road_walk_min'] = min(old_walk, walk_min)
                        except Exception:
                            pass
    
    # Write batch 0
    df_base = pd.DataFrame.from_dict(base_matrix, orient='index')
    
    # Fill NaN with 0 for count and area columns (absence of feature = 0, not NaN)
    # Travel time columns stay as NaN (meaning "beyond propagation range")
    count_cols = [c for c in df_base.columns if c.endswith('_count')]
    area_cols = [c for c in df_base.columns if c.endswith('_in_hex_m2') or c.endswith('_in_hex')]
    fill_zero_cols = count_cols + area_cols
    if fill_zero_cols:
        df_base[fill_zero_cols] = df_base[fill_zero_cols].fillna(0)
        log.info(f"[PROPAGATE] {chunk_id}: Filled {len(fill_zero_cols)} count/area columns with 0")
    
    batch0_path = batch_dir / 'batch_000.parquet'
    df_base.to_parquet(batch0_path, compression='zstd', index=False)
    batch_files.append(batch0_path)
    
    # Clear RAM
    del base_matrix, df_base
    gc.collect()
    
    log.info(f"[PROPAGATE] {chunk_id}: Wrote batch 0 (base metrics)")
    
    # =========================================================================
    # BATCHES 1-N: POI K-RING PROPAGATION (Travel Times)
    # Process categories in batches of CATEGORY_BATCH_SIZE
    # =========================================================================
    
    if not pois.empty:
        # Build list of categories with POIs in this chunk
        cat_items = list(POI_CATEGORIES.items())
        n_batches = (len(cat_items) + CATEGORY_BATCH_SIZE - 1) // CATEGORY_BATCH_SIZE
        
        log.info(f"[PROPAGATE] {chunk_id}: Processing {len(cat_items)} POI categories in {n_batches} batches of {CATEGORY_BATCH_SIZE}")
        
        for batch_idx in range(n_batches):
            batch_start = batch_idx * CATEGORY_BATCH_SIZE
            batch_end = min(batch_start + CATEGORY_BATCH_SIZE, len(cat_items))
            batch_cats = cat_items[batch_start:batch_end]
            
            log.info(f"[PROPAGATE] {chunk_id}: Batch {batch_idx + 1}/{n_batches} ({len(batch_cats)} categories)")
            
            # Build tasks for this batch
            cat_tasks = []
            for cat_name, cat_values in batch_cats:
                cat_pois = pois[pois['category'].isin(cat_values)]
                if not cat_pois.empty:
                    poi_hex_list = cat_pois['h3_index'].unique().tolist()
                    cat_tasks.append((chunk_id, cat_name, resolution, poi_hex_list))
            
            if not cat_tasks:
                continue
            
            # Initialize batch matrix with just h3_index
            batch_matrix = {h: {'h3_index': h} for h in all_hexes}
            
            # Parallel execution for this batch using ThreadPoolExecutor
            # Threads are lightweight and share memory - ideal for inner loop
            # ProcessPoolExecutor is used for outer chunk parallelism
            n_workers = min(THREADS_PER_CHUNK, len(cat_tasks))
            
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = {executor.submit(propagate_single_category, task): task[1] 
                           for task in cat_tasks}
                
                for future in as_completed(futures):
                    cat_name = futures[future]
                    try:
                        _, cat_results = future.result()
                        # Merge category results into batch matrix
                        for h, values in cat_results.items():
                            if h in batch_matrix:
                                batch_matrix[h].update(values)
                            else:
                                # Hex reached by propagation but not in original set
                                batch_matrix[h] = {'h3_index': h, **values}
                    except Exception as e:
                        log.warning(f"[PROPAGATE] Category {cat_name} failed: {e}")
            
            # Write this batch
            df_batch = pd.DataFrame.from_dict(batch_matrix, orient='index')
            batch_path = batch_dir / f'batch_{batch_idx + 1:03d}.parquet'
            df_batch.to_parquet(batch_path, compression='zstd', index=False)
            batch_files.append(batch_path)
            
            # Clear RAM
            del batch_matrix, df_batch
            gc.collect()
            
            log.info(f"[PROPAGATE] {chunk_id}: Wrote batch {batch_idx + 1}/{n_batches}")
    
    # =========================================================================
    # FINAL MERGE: Join all batch parquets with DuckDB
    # =========================================================================
    
    log.info(f"[PROPAGATE] {chunk_id}: Merging {len(batch_files)} batch files")
    
    output_path = OUTPUT_DIR / 'matrix' / f'{chunk_id}_res{resolution}.parquet'
    
    if len(batch_files) == 1:
        # Only one batch, just copy it
        import shutil
        shutil.copy(batch_files[0], output_path)
    else:
        # Multiple batches - merge INCREMENTALLY to avoid memory blow-up
        # Instead of 12-way JOIN, do sequential: b0+b1→temp1, temp1+b2→temp2, etc.
        import shutil
        batch_paths = [str(p) for p in batch_files]
        
        # Start with first batch as current result
        current = batch_dir / 'merged_current.parquet'
        shutil.copy(batch_paths[0], current)
        
        for i, bpath in enumerate(batch_paths[1:], start=1):
            next_result = batch_dir / f'merged_step_{i}.parquet'
            merge_sql = f"""
        COPY (
                SELECT a.*, b.* EXCLUDE (h3_index)
                FROM read_parquet('{current}') a
                LEFT JOIN read_parquet('{bpath}') b ON a.h3_index = b.h3_index
            ) TO '{next_result}' (FORMAT PARQUET, COMPRESSION ZSTD);
            """
            try:
                result = subprocess.run(['duckdb', '-c', merge_sql], check=True, capture_output=True, timeout=MERGE_TIMEOUT_SECONDS)
            except subprocess.CalledProcessError as e:
                log.error(f"[PROPAGATE] DuckDB merge step {i} failed: {e.stderr.decode() if e.stderr else 'unknown'}")
                raise
            except subprocess.TimeoutExpired:
                log.error(f"[PROPAGATE] DuckDB merge step {i} timed out after {MERGE_TIMEOUT_SECONDS}s")
                raise
            current.unlink(missing_ok=True)
            current = next_result
            if i % 3 == 0:
                log.info(f"[PROPAGATE] {chunk_id}: Merged {i+1}/{len(batch_paths)} batches")
        shutil.copy(current, output_path)
    
    # Clean up batch files
    import shutil
    shutil.rmtree(batch_dir, ignore_errors=True)
    
    elapsed = time.time() - start
    
    # Get final row count
    try:
        import pyarrow.parquet as pq
        final_rows = pq.read_metadata(output_path).num_rows
    except Exception:
        final_rows = 0
    
    log.info(f"[PROPAGATE] Completed {chunk_id} @ res{resolution} in {elapsed:.1f}s ({final_rows} hexes)")
    
    return f"{chunk_id}_res{resolution}"


# =============================================================================
# PHASE 3: AGGREGATION & MERGE
# =============================================================================

def aggregate_to_res5(chunk_id: str) -> str:
    """
    Aggregate resolution 8 matrix to resolution 5.
    
    Only counts and areas can aggregate; travel times cannot.
    
    Args:
        chunk_id: Geographic chunk identifier
        
    Returns:
        Output file path
    """
    import h3
    import pandas as pd
    
    res8_path = OUTPUT_DIR / 'matrix' / f'{chunk_id}_res8.parquet'
    if not res8_path.exists():
        log.warning(f"[AGGREGATE] Missing res8 for {chunk_id}")
        return None
    
    df = pd.read_parquet(res8_path)
    
    # Convert to res 5
    df['h3_res5'] = df['h3_index'].apply(lambda x: h3.cell_to_parent(x, 5))
    
    # Build aggregation functions
    agg_funcs = {}
    for col in df.columns:
        if col in ['h3_index', 'h3_res5']:
            continue
        if '_count' in col:
            agg_funcs[col] = 'sum'
        elif '_in_hex_m2' in col:
            agg_funcs[col] = 'sum'
        elif '_avg_' in col or 'avg_' in col:
            agg_funcs[col] = 'mean'
        elif '_density' in col:
            agg_funcs[col] = 'sum'
        # Skip travel times and scores - they don't aggregate correctly
    
    if not agg_funcs:
        return None
    
    res5 = df.groupby('h3_res5').agg(agg_funcs).reset_index()
    res5 = res5.rename(columns={'h3_res5': 'h3_index'})
    
    output_path = OUTPUT_DIR / 'matrix' / f'{chunk_id}_res5.parquet'
    res5.to_parquet(output_path, compression='zstd', index=False)
    
    log.info(f"[AGGREGATE] Completed {chunk_id} res8→res5 ({len(res5)} hexes)")
    return str(output_path)


def merge_all_chunks(resolution: int) -> str:
    """
    Merge all chunk parquets for a resolution into single global file.
    
    Also performs final cleanup: fills NaN with 0 for count/area columns.
    Travel time columns (walk_min, cycle_min, drive_min) stay as NaN
    to indicate "beyond propagation range".
    
    Args:
        resolution: H3 resolution (5, 8, 10, or 11)
        
    Returns:
        Output file path
    """
    log.info(f"[MERGE] Starting resolution {resolution}")
    
    output_file = FINAL_OUTPUT / f'earth_matrix_maxed_res{resolution}.parquet'
    temp_file = FINAL_OUTPUT / f'earth_matrix_maxed_res{resolution}_temp.parquet'
    
    # Step 1: Merge all chunks
    merge_sql = f"""
    COPY (
        SELECT * FROM read_parquet('{OUTPUT_DIR}/matrix/*_res{resolution}.parquet')
        ORDER BY h3_index
    ) TO '{temp_file}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """
    
    try:
        subprocess.run(['duckdb', '-c', merge_sql], check=True, capture_output=True, timeout=1800)
        log.info(f"[MERGE] Merged chunks for resolution {resolution}")
    except subprocess.CalledProcessError as e:
        log.error(f"[MERGE] Failed resolution {resolution}: {e.stderr}")
        raise
    
    # Step 2: Fill NaN with 0 for count/area columns (safety net)
    # This ensures count=0 means "no feature", not NaN
    log.info(f"[MERGE] Cleaning up NaN values in count/area columns...")
    
    import pandas as pd
    
    try:
        df = pd.read_parquet(temp_file)
        
        # Identify columns to fill with 0
        count_cols = [c for c in df.columns if c.endswith('_count')]
        area_cols = [c for c in df.columns if c.endswith('_in_hex_m2') or c.endswith('_in_hex')]
        fill_zero_cols = count_cols + area_cols
        
        if fill_zero_cols:
            before_nan = df[fill_zero_cols].isna().sum().sum()
            df[fill_zero_cols] = df[fill_zero_cols].fillna(0)
            after_nan = df[fill_zero_cols].isna().sum().sum()
            log.info(f"[MERGE] Filled {before_nan - after_nan:,} NaN values with 0 in {len(fill_zero_cols)} columns")
        
        # Write final output
        df.to_parquet(output_file, compression='zstd', index=False)
        
        # Cleanup temp file
        temp_file.unlink(missing_ok=True)
        
        log.info(f"[MERGE] Completed resolution {resolution}")
        return str(output_file)
        
    except Exception as e:
        log.error(f"[MERGE] NaN cleanup failed for resolution {resolution}: {e}")
        # Fall back to temp file if cleanup fails
        import shutil
        shutil.move(str(temp_file), str(output_file))
        return str(output_file)


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def main():
    """Main entry point for global Earth Matrix build."""
    parser = argparse.ArgumentParser(
        description='Build Global Earth Matrix',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--duckdb-workers', type=int, default=DEFAULT_DUCKDB_WORKERS,
        help=f'Parallel DuckDB instances (default: {DEFAULT_DUCKDB_WORKERS})'
    )
    parser.add_argument(
        '--python-workers', type=int, default=DEFAULT_PYTHON_WORKERS,
        help=f'Parallel Python processes (default: {DEFAULT_PYTHON_WORKERS})'
    )
    parser.add_argument(
        '--max-gdp-rank', type=int, default=None,
        help='Only process countries up to this GDP rank (for testing)'
    )
    parser.add_argument(
        '--skip-phase1', action='store_true',
        help='Skip hex fill phase (if already complete)'
    )
    parser.add_argument(
        '--skip-phase2', action='store_true',
        help='Skip propagation phase (if already complete)'
    )
    parser.add_argument(
        '--test-mode', action='store_true',
        help='Run in test mode (uses TEST_REGION from env or hoxton by default)'
    )
    parser.add_argument(
        '--test-region', type=str, default=None,
        help='Test region: hoxton, greater_london, or uk (implies --test-mode)'
    )
    parser.add_argument(
        '--max-chunks', type=int, default=None,
        help=f'Max concurrent chunks for bounded parallelism (default: {MAX_CONCURRENT_CHUNKS})'
    )
    parser.add_argument(
        '--threads-per-chunk', type=int, default=None,
        help=f'Threads per chunk for category propagation (default: {THREADS_PER_CHUNK})'
    )
    args = parser.parse_args()
    
    # Determine if we're in test mode
    is_test_mode = args.test_mode or args.test_region is not None or TEST_MODE
    test_region = args.test_region or TEST_REGION
    
    # Adjust parallelism for local testing
    if is_test_mode:
        # Local machine: fewer workers, conservative parallelism
        if args.duckdb_workers == DEFAULT_DUCKDB_WORKERS:
            args.duckdb_workers = 4
        if args.python_workers == DEFAULT_PYTHON_WORKERS:
            args.python_workers = 8
    
    # Store effective parallelism settings in args for easy access
    args.effective_max_chunks = args.max_chunks if args.max_chunks is not None else (2 if is_test_mode else MAX_CONCURRENT_CHUNKS)
    args.effective_threads = args.threads_per_chunk if args.threads_per_chunk is not None else (4 if is_test_mode else THREADS_PER_CHUNK)
    
    start_time = time.time()
    
    # Load checkpoint for resume capability
    checkpoint = load_checkpoint()
    if checkpoint.get("completed_chunks"):
        log.info(f"Resuming from checkpoint: {len(checkpoint['completed_chunks'])} chunks already done")
    
    # Determine run name for benchmarking
    run_name = f"{test_region}_test" if is_test_mode else "global_build"
    
    log.info("=" * 70)
    if is_test_mode:
        log.info(f"🧪 TEST MODE: Earth Matrix Build ({test_region})")
    else:
        log.info("GLOBAL EARTH MATRIX BUILD (ULTRA-MAXED Schema)")
    log.info("=" * 70)
    log.info(f"Instance: {'Local Machine' if is_test_mode else 'm8i.96xlarge (384 vCPU, 1.5TB RAM, 100Gbps)'}")
    log.info(f"POI Categories: {len(POI_CATEGORIES)} (ALL Level-3)")
    log.info(f"POI Confidence Threshold: {POI_CONFIDENCE_THRESHOLD:.0%} (filters low-quality POIs)")
    log.info(f"Land Use Classes: {len(LAND_USE_CLASSES)}")
    log.info(f"DuckDB workers: {args.duckdb_workers}")
    log.info(f"Concurrent chunks: {args.effective_max_chunks} (bounded parallelism)")
    log.info(f"Threads per chunk: {args.effective_threads}")
    log.info(f"Resolutions: {RESOLUTIONS} + aggregated res5")
    log.info(f"Output directory: {FINAL_OUTPUT}")
    log.info(f"Estimated columns: ~5,745")
    log.info(f"Benchmarking: {'Enabled' if BENCHMARKING_AVAILABLE else 'Disabled'}")
    log.info("=" * 70)
    
    # Setup directories
    for subdir in ['hex_fill', 'water', 'pois', 'buildings', 'coastlines', 'transit', 'roads', 'matrix', 'batch']:
        (OUTPUT_DIR / subdir).mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT.mkdir(parents=True, exist_ok=True)
    
    # Generate processing queue (respects TEST_MODE)
    queue = generate_processing_queue(
        max_gdp_rank=args.max_gdp_rank,
        test_mode=is_test_mode,
        test_region=test_region,
    )
    log.info(f"Processing {len(queue)} geographic chunks")
    
    # Log test region details if applicable
    if is_test_mode and queue:
        chunk = queue[0]
        log.info(f"Test region: {chunk.get('name', test_region)}")
        log.info(f"Bounding box: {chunk.get('bbox')}")
        if 'area_km2' in chunk:
            log.info(f"Area: {chunk['area_km2']} km²")
    
    # =========================================================================
    # RUN BUILD (with benchmarking in test mode)
    # =========================================================================
    
    def run_build():
        """Execute all build phases."""
        _run_phases(args, queue, checkpoint, is_test_mode)
    
    if is_test_mode and BENCHMARKING_AVAILABLE:
        log.info("📊 Benchmarking enabled for cost extrapolation")
        with BenchmarkContext(run_name, test_region=test_region) as ctx:
            run_build()
    else:
        run_build()


def _run_phases(args, queue, checkpoint, is_test_mode):
    """Internal function to run all build phases."""
    # =========================================================================
    # PHASE 1: DuckDB Hex Fill
    # =========================================================================
    
    if not args.skip_phase1:
        log.info("")
        log.info("=" * 70)
        log.info("PHASE 1: DuckDB Hex Fill")
        log.info("=" * 70)
        
        with measure_task("Phase 1: DuckDB Hex Fill"):
            with mp.Pool(args.duckdb_workers) as pool:
                results = pool.map(run_hex_fill, queue)
            
            # Log metrics for cost extrapolation
            log_metric("phase1_chunks_processed", len(results), "chunks", phase="hex_fill")
    else:
        log.info("Skipping Phase 1 (hex fill)")
    
    # =========================================================================
    # PHASE 2: Python Propagation
    # MEMORY-SAFE: Process chunks SEQUENTIALLY, categories in PARALLEL
    # =========================================================================
    
    if not args.skip_phase2:
        log.info("")
        log.info("=" * 70)
        log.info("PHASE 2: Python Propagation (Bounded Parallelism)")
        log.info("=" * 70)
        log.info(f"Strategy: {len(queue)} chunks × {len(RESOLUTIONS)} resolutions")
        log.info(f"Concurrent chunks: {args.effective_max_chunks} (bounded for memory safety)")
        log.info(f"Threads per chunk: {args.effective_threads}")
        
        phase2_start = time.time()
        completed = 0
        total_tasks = len(queue) * len(RESOLUTIONS)
        
        # Build list of all (chunk_id, resolution) tasks
        all_tasks = []
        for chunk in queue:
            for resolution in RESOLUTIONS:
                task_id = f"{chunk['chunk_id']}_res{resolution}"
                # Skip if already done (checkpoint)
                if task_id in checkpoint.get("completed_propagations", []):
                    log.info(f"[PROPAGATE] Skipping {task_id} (already done)")
                    completed += 1
                else:
                    all_tasks.append((chunk['chunk_id'], resolution))
        
        log.info(f"[PROPAGATE] {len(all_tasks)} tasks to process, {completed} already done")
        
        # BOUNDED PARALLELISM: Process up to max_chunks at once
        # This keeps CPU at ~90% while staying safe on RAM
        # Set env var for worker processes to pick up
        os.environ['THREADS_PER_CHUNK'] = str(args.effective_threads)
        
        if all_tasks:
            with ProcessPoolExecutor(max_workers=args.effective_max_chunks) as executor:
                futures = {executor.submit(run_propagation, task): task for task in all_tasks}
                
                for future in as_completed(futures):
                    task = futures[future]
                    task_id = f"{task[0]}_res{task[1]}"
                    try:
                        future.result()
                        
                        # Mark done in checkpoint
                        checkpoint.setdefault("completed_propagations", []).append(task_id)
                        save_checkpoint(checkpoint)
                        
                        completed += 1
                        elapsed = time.time() - phase2_start
                        rate = completed / elapsed if elapsed > 0 else 0
                        eta = (total_tasks - completed) / rate if rate > 0 else 0
                        log.info(f"[PROPAGATE] Progress: {completed}/{total_tasks} ({100*completed/total_tasks:.1f}%) ETA: {eta/60:.1f} min")
                        
                    except Exception as e:
                        log.error(f"[PROPAGATE] Failed {task_id}: {e}")
                        # Continue with next (don't crash entire build)
        
        phase2_elapsed = time.time() - phase2_start
        log.info(f"Phase 2 complete: {completed} matrices in {phase2_elapsed/60:.1f} min")
        
        # Log propagation metrics for cost extrapolation
        log_metric("phase2_matrices_completed", completed, "matrices", phase="propagation")
        log_metric("phase2_duration_s", phase2_elapsed, "seconds", phase="propagation")
        if phase2_elapsed > 0:
            rate = completed / phase2_elapsed
            log_metric("propagation_rate", rate, "matrices/sec", phase="propagation")
    else:
        log.info("Skipping Phase 2 (propagation)")
    
    # =========================================================================
    # PHASE 3a: Aggregate to Resolution 5
    # =========================================================================
    
    log.info("")
    log.info("=" * 70)
    log.info("PHASE 3a: Aggregate to Resolution 5")
    log.info("=" * 70)
    
    with measure_task("Phase 3a: Aggregate to Resolution 5"):
        chunk_ids = [c['chunk_id'] for c in queue]
        with mp.Pool(args.duckdb_workers) as pool:
            pool.map(aggregate_to_res5, chunk_ids)
        
        log_metric("phase3a_chunks_aggregated", len(chunk_ids), "chunks", phase="aggregation")
    
    # =========================================================================
    # PHASE 3b: Merge All Chunks
    # =========================================================================
    
    log.info("")
    log.info("=" * 70)
    log.info("PHASE 3b: Merge All Chunks")
    log.info("=" * 70)
    
    with measure_task("Phase 3b: Merge All Chunks"):
        # Merge all resolutions: res5 (aggregated) + RESOLUTIONS (8, 10)
        for res in [5] + RESOLUTIONS:
            merge_all_chunks(res)
        
        # Log final output sizes
        for f in FINAL_OUTPUT.glob('*.parquet'):
            size_mb = f.stat().st_size / (1024**2)
            log_metric(f"output_size_{f.stem}", size_mb, "MB", phase="merge")
    
    # =========================================================================
    # COMPLETE
    # =========================================================================
    
    log.info("")
    log.info("=" * 70)
    log.info("BUILD PHASES COMPLETE")
    log.info("=" * 70)
    log.info(f"Output files:")
    total_size_mb = 0
    for f in FINAL_OUTPUT.glob('*.parquet'):
        size_mb = f.stat().st_size / (1024**2)
        total_size_mb += size_mb
        log.info(f"  {f.name}: {size_mb:.1f} MB")
    
    # Log final metrics
    log_metric("total_output_size_mb", total_size_mb, "MB", phase="complete")
    log.info("=" * 70)


if __name__ == "__main__":
    main()

