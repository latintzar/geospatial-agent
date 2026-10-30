"""
Wealth Index Tools (HDX Relative Wealth Index)

Fetches the Relative Wealth Index (RWI) from HDX to layer 'Spending Power' onto maps.
RWI is a machine-learning derived index from Meta Data for Good, available for 90+ countries.

RWI Scale:
- Score ranges from approximately -2 (poorest) to +2 (wealthiest)
- 0 represents the country average
- Positive = above average wealth, Negative = below average

Usage:
    from tools_wealth import fetch_wealth_index
    
    # Get wealth data for Ghana
    result = fetch_wealth_index("GHA")
    # Returns: [{'hex': '89...', 'rwi_score': 0.8, 'wealth_category': 'High'}, ...]

System Prompt Context:
    'Use this tool to find high-income areas for retail or assess economic 
    development levels. Layer spending power data onto production maps.'
"""

import pandas as pd
import h3
import json
import logging
import os
import tempfile
from typing import Optional, List, Dict
from hdx.api.configuration import Configuration
from hdx.data.dataset import Dataset
from shapely.geometry import Polygon, box, Point

# Import formatting helper
try:
    from ..utils_formatting import format_layer, format_h3_layer
except ImportError:
    try:
        from utils_formatting import format_layer, format_h3_layer
    except ImportError:
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

# HDX Configuration singleton
_hdx_configured = False

# Default H3 resolution for wealth data (resolution 8 = ~0.74 km²)
DEFAULT_H3_RESOLUTION = 8

# =============================================================================
# ISO3 TO COUNTRY NAME MAPPING
# For HDX search queries
# =============================================================================

# Complete mapping of ISO3 codes to country names in RWI dataset
# Total: 93 countries with RWI data (low/middle-income countries)
ISO3_TO_NAME = {
    'ALB': 'Albania',
    'DZA': 'Algeria',
    'AGO': 'Angola',
    'ARG': 'Argentina',
    'ARM': 'Armenia',
    'AZE': 'Azerbaijan',
    'BGD': 'Bangladesh',
    'BLZ': 'Belize',
    'BEN': 'Benin',
    'BTN': 'Bhutan',
    'BOL': 'Bolivia',
    'BIH': 'Bosnia and Herzegovina',
    'BWA': 'Botswana',
    'BRA': 'Brazil',
    'BGR': 'Bulgaria',
    'BFA': 'Burkina Faso',
    'BDI': 'Burundi',
    'KHM': 'Cambodia',
    'CMR': 'Cameroon',
    'CPV': 'Cape Verde',
    'CAF': 'Central African Republic',
    'TCD': 'Chad',
    'COL': 'Colombia',
    'COM': 'Comoros',
    'CRI': 'Costa Rica',
    'CIV': "Côte d'Ivoire",
    'COD': 'Democratic Republic of the Congo',
    'DJI': 'Djibouti',
    'DMA': 'Dominica',
    'DOM': 'Dominican Republic',
    'ECU': 'Ecuador',
    'EGY': 'Egypt',
    'SLV': 'El Salvador',
    'GNQ': 'Equatorial Guinea',
    'ERI': 'Eritrea',
    'ETH': 'Ethiopia',
    'GAB': 'Gabon',
    'GMB': 'Gambia',
    'GEO': 'Georgia',
    'GHA': 'Ghana',
    'GRD': 'Grenada',
    'GTM': 'Guatemala',
    'GIN': 'Guinea',
    'GNB': 'Guinea-Bissau',
    'GUY': 'Guyana',
    'HTI': 'Haiti',
    'HND': 'Honduras',
    'IND': 'India and Pakistan',  # Note: Combined in RWI dataset
    'IDN': 'Indonesia',
    'JAM': 'Jamaica',
    'JOR': 'Jordan',
    'KAZ': 'Kazakhstan',
    'KEN': 'Kenya',
    'KGZ': 'Kyrgyzstan',
    'LAO': 'Laos',
    'LSO': 'Lesotho',
    'LBR': 'Liberia',
    'LBY': 'Libya',
    'MDG': 'Madagascar',
    'MWI': 'Malawi',
    'MYS': 'Malaysia',
    'MDV': 'Maldives',
    'MLI': 'Mali',
    'MRT': 'Mauritania',
    'MUS': 'Mauritius',
    'MEX': 'Mexico',
    'MDA': 'Moldova',
    'MNG': 'Mongolia',
    'MNE': 'Montenegro',
    'MAR': 'Morocco',
    'MOZ': 'Mozambique',
    'NAM': 'Namibia',
    'NPL': 'Nepal',
    'NIC': 'Nicaragua',
    'NER': 'Niger',
    'NGA': 'Nigeria',
    'MKD': 'North Macedonia',
    'PRY': 'Paraguay',
    'PER': 'Peru',
    'PHL': 'Philippines',
    'COG': 'Republic of Congo',
    'ROU': 'Romania',
    'RWA': 'Rwanda',
    'LCA': 'Saint Lucia',
    'VCT': 'Saint Vincent and Grenadines',
    'STP': 'Sao Tome and Principe',
    'SEN': 'Senegal',
    'SRB': 'Serbia',
    'SLE': 'Sierra Leone',
    'ZAF': 'South Africa',
    'LKA': 'Sri Lanka',
    'SUR': 'Suriname',
    'SWZ': 'Swaziland',
    'TJK': 'Tajikistan',
    'TZA': 'Tanzania',
    'THA': 'Thailand',
    'TLS': 'Timor-Leste',
    'TGO': 'Togo',
    'TUN': 'Tunisia',
    'TUR': 'Turkey',
    'TKM': 'Turkmenistan',
    'UGA': 'Uganda',
    'UKR': 'Ukraine',
    'UZB': 'Uzbekistan',
    'VNM': 'Vietnam',
    'ZMB': 'Zambia',
    'ZWE': 'Zimbabwe',
}

# Wealth category thresholds
WEALTH_CATEGORIES = [
    (-float('inf'), -1.0, 'Very Low'),
    (-1.0, -0.5, 'Low'),
    (-0.5, 0.0, 'Below Average'),
    (0.0, 0.5, 'Above Average'),
    (0.5, 1.0, 'High'),
    (1.0, float('inf'), 'Very High'),
]


def _ensure_hdx_configured():
    """Initialize HDX configuration singleton."""
    global _hdx_configured
    if not _hdx_configured:
        try:
            Configuration.create(
                hdx_site='prod',
                user_agent='PuedoCasa-AgenticMaps/1.0',
                hdx_read_only=True
            )
            _hdx_configured = True
            logger.info("  HDX configured successfully")
        except Exception as e:
            logger.warning(f"  HDX config warning: {e}")
            _hdx_configured = True  # Mark as done even if warning


def _h3_version() -> int:
    """Detect H3 library version (3 or 4)."""
    if hasattr(h3, 'latlng_to_cell'):
        return 4
    return 3


def _latlng_to_h3(lat: float, lng: float, resolution: int) -> str:
    """Convert lat/lng to H3 cell, handling version differences."""
    if _h3_version() >= 4:
        return h3.latlng_to_cell(lat, lng, resolution)
    else:
        return h3.geo_to_h3(lat, lng, resolution)


def _categorize_wealth(rwi_score: float) -> str:
    """Convert RWI score to wealth category."""
    for low, high, category in WEALTH_CATEGORIES:
        if low <= rwi_score < high:
            return category
    return 'Unknown'


def _get_country_name(iso3: str) -> Optional[str]:
    """Get country name from ISO3 code."""
    iso3_upper = iso3.upper()
    
    # Check our mapping first
    if iso3_upper in ISO3_TO_NAME:
        return ISO3_TO_NAME[iso3_upper]
    
    # Try pycountry as fallback
    try:
        import pycountry
        country = pycountry.countries.get(alpha_3=iso3_upper)
        if country:
            return country.name
    except ImportError:
        pass
    
    return None


def fetch_wealth_index(
    country_iso3: str,
    bbox_polygon: Optional[Polygon] = None,
    resolution: int = DEFAULT_H3_RESOLUTION,
    as_layer: bool = False,
    focus_geometry: Optional[Dict] = None,
) -> Optional[List[Dict]]:
    """
    Fetch Relative Wealth Index (RWI) data from HDX and aggregate to H3 hexagons.
    
    The RWI is a machine-learning derived index from Meta Data for Good that
    estimates relative wealth levels at high resolution (~2.4km).
    
    Focus + Context Pattern (Google Earth style):
    - bbox_polygon: Use context bbox for fetching with breathing room
    - focus_geometry: Optional exact boundary to mark is_inside for styling
    
    Args:
        country_iso3: ISO3 country code (e.g., "GHA", "KEN", "NGA")
        bbox_polygon: Optional Shapely Polygon to filter results (use context extent)
        resolution: H3 resolution for aggregation (default 8)
        as_layer: If True, return formatted LayerData dict
        focus_geometry: Optional GeoJSON Polygon to mark is_inside property
                       Data inside focus = 100% opacity, outside = 50% opacity
        
    Returns:
        List of dicts with H3 hexagons and wealth data:
        [{
            'hex': 'h3_index',
            'rwi_score': mean_rwi,
            'wealth_category': 'High'/'Low'/etc,
            'point_count': number_of_data_points,
            'is_inside': bool  # if focus_geometry provided
        }, ...]
        or None if no data found
        
    Example:
        >>> # Fetch Ghana wealth with Focus + Context
        >>> from utils_spatial import get_aoi
        >>> accra = get_aoi("Accra, Ghana")
        >>> result = fetch_wealth_index(
        ...     "GHA",
        ...     bbox_polygon=box(*accra['context_bbox']),
        ...     focus_geometry=accra['focus_geometry']
        ... )
        >>> # Returns wealth data for Accra area, with suburbs at 50% opacity
    """
    logger.info("=" * 60)
    logger.info(f"💰 Fetching Relative Wealth Index for {country_iso3}")
    logger.info("=" * 60)
    
    _ensure_hdx_configured()
    
    # Get country name for finding the correct resource
    country_name = _get_country_name(country_iso3)
    if not country_name:
        logger.error(f"  ❌ Unknown country code: {country_iso3}")
        return None
    
    logger.info(f"  Country: {country_iso3} → {country_name}")
    
    # RWI data is in a single global dataset with per-country CSV files
    # Dataset ID: 'relative-wealth-index'
    try:
        dataset = Dataset.read_from_hdx('relative-wealth-index')
        logger.info(f"  ✅ Found: {dataset.get('title', 'Relative Wealth Index')}")
    except Exception as e:
        logger.error(f"  ❌ Could not read RWI dataset: {e}")
        return None
    
    # Find the country-specific CSV resource
    resources = dataset.get_resources()
    csv_resource = None
    
    # Build expected filename patterns
    expected_names = [
        f"{country_name}_relative_wealth_index.csv",
        f"{country_name.lower()}_relative_wealth_index.csv",
        f"{country_name.replace(' ', '_')}_relative_wealth_index.csv",
    ]
    
    # Also try variations for special country names
    name_variations = [country_name]
    if country_name == "Cote d'Ivoire":
        name_variations.extend(["Côte d'Ivoire", "Ivory Coast", "Cote dIvoire"])
    elif country_name == "Democratic Republic of the Congo":
        name_variations.extend(["DRC", "DR Congo", "Democratic Republic of Congo"])
    
    for resource in resources:
        res_name = resource.get('name', '')
        res_name_lower = res_name.lower()
        
        # Check if this is a CSV for our country
        if not res_name_lower.endswith('.csv'):
            continue
            
        # Check against all name variations
        for name_var in name_variations:
            if name_var.lower() in res_name_lower:
                csv_resource = resource
                logger.info(f"  Found CSV: {res_name}")
                break
        
        if csv_resource:
            break
    
    if not csv_resource:
        logger.error(f"  ❌ No CSV found for {country_name}")
        logger.info(f"  RWI data covers 93 low/middle-income countries")
        logger.info(f"  Try checking available countries with list_available_countries()")
        return None
    
    # Download and process
    try:
        url, path = csv_resource.download()
        logger.info(f"  Downloaded: {path}")
        
        # Read CSV
        df = pd.read_csv(path)
        logger.info(f"  Loaded {len(df):,} rows")
        
        # Find lat/lon/rwi columns (case-insensitive)
        columns_lower = {c.lower(): c for c in df.columns}
        
        lat_col = None
        lon_col = None
        rwi_col = None
        
        for col_lower, col_orig in columns_lower.items():
            if col_lower in ('latitude', 'lat', 'y'):
                lat_col = col_orig
            elif col_lower in ('longitude', 'lon', 'lng', 'long', 'x'):
                lon_col = col_orig
            elif col_lower in ('rwi', 'rwi_score', 'wealth_index', 'relative_wealth_index'):
                rwi_col = col_orig
        
        if not lat_col or not lon_col or not rwi_col:
            logger.error(f"  ❌ Could not find required columns")
            logger.info(f"  Available columns: {list(df.columns)}")
            return None
        
        logger.info(f"  Columns: lat={lat_col}, lon={lon_col}, rwi={rwi_col}")
        
        # Filter to bbox if provided
        if bbox_polygon:
            logger.info(f"  Filtering to bounding box...")
            minx, miny, maxx, maxy = bbox_polygon.bounds
            df = df[
                (df[lat_col] >= miny) & (df[lat_col] <= maxy) &
                (df[lon_col] >= minx) & (df[lon_col] <= maxx)
            ]
            logger.info(f"  After bbox filter: {len(df):,} rows")
        
        if df.empty:
            logger.warning(f"  ❌ No data points in area")
            return None
        
        # Convert to H3 and aggregate
        logger.info(f"  Converting to H3 (resolution {resolution})...")
        
        h3_rwi = {}  # hex -> list of RWI values
        
        for _, row in df.iterrows():
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                rwi = float(row[rwi_col])
                
                if pd.isna(lat) or pd.isna(lon) or pd.isna(rwi):
                    continue
                
                hex_id = _latlng_to_h3(lat, lon, resolution)
                
                if hex_id not in h3_rwi:
                    h3_rwi[hex_id] = []
                h3_rwi[hex_id].append(rwi)
                
            except (ValueError, TypeError):
                continue
        
        # Calculate mean RWI per hexagon
        result = []
        for hex_id, rwi_values in h3_rwi.items():
            mean_rwi = round(sum(rwi_values) / len(rwi_values), 3)
            category = _categorize_wealth(mean_rwi)
            
            result.append({
                'hex': hex_id,
                'rwi_score': mean_rwi,
                'wealth_category': category,
                'point_count': len(rwi_values),
            })
        
        # Sort by RWI descending (highest wealth first)
        result.sort(key=lambda x: x['rwi_score'], reverse=True)
        
        # Summary stats
        if result:
            avg_rwi = sum(r['rwi_score'] for r in result) / len(result)
            max_rwi = max(r['rwi_score'] for r in result)
            min_rwi = min(r['rwi_score'] for r in result)
            
            logger.info(f"  ✅ Aggregated to {len(result)} H3 hexagons")
            logger.info(f"  RWI range: {min_rwi:.2f} to {max_rwi:.2f}")
            logger.info(f"  Average RWI: {avg_rwi:.2f}")
            
            # Category distribution
            categories = {}
            for r in result:
                cat = r['wealth_category']
                categories[cat] = categories.get(cat, 0) + 1
            logger.info(f"  Category distribution: {categories}")
        
        # Apply Focus + Context masking if focus_geometry provided
        if focus_geometry and mask_layer_by_aoi and result:
            logger.info(f"  Applying Focus + Context masking...")
            result = mask_layer_by_aoi(result, focus_geometry)
            inside_count = sum(1 for r in result if r.get('is_inside', False))
            context_count = len(result) - inside_count
            logger.info(f"  Focus: {inside_count}, Context: {context_count}")
        
        # Optionally format as LayerData
        if as_layer and format_h3_layer:
            # Convert to standard format with 'value' key
            h3_data = [
                {'hex': r['hex'], 'value': r['rwi_score'], **r}
                for r in result
            ]
            return format_h3_layer(
                id=f"wealth_index_{country_iso3.lower()}",
                data=h3_data,
                label=f"Wealth Index ({country_iso3})",
                color_scale="RdYlGn",
                property_key="value",
                summary=f"RWI for {country_iso3}: {len(result)} hexagons, avg={avg_rwi:.2f}",
                source="HDX Relative Wealth Index",
                country=country_iso3,
            )
        
        return result
        
    except Exception as e:
        logger.error(f"  ❌ Error processing RWI data: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_wealth_summary(
    country_iso3: str,
    resolution: int = DEFAULT_H3_RESOLUTION,
) -> Optional[Dict]:
    """
    Get a summary of wealth distribution for a country.
    
    Args:
        country_iso3: ISO3 country code
        resolution: H3 resolution
        
    Returns:
        Dictionary with wealth statistics and category distribution
    """
    result = fetch_wealth_index(country_iso3, resolution=resolution)
    
    if not result:
        return None
    
    # Calculate stats
    rwi_values = [r['rwi_score'] for r in result]
    
    categories = {}
    for r in result:
        cat = r['wealth_category']
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        'country': country_iso3,
        'total_hexagons': len(result),
        'avg_rwi': round(sum(rwi_values) / len(rwi_values), 3),
        'min_rwi': round(min(rwi_values), 3),
        'max_rwi': round(max(rwi_values), 3),
        'std_rwi': round(pd.Series(rwi_values).std(), 3),
        'category_distribution': categories,
        'category_percentages': {
            cat: round(count / len(result) * 100, 1)
            for cat, count in categories.items()
        }
    }


def list_available_countries() -> List[str]:
    """Return list of countries with known RWI data availability."""
    return sorted(ISO3_TO_NAME.keys())


def get_wealth_categories() -> List[Dict]:
    """Return the wealth category definitions."""
    return [
        {'range': '< -1.0', 'category': 'Very Low', 'description': 'Significantly below average'},
        {'range': '-1.0 to -0.5', 'category': 'Low', 'description': 'Below average'},
        {'range': '-0.5 to 0.0', 'category': 'Below Average', 'description': 'Slightly below average'},
        {'range': '0.0 to 0.5', 'category': 'Above Average', 'description': 'Slightly above average'},
        {'range': '0.5 to 1.0', 'category': 'High', 'description': 'Above average'},
        {'range': '> 1.0', 'category': 'Very High', 'description': 'Significantly above average'},
    ]


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("💰 Wealth Index Tools - Test Suite")
    print("=" * 70)
    
    print(f"\n📊 Statistics:")
    print(f"  - Countries with known RWI data: {len(ISO3_TO_NAME)}")
    
    print(f"\n📈 Wealth Categories:")
    for cat in get_wealth_categories():
        print(f"  {cat['range']:15} → {cat['category']:15} ({cat['description']})")
    
    print("\n" + "-" * 70)
    print("--- Testing fetch_wealth_index ---")
    print("-" * 70)
    
    # Test Ghana
    print("\n🇬🇭 Test: Ghana Wealth Index")
    result = fetch_wealth_index("GHA", resolution=8)
    
    if result:
        print(f"✅ Got {len(result)} hexagons")
        
        # Show distribution
        categories = {}
        for r in result:
            cat = r['wealth_category']
            categories[cat] = categories.get(cat, 0) + 1
        
        print(f"Category distribution:")
        for cat, count in sorted(categories.items()):
            pct = count / len(result) * 100
            print(f"  {cat}: {count} ({pct:.1f}%)")
        
        print(f"\nTop 5 wealthiest hexagons:")
        for r in result[:5]:
            print(f"  {r['hex'][:12]}... RWI={r['rwi_score']:.2f} ({r['wealth_category']})")
        
        print(f"\nBottom 5 (lowest wealth) hexagons:")
        for r in result[-5:]:
            print(f"  {r['hex'][:12]}... RWI={r['rwi_score']:.2f} ({r['wealth_category']})")
    else:
        print("❌ No data returned")
    
    # Test Kenya
    print("\n🇰🇪 Test: Kenya Wealth Index")
    result = fetch_wealth_index("KEN", resolution=8)
    
    if result:
        print(f"✅ Got {len(result)} hexagons")
        avg_rwi = sum(r['rwi_score'] for r in result) / len(result)
        print(f"Average RWI: {avg_rwi:.2f}")
    else:
        print("❌ No data returned")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)

