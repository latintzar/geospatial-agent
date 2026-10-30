"""
HDX Global Infrastructure Hunter + Regional Data Joiner

Targets high-quality HDX data series and joins regional data with boundaries.

4-Phase Approach:
1. HUNTER: Search for data (point data with coords OR regional data with admin names)
2. BOUNDARY FETCHER: If regional data found, fetch COD-AB boundaries
3. MERGE: Join regional data with boundary polygons using fuzzy name matching
4. RETURN: GeoJSON with polygons + data properties

Usage:
    from tools_hdx import fetch_hdx_spatial_data
    
    # Point data (healthsites, airports) - returns Point features
    geojson = fetch_hdx_spatial_data("KEN", "health")
    
    # Regional data (WFP food security) - returns Polygon features with data
    geojson = fetch_hdx_spatial_data("YEM", "wfp")
"""

import pandas as pd
import geopandas as gpd
import re
import io
import json
import logging
import zipfile
import os
import tempfile
from typing import Optional, Tuple, Union
from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from rapidfuzz import fuzz, process

# Import formatting helper
try:
    from ..utils_formatting import format_layer, format_geojson_layer, format_error
except ImportError:
    try:
        from utils_formatting import format_layer, format_geojson_layer, format_error
    except ImportError:
        format_layer = None
        format_geojson_layer = None
        format_error = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flag to track if HDX is configured
_hdx_configured = False

# =============================================================================
# CACHING - TODO: Implement global caching solution later
# For now, just basic in-memory boundary cache per session
# =============================================================================

# In-memory cache for boundaries (per session only - speeds up repeated queries)
_boundary_cache: dict[str, gpd.GeoDataFrame] = {}


def _get_cached_boundary(country_iso3: str) -> Optional[gpd.GeoDataFrame]:
    """Get a cached boundary GeoDataFrame (memory only)."""
    if country_iso3 in _boundary_cache:
        logger.info(f"  💾 Using cached boundary for {country_iso3}")
        return _boundary_cache[country_iso3]
    return None


def _cache_boundary(country_iso3: str, gdf: gpd.GeoDataFrame) -> None:
    """Cache a boundary GeoDataFrame (memory only)."""
    _boundary_cache[country_iso3] = gdf
    logger.info(f"  💾 Cached boundary for {country_iso3} ({len(gdf)} features)")

# =============================================================================
# SMART QUERY MAPPINGS
# =============================================================================

KEYWORD_TO_SERIES = {
    # Health facilities
    'health': ['healthsites', 'health facilities'],
    'hospital': ['healthsites', 'hospitals'],
    'clinic': ['healthsites', 'health facilities'],
    'healthsite': ['healthsites'],
    
    # Education
    'school': ['hotosm schools', 'schools', 'education facilities'],
    'education': ['hotosm education', 'schools', 'education facilities'],
    'university': ['universities', 'higher education'],
    
    # Food & Markets (WFP) - often regional data
    'food': ['wfp food prices', 'wfp markets', 'food prices', 'food security'],
    'market': ['wfp markets', 'wfp food prices', 'markets locations'],
    'prices': ['wfp food prices', 'wfp markets', 'commodity prices'],
    'wfp': ['wfp food prices', 'wfp markets', 'wfp hungermap'],
    'hunger': ['hungermap', 'food security', 'ipc'],
    'hungermap': ['hungermap'],
    'ipc': ['ipc', 'food security', 'acute food insecurity'],
    
    # Agriculture
    'agriculture': ['mapspam', 'crop production', 'faostat', 'agricultural'],
    'crops': ['mapspam', 'crop production', 'faostat', 'crops'],
    'cocoa': ['mapspam', 'cocoa production', 'crop production'],
    'yield': ['mapspam', 'crop yield', 'faostat', 'agricultural yield'],
    'farming': ['mapspam', 'crop production', 'agricultural'],
    
    # Transportation
    'airport': ['airports', 'airfields'],
    'aviation': ['airports', 'airfields'],
    'road': ['hotosm roads', 'roads'],
    'port': ['ports', 'seaports'],
    
    # Conflict
    'conflict': ['acled', 'conflict events'],
    'violence': ['acled', 'political violence'],
    
    # Other infrastructure
    'water': ['hotosm waterways', 'water points', 'wash'],
    'bank': ['banks', 'financial services'],
    'populated': ['populated places', 'settlements'],
    
    # Administrative
    'admin': ['administrative boundaries', 'admin boundaries'],
    'boundary': ['administrative boundaries', 'boundaries'],
}

# =============================================================================
# COLUMN DETECTION PATTERNS
# =============================================================================

LAT_PATTERNS = [
    r'^lat$', r'^latitude$', r'^lat_', r'^latitude_', r'_lat$', r'_latitude$',
    r'^y$', r'^y_coord', r'^point_y$', r'^gps_lat', r'^gps_lat.*',
    r'^geo_lat', r'^lat[ei]tude', r'^coord_y', r'^centroid_lat',
]

LON_PATTERNS = [
    r'^lon$', r'^lng$', r'^long$', r'^longitude$', r'^lon_', r'^lng_',
    r'^longitude_', r'_lon$', r'_lng$', r'_longitude$', r'^x$', r'^x_coord',
    r'^point_x$', r'^gps_lon', r'^gps_lon.*', r'^gps_lng', r'^gps_lng.*',
    r'^geo_lon', r'^geo_lng', r'^long[ei]tude', r'^coord_x', r'^centroid_lon',
]

# Admin column patterns (for regional data)
ADMIN_PATTERNS = [
    r'^admin1$', r'^admin_1$', r'^admin1_name$', r'^adm1_en$', r'^adm1_name$',
    r'^admin2$', r'^admin_2$', r'^admin2_name$', r'^adm2_en$', r'^adm2_name$',
    r'^adminone$', r'^admin_one$', r'^admintwo$', r'^admin_two$',
    r'^region$', r'^region_name$', r'^district$', r'^district_name$',
    r'^province$', r'^province_name$', r'^state$', r'^state_name$',
    r'^governorate$', r'^county$', r'^department$',
]

# Boundary GeoJSON admin name column patterns (case-insensitive)
BOUNDARY_NAME_PATTERNS = [
    r'^adm1_name$', r'^adm2_name$',           # COD-AB standard
    r'^adm1_en$', r'^adm2_en$',               # English versions
    r'^adm1name$', r'^adm2name$',             # No underscore
    r'^admin1name$', r'^admin2name$',
    r'^admin1_name$', r'^admin2_name$',
    r'^adm1name_en$', r'^adm2name_en$',
    r'^adm1_ref_name$', r'^adm2_ref_name$',   # Reference names
    r'^name$', r'^name_en$', r'^name_1$', r'^name_2$',
    r'^shapename$', r'^region$', r'^district$', r'^province$', r'^governorate$',
]

PROPERTY_COLUMNS = [
    'name', 'title', 'label', 'type', 'amenity', 'category', 'facility_type',
    'status', 'operational_status', 'admin1', 'admin2', 'region', 'district',
    'province', 'city', 'town', 'village', 'location', 'address', 'phone',
    'email', 'url', 'website', 'capacity', 'beds', 'staff', 'operator',
    'owner', 'source', 'date', 'year', 'updated',
]


def _ensure_hdx_configured():
    """Initialize HDX configuration (once per session)."""
    global _hdx_configured
    if not _hdx_configured:
        logger.info("Configuring HDX API (read-only)...")
        Configuration.create(
            hdx_site="prod",
            user_agent="PuedoCasa-InfraHunter/2.0",
            hdx_read_only=True
        )
        _hdx_configured = True
        logger.info("HDX API configured")


def _get_smart_queries(keyword: str) -> list[str]:
    """Translate keyword into HDX data series queries."""
    keyword_lower = keyword.lower().strip()
    for key, queries in KEYWORD_TO_SERIES.items():
        if key in keyword_lower or keyword_lower in key:
            logger.info(f"Smart query: '{keyword}' → {queries}")
            return queries
    logger.info(f"No smart mapping for '{keyword}', using raw query")
    return [keyword]


def _find_column_by_patterns(columns: list[str], patterns: list[str]) -> Optional[str]:
    """Find a column matching any regex pattern."""
    for col in columns:
        col_lower = col.lower().strip()
        for pattern in patterns:
            if re.match(pattern, col_lower):
                return col
    return None


def _find_admin_column(columns: list[str]) -> Optional[str]:
    """Find admin/region name column in DataFrame."""
    return _find_column_by_patterns(columns, ADMIN_PATTERNS)


def _find_boundary_name_column(columns: list[str]) -> Optional[str]:
    """Find admin name column in boundary GeoJSON."""
    return _find_column_by_patterns(columns, BOUNDARY_NAME_PATTERNS)


def _normalize_name(name: str) -> str:
    """Normalize admin name for matching."""
    if pd.isna(name):
        return ""
    name = str(name).lower().strip()
    # Remove common prefixes/suffixes
    name = re.sub(r'\s+(governorate|province|region|district|county|department)$', '', name)
    name = re.sub(r'^(governorate|province|region|district|county|department)\s+of\s+', '', name)
    # Remove special characters but keep spaces
    name = re.sub(r'[^\w\s]', '', name)
    return name


def _parse_resource(resource, resource_format: str) -> Optional[pd.DataFrame]:
    """Download and parse a resource into a DataFrame."""
    try:
        url, path = resource.download()
        logger.info(f"Downloaded: {path}")
        
        actual_path = path
        if path.endswith('.zip') or '.zip' in path:
            try:
                extract_dir = path + '_extracted'
                with zipfile.ZipFile(path, 'r') as zf:
                    zf.extractall(extract_dir)
                    extracted_files = os.listdir(extract_dir)
                    if extracted_files:
                        actual_path = os.path.join(extract_dir, extracted_files[0])
                        logger.info(f"Extracted: {actual_path}")
                        if actual_path.endswith('.geojson') or actual_path.endswith('.json'):
                            resource_format = 'GEOJSON'
                        elif actual_path.endswith('.csv'):
                            resource_format = 'CSV'
            except zipfile.BadZipFile:
                logger.warning("Not a valid zip file, trying as-is")
        
        if resource_format in ('XLSX', 'XLS'):
            df = pd.read_excel(actual_path, engine='openpyxl' if resource_format == 'XLSX' else 'xlrd')
        elif resource_format == 'CSV':
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    df = pd.read_csv(actual_path, encoding=encoding, low_memory=False)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                logger.warning("Could not decode CSV")
                return None
        elif resource_format == 'GEOJSON':
            with open(actual_path, 'r', encoding='utf-8') as f:
                geojson = json.load(f)
            rows = []
            for feature in geojson.get('features', []):
                geom = feature.get('geometry', {})
                props = feature.get('properties', {})
                geom_type = geom.get('type', '')
                coords = geom.get('coordinates', [])
                if geom_type == 'Point' and len(coords) >= 2:
                    row = {'longitude': coords[0], 'latitude': coords[1]}
                    row.update(props)
                    rows.append(row)
                elif geom_type in ('Polygon', 'MultiPolygon') and coords:
                    ring = coords[0] if geom_type == 'Polygon' else coords[0][0]
                    if ring:
                        avg_lon = sum(p[0] for p in ring) / len(ring)
                        avg_lat = sum(p[1] for p in ring) / len(ring)
                        row = {'longitude': avg_lon, 'latitude': avg_lat}
                        row.update(props)
                        rows.append(row)
            df = pd.DataFrame(rows)
            logger.info(f"Extracted {len(rows)} features from GeoJSON")
        else:
            logger.warning(f"Unsupported format: {resource_format}")
            return None
        
        logger.info(f"Parsed {len(df)} rows, {len(df.columns)} columns")
        return df
    except Exception as e:
        logger.warning(f"Parse error: {e}")
        return None


def _df_to_geojson(df: pd.DataFrame, lat_col: str, lon_col: str, limit: int = 500) -> dict:
    """Convert DataFrame to GeoJSON FeatureCollection (Point features)."""
    features = []
    for idx, row in df.head(limit).iterrows():
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            if pd.isna(lat) or pd.isna(lon):
                continue
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                continue
            properties = {}
            for col in df.columns:
                if col not in (lat_col, lon_col):
                    val = row[col]
                    if pd.isna(val):
                        continue
                    elif hasattr(val, 'isoformat'):
                        properties[col] = val.isoformat()
                    elif isinstance(val, (int, float, bool, str)):
                        properties[col] = val
                    else:
                        properties[col] = str(val)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": properties
            })
        except (ValueError, TypeError):
            continue
    return {"type": "FeatureCollection", "features": features}


# =============================================================================
# PHASE 2: BOUNDARY FETCHER
# =============================================================================

def _download_and_read_boundary(resource, prefer_admin_level: int = 1) -> Optional[gpd.GeoDataFrame]:
    """
    Download a boundary resource and read it into a GeoDataFrame.
    For zip files, prioritize admin1 (or specified admin level) files.
    """
    try:
        url, path = resource.download()
        logger.info(f"    Downloaded: {path}")
        
        actual_path = path
        
        # Handle zip files - look for admin level files inside
        if '.zip' in path:
            try:
                extract_dir = path + '_extracted'
                with zipfile.ZipFile(path, 'r') as zf:
                    zf.extractall(extract_dir)
                    files = os.listdir(extract_dir)
                    logger.info(f"    Zip contains: {files}")
                    
                    # Priority 1: Exact admin level match (admin1, adm1)
                    admin_patterns = [f'admin{prefer_admin_level}', f'adm{prefer_admin_level}']
                    for f in files:
                        f_lower = f.lower()
                        if (f.endswith('.geojson') or f.endswith('.json')):
                            for pattern in admin_patterns:
                                if pattern in f_lower:
                                    actual_path = os.path.join(extract_dir, f)
                                    logger.info(f"    Using: {f}")
                                    break
                            if actual_path != path:
                                break
                    
                    # Priority 2: Any geojson file (not admin0)
                    if actual_path == path:
                        for f in files:
                            f_lower = f.lower()
                            if f.endswith('.geojson') and 'admin0' not in f_lower and 'adm0' not in f_lower:
                                actual_path = os.path.join(extract_dir, f)
                                logger.info(f"    Using: {f}")
                                break
                                
            except zipfile.BadZipFile:
                logger.warning("    Not a valid zip file")
                return None
        
        gdf = gpd.read_file(actual_path)
        logger.info(f"    Loaded {len(gdf)} features")
        logger.info(f"    Columns: {list(gdf.columns)[:10]}...")
        return gdf
        
    except Exception as e:
        logger.warning(f"    Failed to load: {e}")
        return None


def _fetch_admin_boundaries(country_iso3: str) -> Optional[gpd.GeoDataFrame]:
    """
    Fetch administrative boundaries (COD-AB) for a country.
    Uses caching to avoid repeated downloads.
    
    Args:
        country_iso3: ISO3 country code
        
    Returns:
        GeoDataFrame with boundary polygons, or None if not found
    """
    logger.info(f"🗺️  Phase 2: Fetching admin boundaries for {country_iso3}...")
    
    # Check cache first
    cached = _get_cached_boundary(country_iso3)
    if cached is not None:
        return cached
    
    _ensure_hdx_configured()
    
    # Country name mapping for better search
    country_names = {
        'YEM': 'yemen', 'SSD': 'south sudan', 'SDN': 'sudan', 'SOM': 'somalia',
        'ETH': 'ethiopia', 'KEN': 'kenya', 'UGA': 'uganda', 'COD': 'congo',
        'NGA': 'nigeria', 'MLI': 'mali', 'NER': 'niger', 'TCD': 'chad',
        'CAF': 'central african republic', 'SYR': 'syria', 'IRQ': 'iraq',
        'AFG': 'afghanistan', 'PAK': 'pakistan', 'BGD': 'bangladesh',
        'MMR': 'myanmar', 'HTI': 'haiti', 'VEN': 'venezuela', 'COL': 'colombia',
        'GTM': 'guatemala', 'HND': 'honduras', 'SLV': 'el salvador',
        'MOZ': 'mozambique', 'ZWE': 'zimbabwe', 'MWI': 'malawi', 'ZMB': 'zambia',
    }
    
    country_name = country_names.get(country_iso3, country_iso3.lower())
    
    # Try direct COD-AB dataset read first (most reliable)
    cod_ab_ids = [f"cod-ab-{country_iso3.lower()}"]
    
    for ds_id in cod_ab_ids:
        logger.info(f"  Trying direct read: {ds_id}")
        try:
            dataset = Dataset.read_from_hdx(ds_id)
            if dataset:
                logger.info(f"  Found: {dataset.get('title', 'Unknown')}")
                resources = dataset.get_resources()
                
                # COD-AB datasets often have a single geojson.zip with all admin levels inside
                # Look for geojson.zip or geojson resources
                for resource in resources:
                    res_name = resource.get('name', '').lower()
                    res_format = resource.get('format', '').upper()
                    
                    # Prefer GeoJSON (zip files will be extracted in _download_and_read_boundary)
                    if res_format == 'GEOJSON' or 'geojson' in res_name:
                        logger.info(f"  Trying: {resource.get('name', 'Unknown')}")
                        gdf = _download_and_read_boundary(resource, prefer_admin_level=1)
                        if gdf is not None and len(gdf) > 1:
                            _cache_boundary(country_iso3, gdf)
                            return gdf
                
                # Fallback: try SHP
                for resource in resources:
                    res_name = resource.get('name', '').lower()
                    res_format = resource.get('format', '').upper()
                    if res_format == 'SHP' or '.shp' in res_name:
                        logger.info(f"  Trying SHP: {resource.get('name', 'Unknown')}")
                        gdf = _download_and_read_boundary(resource, prefer_admin_level=1)
                        if gdf is not None and len(gdf) > 1:
                            _cache_boundary(country_iso3, gdf)
                            return gdf
        except Exception as e:
            logger.debug(f"  Direct read failed: {e}")
    
    # Fallback to search
    queries = [
        f"{country_name} administrative boundaries",
        f"{country_name} subnational boundaries",
        f"cod-ab {country_name}",
        f"{country_iso3} boundaries",
    ]
    
    for query in queries:
        logger.info(f"  Searching: '{query}'")
        try:
            datasets = Dataset.search_in_hdx(query, rows=10)
        except Exception as e:
            logger.warning(f"  Search failed: {e}")
            continue
        
        if not datasets:
            continue
        
        for dataset in datasets:
            ds_title = dataset.get('title', '').lower()
            ds_name = dataset.get('name', '').lower()
            
            # Check if dataset is for the right country
            if country_name not in ds_title and country_iso3.lower() not in ds_name:
                continue
            
            # Prefer boundary/admin datasets
            is_boundary = any(x in ds_title or x in ds_name for x in 
                           ['boundary', 'boundaries', 'admin', 'subnational', 'cod-ab', 'cod_ab'])
            if not is_boundary:
                continue
            
            logger.info(f"  Checking: {ds_title[:50]}...")
            
            try:
                resources = dataset.get_resources()
            except Exception:
                continue
            
            # First pass: look for admin1 resources
            admin1_resources = []
            admin2_resources = []
            other_resources = []
            
            for resource in resources:
                res_format = resource.get('format', '').upper()
                res_name = resource.get('name', '').lower()
                
                # Look for GeoJSON or Shapefile (with zip support)
                if res_format not in ('GEOJSON', 'SHP', 'GPKG', 'ZIP'):
                    continue
                
                # Skip country-level (admin0)
                if 'adm0' in res_name or 'admin0' in res_name:
                    if 'adm1' not in res_name and 'adm2' not in res_name:
                        continue
                
                # Categorize by admin level
                if 'adm1' in res_name or 'admin1' in res_name:
                    admin1_resources.append(resource)
                elif 'adm2' in res_name or 'admin2' in res_name:
                    admin2_resources.append(resource)
                else:
                    other_resources.append(resource)
            
            # Prioritize admin1, then admin2, then others
            prioritized = admin1_resources + admin2_resources + other_resources
            
            for resource in prioritized:
                res_name = resource.get('name', '').lower()
                admin_level = 1 if 'adm1' in res_name else (2 if 'adm2' in res_name else None)
                
                logger.info(f"  Found boundary: {resource.get('name', 'Unknown')} (Admin level: {admin_level})")
                
                try:
                    url, path = resource.download()
                    
                    # Handle zip files
                    actual_path = path
                    if '.zip' in path:
                        try:
                            extract_dir = path + '_extracted'
                            with zipfile.ZipFile(path, 'r') as zf:
                                zf.extractall(extract_dir)
                                for f in os.listdir(extract_dir):
                                    if f.endswith('.geojson') or f.endswith('.json') or f.endswith('.shp'):
                                        actual_path = os.path.join(extract_dir, f)
                                        break
                        except zipfile.BadZipFile:
                            pass
                    
                    gdf = gpd.read_file(actual_path)
                    logger.info(f"  ✅ Loaded {len(gdf)} boundary features")
                    logger.info(f"  Columns: {list(gdf.columns)[:8]}...")
                    _cache_boundary(country_iso3, gdf)
                    return gdf
                    
                except Exception as e:
                    logger.warning(f"  Failed to load: {e}")
                    continue
    
    logger.warning(f"  ❌ No admin boundaries found for {country_iso3}")
    return None


# =============================================================================
# PHASE 3: FUZZY MERGE
# =============================================================================

def _fuzzy_merge_with_boundaries(
    data_df: pd.DataFrame,
    data_admin_col: str,
    boundaries_gdf: gpd.GeoDataFrame,
    min_score: int = 70
) -> Optional[gpd.GeoDataFrame]:
    """
    Merge regional data with boundary polygons using fuzzy name matching.
    
    Args:
        data_df: DataFrame with regional data
        data_admin_col: Column name containing admin region names
        boundaries_gdf: GeoDataFrame with boundary polygons
        min_score: Minimum fuzzy match score (0-100)
        
    Returns:
        Merged GeoDataFrame with polygons + data, or None if merge fails
    """
    logger.info(f"🔗 Phase 3: Merging data with boundaries...")
    
    # Find the admin name column in boundaries
    boundary_name_col = _find_boundary_name_column(boundaries_gdf.columns.tolist())
    
    if boundary_name_col is None:
        # Try common column names directly (case-insensitive)
        common_names = [
            'ADM1_EN', 'adm1_en', 'ADM1_NAME', 'adm1_name', 'admin1Name', 
            'ADM1NAME_EN', 'ADM1_REF', 'shapeName', 'NAME_1', 'name_1',
            'ADM2_EN', 'adm2_en', 'ADM2_NAME', 'adm2_name', 'admin2Name',
            'ADM2NAME_EN', 'ADM2_REF', 'NAME_2', 'name_2',
            'NAME', 'name', 'ADMIN_NAME', 'admin_name',
        ]
        cols_lower = {c.lower(): c for c in boundaries_gdf.columns}
        for name in common_names:
            if name.lower() in cols_lower:
                boundary_name_col = cols_lower[name.lower()]
                break
    
    if boundary_name_col is None:
        logger.warning("  Could not find admin name column in boundaries")
        logger.info(f"  Available columns: {list(boundaries_gdf.columns)}")
        return None
    
    logger.info(f"  Data admin column: {data_admin_col}")
    logger.info(f"  Boundary admin column: {boundary_name_col}")
    
    # Normalize names for matching
    data_df = data_df.copy()
    data_df['_normalized_name'] = data_df[data_admin_col].apply(_normalize_name)
    
    boundaries_gdf = boundaries_gdf.copy()
    boundaries_gdf['_normalized_name'] = boundaries_gdf[boundary_name_col].apply(_normalize_name)
    
    # Get unique admin names from data
    data_names = data_df['_normalized_name'].dropna().unique().tolist()
    boundary_names = boundaries_gdf['_normalized_name'].dropna().unique().tolist()
    
    logger.info(f"  Data regions: {len(data_names)}")
    logger.info(f"  Boundary regions: {len(boundary_names)}")
    
    # Build fuzzy match mapping
    name_mapping = {}
    for data_name in data_names:
        if not data_name:
            continue
        match = process.extractOne(
            data_name,
            boundary_names,
            scorer=fuzz.token_sort_ratio
        )
        if match and match[1] >= min_score:
            name_mapping[data_name] = match[0]
            logger.debug(f"  Matched: '{data_name}' → '{match[0]}' (score: {match[1]})")
    
    logger.info(f"  Matched {len(name_mapping)} / {len(data_names)} regions")
    
    if not name_mapping:
        logger.warning("  No regions matched!")
        return None
    
    # Map data names to boundary names
    data_df['_match_name'] = data_df['_normalized_name'].map(name_mapping)
    
    # Aggregate data by admin region (in case of multiple rows per region)
    # Keep first row for non-numeric columns, sum/mean for numeric
    agg_funcs = {}
    for col in data_df.columns:
        if col in ['_normalized_name', '_match_name', data_admin_col]:
            continue
        if pd.api.types.is_numeric_dtype(data_df[col]):
            agg_funcs[col] = 'mean'  # Average numeric values
        else:
            agg_funcs[col] = 'first'  # Keep first value for strings
    
    if agg_funcs:
        data_agg = data_df.groupby('_match_name').agg(agg_funcs).reset_index()
    else:
        data_agg = data_df.drop_duplicates('_match_name')[['_match_name']]
    
    # Merge with boundaries
    merged = boundaries_gdf.merge(
        data_agg,
        left_on='_normalized_name',
        right_on='_match_name',
        how='inner'
    )
    
    # Clean up temporary columns
    drop_cols = ['_normalized_name', '_match_name']
    merged = merged.drop(columns=[c for c in drop_cols if c in merged.columns], errors='ignore')
    
    logger.info(f"  ✅ Merged result: {len(merged)} features")
    
    if len(merged) == 0:
        return None
    
    return merged


def _gdf_to_geojson(gdf: gpd.GeoDataFrame) -> dict:
    """Convert GeoDataFrame to GeoJSON dict, handling Timestamp serialization."""
    # Convert Timestamp columns to strings to avoid JSON serialization errors
    gdf = gdf.copy()
    for col in gdf.columns:
        if col != 'geometry':
            # Convert datetime/Timestamp to ISO format string
            if hasattr(gdf[col].dtype, 'tz') or 'datetime' in str(gdf[col].dtype).lower():
                gdf[col] = gdf[col].astype(str)
            # Handle any other non-serializable types
            try:
                json.dumps(gdf[col].iloc[0] if len(gdf) > 0 else None)
            except (TypeError, ValueError):
                gdf[col] = gdf[col].astype(str)
    
    # Convert to GeoJSON string then parse to dict
    geojson_str = gdf.to_json()
    return json.loads(geojson_str)


# =============================================================================
# MAIN FUNCTION: 4-PHASE APPROACH
# =============================================================================

def fetch_hdx_spatial_data(
    country_iso3: str,
    keyword: str,
    max_datasets: int = 5,
    max_features: int = 500,
    as_layer: bool = False,
) -> Union[str, dict]:
    """
    Hunt for spatial data from HDX with Regional Data Joiner support.
    
    4-Phase Approach:
    1. HUNTER: Search for data (points with coords OR regional data with admin names)
    2. BOUNDARY FETCHER: If regional data, fetch COD-AB boundaries
    3. MERGE: Join regional data with boundaries using fuzzy matching
    4. RETURN: GeoJSON (Points or Polygons with data properties)
    
    Args:
        country_iso3: ISO3 country code (e.g., "KEN", "YEM", "COD")
        keyword: Search keyword (e.g., "health", "wfp", "food security")
        max_datasets: Maximum datasets to check (default 5)
        max_features: Maximum features to return (default 500)
        
    Returns:
        GeoJSON string (Points or Polygons), or error message string
    """
    _ensure_hdx_configured()
    
    country_iso3 = country_iso3.upper()
    
    logger.info(f"=" * 60)
    logger.info(f"🔍 HDX Hunter for '{keyword}' in {country_iso3}")
    logger.info(f"=" * 60)
    
    # Get country name for better search
    country_names = {
        'YEM': 'yemen', 'SSD': 'south sudan', 'SDN': 'sudan', 'SOM': 'somalia',
        'ETH': 'ethiopia', 'KEN': 'kenya', 'UGA': 'uganda', 'COD': 'congo',
        'NGA': 'nigeria', 'MLI': 'mali', 'NER': 'niger', 'TCD': 'chad',
        'CAF': 'central african republic', 'SYR': 'syria', 'IRQ': 'iraq',
        'AFG': 'afghanistan', 'PAK': 'pakistan', 'BGD': 'bangladesh',
        'MMR': 'myanmar', 'HTI': 'haiti', 'VEN': 'venezuela', 'COL': 'colombia',
    }
    country_name = country_names.get(country_iso3, country_iso3.lower())
    
    base_queries = _get_smart_queries(keyword)
    
    # Build query list: simpler queries work better on HDX
    queries = []
    # Try country + simple keyword first (this works best)
    queries.append(f"{country_name} {keyword}")  # "yemen hunger"
    # Then try country + each mapped query term
    for q in base_queries:
        queries.append(f"{country_name} {q}")  # "yemen hungermap"
    # Finally try with ISO code
    queries.append(f"{keyword} {country_iso3}")  # "hunger YEM"
    
    datasets_checked = 0
    resources_checked = 0
    errors = []
    
    # Track regional data candidates (no coords but has admin column)
    regional_candidates = []
    
    # =========================================================================
    # PHASE 1: THE HUNTER
    # =========================================================================
    logger.info(f"\n📍 Phase 1: Hunting for data...")
    
    for query in queries:
        if datasets_checked >= max_datasets:
            break
        
        full_query = query
        logger.info(f"Searching: '{full_query}'")
        
        try:
            datasets = Dataset.search_in_hdx(full_query, rows=max_datasets - datasets_checked)
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            errors.append(f"Search '{query}' failed: {e}")
            continue
        
        if not datasets:
            logger.info(f"No datasets found for '{query}'")
            continue
        
        logger.info(f"Found {len(datasets)} datasets")
        
        for dataset in datasets:
            if datasets_checked >= max_datasets:
                break
            
            datasets_checked += 1
            ds_title = dataset.get('title', 'Unknown')
            ds_name = dataset.get('name', '')
            
            logger.info(f"[{datasets_checked}/{max_datasets}] {ds_title[:50]}...")
            
            try:
                resources = dataset.get_resources()
            except Exception as e:
                logger.warning(f"  Could not get resources: {e}")
                continue
            
            if not resources:
                continue
            
            for resource in resources:
                resource_format = resource.get('format', '').upper()
                resource_name = resource.get('name', 'Unknown')
                
                if resource_format not in ('CSV', 'XLSX', 'XLS', 'GEOJSON'):
                    continue
                
                resources_checked += 1
                logger.info(f"  Trying: {resource_name[:40]}... [{resource_format}]")
                
                df = _parse_resource(resource, resource_format)
                
                if df is None or df.empty:
                    continue
                
                # Check for coordinate columns
                lat_col = _find_column_by_patterns(df.columns.tolist(), LAT_PATTERNS)
                lon_col = _find_column_by_patterns(df.columns.tolist(), LON_PATTERNS)
                
                if lat_col and lon_col:
                    # SUCCESS: Point data with coordinates
                    logger.info(f"  ✅ Found coordinates: {lat_col}, {lon_col}")
                    
                    df = df.dropna(subset=[lat_col, lon_col])
                    if df.empty:
                        continue
                    
                    geojson = _df_to_geojson(df, lat_col, lon_col, limit=max_features)
                    
                    if not geojson['features']:
                        continue
                    
                    geojson['metadata'] = {
                        'source': 'HDX',
                        'data_type': 'point',
                        'dataset_name': ds_name,
                        'dataset_title': ds_title,
                        'resource_name': resource_name,
                        'country': country_iso3,
                        'keyword': keyword,
                        'features_returned': len(geojson['features']),
                    }
                    
                    logger.info(f"  🎯 SUCCESS! Returning {len(geojson['features'])} point features")
                    
                    # Optionally format as LayerData
                    if as_layer and format_geojson_layer:
                        return format_geojson_layer(
                            id=f"hdx_{keyword}_{country_iso3.lower()}",
                            data=geojson,
                            label=f"{keyword.title()} ({country_iso3})",
                            style="symbol",
                            summary=f"HDX {keyword}: {len(geojson['features'])} features in {country_iso3}",
                            source="HDX",
                            country=country_iso3,
                            keyword=keyword,
                        )
                    
                    return json.dumps(geojson, indent=2)
                
                else:
                    # No coordinates - check for admin columns
                    admin_col = _find_admin_column(df.columns.tolist())
                    
                    if admin_col:
                        # Skip HXL header rows (start with #)
                        for col in df.columns:
                            if df[col].astype(str).str.startswith('#').any():
                                df = df[~df[col].astype(str).str.startswith('#')]
                                break
                        
                        # Check if this data is for the requested country
                        is_right_country = False
                        
                        for col in df.columns:
                            col_lower = col.lower()
                            if 'country' in col_lower or 'iso' in col_lower:
                                # Check if any row matches our country
                                values = df[col].astype(str).str.upper().unique()
                                if country_iso3 in values or country_iso3[:2] in values:
                                    is_right_country = True
                                    # Filter to only this country's data
                                    mask = df[col].astype(str).str.upper().isin([country_iso3, country_iso3[:2]])
                                    df = df[mask]
                                    logger.info(f"  Filtered to {len(df)} rows for {country_iso3}")
                                    break
                        
                        if not is_right_country:
                            # Check dataset title/name for country
                            if country_iso3.lower() in ds_name.lower() or country_iso3.lower() in ds_title.lower():
                                is_right_country = True
                            # Also check country name
                            if country_name in ds_name.lower() or country_name in ds_title.lower():
                                is_right_country = True
                        
                        if is_right_country and len(df) > 0:
                            logger.info(f"  📊 Regional data found for {country_iso3} (admin col: {admin_col})")
                            logger.info(f"     Columns: {list(df.columns)[:8]}...")
                            logger.info(f"     Sample admin values: {df[admin_col].dropna().head(3).tolist()}")
                            
                            regional_candidates.append({
                                'df': df,
                                'admin_col': admin_col,
                                'dataset_name': ds_name,
                                'dataset_title': ds_title,
                                'resource_name': resource_name,
                            })
                        else:
                            logger.info(f"  Regional data found but wrong country (not {country_iso3})")
                    else:
                        logger.info(f"  No coordinates or admin columns. Columns: {list(df.columns)[:8]}...")
    
    # =========================================================================
    # PHASE 2 & 3: BOUNDARY FETCHER + MERGE (if regional data found)
    # =========================================================================
    
    if regional_candidates:
        logger.info(f"\n📊 Found {len(regional_candidates)} regional data candidate(s)")
        
        # Fetch admin boundaries
        boundaries_gdf = _fetch_admin_boundaries(country_iso3)
        
        if boundaries_gdf is not None:
            # Try to merge each candidate
            for candidate in regional_candidates:
                logger.info(f"\n🔗 Trying to merge: {candidate['dataset_title'][:40]}...")
                
                merged_gdf = _fuzzy_merge_with_boundaries(
                    candidate['df'],
                    candidate['admin_col'],
                    boundaries_gdf
                )
                
                if merged_gdf is not None and len(merged_gdf) > 0:
                    # SUCCESS: Regional data merged with boundaries
                    geojson = _gdf_to_geojson(merged_gdf.head(max_features))
                    
                    geojson['metadata'] = {
                        'source': 'HDX',
                        'data_type': 'regional_polygon',
                        'dataset_name': candidate['dataset_name'],
                        'dataset_title': candidate['dataset_title'],
                        'resource_name': candidate['resource_name'],
                        'country': country_iso3,
                        'keyword': keyword,
                        'admin_column': candidate['admin_col'],
                        'features_returned': len(geojson.get('features', [])),
                        'merge_note': 'Regional data joined with COD-AB boundaries',
                    }
                    
                    logger.info(f"  🎯 SUCCESS! Returning {len(geojson.get('features', []))} polygon features")
                    
                    # Optionally format as LayerData
                    if as_layer and format_geojson_layer:
                        return format_geojson_layer(
                            id=f"hdx_{keyword}_{country_iso3.lower()}_regional",
                            data=geojson,
                            label=f"{keyword.title()} Regions ({country_iso3})",
                            style="choropleth",
                            summary=f"HDX {keyword}: {len(geojson.get('features', []))} regions in {country_iso3}",
                            source="HDX",
                            country=country_iso3,
                            keyword=keyword,
                        )
                    
                    return json.dumps(geojson, indent=2)
            
            logger.warning("  Merge failed for all candidates")
        else:
            logger.warning("  No boundaries available for merge")
    
    # =========================================================================
    # PHASE 4: ERROR RESPONSE
    # =========================================================================
    
    error_msg = {
        'error': True,
        'message': f"No spatial data found for '{keyword}' in {country_iso3}",
        'details': {
            'country': country_iso3,
            'keyword': keyword,
            'queries_tried': queries,
            'datasets_checked': datasets_checked,
            'resources_checked': resources_checked,
            'regional_candidates_found': len(regional_candidates),
            'errors': errors[:5],
        },
        'suggestions': [
            "Try a different keyword (e.g., 'health', 'airport', 'wfp')",
            f"Check HDX directly: https://data.humdata.org/dataset?q={keyword}+{country_iso3}",
        ]
    }
    
    logger.warning(f"❌ No data found after checking {datasets_checked} datasets")
    
    # Optionally format as error LayerData
    if as_layer and format_error:
        return format_error(
            message=error_msg['message'],
            layer_id=f"hdx_{keyword}_{country_iso3.lower()}",
            details=error_msg['details']
        )
    
    return json.dumps(error_msg, indent=2)


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🔍 HDX Infrastructure Hunter + Regional Data Joiner - Test Suite")
    print("=" * 70)
    
    tests = [
        ("KEN", "healthsite", "Point data: Healthsites in Kenya"),
        ("COD", "airport", "Point data: Airports in DRC"),
        ("YEM", "hungermap", "Regional data: HungerMap in Yemen"),
        ("ETH", "hungermap", "Regional data: HungerMap in Ethiopia"),
    ]
    
    for country, keyword, description in tests:
        print(f"\n{'='*60}")
        print(f"🎯 Test: {description}")
        print(f"{'='*60}")
        
        result = fetch_hdx_spatial_data(country, keyword, max_features=10)
        
        try:
            data = json.loads(result)
            
            if data.get('error'):
                print(f"\n⚠️  {data['message']}")
                print(f"   Datasets checked: {data['details']['datasets_checked']}")
                print(f"   Regional candidates: {data['details']['regional_candidates_found']}")
            else:
                features = data.get('features', [])
                metadata = data.get('metadata', {})
                data_type = metadata.get('data_type', 'unknown')
                
                print(f"\n✅ Success!")
                print(f"   Data type: {data_type}")
                print(f"   Dataset: {metadata.get('dataset_title', 'N/A')[:50]}...")
                print(f"   Features: {len(features)}")
                
                if features and features[0].get('geometry'):
                    geom_type = features[0]['geometry']['type']
                    print(f"   Geometry: {geom_type}")
                    
                    props = features[0].get('properties', {})
                    print(f"   Properties: {list(props.keys())[:6]}...")
                    
        except json.JSONDecodeError:
            print(f"   ❌ Invalid JSON response")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)
