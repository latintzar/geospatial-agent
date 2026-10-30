"""
Demographics & Population Tools - WorldPop R2025A

Provides population density and age/sex structure data using WorldPop R2025A v1:
- 100m resolution (constrained to settlements)
- Annual estimates 2015-2030
- Global coverage (200+ countries)
- Default year: 2020 (or 2026 for projections)

Data Source:
- WorldPop R2025A v1 via HDX: https://data.humdata.org/
- Direct download: https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/
- Resolution: 100m (constrained)
- Format: GeoTIFF

Data Types:
- Population counts: Single TIF per country/year (~50-300MB)
- Age/Sex structures: ZIP with multiple TIFs per country/year (~1-10GB)

Usage:
    from tools_demographics import get_population_density, get_population_for_location
    
    # Get population for a bounding box
    result = get_population_density(bbox=[minx, miny, maxx, maxy])
    
    # Get population for a location name
    result = get_population_for_location("Madrid, Spain")
    
    # Download data for a country (run once, then data is cached)
    download_country_data("ESP", year=2020)
"""

import os
import logging
import requests
import subprocess
import zipfile
import h3
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Union

# Import formatting helper
try:
    from ..utils_formatting import format_layer, format_h3_layer
except ImportError:
    try:
        from utils_formatting import format_layer, format_h3_layer
    except ImportError:
        # Fallback if helper not available
        format_layer = None
        format_h3_layer = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import masking utility for Focus + Context pattern (Google Earth style)
try:
    from ..utils_spatial import mask_layer_by_aoi
except ImportError:
    try:
        from utils_spatial import mask_layer_by_aoi
    except ImportError:
        mask_layer_by_aoi = None
        logger.warning("mask_layer_by_aoi not available - Focus+Context masking disabled")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default year for population estimates (2015-2030 available)
DEFAULT_YEAR = 2026

# S3 Configuration (primary data source - 218+ countries already uploaded)
S3_BUCKET = "puedo-casa-html-archive"
S3_PREFIX = "worldpop"
S3_REGION = "us-east-1"

# Local data directory (fallback/cache)
DATA_DIR = Path(__file__).parent.parent / "data" / "worldpop"

# WorldPop R2025A direct download URLs
WORLDPOP_BASE_URL = "https://data.worldpop.org/GIS"

# URL patterns for R2025A data
POPULATION_URL_PATTERN = "{base}/Population/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/constrained/{iso3_lower}_pop_{year}_CN_100m_R2025A_v1.tif"
AGESEX_URL_PATTERN = "{base}/AgeSex_structures/Global_2015_2030/R2025A/{year}/{iso3_upper}/v1/100m/{iso3_lower}_agesex_structures_{year}_CN_100m_R2025A_v1.zip"

# HDX API for discovering available datasets
HDX_API_BASE = "https://data.humdata.org/api/3/action"

# Minimum bbox size to avoid tiny queries
MIN_BBOX_SIZE_DEG = 0.001  # ~100m


def _ensure_data_dir() -> Path:
    """Ensure WorldPop data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _find_s3_key(iso3: str, year: int) -> Optional[str]:
    """Find the S3 key for a country's population file (handles different naming)."""
    try:
        import boto3
        s3_client = boto3.client('s3', region_name=S3_REGION)
        prefix = f"{S3_PREFIX}/{iso3.upper()}/"
        
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        for obj in response.get('Contents', []):
            key = obj['Key']
            # Match files like esp_pop_2026.tif or esp_pop_2026_COG.tif
            if f"{iso3.lower()}_pop_{year}" in key and key.endswith('.tif'):
                return key
        return None
    except Exception as e:
        logger.debug(f"S3 lookup failed: {e}")
        return None


def _get_s3_url(iso3: str, year: int) -> Optional[str]:
    """Get presigned S3 URL for a country's population file."""
    try:
        import boto3
        key = _find_s3_key(iso3, year)
        if not key:
            return None
        
        s3_client = boto3.client('s3', region_name=S3_REGION)
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': key},
            ExpiresIn=3600  # 1 hour
        )
        return url
    except Exception as e:
        logger.warning(f"Could not generate presigned URL: {e}")
        return None


def _check_s3_exists(iso3: str, year: int) -> bool:
    """Check if population file exists on S3."""
    return _find_s3_key(iso3, year) is not None


def _get_data_source(iso3: str, year: int, auto_download: bool = True) -> Optional[str]:
    """
    Get the best available data source for a country.
    Priority: S3 > Local file > Auto-download from WorldPop
    
    Returns:
        URL or path string to data source, or None if not available
    """
    # 1. Check S3 first (instant access, no download needed)
    if _check_s3_exists(iso3, year):
        s3_url = _get_s3_url(iso3, year)
        logger.info(f"   {iso3}: Using S3 ({s3_url.split('/')[-1]})")
        return s3_url
    
    # 2. Check local file
    local_path = get_population_file_path(iso3, year)
    if local_path.exists():
        logger.info(f"   {iso3}: Using local file")
        return str(local_path)
    
    # 3. Auto-download from WorldPop if enabled
    if auto_download:
        logger.info(f"   {iso3}: Downloading from WorldPop...")
        downloaded = download_population_data(iso3, year)
        if downloaded and downloaded.exists():
            return str(downloaded)
    
    logger.warning(f"   {iso3}: No data available (not on S3, not local)")
    return None


# =============================================================================
# COUNTRY CODES
# =============================================================================

ISO2_TO_ISO3 = {
    'AD': 'AND', 'AE': 'ARE', 'AF': 'AFG', 'AG': 'ATG', 'AI': 'AIA', 'AL': 'ALB',
    'AM': 'ARM', 'AO': 'AGO', 'AQ': 'ATA', 'AR': 'ARG', 'AS': 'ASM', 'AT': 'AUT',
    'AU': 'AUS', 'AW': 'ABW', 'AX': 'ALA', 'AZ': 'AZE', 'BA': 'BIH', 'BB': 'BRB',
    'BD': 'BGD', 'BE': 'BEL', 'BF': 'BFA', 'BG': 'BGR', 'BH': 'BHR', 'BI': 'BDI',
    'BJ': 'BEN', 'BL': 'BLM', 'BM': 'BMU', 'BN': 'BRN', 'BO': 'BOL', 'BQ': 'BES',
    'BR': 'BRA', 'BS': 'BHS', 'BT': 'BTN', 'BV': 'BVT', 'BW': 'BWA', 'BY': 'BLR',
    'BZ': 'BLZ', 'CA': 'CAN', 'CC': 'CCK', 'CD': 'COD', 'CF': 'CAF', 'CG': 'COG',
    'CH': 'CHE', 'CI': 'CIV', 'CK': 'COK', 'CL': 'CHL', 'CM': 'CMR', 'CN': 'CHN',
    'CO': 'COL', 'CR': 'CRI', 'CU': 'CUB', 'CV': 'CPV', 'CW': 'CUW', 'CX': 'CXR',
    'CY': 'CYP', 'CZ': 'CZE', 'DE': 'DEU', 'DJ': 'DJI', 'DK': 'DNK', 'DM': 'DMA',
    'DO': 'DOM', 'DZ': 'DZA', 'EC': 'ECU', 'EE': 'EST', 'EG': 'EGY', 'EH': 'ESH',
    'ER': 'ERI', 'ES': 'ESP', 'ET': 'ETH', 'FI': 'FIN', 'FJ': 'FJI', 'FK': 'FLK',
    'FM': 'FSM', 'FO': 'FRO', 'FR': 'FRA', 'GA': 'GAB', 'GB': 'GBR', 'GD': 'GRD',
    'GE': 'GEO', 'GF': 'GUF', 'GG': 'GGY', 'GH': 'GHA', 'GI': 'GIB', 'GL': 'GRL',
    'GM': 'GMB', 'GN': 'GIN', 'GP': 'GLP', 'GQ': 'GNQ', 'GR': 'GRC', 'GS': 'SGS',
    'GT': 'GTM', 'GU': 'GUM', 'GW': 'GNB', 'GY': 'GUY', 'HK': 'HKG', 'HM': 'HMD',
    'HN': 'HND', 'HR': 'HRV', 'HT': 'HTI', 'HU': 'HUN', 'ID': 'IDN', 'IE': 'IRL',
    'IL': 'ISR', 'IM': 'IMN', 'IN': 'IND', 'IO': 'IOT', 'IQ': 'IRQ', 'IR': 'IRN',
    'IS': 'ISL', 'IT': 'ITA', 'JE': 'JEY', 'JM': 'JAM', 'JO': 'JOR', 'JP': 'JPN',
    'KE': 'KEN', 'KG': 'KGZ', 'KH': 'KHM', 'KI': 'KIR', 'KM': 'COM', 'KN': 'KNA',
    'KP': 'PRK', 'KR': 'KOR', 'KW': 'KWT', 'KY': 'CYM', 'KZ': 'KAZ', 'LA': 'LAO',
    'LB': 'LBN', 'LC': 'LCA', 'LI': 'LIE', 'LK': 'LKA', 'LR': 'LBR', 'LS': 'LSO',
    'LT': 'LTU', 'LU': 'LUX', 'LV': 'LVA', 'LY': 'LBY', 'MA': 'MAR', 'MC': 'MCO',
    'MD': 'MDA', 'ME': 'MNE', 'MF': 'MAF', 'MG': 'MDG', 'MH': 'MHL', 'MK': 'MKD',
    'ML': 'MLI', 'MM': 'MMR', 'MN': 'MNG', 'MO': 'MAC', 'MP': 'MNP', 'MQ': 'MTQ',
    'MR': 'MRT', 'MS': 'MSR', 'MT': 'MLT', 'MU': 'MUS', 'MV': 'MDV', 'MW': 'MWI',
    'MX': 'MEX', 'MY': 'MYS', 'MZ': 'MOZ', 'NA': 'NAM', 'NC': 'NCL', 'NE': 'NER',
    'NF': 'NFK', 'NG': 'NGA', 'NI': 'NIC', 'NL': 'NLD', 'NO': 'NOR', 'NP': 'NPL',
    'NR': 'NRU', 'NU': 'NIU', 'NZ': 'NZL', 'OM': 'OMN', 'PA': 'PAN', 'PE': 'PER',
    'PF': 'PYF', 'PG': 'PNG', 'PH': 'PHL', 'PK': 'PAK', 'PL': 'POL', 'PM': 'SPM',
    'PN': 'PCN', 'PR': 'PRI', 'PS': 'PSE', 'PT': 'PRT', 'PW': 'PLW', 'PY': 'PRY',
    'QA': 'QAT', 'RE': 'REU', 'RO': 'ROU', 'RS': 'SRB', 'RU': 'RUS', 'RW': 'RWA',
    'SA': 'SAU', 'SB': 'SLB', 'SC': 'SYC', 'SD': 'SDN', 'SE': 'SWE', 'SG': 'SGP',
    'SH': 'SHN', 'SI': 'SVN', 'SJ': 'SJM', 'SK': 'SVK', 'SL': 'SLE', 'SM': 'SMR',
    'SN': 'SEN', 'SO': 'SOM', 'SR': 'SUR', 'SS': 'SSD', 'ST': 'STP', 'SV': 'SLV',
    'SX': 'SXM', 'SY': 'SYR', 'SZ': 'SWZ', 'TC': 'TCA', 'TD': 'TCD', 'TF': 'ATF',
    'TG': 'TGO', 'TH': 'THA', 'TJ': 'TJK', 'TK': 'TKL', 'TL': 'TLS', 'TM': 'TKM',
    'TN': 'TUN', 'TO': 'TON', 'TR': 'TUR', 'TT': 'TTO', 'TV': 'TUV', 'TW': 'TWN',
    'TZ': 'TZA', 'UA': 'UKR', 'UG': 'UGA', 'UK': 'GBR', 'UM': 'UMI', 'US': 'USA',
    'UY': 'URY', 'UZ': 'UZB', 'VA': 'VAT', 'VC': 'VCT', 'VE': 'VEN', 'VG': 'VGB',
    'VI': 'VIR', 'VN': 'VNM', 'VU': 'VUT', 'WF': 'WLF', 'WS': 'WSM', 'XK': 'XKX',
    'YE': 'YEM', 'YT': 'MYT', 'ZA': 'ZAF', 'ZM': 'ZMB', 'ZW': 'ZWE',
}

ISO3_TO_ISO2 = {v: k for k, v in ISO2_TO_ISO3.items()}


# =============================================================================
# COUNTRY DETECTION
# =============================================================================

def detect_countries_from_bbox(bbox: List[float]) -> List[str]:
    """
    Detect which countries a bounding box intersects using reverse geocoding.
    
    Args:
        bbox: [west, south, east, north] in WGS84
        
    Returns:
        List of ISO3 country codes
    """
    west, south, east, north = bbox
    
    # Sample points within the bbox to detect countries
    sample_points = [
        ((west + east) / 2, (south + north) / 2),  # center
        (west, south),  # SW corner
        (east, south),  # SE corner
        (west, north),  # NW corner
        (east, north),  # NE corner
    ]
    
    countries = set()
    
    for lon, lat in sample_points:
        try:
            url = "https://nominatim.openstreetmap.org/reverse"
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'zoom': 3,
            }
            headers = {'User-Agent': 'Leo-Demographics/1.0'}
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                address = data.get('address', {})
                country_code = address.get('country_code', '').upper()
                
                if country_code and country_code in ISO2_TO_ISO3:
                    countries.add(ISO2_TO_ISO3[country_code])
                
        except Exception as e:
            logger.debug(f"Reverse geocode failed for ({lon}, {lat}): {e}")
            continue
    
    if not countries:
        logger.warning("Could not detect countries from bbox")
        return []
    
    logger.info(f"Detected countries: {list(countries)}")
    return list(countries)


# =============================================================================
# DATA DOWNLOAD FUNCTIONS
# =============================================================================

def get_population_file_path(iso3: str, year: int) -> Path:
    """Get the expected local path for a population GeoTIFF."""
    return DATA_DIR / iso3.upper() / f"{iso3.lower()}_pop_{year}_CN_100m_R2025A_v1.tif"


def get_agesex_dir_path(iso3: str, year: int) -> Path:
    """Get the expected local directory for age/sex GeoTIFFs."""
    return DATA_DIR / iso3.upper() / f"agesex_{year}"


def download_population_data(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> Optional[Path]:
    """
    Download WorldPop R2025A population data for a country.
    
    Args:
        iso3: ISO3 country code (e.g., 'ESP', 'USA')
        year: Year (2015-2030)
        force: If True, re-download even if file exists
        
    Returns:
        Path to downloaded TIF file, or None if failed
    """
    _ensure_data_dir()
    
    # Check if already downloaded
    local_path = get_population_file_path(iso3, year)
    if local_path.exists() and not force:
        logger.info(f"✅ Population data already exists: {local_path}")
        return local_path
    
    # Create country directory
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build download URL
    url = POPULATION_URL_PATTERN.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    logger.info(f"📥 Downloading WorldPop R2025A population for {iso3} {year}...")
    logger.info(f"   URL: {url}")
    
    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        temp_path = local_path.with_suffix('.tmp')
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0 and downloaded % (5 * 1024 * 1024) < 8192:
                    pct = (downloaded / total_size) * 100
                    logger.info(f"   {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({pct:.0f}%)")
        
        temp_path.rename(local_path)
        logger.info(f"✅ Downloaded: {local_path}")
        return local_path
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.error(f"❌ Data not available for {iso3} year {year}")
        else:
            logger.error(f"❌ HTTP error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return None


def download_agesex_data(iso3: str, year: int = DEFAULT_YEAR, force: bool = False) -> Optional[Path]:
    """
    Download WorldPop R2025A age/sex structure data for a country.
    
    WARNING: These files are large (1-10 GB per country)!
    
    Args:
        iso3: ISO3 country code (e.g., 'ESP', 'USA')
        year: Year (2015-2030)
        force: If True, re-download even if files exist
        
    Returns:
        Path to extracted directory containing TIF files, or None if failed
    """
    _ensure_data_dir()
    
    # Check if already extracted
    extract_dir = get_agesex_dir_path(iso3, year)
    if extract_dir.exists() and list(extract_dir.glob("*.tif")) and not force:
        logger.info(f"✅ Age/sex data already exists: {extract_dir}")
        return extract_dir
    
    # Create directories
    extract_dir.parent.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(exist_ok=True)
    
    # Build download URL
    url = AGESEX_URL_PATTERN.format(
        base=WORLDPOP_BASE_URL,
        year=year,
        iso3_upper=iso3.upper(),
        iso3_lower=iso3.lower()
    )
    
    logger.info(f"📥 Downloading WorldPop R2025A age/sex for {iso3} {year}...")
    logger.info(f"   URL: {url}")
    logger.warning(f"   ⚠️ This file may be several GB - please be patient!")
    
    try:
        zip_path = extract_dir.parent / f"{iso3.lower()}_agesex_{year}.zip"
        
        response = requests.get(url, stream=True, timeout=3600)  # 1 hour timeout for large files
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):  # Larger chunks for big files
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0 and downloaded % (50 * 1024 * 1024) < 65536:
                    pct = (downloaded / total_size) * 100
                    logger.info(f"   {downloaded / (1024*1024):.0f} MB / {total_size / (1024*1024):.0f} MB ({pct:.0f}%)")
        
        # Extract ZIP
        logger.info(f"📦 Extracting {zip_path.name}...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
        
        # Remove ZIP to save space
        zip_path.unlink()
        
        tif_count = len(list(extract_dir.glob("**/*.tif")))
        logger.info(f"✅ Extracted {tif_count} TIF files to {extract_dir}")
        return extract_dir
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.error(f"❌ Age/sex data not available for {iso3} year {year}")
        else:
            logger.error(f"❌ HTTP error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        return None


def download_country_data(iso3: str, year: int = DEFAULT_YEAR, include_agesex: bool = False) -> Dict:
    """
    Download all WorldPop data for a country.
    
    Args:
        iso3: ISO3 country code
        year: Year (2015-2030)
        include_agesex: If True, also download age/sex structure (large!)
        
    Returns:
        Dict with paths to downloaded data
    """
    result = {
        'iso3': iso3,
        'year': year,
        'population': None,
        'agesex': None,
    }
    
    # Download population (required)
    result['population'] = download_population_data(iso3, year)
    
    # Download age/sex (optional, large files)
    if include_agesex:
        result['agesex'] = download_agesex_data(iso3, year)
    
    return result


# =============================================================================
# H3 UTILITIES
# =============================================================================

def _h3_version() -> int:
    """Detect H3 library version (3 or 4)."""
    if hasattr(h3, 'latlng_to_cell'):
        return 4
    return 3


def _latlng_to_h3(lat: float, lng: float, resolution: int) -> str:
    """Convert lat/lng to H3 cell."""
    if _h3_version() >= 4:
        return h3.latlng_to_cell(lat, lng, resolution)
    else:
        return h3.geo_to_h3(lat, lng, resolution)


def _h3_to_latlng(cell: str) -> Tuple[float, float]:
    """Get center of H3 cell."""
    if _h3_version() >= 4:
        return h3.cell_to_latlng(cell)
    else:
        return h3.h3_to_geo(cell)


# =============================================================================
# MAIN POPULATION FUNCTIONS
# =============================================================================

def fetch_worldpop_population(
    bbox: List[float],
    year: int = DEFAULT_YEAR,
    countries: Optional[List[str]] = None,
    aggregate_h3: bool = False,
    h3_resolution: int = 9,
    auto_download: bool = True,
    focus_geometry: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Fetch population data from local WorldPop R2025A files.
    
    Focus + Context Pattern (Google Earth style):
    - bbox: Use context_bbox (expanded) for fetching with breathing room
    - focus_geometry: Optional exact boundary to mark is_inside for styling
    
    Args:
        bbox: [west, south, east, north] bounding box - use context_bbox for breathing room
        year: Year for population estimate (2015-2030)
        countries: Optional list of ISO3 codes (auto-detected if None)
        aggregate_h3: If True, aggregate to H3 hexagons
        h3_resolution: H3 resolution if aggregating (default 9, ~174m)
        auto_download: If True, download missing data automatically
        focus_geometry: Optional GeoJSON Polygon to mark is_inside property
                       Data inside focus = 100% opacity, outside = 50% opacity
        
    Returns:
        Dict with population data and metadata. Each data point has 'is_inside' if focus_geometry provided.
    """
    logger.info("=" * 60)
    logger.info(f"📊 Fetching WorldPop R2025A Population")
    logger.info(f"   Year: {year}")
    logger.info(f"   BBox: {bbox}")
    logger.info(f"   Resolution: {'H3 res ' + str(h3_resolution) if aggregate_h3 else '100m (native)'}")
    logger.info("=" * 60)
    
    try:
        import rasterio
        from rasterio.windows import from_bounds
    except ImportError:
        logger.error("❌ rasterio not installed. Run: pip install rasterio")
        return None
    
    west, south, east, north = bbox
    
    # Validate bbox
    if east - west < MIN_BBOX_SIZE_DEG or north - south < MIN_BBOX_SIZE_DEG:
        logger.warning(f"BBox too small, expanding to minimum size")
        center_lon, center_lat = (west + east) / 2, (south + north) / 2
        half_size = MIN_BBOX_SIZE_DEG / 2
        west, east = center_lon - half_size, center_lon + half_size
        south, north = center_lat - half_size, center_lat + half_size
        bbox = [west, south, east, north]
    
    # Auto-detect countries if not provided
    if not countries:
        countries = detect_countries_from_bbox(bbox)
        
    if not countries:
        logger.error("❌ Could not detect countries for bbox")
        return None
    
    logger.info(f"📍 Countries: {countries}")
    
    # Get data sources for each country (S3 > local > download)
    country_sources = []
    for iso3 in countries:
        source = _get_data_source(iso3, year, auto_download)
        if source:
            country_sources.append((iso3, source))
    
    if not country_sources:
        logger.error("❌ No WorldPop data available")
        return None
    
    # Read and process data from all countries
    all_population_data = []
    total_population = 0
    
    for iso3, data_source in country_sources:
        is_s3 = data_source.startswith('http')
        source_name = data_source.split('/')[-1] if is_s3 else Path(data_source).name
        logger.info(f"📖 Reading {iso3} from {'S3' if is_s3 else 'local'}: {source_name}")
        
        try:
            with rasterio.open(data_source) as src:
                # Check if bbox overlaps with this file
                file_bounds = src.bounds
                if (west > file_bounds.right or east < file_bounds.left or
                    south > file_bounds.top or north < file_bounds.bottom):
                    logger.info(f"   {iso3}: No overlap with bbox, skipping")
                    continue
                
                # Calculate window for our bbox (clipped to file bounds)
                read_west = max(west, file_bounds.left)
                read_east = min(east, file_bounds.right)
                read_south = max(south, file_bounds.bottom)
                read_north = min(north, file_bounds.top)
                
                window = from_bounds(read_west, read_south, read_east, read_north, src.transform)
                
                # Read the data
                data = src.read(1, window=window)
                transform = src.window_transform(window)
                
                logger.info(f"   {iso3}: Read {data.shape[1]}x{data.shape[0]} pixels")
                
                # Get coordinates for all pixels with population > 0
                rows, cols = np.where((data > 0) & ~np.isnan(data))
                
                if len(rows) == 0:
                    logger.info(f"   {iso3}: No populated pixels in bbox")
                    continue
                
                # Convert pixel indices to coordinates
                xs, ys = rasterio.transform.xy(transform, rows, cols)
                
                if aggregate_h3:
                    # Aggregate to H3 hexagons
                    h3_counts = {}
                    for i in range(len(rows)):
                        pop = data[rows[i], cols[i]]
                        if pop > 0 and not np.isnan(pop):
                            hex_id = _latlng_to_h3(ys[i], xs[i], h3_resolution)
                            h3_counts[hex_id] = h3_counts.get(hex_id, 0) + pop
                    
                    for hex_id, count in h3_counts.items():
                        lat, lng = _h3_to_latlng(hex_id)
                        all_population_data.append({
                            'hex': hex_id,
                            'lat': lat,
                            'lng': lng,
                            'count': int(round(count)),
                            'country': iso3,
                        })
                        total_population += count
                else:
                    # Full resolution - return all pixels
                    for i in range(len(rows)):
                        pop = data[rows[i], cols[i]]
                        if pop > 0 and not np.isnan(pop):
                            all_population_data.append({
                                'lat': ys[i],
                                'lng': xs[i],
                                'count': float(pop),
                                'country': iso3,
                            })
                            total_population += pop
                
                logger.info(f"   {iso3}: {len(rows)} populated pixels, {total_population:,.0f} total pop")
                
        except Exception as e:
            logger.error(f"   {iso3}: Error reading file: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            continue
    
    if not all_population_data:
        logger.warning("❌ No population data found in bbox")
        return None
    
    # Determine resolution description
    if aggregate_h3:
        h3_edge_m = {7: 1220, 8: 460, 9: 174, 10: 66, 11: 25}
        resolution_m = h3_edge_m.get(h3_resolution, 100)
        resolution_desc = f"H3 res {h3_resolution} (~{resolution_m}m)"
    else:
        resolution_m = 100
        resolution_desc = "100m (native WorldPop R2025A)"
    
    logger.info("=" * 60)
    logger.info(f"✅ WorldPop data fetched successfully!")
    logger.info(f"   Points/Hexagons: {len(all_population_data):,}")
    logger.info(f"   Total Population: {total_population:,.0f}")
    logger.info(f"   Resolution: {resolution_desc}")
    logger.info("=" * 60)
    
    # Apply Focus + Context masking if focus_geometry provided
    if focus_geometry and mask_layer_by_aoi:
        logger.info(f"   Applying Focus + Context masking...")
        all_population_data = mask_layer_by_aoi(all_population_data, focus_geometry)
        inside_count = sum(1 for r in all_population_data if r.get('is_inside', False))
        context_count = len(all_population_data) - inside_count
        logger.info(f"   Focus: {inside_count}, Context: {context_count}")
    
    return {
        'data': all_population_data,
        'total_population': int(round(total_population)),
        'countries': countries,
        'resolution_m': resolution_m,
        'resolution_desc': resolution_desc,
        'year': year,
        'bbox': bbox,
        'aggregate_h3': aggregate_h3,
        'h3_resolution': h3_resolution if aggregate_h3 else None,
        'point_count': len(all_population_data),
        'source': 'WorldPop R2025A v1',
    }


def get_population_density(
    bbox: Optional[List[float]] = None,
    countries: Optional[List[str]] = None,
    year: int = DEFAULT_YEAR,
    aggregate_h3: bool = False,
    h3_resolution: int = 9,
    auto_download: bool = True,
    as_layer: bool = False,
    focus_geometry: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Get population density for a bounding box using WorldPop R2025A.
    
    This is the main entry point for population queries.
    
    Focus + Context Pattern (Google Earth style):
    - bbox: Use context_bbox (expanded) for fetching with breathing room
    - focus_geometry: Optional exact boundary to mark is_inside for styling
    
    Args:
        bbox: [west, south, east, north] - use context_bbox for breathing room
        countries: List of ISO3 country codes (auto-detected if None)
        year: Year for population estimate (2015-2030, default 2020)
        aggregate_h3: If True, aggregate to H3 hexagons
        h3_resolution: H3 resolution if aggregating (default 9)
        auto_download: If True, download missing data automatically
        as_layer: If True, return formatted LayerData dict
        focus_geometry: Optional GeoJSON Polygon to mark is_inside property
        
    Returns:
        Dict with population data and metadata. Each point has 'is_inside' if focus_geometry provided.
        If as_layer=True, returns LayerData-formatted dict.
        
    Example:
        # Get population for Berlin with breathing room
        from utils_spatial import get_aoi
        aoi = get_aoi("Berlin, Germany")
        
        result = get_population_density(
            bbox=aoi['context_bbox'],  # Expanded for breathing room
            focus_geometry=aoi['focus_geometry'],  # For is_inside marking
            aggregate_h3=True
        )
        # Data inside Berlin = 100% opacity, suburbs = 50% opacity
    """
    if bbox is None:
        logger.error("bbox is required. Provide [west, south, east, north] coordinates.")
        return None

    result = fetch_worldpop_population(
        bbox=bbox,
        year=year,
        countries=countries,
        aggregate_h3=aggregate_h3,
        h3_resolution=h3_resolution,
        auto_download=auto_download,
        focus_geometry=focus_geometry,
    )
    
    # Optionally format as LayerData
    if as_layer and result and format_h3_layer:
        data = result.get('data', [])
        # Convert to standard H3 format with 'hex' and 'value' keys
        h3_data = [
            {'hex': d.get('hex', ''), 'value': d.get('count', 0), **d}
            for d in data if d.get('hex')
        ] if aggregate_h3 else data
        
        return format_h3_layer(
            id=f"population_{year}",
            data=h3_data,
            label=f"Population Density ({year})",
            color_scale="magma",
            property_key="value",
            summary=f"Population: {result.get('total_population', 0):,} in {result.get('point_count', 0)} hexagons",
            source="WorldPop R2025A",
            year=year,
            resolution=result.get('resolution_desc'),
            total_population=result.get('total_population'),
        )
    
    return result


def get_population_for_location(
    location_query: str,
    year: int = DEFAULT_YEAR,
    buffer_km: float = 5.0,
    aggregate_h3: bool = False,
    h3_resolution: int = 9,
) -> Optional[Dict]:
    """
    Get population for a named location using WorldPop R2025A.
    
    Args:
        location_query: Location name (e.g., "Madrid, Spain")
        year: Year (2015-2030)
        buffer_km: Buffer around location in km (default 5km)
        aggregate_h3: If True, aggregate to H3 hexagons
        h3_resolution: H3 resolution if aggregating
        
    Returns:
        Dict with population data and location metadata
    """
    logger.info(f"📍 Getting population for: {location_query}")
    
    # Geocode the location
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': location_query,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1,
        }
        headers = {'User-Agent': 'Leo-Demographics/1.0'}
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if not data:
            logger.error(f"Location not found: {location_query}")
        return None
    
        result = data[0]
        lat = float(result['lat'])
        lon = float(result['lon'])
        display_name = result.get('display_name', location_query)
        
        # Get country code
        address = result.get('address', {})
        country_code = address.get('country_code', '').upper()
        country_iso3 = ISO2_TO_ISO3.get(country_code)
        
        # Use bounding box if available, otherwise create from buffer
        if 'boundingbox' in result:
            bb = result['boundingbox']
            bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
        else:
            buffer_deg = buffer_km / 111.0
            bbox = [lon - buffer_deg, lat - buffer_deg, lon + buffer_deg, lat + buffer_deg]
        
        logger.info(f"   Geocoded to: ({lat:.4f}, {lon:.4f})")
        logger.info(f"   Country: {country_iso3}")
        
    except Exception as e:
        logger.error(f"Geocoding failed: {e}")
    return None

    # Fetch population
    pop_result = get_population_density(
        bbox=bbox,
        countries=[country_iso3] if country_iso3 else None,
        year=year,
        aggregate_h3=aggregate_h3,
        h3_resolution=h3_resolution,
    )
    
    if pop_result:
        pop_result['location'] = {
            'query': location_query,
            'display_name': display_name,
            'lat': lat,
            'lon': lon,
            'country_iso3': country_iso3,
        }
    
    return pop_result


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def list_available_years() -> List[int]:
    """Return list of available years in WorldPop R2025A dataset."""
    return list(range(2015, 2031))


def list_downloaded_data() -> Dict:
    """List all locally downloaded WorldPop data."""
    _ensure_data_dir()
    
    result = {
        'data_dir': str(DATA_DIR),
        'countries': {},
    }
    
    for country_dir in DATA_DIR.iterdir():
        if country_dir.is_dir() and len(country_dir.name) == 3:
            iso3 = country_dir.name
            result['countries'][iso3] = {
                'population_files': [],
                'agesex_dirs': [],
            }
            
            for f in country_dir.glob("*_pop_*_CN_100m_R2025A_v1.tif"):
                # Extract year from filename
                year = int(f.stem.split('_')[2])
                size_mb = f.stat().st_size / (1024 * 1024)
                result['countries'][iso3]['population_files'].append({
                    'year': year,
                    'path': str(f),
                    'size_mb': round(size_mb, 1),
                })
            
            for d in country_dir.glob("agesex_*"):
                if d.is_dir():
                    year = int(d.name.split('_')[1])
                    tif_count = len(list(d.glob("**/*.tif")))
                    result['countries'][iso3]['agesex_dirs'].append({
                        'year': year,
                        'path': str(d),
                        'tif_count': tif_count,
                    })
    
    return result


def clear_downloaded_data(iso3: Optional[str] = None, year: Optional[int] = None):
    """
    Clear downloaded WorldPop data.
    
    Args:
        iso3: If provided, only clear data for this country
        year: If provided, only clear data for this year
    """
    import shutil
    
    if iso3:
        country_dir = DATA_DIR / iso3.upper()
        if year:
            # Delete specific year's files
            for f in country_dir.glob(f"*_{year}_*.tif"):
                logger.info(f"Deleting {f}")
                f.unlink()
            agesex_dir = country_dir / f"agesex_{year}"
            if agesex_dir.exists():
                logger.info(f"Deleting {agesex_dir}")
                shutil.rmtree(agesex_dir)
        else:
            # Delete entire country
            if country_dir.exists():
                logger.info(f"Deleting {country_dir}")
                shutil.rmtree(country_dir)
    else:
        # Delete all data
        if DATA_DIR.exists():
            logger.info(f"Deleting all WorldPop data in {DATA_DIR}")
            shutil.rmtree(DATA_DIR)
        _ensure_data_dir()


# =============================================================================
# TEST / CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    
    print("=" * 70)
    print("📊 WorldPop R2025A Demographics Tools")
    print(f"   Data Directory: {DATA_DIR}")
    print(f"   Default Year: {DEFAULT_YEAR}")
    print(f"   Available Years: 2015-2030")
    print("=" * 70)
    
    # Check what's downloaded
    downloaded = list_downloaded_data()
    if downloaded['countries']:
        print("\n📁 Downloaded Data:")
        for iso3, data in downloaded['countries'].items():
            pop_years = [f['year'] for f in data['population_files']]
            print(f"   {iso3}: Population years {pop_years}")
    else:
        print("\n📁 No data downloaded yet.")
        print("   Run: download_population_data('ESP', 2020) to download Spain 2020")
    
    # Quick test if we have data
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print("\n--- Test: Madrid, Spain ---")
        result = get_population_density(
            bbox=[-3.72, 40.41, -3.68, 40.43],
            year=2020,
            aggregate_h3=True,
            h3_resolution=9,
        )
    
    if result:
            print(f"✅ Success!")
            print(f"   Points: {result['point_count']:,}")
            print(f"   Total Population: {result['total_population']:,}")
    else:
            print("❌ Test failed - try downloading data first:")
            print("   download_population_data('ESP', 2020)")
    
    print("\n" + "=" * 70)
