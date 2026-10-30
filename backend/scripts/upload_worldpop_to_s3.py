#!/usr/bin/env python3
"""
Upload WorldPop R2025A data to S3 as Cloud-Optimized GeoTIFFs (COGs)

This script:
1. Downloads WorldPop R2025A data from HDX/WorldPop
2. Converts to Cloud-Optimized GeoTIFF format
3. Uploads to S3 for instant range-read access

Usage:
    # Upload specific countries
    python upload_worldpop_to_s3.py ESP FRA DEU
    
    # Upload all 241 countries (takes ~18 hours)
    python upload_worldpop_to_s3.py --all
    
    # Upload priority countries (top 50 by population)
    python upload_worldpop_to_s3.py --priority
    
    # Include age/sex data (WARNING: much larger files!)
    python upload_worldpop_to_s3.py ESP --include-agesex
"""

import os
import sys
import subprocess
import tempfile
import shutil
import logging
import argparse
import requests
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
S3_BUCKET = "puedo-casa-html-archive"
S3_PREFIX = "worldpop"
WORLDPOP_BASE_URL = "https://data.worldpop.org/GIS"
DEFAULT_YEAR = 2026

# URL patterns
POPULATION_URL = "{base}/Population/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/constrained/{iso3_lower}_pop_{year}_CN_100m_R2025A_v1.tif"
AGESEX_URL = "{base}/AgeSex_structures/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/{iso3_lower}_agesex_structures_{year}_CN_100m_R2025A_v1.zip"

# Priority countries (top 50 by population + key markets)
PRIORITY_COUNTRIES = [
    'CHN', 'IND', 'USA', 'IDN', 'PAK', 'BRA', 'NGA', 'BGD', 'RUS', 'MEX',
    'JPN', 'ETH', 'PHL', 'EGY', 'VNM', 'COD', 'TUR', 'IRN', 'DEU', 'THA',
    'GBR', 'FRA', 'ITA', 'TZA', 'ZAF', 'KEN', 'MMR', 'KOR', 'COL', 'ESP',
    'UGA', 'ARG', 'DZA', 'SDN', 'UKR', 'IRQ', 'AFG', 'POL', 'CAN', 'MAR',
    'SAU', 'UZB', 'PER', 'AGO', 'MYS', 'MOZ', 'GHA', 'YEM', 'NPL', 'VEN',
]

# All 241 countries (will be fetched from HDX)
def get_all_countries() -> List[str]:
    """Fetch all available countries from HDX."""
    try:
        url = "https://data.humdata.org/api/3/action/package_search"
        params = {'q': 'worldpop-population-counts-2015-2030', 'rows': 300}
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        countries = []
        for result in data.get('result', {}).get('results', []):
            name = result.get('name', '')
            if 'population-counts-2015-2030' in name:
                iso3 = name.split('-')[-1].upper()
                if len(iso3) == 3:
                    countries.append(iso3)
        
        return sorted(set(countries))
    except Exception as e:
        logger.error(f"Failed to fetch country list: {e}")
        return PRIORITY_COUNTRIES


def check_s3_exists(s3_path: str) -> bool:
    """Check if file exists on S3."""
    result = subprocess.run(
        ['aws', 's3', 'ls', s3_path],
        capture_output=True, text=True
    )
    return result.returncode == 0 and len(result.stdout.strip()) > 0


def download_file(url: str, dest: Path, desc: str = "") -> bool:
    """Download file with progress."""
    logger.info(f"📥 Downloading {desc}: {url[:80]}...")
    try:
        response = requests.get(url, stream=True, timeout=600)
        response.raise_for_status()
        
        total = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (10 * 1024 * 1024) < 65536:
                    pct = (downloaded / total) * 100
                    logger.info(f"   {downloaded / (1024*1024):.0f} MB / {total / (1024*1024):.0f} MB ({pct:.0f}%)")
        
        return True
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return False


def convert_to_cog(input_path: Path, output_path: Path) -> bool:
    """Convert GeoTIFF to Cloud-Optimized GeoTIFF."""
    logger.info(f"🔄 Converting to COG: {input_path.name}")
    try:
        result = subprocess.run(
            ['rio', 'cogeo', 'create', str(input_path), str(output_path), '--overview-level', '5'],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            logger.error(f"COG conversion failed: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ COG conversion failed: {e}")
        return False


def upload_to_s3(local_path: Path, s3_path: str) -> bool:
    """Upload file to S3."""
    logger.info(f"☁️ Uploading to S3: {s3_path}")
    try:
        result = subprocess.run(
            ['aws', 's3', 'cp', str(local_path), s3_path, '--no-progress'],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            logger.error(f"S3 upload failed: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ S3 upload failed: {e}")
        return False


def process_country_population(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> bool:
    """Download, convert, and upload population data for one country."""
    s3_key = f"s3://{S3_BUCKET}/{S3_PREFIX}/{iso3}/{iso3.lower()}_pop_{year}_COG.tif"
    
    # Check if already uploaded
    if not force and check_s3_exists(s3_key):
        logger.info(f"✅ {iso3} population {year} already on S3, skipping")
        return True
    
    # Build download URL
    url = POPULATION_URL.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Download
        raw_file = tmpdir / f"{iso3.lower()}_pop_{year}_raw.tif"
        if not download_file(url, raw_file, f"{iso3} population {year}"):
            return False
        
        # Convert to COG
        cog_file = tmpdir / f"{iso3.lower()}_pop_{year}_COG.tif"
        if not convert_to_cog(raw_file, cog_file):
            return False
        
        # Upload to S3
        if not upload_to_s3(cog_file, s3_key):
            return False
    
    logger.info(f"✅ {iso3} population {year} uploaded successfully!")
    return True


def process_country_agesex(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> bool:
    """Download, convert, and upload age/sex data for one country."""
    # This downloads a ZIP with multiple TIFs, converts each to COG
    s3_prefix = f"s3://{S3_BUCKET}/{S3_PREFIX}/{iso3}/agesex_{year}/"
    
    # Check if already uploaded (check for at least one file)
    test_key = f"{s3_prefix}{iso3.lower()}_f_0_2020_COG.tif"  # Example file
    if not force and check_s3_exists(test_key):
        logger.info(f"✅ {iso3} age/sex {year} already on S3, skipping")
        return True
    
    url = AGESEX_URL.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Download ZIP
        zip_file = tmpdir / f"{iso3.lower()}_agesex_{year}.zip"
        if not download_file(url, zip_file, f"{iso3} age/sex {year}"):
            return False
        
        # Extract
        extract_dir = tmpdir / "extracted"
        logger.info(f"📦 Extracting {zip_file.name}...")
        import zipfile
        with zipfile.ZipFile(zip_file, 'r') as zf:
            zf.extractall(extract_dir)
        
        # Convert each TIF to COG and upload
        tif_files = list(extract_dir.rglob("*.tif"))
        logger.info(f"   Found {len(tif_files)} TIF files")
        
        for i, tif_file in enumerate(tif_files):
            cog_file = tmpdir / f"{tif_file.stem}_COG.tif"
            
            if not convert_to_cog(tif_file, cog_file):
                continue
            
            s3_key = f"{s3_prefix}{tif_file.stem}_COG.tif"
            if not upload_to_s3(cog_file, s3_key):
                continue
            
            # Clean up COG to save space
            cog_file.unlink()
            
            if (i + 1) % 10 == 0:
                logger.info(f"   Processed {i + 1}/{len(tif_files)} files")
    
    logger.info(f"✅ {iso3} age/sex {year} uploaded successfully!")
    return True


def main():
    parser = argparse.ArgumentParser(description='Upload WorldPop data to S3 as COGs')
    parser.add_argument('countries', nargs='*', help='ISO3 country codes (e.g., ESP FRA DEU)')
    parser.add_argument('--all', action='store_true', help='Upload all 241 countries')
    parser.add_argument('--priority', action='store_true', help='Upload top 50 priority countries')
    parser.add_argument('--include-agesex', action='store_true', help='Also upload age/sex data (large!)')
    parser.add_argument('--year', type=int, default=DEFAULT_YEAR, help='Year (2015-2030)')
    parser.add_argument('--force', action='store_true', help='Re-upload even if exists')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be uploaded')
    
    args = parser.parse_args()
    
    # Determine which countries to process
    if args.all:
        countries = get_all_countries()
    elif args.priority:
        countries = PRIORITY_COUNTRIES
    elif args.countries:
        countries = [c.upper() for c in args.countries]
    else:
        print("Usage: python upload_worldpop_to_s3.py ESP FRA DEU")
        print("       python upload_worldpop_to_s3.py --priority")
        print("       python upload_worldpop_to_s3.py --all")
        sys.exit(1)
    
    logger.info(f"=" * 60)
    logger.info(f"WorldPop to S3 Uploader")
    logger.info(f"   Countries: {len(countries)}")
    logger.info(f"   Year: {args.year}")
    logger.info(f"   Include age/sex: {args.include_agesex}")
    logger.info(f"=" * 60)
    
    if args.dry_run:
        for iso3 in countries:
            print(f"Would upload: {iso3} population {args.year}")
            if args.include_agesex:
                print(f"Would upload: {iso3} age/sex {args.year}")
        sys.exit(0)
    
    # Process countries
    success = 0
    failed = []
    
    for i, iso3 in enumerate(countries):
        logger.info(f"\n[{i+1}/{len(countries)}] Processing {iso3}...")
        
        if process_country_population(iso3, args.year, args.force):
            success += 1
        else:
            failed.append(iso3)
        
        if args.include_agesex:
            process_country_agesex(iso3, args.year, args.force)
    
    # Summary
    logger.info(f"\n" + "=" * 60)
    logger.info(f"✅ Completed: {success}/{len(countries)} countries")
    if failed:
        logger.info(f"❌ Failed: {failed}")
    logger.info(f"=" * 60)


if __name__ == "__main__":
    main()
