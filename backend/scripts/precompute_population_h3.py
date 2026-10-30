#!/usr/bin/env python3
"""
Pre-compute Global Population H3 Grid from GHS-POP
===================================================

This script converts Copernicus GHS-POP raster data to H3 hexagon parquet files
that can be queried instantly with DuckDB (like Overture Maps).

Output Structure (S3):
    s3://puedo-casa-population/h3_res8/
        ├── 80/  (H3 res-0 prefix for partitioning)
        │   ├── population_80.parquet
        │   └── ...
        ├── 81/
        └── ...

Each parquet file contains:
    - hex: H3 cell index (resolution 8)
    - population: Population count
    - lat: Cell center latitude
    - lng: Cell center longitude

Query Example:
    SELECT * FROM read_parquet('s3://puedo-casa-population/h3_res8/*/*.parquet')
    WHERE hex LIKE '88...'  -- Filter by H3 prefix for bbox

Cost Estimate:
    - Storage: ~2-5 GB for global data = ~$0.12/month
    - Queries: ~$0.005 per query (scan ~100MB)
    - Total: ~$2/month for moderate usage

Usage:
    # Process a single tile (for testing)
    python precompute_population_h3.py --tile R5_C19  # Tokyo area
    
    # Process all tiles (full global coverage)
    python precompute_population_h3.py --all
    
    # Upload to S3
    python precompute_population_h3.py --upload

Requirements:
    pip install rasterio h3 pandas pyarrow boto3 tqdm
"""

import os
import sys
import argparse
import logging
import tempfile
import zipfile
import requests
import numpy as np
import pandas as pd
import h3
from pathlib import Path
from typing import Optional, Tuple, List
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# GHS-POP source (same as tools_demographics.py)
GHS_TILES_BASE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_POP_GLOBE_R2023A/GHS_POP_E2025_GLOBE_R2023A_4326_3ss/V1-0/tiles"
)

# Output configuration
OUTPUT_DIR = Path("./data/population_h3")
S3_BUCKET = "puedo-casa-population"
S3_PREFIX = "h3_res8"

# H3 resolution options:
#   8 = ~460m edge (neighborhood) - ~2GB global, fast queries
#   9 = ~174m edge (street level) - ~15GB global, recommended
#  10 = ~66m edge (building level) - ~100GB global, detailed
H3_RESOLUTION = 10  # Building level for detailed analysis

# Tile grid (18 rows x 36 cols, each 10° x 10°)
TILE_ROWS = 18
TILE_COLS = 36

# =============================================================================
# REGIONAL PRESETS (process just the areas you need)
# =============================================================================

REGIONS = {
    # Format: 'name': [(row, col), (row, col), ...]
    # Row 1 = 80-90°N, Row 18 = 80-90°S
    # Col 1 = 180-170°W, Col 36 = 170-180°E
    
    'japan': [
        (5, 32), (5, 33),  # Northern Japan (Hokkaido)
        (6, 32), (6, 33),  # Central Japan (Tokyo, Osaka)
        (7, 32), (7, 33),  # Southern Japan (Kyushu)
    ],
    
    'tokyo': [
        (6, 33),  # Tokyo metro area (single tile)
    ],
    
    'europe_west': [
        (5, 18), (5, 19), (5, 20),  # UK, Ireland, France north
        (6, 18), (6, 19), (6, 20),  # Spain, France, Germany
    ],
    
    'usa_east': [
        (5, 8), (5, 9), (5, 10),   # Northeast
        (6, 8), (6, 9), (6, 10),   # Southeast
    ],
    
    'usa_west': [
        (5, 5), (5, 6), (5, 7),    # Pacific Northwest
        (6, 5), (6, 6), (6, 7),    # California, Southwest
    ],
    
    'china_east': [
        (5, 29), (5, 30), (5, 31),  # Northern China
        (6, 29), (6, 30), (6, 31),  # Eastern China (Shanghai, etc)
    ],
    
    'india': [
        (6, 26), (6, 27),  # Northern India
        (7, 26), (7, 27),  # Southern India
    ],
    
    'brazil': [
        (8, 12), (8, 13),   # Northern Brazil
        (9, 12), (9, 13),   # Central Brazil
        (10, 12), (10, 13), # Southern Brazil
    ],
    
    'africa_west': [
        (7, 18), (7, 19),  # West Africa (Ghana, Nigeria)
        (8, 18), (8, 19),  # Central West Africa
    ],
    
    # Time estimates at H3 res 10:
    # - tokyo: ~10 minutes (1 tile)
    # - japan: ~45 minutes (6 tiles)
    # - europe_west: ~2 hours (6 tiles)
    # - usa_east: ~2 hours (6 tiles)
}


# =============================================================================
# TILE PROCESSING
# =============================================================================

def download_tile(row: int, col: int, cache_dir: Path) -> Optional[Path]:
    """Download a GHS-POP tile if not cached."""
    tile_name = f"GHS_POP_E2025_GLOBE_R2023A_4326_3ss_V1_0_R{row}_C{col}"
    tif_path = cache_dir / f"{tile_name}.tif"
    
    if tif_path.exists():
        logger.debug(f"Using cached: R{row}_C{col}")
        return tif_path
    
    zip_url = f"{GHS_TILES_BASE}/{tile_name}.zip"
    zip_path = cache_dir / f"{tile_name}.zip"
    
    logger.info(f"Downloading R{row}_C{col}...")
    
    try:
        response = requests.get(zip_url, stream=True, timeout=120)
        if response.status_code == 404:
            logger.debug(f"Tile R{row}_C{col} not found (ocean/unpopulated)")
            return None
        response.raise_for_status()
        
        # Download with progress
        total = int(response.headers.get('content-length', 0))
        with open(zip_path, 'wb') as f:
            for chunk in tqdm(response.iter_content(8192), 
                            total=total//8192, 
                            desc=f"R{row}_C{col}",
                            leave=False):
                f.write(chunk)
        
        # Extract
        with zipfile.ZipFile(zip_path, 'r') as zf:
            tif_files = [f for f in zf.namelist() if f.endswith('.tif')]
            if tif_files:
                zf.extract(tif_files[0], cache_dir)
                extracted = cache_dir / tif_files[0]
                if extracted != tif_path:
                    extracted.rename(tif_path)
        
        zip_path.unlink()
        return tif_path
        
    except Exception as e:
        logger.warning(f"Failed R{row}_C{col}: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return None


def process_tile_to_h3(tif_path: Path, resolution: int = H3_RESOLUTION) -> pd.DataFrame:
    """
    Convert a GHS-POP GeoTIFF tile to H3 hexagon DataFrame.
    
    Args:
        tif_path: Path to the GeoTIFF file
        resolution: H3 resolution (default 8)
        
    Returns:
        DataFrame with columns: hex, population, lat, lng
    """
    import rasterio
    
    logger.info(f"Processing {tif_path.name}...")
    
    h3_data = {}
    
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        transform = src.transform
        
        rows, cols = data.shape
        logger.info(f"  Tile size: {rows}x{cols} pixels")
        
        # Process in chunks for memory efficiency
        chunk_size = 1000
        total_chunks = (rows // chunk_size + 1) * (cols // chunk_size + 1)
        
        with tqdm(total=total_chunks, desc="  Processing", leave=False) as pbar:
            for r_start in range(0, rows, chunk_size):
                for c_start in range(0, cols, chunk_size):
                    r_end = min(r_start + chunk_size, rows)
                    c_end = min(c_start + chunk_size, cols)
                    
                    for r in range(r_start, r_end):
                        for c in range(c_start, c_end):
                            pop_value = data[r, c]
                            
                            # Skip NoData/zero
                            if pop_value <= 0 or np.isnan(pop_value):
                                continue
                            
                            # Get coordinates
                            lon, lat = rasterio.transform.xy(transform, r, c)
                            
                            # Convert to H3
                            hex_id = h3.latlng_to_cell(lat, lon, resolution)
                            
                            # Aggregate population per hex
                            h3_data[hex_id] = h3_data.get(hex_id, 0) + pop_value
                    
                    pbar.update(1)
    
    # Convert to DataFrame
    if not h3_data:
        return pd.DataFrame(columns=['hex', 'population', 'lat', 'lng'])
    
    records = []
    for hex_id, pop in h3_data.items():
        lat, lng = h3.cell_to_latlng(hex_id)
        records.append({
            'hex': hex_id,
            'population': int(round(pop)),
            'lat': round(lat, 6),
            'lng': round(lng, 6)
        })
    
    df = pd.DataFrame(records)
    logger.info(f"  Generated {len(df)} H3 hexagons, total pop: {df['population'].sum():,}")
    
    return df


def save_parquet(df: pd.DataFrame, tile_row: int, tile_col: int, output_dir: Path):
    """Save DataFrame as parquet, partitioned by H3 prefix."""
    if df.empty:
        return
    
    # Get H3 res-0 prefix for partitioning (first 2 chars after '8')
    # This creates ~122 partitions globally
    df['h3_prefix'] = df['hex'].str[:3]
    
    for prefix, group in df.groupby('h3_prefix'):
        partition_dir = output_dir / prefix
        partition_dir.mkdir(parents=True, exist_ok=True)
        
        out_path = partition_dir / f"R{tile_row}_C{tile_col}.parquet"
        group.drop(columns=['h3_prefix']).to_parquet(out_path, index=False)
    
    logger.info(f"  Saved to {output_dir}")


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_single_tile(row: int, col: int, cache_dir: Path, output_dir: Path):
    """Process a single GHS-POP tile."""
    tif_path = download_tile(row, col, cache_dir)
    
    if tif_path is None:
        logger.info(f"Tile R{row}_C{col} not available (ocean/unpopulated)")
        return
    
    df = process_tile_to_h3(tif_path)
    save_parquet(df, row, col, output_dir)


def process_all_tiles(cache_dir: Path, output_dir: Path, skip_existing: bool = True):
    """Process all GHS-POP tiles globally."""
    logger.info(f"Processing all {TILE_ROWS * TILE_COLS} tiles...")
    
    for row in range(1, TILE_ROWS + 1):
        for col in range(1, TILE_COLS + 1):
            # Check if already processed
            if skip_existing:
                # Check if any parquet exists for this tile
                existing = list(output_dir.glob(f"*/R{row}_C{col}.parquet"))
                if existing:
                    logger.debug(f"Skipping R{row}_C{col} (already processed)")
                    continue
            
            try:
                process_single_tile(row, col, cache_dir, output_dir)
            except Exception as e:
                logger.error(f"Error processing R{row}_C{col}: {e}")
                continue


def upload_to_s3(local_dir: Path, bucket: str, prefix: str):
    """Upload processed parquet files to S3."""
    import boto3
    
    logger.info(f"Uploading to s3://{bucket}/{prefix}/...")
    
    s3 = boto3.client('s3')
    
    parquet_files = list(local_dir.glob("**/*.parquet"))
    logger.info(f"Found {len(parquet_files)} parquet files")
    
    for pq_file in tqdm(parquet_files, desc="Uploading"):
        # Preserve partition structure
        relative_path = pq_file.relative_to(local_dir)
        s3_key = f"{prefix}/{relative_path}"
        
        s3.upload_file(str(pq_file), bucket, s3_key)
    
    logger.info(f"✅ Uploaded to s3://{bucket}/{prefix}/")


# =============================================================================
# QUERY HELPER (for tools_demographics.py)
# =============================================================================

def query_population_h3_s3(
    bbox: list,
    bucket: str = S3_BUCKET,
    prefix: str = S3_PREFIX,
    resolution: int = H3_RESOLUTION
) -> list[dict]:
    """
    Query pre-computed population H3 data from S3.
    
    This is the FAST version - replaces fetch_ghs_population().
    Should return in <2 seconds for any bbox.
    
    Args:
        bbox: [west, south, east, north]
        bucket: S3 bucket name
        prefix: S3 prefix
        resolution: H3 resolution (must match pre-computed data)
        
    Returns:
        List of dicts [{'hex': '...', 'count': 1234}, ...]
    """
    import duckdb
    
    west, south, east, north = bbox
    
    # Initialize DuckDB with S3 access
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    conn.execute("SET s3_region='us-west-2';")
    
    # Query with bbox filter
    # DuckDB will use partition pruning on h3_prefix
    query = f"""
    SELECT hex, population as count
    FROM read_parquet('s3://{bucket}/{prefix}/*/*.parquet')
    WHERE lat >= {south} AND lat <= {north}
      AND lng >= {west} AND lng <= {east}
    """
    
    result = conn.execute(query).fetchdf()
    conn.close()
    
    return result.to_dict('records')


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Pre-compute GHS-POP to H3 parquet")
    parser.add_argument('--tile', type=str, help="Single tile (e.g., R5_C19 for Tokyo)")
    parser.add_argument('--all', action='store_true', help="Process all tiles")
    parser.add_argument('--upload', action='store_true', help="Upload to S3")
    parser.add_argument('--output', type=str, default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument('--cache', type=str, default='/tmp/ghs_cache', help="Tile cache directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    cache_dir = Path(args.cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    if args.tile:
        # Parse tile ID (e.g., "R5_C19")
        parts = args.tile.upper().replace('R', '').replace('C', '_').split('_')
        row, col = int(parts[0]), int(parts[1])
        logger.info(f"Processing single tile: R{row}_C{col}")
        process_single_tile(row, col, cache_dir, output_dir)
        
    elif args.all:
        logger.info("Processing all global tiles...")
        process_all_tiles(cache_dir, output_dir)
        
    elif args.upload:
        upload_to_s3(output_dir, S3_BUCKET, S3_PREFIX)
        
    else:
        parser.print_help()
        print("\n📋 Quick Start:")
        print("  1. Test with Tokyo: python precompute_population_h3.py --tile R5_C19")
        print("  2. Process all:     python precompute_population_h3.py --all")
        print("  3. Upload to S3:    python precompute_population_h3.py --upload")


if __name__ == "__main__":
    main()

