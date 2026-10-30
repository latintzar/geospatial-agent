"""
Corporate Data Tools (OpenCorporates)

⚠️  STATUS: PARKED - Requires paid OpenCorporates API key
    The tool is fully implemented and ready to use once API access is available.
    Pricing: https://opencorporates.com/info/pricing

Smart OpenCorporates client with automatic jurisdiction discovery.
Converts human-readable location names to API codes automatically.

Usage:
    from tools_corporate import search_companies
    
    # Search for cocoa companies in Ghana (auto-resolves 'Ghana' → 'gh')
    result = search_companies("cocoa", location="Ghana")
    
    # Search for active tech companies in California
    result = search_companies("tech", location="California", status="Active")

System Prompt Context:
    'Use this tool to find companies. You can pass full country names 
    (e.g. "Kenya") and the tool will auto-resolve them to the correct 
    code ("ke"). Returns GeoJSON with company locations.'
    
Setup (when ready):
    export OPENCORPORATES_API_KEY=your_key_here
"""

import requests
import pandas as pd
import os
import time
import json
import logging
from typing import Optional, List, Dict, Literal, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Configuration
OPENCORPORATES_BASE_URL = "https://api.opencorporates.com/v0.4"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Rate limiting
_last_nominatim_call = 0.0
NOMINATIM_RATE_LIMIT = 1.0  # seconds between calls

# Cache for jurisdiction lookups
_jurisdiction_cache: Dict[str, str] = {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def resolve_jurisdiction(location_name: str) -> str:
    """
    Convert human-readable location names to OpenCorporates jurisdiction codes.
    
    Examples:
        'United Kingdom' → 'gb'
        'California' → 'us_ca'
        'Kenya' → 'ke'
        'Germany' → 'de'
    
    Args:
        location_name: Human-readable location (country, state, etc.)
        
    Returns:
        Jurisdiction code (e.g., 'gb', 'us_ca', 'ke')
    """
    if not location_name:
        return None
    
    location_lower = location_name.lower().strip()
    
    # Check cache first
    if location_lower in _jurisdiction_cache:
        return _jurisdiction_cache[location_lower]
    
    # If already looks like a code (2 letters or xx_xx format), return as-is
    if len(location_name) == 2 or (len(location_name) == 5 and location_name[2] == '_'):
        return location_name.lower()
    
    # Common mappings (fast path)
    COMMON_JURISDICTIONS = {
        'united states': 'us',
        'usa': 'us',
        'us': 'us',
        'united kingdom': 'gb',
        'uk': 'gb',
        'great britain': 'gb',
        'england': 'gb',
        'germany': 'de',
        'france': 'fr',
        'spain': 'es',
        'italy': 'it',
        'netherlands': 'nl',
        'belgium': 'be',
        'switzerland': 'ch',
        'austria': 'at',
        'poland': 'pl',
        'sweden': 'se',
        'norway': 'no',
        'denmark': 'dk',
        'finland': 'fi',
        'ireland': 'ie',
        'portugal': 'pt',
        'greece': 'gr',
        'czech republic': 'cz',
        'czechia': 'cz',
        'romania': 'ro',
        'hungary': 'hu',
        'bulgaria': 'bg',
        'slovakia': 'sk',
        'slovenia': 'si',
        'croatia': 'hr',
        'estonia': 'ee',
        'latvia': 'lv',
        'lithuania': 'lt',
        'luxembourg': 'lu',
        'malta': 'mt',
        'cyprus': 'cy',
        'canada': 'ca',
        'australia': 'au',
        'new zealand': 'nz',
        'japan': 'jp',
        'china': 'cn',
        'india': 'in',
        'brazil': 'br',
        'mexico': 'mx',
        'argentina': 'ar',
        'chile': 'cl',
        'colombia': 'co',
        'peru': 'pe',
        'south africa': 'za',
        'nigeria': 'ng',
        'kenya': 'ke',
        'ghana': 'gh',
        'egypt': 'eg',
        'morocco': 'ma',
        'israel': 'il',
        'turkey': 'tr',
        'russia': 'ru',
        'ukraine': 'ua',
        'singapore': 'sg',
        'hong kong': 'hk',
        'malaysia': 'my',
        'indonesia': 'id',
        'thailand': 'th',
        'vietnam': 'vn',
        'philippines': 'ph',
        'south korea': 'kr',
        'korea': 'kr',
        'taiwan': 'tw',
        'uae': 'ae',
        'united arab emirates': 'ae',
        'saudi arabia': 'sa',
        # US States
        'california': 'us_ca',
        'texas': 'us_tx',
        'new york': 'us_ny',
        'florida': 'us_fl',
        'illinois': 'us_il',
        'pennsylvania': 'us_pa',
        'ohio': 'us_oh',
        'georgia': 'us_ga',
        'north carolina': 'us_nc',
        'michigan': 'us_mi',
        'new jersey': 'us_nj',
        'virginia': 'us_va',
        'washington': 'us_wa',
        'arizona': 'us_az',
        'massachusetts': 'us_ma',
        'tennessee': 'us_tn',
        'indiana': 'us_in',
        'missouri': 'us_mo',
        'maryland': 'us_md',
        'wisconsin': 'us_wi',
        'colorado': 'us_co',
        'minnesota': 'us_mn',
        'south carolina': 'us_sc',
        'alabama': 'us_al',
        'louisiana': 'us_la',
        'kentucky': 'us_ky',
        'oregon': 'us_or',
        'oklahoma': 'us_ok',
        'connecticut': 'us_ct',
        'iowa': 'us_ia',
        'utah': 'us_ut',
        'nevada': 'us_nv',
        'arkansas': 'us_ar',
        'mississippi': 'us_ms',
        'kansas': 'us_ks',
        'new mexico': 'us_nm',
        'nebraska': 'us_ne',
        'west virginia': 'us_wv',
        'idaho': 'us_id',
        'hawaii': 'us_hi',
        'new hampshire': 'us_nh',
        'maine': 'us_me',
        'montana': 'us_mt',
        'rhode island': 'us_ri',
        'delaware': 'us_de',
        'south dakota': 'us_sd',
        'north dakota': 'us_nd',
        'alaska': 'us_ak',
        'vermont': 'us_vt',
        'wyoming': 'us_wy',
        # Canadian Provinces
        'ontario': 'ca_on',
        'quebec': 'ca_qc',
        'british columbia': 'ca_bc',
        'alberta': 'ca_ab',
        'manitoba': 'ca_mb',
        'saskatchewan': 'ca_sk',
        'nova scotia': 'ca_ns',
        'new brunswick': 'ca_nb',
        # UK Parts
        'scotland': 'gb_sct',
        'wales': 'gb',
        'northern ireland': 'gb',
        # African Countries
        "cote d'ivoire": 'ci',
        'ivory coast': 'ci',
        'ethiopia': 'et',
        'tanzania': 'tz',
        'uganda': 'ug',
        'cameroon': 'cm',
        'senegal': 'sn',
        'mali': 'ml',
        'burkina faso': 'bf',
        'niger': 'ne',
        'benin': 'bj',
        'togo': 'tg',
        'rwanda': 'rw',
        'zambia': 'zm',
        'zimbabwe': 'zw',
        'botswana': 'bw',
        'namibia': 'na',
        'mozambique': 'mz',
        'angola': 'ao',
        'congo': 'cg',
        'dr congo': 'cd',
        'democratic republic of congo': 'cd',
    }
    
    if location_lower in COMMON_JURISDICTIONS:
        code = COMMON_JURISDICTIONS[location_lower]
        _jurisdiction_cache[location_lower] = code
        return code
    
    # Call OpenCorporates API to resolve
    logger.info(f"  🔍 Resolving jurisdiction: '{location_name}'")
    
    try:
        api_token = os.getenv('OPENCORPORATES_API_KEY')
        params = {'q': location_name}
        if api_token:
            params['api_token'] = api_token
        
        response = requests.get(
            f"{OPENCORPORATES_BASE_URL}/jurisdictions/match",
            params=params,
            timeout=10,
            headers={'User-Agent': 'PuedoCasa-AgenticMaps/1.0'}
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract jurisdiction code from response
            if 'results' in data and data['results']:
                jurisdiction = data['results'].get('jurisdiction', {})
                code = jurisdiction.get('code')
                if code:
                    logger.info(f"  ✅ Resolved '{location_name}' → '{code}'")
                    _jurisdiction_cache[location_lower] = code
                    return code
            
            # Alternative response structure
            if 'jurisdiction' in data:
                code = data['jurisdiction'].get('code')
                if code:
                    logger.info(f"  ✅ Resolved '{location_name}' → '{code}'")
                    _jurisdiction_cache[location_lower] = code
                    return code
        
        logger.warning(f"  ⚠️ Could not resolve jurisdiction for '{location_name}'")
        
    except Exception as e:
        logger.warning(f"  ⚠️ Error resolving jurisdiction: {e}")
    
    # Fallback: return the input as-is (lowercase, no spaces)
    fallback = location_name.lower().replace(' ', '_')
    _jurisdiction_cache[location_lower] = fallback
    return fallback


def geocode_address(address_string: str) -> Optional[List[float]]:
    """
    Convert a company address to [longitude, latitude] coordinates.
    
    Uses Nominatim (OpenStreetMap) for geocoding with proper rate limiting.
    
    Args:
        address_string: Full address text
        
    Returns:
        [lon, lat] or None if geocoding fails
    """
    global _last_nominatim_call
    
    if not address_string or not address_string.strip():
        return None
    
    # Clean the address
    address_clean = address_string.strip()
    
    # Try importing from tools_overture first
    try:
        from tools_overture import OvertureEngine
        engine = OvertureEngine()
        result = engine.get_location_boundary(address_clean)
        if result and 'bbox' in result:
            bbox = result['bbox']
            # Return center of bbox
            lon = (bbox[0] + bbox[2]) / 2
            lat = (bbox[1] + bbox[3]) / 2
            return [lon, lat]
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"  tools_overture failed: {e}")
    
    # Fallback to Nominatim
    # Enforce rate limit
    elapsed = time.time() - _last_nominatim_call
    if elapsed < NOMINATIM_RATE_LIMIT:
        time.sleep(NOMINATIM_RATE_LIMIT - elapsed)
    
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                'q': address_clean,
                'format': 'json',
                'limit': 1,
            },
            headers={
                'User-Agent': 'PuedoCasa-AgenticMaps/1.0 (corporate-search)',
            },
            timeout=10,
        )
        _last_nominatim_call = time.time()
        
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                lat = float(data[0]['lat'])
                lon = float(data[0]['lon'])
                return [lon, lat]
        
    except Exception as e:
        logger.debug(f"  Nominatim geocoding failed: {e}")
    
    return None


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def search_companies(
    query: str,
    location: Optional[str] = None,
    status: Optional[Literal['Active', 'Dissolved', 'Inactive']] = None,
    date_type: Literal['incorporation', 'dissolution'] = 'incorporation',
    min_date: Optional[str] = None,
    max_date: Optional[str] = None,
    address_filter: Optional[str] = None,
    max_results: int = 20,
    geocode: bool = True,
) -> str:
    """
    Search for companies using OpenCorporates API with automatic jurisdiction resolution.
    
    Args:
        query: Search query (company name, keywords)
        location: Location name (e.g., 'Kenya', 'California') - auto-resolved to code
        status: Filter by company status ('Active', 'Dissolved', 'Inactive')
        date_type: Which date to filter ('incorporation' or 'dissolution')
        min_date: Start date for date filter (YYYY-MM-DD)
        max_date: End date for date filter (YYYY-MM-DD)
        address_filter: Filter by address text
        max_results: Maximum companies to return (default 20)
        geocode: Whether to geocode addresses (default True)
        
    Returns:
        GeoJSON FeatureCollection string with company locations,
        or error object if request fails
        
    Example:
        >>> result = search_companies("cocoa", location="Ghana", status="Active")
        >>> # Returns GeoJSON with active cocoa companies in Ghana
    """
    logger.info("=" * 60)
    logger.info(f"🏢 Searching companies: '{query}'")
    logger.info("=" * 60)
    
    # Step A: Auto-Discovery - Resolve jurisdiction code
    jurisdiction_code = None
    if location:
        if len(location) > 2:
            jurisdiction_code = resolve_jurisdiction(location)
            logger.info(f"  Location: '{location}' → '{jurisdiction_code}'")
        else:
            jurisdiction_code = location.lower()
            logger.info(f"  Location: '{jurisdiction_code}'")
    
    # Step B: Build the API request
    api_token = os.getenv('OPENCORPORATES_API_KEY')
    
    params = {
        'q': query,
        'per_page': min(max_results, 100),  # API max is 100
        'order': 'score',
    }
    
    if api_token:
        params['api_token'] = api_token
    
    if jurisdiction_code:
        params['jurisdiction_code'] = jurisdiction_code
    
    if status:
        params['current_status'] = status.lower()
    
    if address_filter:
        params['registered_address'] = address_filter
    
    # Handle date filtering
    if min_date or max_date:
        date_range = f"{min_date or ''}:{max_date or ''}"
        if date_type == 'incorporation':
            params['incorporation_date'] = date_range
        else:
            params['dissolution_date'] = date_range
    
    logger.info(f"  API params: {params}")
    
    # Make the API request
    try:
        response = requests.get(
            f"{OPENCORPORATES_BASE_URL}/companies/search",
            params=params,
            headers={'User-Agent': 'PuedoCasa-AgenticMaps/1.0'},
            timeout=30,
        )
        
        if response.status_code == 401:
            logger.error("  ❌ Authentication failed - check OPENCORPORATES_API_KEY")
            return json.dumps({
                'error': True,
                'error_type': 'auth_error',
                'message': 'OpenCorporates API authentication failed. Set OPENCORPORATES_API_KEY environment variable.',
                'suggestion': 'Get a free API key at https://opencorporates.com/api_accounts/new',
            })
        
        if response.status_code == 429:
            logger.error("  ❌ Rate limited by OpenCorporates API")
            return json.dumps({
                'error': True,
                'error_type': 'rate_limit',
                'message': '⏳ OpenCorporates API rate limit reached. Please wait before trying again.',
                'retry_after_seconds': 60,
                'suggestion': 'The free tier has strict rate limits. Wait a minute and try again.',
            })
        
        if response.status_code != 200:
            logger.error(f"  ❌ API error: HTTP {response.status_code}")
            return json.dumps({
                'error': True,
                'error_type': 'api_error',
                'message': f'OpenCorporates API error (HTTP {response.status_code})',
                'status_code': response.status_code,
            })
        
        data = response.json()
        
    except requests.exceptions.Timeout:
        logger.error("  ❌ Request timed out")
        return json.dumps({
            'error': True,
            'error_type': 'timeout',
            'message': '⏳ OpenCorporates API request timed out. Please try again.',
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request failed: {e}")
        return json.dumps({
            'error': True,
            'error_type': 'request_error',
            'message': f'Network error: {str(e)}',
        })
    
    # Step C: Process results
    results = data.get('results', {})
    companies = results.get('companies', [])
    total_count = results.get('total_count', 0)
    
    logger.info(f"  Found {total_count} total companies, processing top {len(companies)}")
    
    if not companies:
        logger.warning("  ⚠️ No companies found")
        return json.dumps({
            'error': True,
            'error_type': 'no_results',
            'message': f'No companies found matching "{query}" in {location or "any jurisdiction"}',
            'suggestion': 'Try a different search query or location.',
            'total_count': 0,
        })
    
    # Step C: Process and optionally geocode
    features = []
    geocoded_count = 0
    
    for item in companies[:max_results]:
        company = item.get('company', {})
        
        company_name = company.get('name', 'Unknown')
        company_number = company.get('company_number', '')
        jurisdiction = company.get('jurisdiction_code', '')
        status_val = company.get('current_status', 'Unknown')
        incorporation_date = company.get('incorporation_date', '')
        dissolution_date = company.get('dissolution_date', '')
        address = company.get('registered_address_in_full', '')
        opencorporates_url = company.get('opencorporates_url', '')
        company_type = company.get('company_type', '')
        
        # Build properties
        properties = {
            'company_name': company_name,
            'company_number': company_number,
            'status': status_val,
            'incorporation_date': incorporation_date,
            'dissolution_date': dissolution_date,
            'address': address,
            'jurisdiction_code': jurisdiction,
            'company_type': company_type,
            'url': opencorporates_url,
        }
        
        # Try to geocode the address
        coordinates = None
        if geocode and address:
            coordinates = geocode_address(address)
            if coordinates:
                geocoded_count += 1
        
        if coordinates:
            # Create Point feature
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': coordinates,
                },
                'properties': properties,
            }
        else:
            # Create feature without geometry (null geometry allowed in GeoJSON)
            feature = {
                'type': 'Feature',
                'geometry': None,
                'properties': properties,
            }
        
        features.append(feature)
    
    # Step D: Build GeoJSON output
    geojson = {
        'type': 'FeatureCollection',
        'features': features,
        'properties': {
            'query': query,
            'location': location,
            'jurisdiction_code': jurisdiction_code,
            'total_count': total_count,
            'returned_count': len(features),
            'geocoded_count': geocoded_count,
        }
    }
    
    logger.info(f"  ✅ Returning {len(features)} companies ({geocoded_count} geocoded)")
    
    return json.dumps(geojson, indent=2)


def get_company_details(jurisdiction_code: str, company_number: str) -> str:
    """
    Get detailed information about a specific company.
    
    Args:
        jurisdiction_code: OpenCorporates jurisdiction code (e.g., 'gb', 'us_de')
        company_number: Company registration number
        
    Returns:
        JSON string with company details or error object
    """
    logger.info(f"🏢 Fetching details for {jurisdiction_code}/{company_number}")
    
    api_token = os.getenv('OPENCORPORATES_API_KEY')
    params = {}
    if api_token:
        params['api_token'] = api_token
    
    try:
        response = requests.get(
            f"{OPENCORPORATES_BASE_URL}/companies/{jurisdiction_code}/{company_number}",
            params=params,
            headers={'User-Agent': 'PuedoCasa-AgenticMaps/1.0'},
            timeout=30,
        )
        
        if response.status_code == 404:
            return json.dumps({
                'error': True,
                'error_type': 'not_found',
                'message': f'Company not found: {jurisdiction_code}/{company_number}',
            })
        
        if response.status_code == 429:
            return json.dumps({
                'error': True,
                'error_type': 'rate_limit',
                'message': '⏳ OpenCorporates API rate limit reached. Please wait before trying again.',
            })
        
        if response.status_code != 200:
            return json.dumps({
                'error': True,
                'error_type': 'api_error',
                'message': f'OpenCorporates API error (HTTP {response.status_code})',
            })
        
        data = response.json()
        company = data.get('results', {}).get('company', {})
        
        return json.dumps(company, indent=2)
        
    except Exception as e:
        return json.dumps({
            'error': True,
            'error_type': 'request_error',
            'message': str(e),
        })


def list_jurisdictions() -> Dict[str, str]:
    """Return common jurisdiction code mappings."""
    return {
        'United States': 'us',
        'United Kingdom': 'gb',
        'Germany': 'de',
        'France': 'fr',
        'Canada': 'ca',
        'Australia': 'au',
        'Kenya': 'ke',
        'Ghana': 'gh',
        'Nigeria': 'ng',
        'South Africa': 'za',
        'India': 'in',
        'Singapore': 'sg',
        'Hong Kong': 'hk',
        'California': 'us_ca',
        'Delaware': 'us_de',
        'New York': 'us_ny',
        'Texas': 'us_tx',
    }


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🏢 Corporate Data Tools - Test Suite")
    print("=" * 70)
    
    # Test jurisdiction resolution
    print("\n--- Testing resolve_jurisdiction ---")
    test_locations = ['Kenya', 'Ghana', 'United Kingdom', 'California', 'Germany', 'Côte d\'Ivoire']
    for loc in test_locations:
        code = resolve_jurisdiction(loc)
        print(f"  '{loc}' → '{code}'")
    
    # Check for API key
    api_key = os.getenv('OPENCORPORATES_API_KEY')
    print(f"\n📋 API Key: {'✅ Set' if api_key else '❌ Not set (limited access)'}")
    
    # Test company search
    print("\n--- Testing search_companies ---")
    
    def handle_result(result, test_name):
        """Helper to handle responses."""
        if not result:
            print("❌ No result")
            return
        
        data = json.loads(result)
        
        if data.get('error'):
            print(f"⚠️  {data.get('message', 'Unknown error')}")
            if 'suggestion' in data:
                print(f"   💡 {data['suggestion']}")
            return
        
        total = data.get('properties', {}).get('total_count', 0)
        returned = data.get('properties', {}).get('returned_count', 0)
        geocoded = data.get('properties', {}).get('geocoded_count', 0)
        
        print(f"✅ Found {total} companies, returned {returned}, geocoded {geocoded}")
        
        for f in data['features'][:3]:
            props = f['properties']
            coords = f['geometry']['coordinates'] if f['geometry'] else None
            coord_str = f"({coords[1]:.2f}, {coords[0]:.2f})" if coords else "(no coords)"
            print(f"   • {props['company_name'][:40]} - {props['status']} {coord_str}")
    
    # Test 1: Cocoa companies in Ghana
    print("\n🍫 Test: Cocoa companies in Ghana")
    result = search_companies("cocoa", location="Ghana", max_results=5, geocode=False)
    handle_result(result, "Ghana Cocoa")
    
    # Test 2: Active tech companies in Kenya
    print("\n🌍 Test: Tech companies in Kenya")
    result = search_companies("technology", location="Kenya", status="Active", max_results=5, geocode=False)
    handle_result(result, "Kenya Tech")
    
    # Test 3: Coffee companies in UK
    print("\n☕ Test: Coffee companies in UK")
    result = search_companies("coffee", location="United Kingdom", max_results=5, geocode=False)
    handle_result(result, "UK Coffee")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)

