#!/usr/bin/env python3
"""
Upload WorldPop R2025A data to S3 as Cloud-Optimized GeoTIFFs (COGs)

This script:
1. Downloads WorldPop R2025A data from HDX/WorldPop
2. Converts to Cloud-Optimized GeoTIFF format
3. Uploads to S3 for instant range-read access

Default and --dry-run print a local plan. Execute a selected transfer with
--upload, an explicit owner account/bucket/region and byte allowances.
See docs/CLOUD-COSTS.md for the complete configuration and per-run bounds.
"""

import os
import sys
import subprocess
import tempfile
import shutil
import logging
import argparse
import re
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
S3_BUCKET = ""
AWS_REGION = ""
AWS_ACCOUNT_ID = ""
_account_verified = False
_allowance = None
_aws_calls = 0
MAX_AWS_CALLS = 256
S3_PREFIX = "worldpop"
WORLDPOP_BASE_URL = "https://data.worldpop.org/GIS"
DEFAULT_YEAR = 2026


class TransferAllowance:
    """Conservative per-run transfer bounds; failed attempts consume allowance."""
    def __init__(self, download_bytes, upload_bytes, max_files=1000):
        if min(download_bytes, upload_bytes, max_files) <= 0:
            raise ValueError('Choose positive download, upload and file limits.')
        self.download_limit = download_bytes
        self.upload_limit = upload_bytes
        self.max_files = max_files
        self.downloaded = 0
        self.uploaded = 0
        self.files = 0

    def download(self, size):
        if size < 0 or self.downloaded + size > self.download_limit:
            raise ValueError('The download allowance is used. Choose the next transfer explicitly.')
        self.downloaded += size

    def upload(self, size):
        if size < 0 or self.uploaded + size > self.upload_limit or self.files >= self.max_files:
            raise ValueError('The upload allowance is used. Choose the next transfer explicitly.')
        self.uploaded += size
        self.files += 1


def _aws(arguments, *, verifying=False):
    global _aws_calls
    if not AWS_REGION or not AWS_ACCOUNT_ID or not S3_BUCKET or (not verifying and not _account_verified):
        raise RuntimeError('Configure and verify the selected account and bucket first.')
    if _aws_calls >= MAX_AWS_CALLS:
        raise ValueError('The AWS request allowance is used. Choose the next transfer explicitly.')
    _aws_calls += 1
    environment = {**os.environ, 'AWS_MAX_ATTEMPTS': '1', 'AWS_RETRY_MODE': 'standard'}
    return subprocess.run(['aws', '--region', AWS_REGION, *arguments],
                          capture_output=True, text=True, timeout=600, env=environment)


def verify_cloud_owner():
    """Check the explicit account and bucket before any data download or upload."""
    global _account_verified
    _account_verified = False
    identity = _aws(['sts', 'get-caller-identity', '--query', 'Account', '--output', 'text'], verifying=True)
    if identity.returncode or identity.stdout.strip() != AWS_ACCOUNT_ID:
        raise RuntimeError('Select credentials for the account supplied with --account-id.')
    bucket = _aws(['s3api', 'head-bucket', '--bucket', S3_BUCKET,
                   '--expected-bucket-owner', AWS_ACCOUNT_ID], verifying=True)
    if bucket.returncode:
        raise RuntimeError('Select an accessible bucket owned by the supplied account.')
    _account_verified = True


def configure_cloud_transfer(*, bucket, account_id, region, download_bytes, upload_bytes,
                             max_files=1000, max_aws_requests=256):
    """Select an owned destination and allowances before connected file work."""
    global S3_BUCKET, AWS_REGION, AWS_ACCOUNT_ID, _allowance, _aws_calls, MAX_AWS_CALLS
    if not bucket or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ValueError('Supply the selected bucket with --bucket.')
    if not account_id or not re.fullmatch(r'[0-9]{12}', account_id):
        raise ValueError('Supply the selected 12-digit account with --account-id.')
    if not region or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[0-9]', region):
        raise ValueError('Supply the selected AWS region with --region.')
    if any(n is None or n <= 0 for n in [download_bytes, upload_bytes, max_files, max_aws_requests]):
        raise ValueError('Supply positive byte, file and AWS request allowances.')
    S3_BUCKET, AWS_REGION, AWS_ACCOUNT_ID = bucket, region, account_id
    _aws_calls, MAX_AWS_CALLS = 0, max_aws_requests
    _allowance = TransferAllowance(download_bytes, upload_bytes, max_files)
    verify_cloud_owner()

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
    import requests
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
                if re.fullmatch(r'[A-Z]{3}', iso3):
                    countries.append(iso3)
        
        return sorted(set(countries))
    except Exception as e:
        raise RuntimeError('Choose explicit ISO3 codes or retry the country-list request.') from e


def check_s3_exists(s3_path: str) -> bool:
    """Check if file exists on S3."""
    result = _aws(['s3', 'ls', s3_path])
    return result.returncode == 0 and len(result.stdout.strip()) > 0


def download_file(url: str, dest: Path, desc: str = "") -> bool:
    """Download file with progress."""
    if not _account_verified or _allowance is None:
        raise RuntimeError('Configure the selected account and transfer allowance first.')
    import requests
    logger.info(f"📥 Downloading {desc}: {url[:80]}...")
    try:
        response = requests.get(url, stream=True, timeout=600)
        response.raise_for_status()
        
        total = int(response.headers.get('content-length', 0))
        if total > _allowance.download_limit - _allowance.downloaded:
            response.close()
            raise ValueError('Choose a download allowance that covers this file.')
        downloaded = 0
        
        with open(dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                _allowance.download(len(chunk))
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
        if _allowance is None:
            raise RuntimeError('Configure a transfer allowance first.')
        _allowance.upload(local_path.stat().st_size)
        result = _aws(['s3', 'cp', str(local_path), s3_path, '--no-progress'])
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
            members = zf.infolist()
            if len(members) > _allowance.max_files or sum(m.file_size for m in members) > _allowance.download_limit:
                raise ValueError('Choose file and expanded-byte allowances that cover this archive.')
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
    parser.add_argument('--upload', action='store_true', help='Execute an explicitly configured transfer')
    parser.add_argument('--bucket', help='Bucket owned by the selected AWS account')
    parser.add_argument('--account-id', help='Expected 12-digit AWS account ID')
    parser.add_argument('--region', help='Region of the selected bucket')
    parser.add_argument('--max-download-bytes', type=int, help='Total data-download allowance for this run')
    parser.add_argument('--max-upload-bytes', type=int, help='Total conservative upload allowance for this run')
    parser.add_argument('--max-countries', type=int, default=1, help='Country limit for this run (default: 1)')
    parser.add_argument('--max-files', type=int, default=1000, help='Upload/archive member limit (default: 1000)')
    parser.add_argument('--max-aws-requests', type=int, default=256, help='AWS CLI invocation limit (default: 256)')
    
    args = parser.parse_args()

    if not args.upload or args.dry_run:
        print('WorldPop transfer: local plan only.')
        print('Select --upload, --bucket, --account-id, --region and explicit download/upload byte allowances to transfer data.')
        print('Country selection: ' + ('all available countries' if args.all else 'priority countries' if args.priority else ', '.join(args.countries) or 'choose ISO3 codes'))
        print('Historical transfer design: docs/historical/cloud-build-scripts.md')
        return 0

    if not 2015 <= args.year <= 2030:
        parser.error('Choose a year from 2015 through 2030.')
    if sum([args.all, args.priority, bool(args.countries)]) != 1:
        parser.error('Select ISO3 codes, --priority or --all.')
    if any(not re.fullmatch(r'[A-Za-z]{3}', c) for c in args.countries):
        parser.error('Use three-letter ISO3 country codes.')
    limits = [args.max_download_bytes, args.max_upload_bytes, args.max_countries, args.max_files, args.max_aws_requests]
    if any(n is None or n <= 0 for n in limits):
        parser.error('Supply positive byte, country, file and AWS request allowances.')
    known_countries = PRIORITY_COUNTRIES if args.priority else list(dict.fromkeys(c.upper() for c in args.countries))
    if not args.all and len(known_countries) > args.max_countries:
        parser.error('The selected countries exceed --max-countries. Choose the transfer scope explicitly.')
    try:
        configure_cloud_transfer(bucket=args.bucket, account_id=args.account_id, region=args.region,
                                 download_bytes=args.max_download_bytes, upload_bytes=args.max_upload_bytes,
                                 max_files=args.max_files, max_aws_requests=args.max_aws_requests)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        parser.error(str(error))
    
    # Determine which countries to process
    if args.all:
        try:
            countries = get_all_countries()
        except RuntimeError as error:
            parser.error(str(error))
    elif args.priority:
        countries = PRIORITY_COUNTRIES
    elif args.countries:
        countries = [c.upper() for c in args.countries]
    else:
        print("Usage: python upload_worldpop_to_s3.py ESP FRA DEU")
        print("       python upload_worldpop_to_s3.py --priority")
        print("       python upload_worldpop_to_s3.py --all")
        sys.exit(1)
    countries = list(dict.fromkeys(countries))
    if len(countries) > args.max_countries:
        parser.error('The selected countries exceed --max-countries. Choose the transfer scope explicitly.')
    
    logger.info(f"=" * 60)
    logger.info(f"WorldPop to S3 Uploader")
    logger.info(f"   Countries: {len(countries)}")
    logger.info(f"   Year: {args.year}")
    logger.info(f"   Include age/sex: {args.include_agesex}")
    logger.info(f"=" * 60)
    
    # Process countries
    success = 0
    failed = []
    
    for i, iso3 in enumerate(countries):
        logger.info(f"\n[{i+1}/{len(countries)}] Processing {iso3}...")
        
        if process_country_population(iso3, args.year, args.force):
            success += 1
        else:
            failed.append(iso3)
        
        if args.include_agesex and not process_country_agesex(iso3, args.year, args.force):
            failed.append(iso3 + ' age/sex')
    
    # Summary
    logger.info(f"\n" + "=" * 60)
    logger.info(f"✅ Completed: {success}/{len(countries)} countries")
    if failed:
        logger.info(f"❌ Failed: {failed}")
    logger.info(f"=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
