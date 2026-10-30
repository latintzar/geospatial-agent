"""
Google Maps Scraper Tools (ScrapingDog API)

⚠️ PAID API - USE SPARINGLY! ⚠️
================================
This module uses ScrapingDog which costs ~$0.001-0.002 per API call.
Only use when ESSENTIAL to the task - specifically for:
- Reviews/ratings data (not available in free Overture data)
- Competitor analysis requiring review sentiment
- Qualitative "voice of customer" research

For basic place/POI data, PREFER tools_athena (FREE Overture data via Athena) instead!

Cost Estimates:
- search_places(): ~$0.001 (1 API call)
- get_place_details(): ~$0.002 (1-2 API calls if fetching reviews)
- get_brand_high_performers(): ~$0.001-0.005 (1 search call)
- analyze_competitor_weaknesses(): ~$0.01-0.05 (search + multiple review fetches)
- fetch_qualitative_data(): ~$0.01-0.03 (search + multiple review fetches)
- summarize_sentiment(): FREE (local processing, no API call)

ScrapingDog Google Maps API:
- Search: https://api.scrapingdog.com/google_maps
- Reviews: https://api.scrapingdog.com/google_maps_reviews

Usage:
    from tools_scraper import search_places, get_place_details, get_brand_high_performers
    from tools_scraper import analyze_competitor_weaknesses, fetch_qualitative_data
    
    # 1. Search for places in a city
    places = search_places("coffee shop", "Mexico City")
    
    # 2. Get detailed info for a specific place
    details = get_place_details("ChIJ...")
    
    # 3. Find top-performing brand locations
    winners = get_brand_high_performers("Starbucks", "Tokyo")
    
    # 4. Analyze competitor weaknesses for displacement
    vulnerabilities = analyze_competitor_weaknesses("Starbucks", "Barcelona", limit=5)
    
    # 5. Get qualitative data (Voice of the Customer) for any search term
    vibe = fetch_qualitative_data("Parks", "Brooklyn")

System Prompt Context:
    '⚠️ PAID API - Use only when reviews/ratings are essential to the task.'
    'For basic place data, use tools_athena (FREE Overture data) instead.'
    'Use search_places to find actual locations of businesses in any city.'
    'Use get_place_details to get ratings, reviews, phone, hours for a specific place.'
    'Use get_brand_high_performers to find top-performing brand locations (rating > 4.2, reviews > 100).'
    'Use analyze_competitor_weaknesses to find where a competitor is failing, so we can steal their customers.'
    'Use fetch_qualitative_data to get Voice of the Customer for any search term (Parks, Bars, specific businesses) to understand the local vibe.'

API Reference:
- ScrapingDog Google Maps: https://www.scrapingdog.com/google-maps-api
"""

import os
import re
import json
import logging
import requests
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlencode, quote
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# SCRAPINGDOG API CONFIGURATION
# =============================================================================

SCRAPINGDOG_BASE_URL = "https://api.scrapingdog.com"
GOOGLE_MAPS_ENDPOINT = f"{SCRAPINGDOG_BASE_URL}/google_maps"
GOOGLE_MAPS_REVIEWS_ENDPOINT = f"{SCRAPINGDOG_BASE_URL}/google_maps_reviews"

DEFAULT_TIMEOUT = 30  # seconds

# High performer thresholds
HIGH_PERFORMER_MIN_RATING = 4.2
HIGH_PERFORMER_MIN_REVIEWS = 100

# Vacancy detection thresholds
VACANCY_MONTHS_THRESHOLD = 6  # Flag if last review > 6 months ago
WEBSITE_CHECK_TIMEOUT = 5  # seconds

# Competitor weakness analysis
VULNERABILITY_RATING_THRESHOLD = 4.0  # Locations below this are "vulnerable"
NEGATIVE_REVIEW_STARS = [1, 2]  # Reviews to flag as complaints

# Keywords that indicate negative sentiment (case-insensitive)
COMPLAINT_KEYWORDS = [
    'slow', 'rude', 'dirty', 'expensive', 'parking', 'noisy', 'wait',
    'cold', 'stale', 'bad', 'terrible', 'awful', 'worst', 'horrible',
    'overpriced', 'crowded', 'unfriendly', 'disappointing', 'mediocre',
    'poor', 'broken', 'smelly', 'gross', 'tasteless', 'bland', 'wrong',
    'mistake', 'ignored', 'unprofessional', 'long wait', 'never again'
]

# Complaint category mapping
COMPLAINT_CATEGORIES = {
    'Service': [
        'slow', 'rude', 'wait', 'ignored', 'unfriendly', 'unprofessional',
        'long wait', 'mistake', 'wrong order', 'wrong', 'staff', 'service'
    ],
    'Price': [
        'expensive', 'overpriced', 'pricey', 'costly', 'not worth', 'ripoff',
        'price', 'cost', 'money'
    ],
    'Cleanliness': [
        'dirty', 'smelly', 'gross', 'unclean', 'disgusting', 'filthy',
        'messy', 'sticky', 'stained', 'bathroom', 'restroom'
    ],
    'Food/Product Quality': [
        'cold', 'stale', 'tasteless', 'bland', 'undercooked', 'overcooked',
        'raw', 'burnt', 'soggy', 'dry', 'quality', 'taste', 'flavor'
    ],
    'Atmosphere': [
        'noisy', 'crowded', 'loud', 'cramped', 'uncomfortable', 'dark',
        'hot', 'stuffy', 'atmosphere', 'ambiance', 'music'
    ],
    'Location/Access': [
        'parking', 'location', 'far', 'hard to find', 'access', 'stairs',
        'entrance', 'seating', 'space'
    ],
    'General': [
        'bad', 'terrible', 'awful', 'worst', 'horrible', 'disappointing',
        'mediocre', 'poor', 'never again', 'not recommend'
    ]
}

# Sentiment keywords for qualitative analysis (Voice of the Customer)
SENTIMENT_KEYWORDS = {
    # Safety & Security
    'safe': 'positive',
    'secure': 'positive',
    'dangerous': 'negative',
    'unsafe': 'negative',
    'sketchy': 'negative',
    'scary': 'negative',
    
    # Noise & Atmosphere
    'quiet': 'positive',
    'peaceful': 'positive',
    'relaxing': 'positive',
    'calm': 'positive',
    'loud': 'negative',
    'noisy': 'negative',
    'crowded': 'negative',
    'busy': 'neutral',
    
    # Price & Value
    'cheap': 'positive',
    'affordable': 'positive',
    'value': 'positive',
    'worth it': 'positive',
    'expensive': 'negative',
    'overpriced': 'negative',
    'pricey': 'negative',
    'ripoff': 'negative',
    
    # Cleanliness
    'clean': 'positive',
    'spotless': 'positive',
    'dirty': 'negative',
    'filthy': 'negative',
    'gross': 'negative',
    
    # Service & Experience
    'friendly': 'positive',
    'helpful': 'positive',
    'welcoming': 'positive',
    'amazing': 'positive',
    'wonderful': 'positive',
    'great': 'positive',
    'excellent': 'positive',
    'love': 'positive',
    'best': 'positive',
    'perfect': 'positive',
    'rude': 'negative',
    'slow': 'negative',
    'terrible': 'negative',
    'awful': 'negative',
    'worst': 'negative',
    'hate': 'negative',
    'disappointing': 'negative',
    
    # Family & Accessibility
    'family friendly': 'positive',
    'kid friendly': 'positive',
    'accessible': 'positive',
    'wheelchair': 'neutral',
    'stroller': 'neutral',
    'dog friendly': 'positive',
    'pet friendly': 'positive',
}


def _parse_relative_date(relative_date: str) -> Tuple[Optional[datetime], int]:
    """
    Parse a relative date string (e.g., "2 days ago", "3 months ago") into an actual date.
    
    Args:
        relative_date: String like "2 days ago", "a month ago", "a year ago"
        
    Returns:
        Tuple of (parsed_datetime, months_ago)
        Returns (None, -1) if parsing fails
    """
    if not relative_date:
        return None, -1
    
    relative_date = relative_date.lower().strip()
    now = datetime.now()
    
    # Handle "a/an" as 1
    relative_date = re.sub(r'\b(a|an)\b', '1', relative_date)
    
    # Extract number and unit
    match = re.search(r'(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago', relative_date)
    
    if not match:
        # Try to handle edge cases like "yesterday"
        if 'yesterday' in relative_date:
            return now - timedelta(days=1), 0
        elif 'today' in relative_date or 'just now' in relative_date:
            return now, 0
        return None, -1
    
    num = int(match.group(1))
    unit = match.group(2)
    
    # Calculate the date and months ago
    if unit == 'second':
        delta = timedelta(seconds=num)
        months_ago = 0
    elif unit == 'minute':
        delta = timedelta(minutes=num)
        months_ago = 0
    elif unit == 'hour':
        delta = timedelta(hours=num)
        months_ago = 0
    elif unit == 'day':
        delta = timedelta(days=num)
        months_ago = num // 30  # Approximate
    elif unit == 'week':
        delta = timedelta(weeks=num)
        months_ago = (num * 7) // 30  # Approximate
    elif unit == 'month':
        delta = timedelta(days=num * 30)  # Approximate
        months_ago = num
    elif unit == 'year':
        delta = timedelta(days=num * 365)  # Approximate
        months_ago = num * 12
    else:
        return None, -1
    
    return now - delta, months_ago


def _check_website_status(url: str) -> Dict:
    """
    Check if a website URL is reachable and returns status.
    
    Args:
        url: Website URL to check
        
    Returns:
        Dict with:
        - reachable: bool
        - status_code: int or None
        - error: str or None
    """
    if not url:
        return {
            "reachable": None,
            "status_code": None,
            "error": "No website URL provided"
        }
    
    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        response = requests.head(
            url,
            timeout=WEBSITE_CHECK_TIMEOUT,
            allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; PuedoCasa/1.0)'}
        )
        
        # Consider 2xx and 3xx as reachable
        is_reachable = response.status_code < 400
        
        return {
            "reachable": is_reachable,
            "status_code": response.status_code,
            "error": None if is_reachable else f"HTTP {response.status_code}"
        }
        
    except requests.exceptions.Timeout:
        return {
            "reachable": False,
            "status_code": None,
            "error": "Connection timed out"
        }
    except requests.exceptions.ConnectionError:
        return {
            "reachable": False,
            "status_code": None,
            "error": "Connection failed"
        }
    except requests.exceptions.RequestException as e:
        return {
            "reachable": False,
            "status_code": None,
            "error": str(e)[:100]
        }


def _assess_vacancy_probability(
    latest_review_date: Optional[str],
    website_status: Dict,
    status: str,
    reviews_count: int
) -> Dict:
    """
    Assess vacancy probability based on review recency and website status.
    
    Flags as "High Vacancy Probability" if:
    - Last review > 6 months ago, OR
    - Website is unreachable AND last review > 3 months ago
    - Listed status indicates closure
    
    Args:
        latest_review_date: Relative date string of latest review
        website_status: Dict from _check_website_status
        status: Business status from Google Maps
        reviews_count: Total review count
        
    Returns:
        Dict with vacancy assessment:
        - vacancy_flag: "High Vacancy Probability" | "Medium Vacancy Risk" | "Active" | "Unknown"
        - reasons: List of reasons for the flag
        - latest_review_months_ago: int
        - confidence: "high" | "medium" | "low"
    """
    reasons = []
    vacancy_flag = "Active"
    confidence = "low"
    
    # Parse the latest review date
    _, months_ago = _parse_relative_date(latest_review_date or "")
    
    # Check explicit closure status
    status_lower = (status or "").lower()
    if any(word in status_lower for word in ['closed', 'permanently closed', 'temporarily closed']):
        vacancy_flag = "High Vacancy Probability"
        reasons.append(f"Listed as '{status}'")
        confidence = "high"
        return {
            "vacancy_flag": vacancy_flag,
            "reasons": reasons,
            "latest_review_months_ago": months_ago,
            "confidence": confidence
        }
    
    # Check review recency
    if months_ago >= VACANCY_MONTHS_THRESHOLD:
        vacancy_flag = "High Vacancy Probability"
        reasons.append(f"Last review was {months_ago}+ months ago")
        confidence = "high"
    elif months_ago >= 3:
        # Check website status for medium risk
        if website_status.get("reachable") is False:
            vacancy_flag = "High Vacancy Probability"
            reasons.append(f"Last review was {months_ago} months ago")
            reasons.append(f"Website unreachable: {website_status.get('error', 'Unknown error')}")
            confidence = "high"
        else:
            vacancy_flag = "Medium Vacancy Risk"
            reasons.append(f"Last review was {months_ago} months ago")
            confidence = "medium"
    elif months_ago == -1 and reviews_count == 0:
        # No reviews at all
        vacancy_flag = "Medium Vacancy Risk"
        reasons.append("No reviews found")
        confidence = "low"
    
    # Additional website check for active places
    if vacancy_flag == "Active" and website_status.get("reachable") is False:
        # Don't upgrade to high probability just for website, but note it
        if vacancy_flag == "Active":
            vacancy_flag = "Medium Vacancy Risk"
        reasons.append(f"Website unreachable: {website_status.get('error', 'Unknown error')}")
        confidence = "medium" if confidence == "low" else confidence
    
    if not reasons:
        reasons.append("Recent reviews indicate active business")
    
    return {
        "vacancy_flag": vacancy_flag,
        "reasons": reasons,
        "latest_review_months_ago": months_ago,
        "confidence": confidence
    }


def _get_api_key() -> str:
    """
    Get ScrapingDog API key from environment.
    
    Returns:
        API key string
        
    Raises:
        ValueError: If API key is not set
    """
    api_key = os.environ.get("SCRAPINGDOG_API_KEY")
    if not api_key:
        raise ValueError(
            "SCRAPINGDOG_API_KEY environment variable not set. "
            "Add it to your .env.local file."
        )
    return api_key


def _empty_geojson(query: str, reason: str) -> Dict:
    """Return an empty but valid GeoJSON FeatureCollection."""
    return {
        'type': 'FeatureCollection',
        'metadata': {
            'query': query,
            'reason': reason,
            'source': 'ScrapingDog Google Maps',
        },
        'features': [],
    }


# =============================================================================
# FUNCTION 1: SEARCH PLACES
# =============================================================================

def search_places(
    query: str,
    city: str,
    limit: int = 20,
) -> Dict:
    """
    Search for places on Google Maps using ScrapingDog API.
    
    Searches for "{query} in {city}" and returns a list of places with
    basic info including place_id, name, coordinates, rating, and reviews.
    
    Args:
        query: What to search for (e.g., "coffee shop", "Starbucks", "ramen")
        city: City to search in (e.g., "Tokyo", "Mexico City", "Barcelona")
        limit: Maximum number of results (default 20)
        
    Returns:
        Dict with places list:
        {
            "success": True,
            "query": "coffee shop in Tokyo",
            "count": 15,
            "places": [{
                "place_id": "ChIJ...",
                "data_id": "0x...",  # Used for reviews API
                "name": "Blue Bottle Coffee",
                "address": "1-2-3 Shibuya, Tokyo",
                "lat": 35.6612,
                "lon": 139.7031,
                "rating": 4.5,
                "reviews_count": 284,
                "type": "Coffee shop",
                "thumbnail": "https://..."
            }, ...]
        }
        
    Example:
        >>> places = search_places("Starbucks", "Mexico City")
        >>> print(f"Found {places['count']} Starbucks locations")
        >>> for p in places['places'][:3]:
        ...     print(f"  {p['name']}: {p['rating']}⭐ ({p['reviews_count']} reviews)")
    """
    logger.info("=" * 60)
    logger.info(f"🔍 Searching places: '{query}' in '{city}'")
    logger.info("=" * 60)
    
    try:
        api_key = _get_api_key()
    except ValueError as e:
        logger.error(f"  ❌ {e}")
        return {
            "success": False,
            "error": str(e),
            "query": f"{query} in {city}",
            "count": 0,
            "places": []
        }
    
    # Build search query
    search_query = f"{query} in {city}"
    logger.info(f"  📍 Search query: {search_query}")
    
    # Build API parameters
    params = {
        "api_key": api_key,
        "query": search_query,
        "page": 0,
    }
    
    try:
        logger.info(f"  📡 Calling ScrapingDog Google Maps API...")
        
        response = requests.get(
            GOOGLE_MAPS_ENDPOINT,
            params=params,
            timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        
    except requests.exceptions.Timeout:
        logger.error("  ❌ Request timed out")
        return {
            "success": False,
            "error": "Request timed out",
            "query": search_query,
            "count": 0,
            "places": []
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "query": search_query,
            "count": 0,
            "places": []
        }
    except json.JSONDecodeError as e:
        logger.error(f"  ❌ Invalid JSON response: {e}")
        return {
            "success": False,
            "error": "Invalid JSON response from API",
            "query": search_query,
            "count": 0,
            "places": []
        }
    
    # Parse results from local_results
    local_results = data.get("local_results", [])
    logger.info(f"  📥 Received {len(local_results)} results")
    
    if not local_results:
        logger.warning("  ⚠️ No places found")
        return {
            "success": True,
            "query": search_query,
            "count": 0,
            "places": [],
            "message": "No places found for this search"
        }
    
    # Process and structure places
    places = []
    for result in local_results[:limit]:
        try:
            # Extract GPS coordinates
            gps = result.get("gps_coordinates", {})
            lat = gps.get("latitude")
            lon = gps.get("longitude")
            
            # Extract rating and reviews
            rating = result.get("rating")
            reviews_count = result.get("reviews")
            
            # Parse reviews count (can be string like "284 reviews" or int)
            if isinstance(reviews_count, str):
                reviews_count = int(''.join(filter(str.isdigit, reviews_count)) or 0)
            elif reviews_count is None:
                reviews_count = 0
            
            place = {
                "place_id": result.get("place_id", ""),
                "data_id": result.get("data_id", ""),  # Used for reviews API
                "name": result.get("title", "Unknown"),
                "address": result.get("address", ""),
                "lat": lat,
                "lon": lon,
                "rating": float(rating) if rating else None,
                "reviews_count": int(reviews_count) if reviews_count else 0,
                "type": result.get("type", ""),
                "price": result.get("price", ""),
                "thumbnail": result.get("thumbnail", ""),
                "hours": result.get("hours", ""),
                "phone": result.get("phone", ""),
            }
            
            places.append(place)
            
        except Exception as e:
            logger.debug(f"  Skipped result: {e}")
            continue
    
    logger.info(f"  ✅ Processed {len(places)} places")
    
    # Log sample results
    if places:
        logger.info(f"  📍 Sample results:")
        for p in places[:3]:
            rating_str = f"{p['rating']}⭐" if p['rating'] else "No rating"
            logger.info(f"     - {p['name']}: {rating_str} ({p['reviews_count']} reviews)")
    
    return {
        "success": True,
        "query": search_query,
        "count": len(places),
        "places": places,
    }


# =============================================================================
# FUNCTION 2: GET PLACE DETAILS
# =============================================================================

def get_place_details(
    place_id: str,
    include_reviews: bool = True,
    max_reviews: int = 10,
    check_vacancy: bool = True,
) -> Dict:
    """
    Get detailed information for a specific Google Maps place.
    
    Fetches full details including rating, reviews count, category,
    address, phone, operational status, and optionally recent reviews.
    
    Also performs vacancy detection by checking:
    - Latest review date (flags if > 6 months ago)
    - Website status (reachable or not)
    - Listed business status
    
    Args:
        place_id: Google Maps place_id or data_id (from search_places)
        include_reviews: Whether to fetch reviews (default True)
        max_reviews: Maximum reviews to fetch if include_reviews=True
        check_vacancy: Whether to perform vacancy detection (default True)
        
    Returns:
        Dict with place details:
        {
            "success": True,
            "place_id": "ChIJ...",
            "name": "Blue Bottle Coffee",
            "address": "1-2-3 Shibuya, Tokyo",
            "lat": 35.6612,
            "lon": 139.7031,
            "rating": 4.5,
            "reviews_count": 284,
            "type": "Coffee shop",
            "phone": "+81-3-1234-5678",
            "status": "Operational",
            "hours": {...},
            "price_level": "$$",
            "website": "https://...",
            "website_status": {
                "reachable": True,
                "status_code": 200,
                "error": null
            },
            "latest_review_date": "2 days ago",
            "vacancy_assessment": {
                "vacancy_flag": "Active",  # or "High Vacancy Probability" / "Medium Vacancy Risk"
                "reasons": ["Recent reviews indicate active business"],
                "latest_review_months_ago": 0,
                "confidence": "high"
            },
            "reviews": [...]
        }
        
    Example:
        >>> details = get_place_details("ChIJ...")
        >>> print(f"{details['name']}: {details['rating']}⭐")
        >>> print(f"Vacancy: {details['vacancy_assessment']['vacancy_flag']}")
    """
    logger.info("=" * 60)
    logger.info(f"📋 Getting place details: {place_id[:30]}...")
    logger.info("=" * 60)
    
    try:
        api_key = _get_api_key()
    except ValueError as e:
        logger.error(f"  ❌ {e}")
        return {
            "success": False,
            "error": str(e),
            "place_id": place_id,
        }
    
    # First, search for the place to get details
    # ScrapingDog's Google Maps API returns full details in search results
    # We'll use the place_id directly in a search query
    
    params = {
        "api_key": api_key,
        "query": place_id,  # Can search by place_id
    }
    
    try:
        logger.info(f"  📡 Fetching place details...")
        
        response = requests.get(
            GOOGLE_MAPS_ENDPOINT,
            params=params,
            timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "place_id": place_id,
        }
    
    # Get the first (and likely only) result
    local_results = data.get("local_results", [])
    
    if not local_results:
        logger.warning("  ⚠️ Place not found")
        return {
            "success": False,
            "error": "Place not found",
            "place_id": place_id,
        }
    
    result = local_results[0]
    
    # Extract coordinates
    gps = result.get("gps_coordinates", {})
    
    # Parse reviews count
    reviews_count = result.get("reviews", 0)
    if isinstance(reviews_count, str):
        reviews_count = int(''.join(filter(str.isdigit, reviews_count)) or 0)
    
    # Get website URL
    website = result.get("website", "")
    
    # Build details object
    details = {
        "success": True,
        "place_id": result.get("place_id", place_id),
        "data_id": result.get("data_id", ""),
        "name": result.get("title", "Unknown"),
        "address": result.get("address", ""),
        "lat": gps.get("latitude"),
        "lon": gps.get("longitude"),
        "rating": float(result.get("rating")) if result.get("rating") else None,
        "reviews_count": int(reviews_count),
        "type": result.get("type", ""),
        "phone": result.get("phone", ""),
        "status": result.get("status", "Unknown"),
        "hours": result.get("hours", ""),
        "price_level": result.get("price", ""),
        "website": website,
        "thumbnail": result.get("thumbnail", ""),
    }
    
    logger.info(f"  ✅ Found: {details['name']}")
    logger.info(f"     Rating: {details['rating']}⭐ ({details['reviews_count']} reviews)")
    logger.info(f"     Status: {details['status']}")
    
    # Fetch reviews (needed for vacancy detection)
    latest_review_date = None
    if include_reviews and details.get("data_id"):
        logger.info(f"  📝 Fetching reviews...")
        reviews = _fetch_reviews(details["data_id"], api_key, max_reviews)
        details["reviews"] = reviews
        logger.info(f"     Fetched {len(reviews)} reviews")
        
        # Get the latest review date
        if reviews:
            latest_review_date = reviews[0].get("date", "")
            details["latest_review_date"] = latest_review_date
            logger.info(f"     Latest review: {latest_review_date}")
    else:
        details["reviews"] = []
        details["latest_review_date"] = None
    
    # Perform vacancy detection
    if check_vacancy:
        logger.info(f"  🔍 Checking vacancy indicators...")
        
        # Check website status
        website_status = _check_website_status(website)
        details["website_status"] = website_status
        
        if website:
            if website_status["reachable"]:
                logger.info(f"     Website: ✅ Reachable (HTTP {website_status['status_code']})")
            else:
                logger.info(f"     Website: ❌ {website_status['error']}")
        else:
            logger.info(f"     Website: No URL listed")
        
        # Assess vacancy probability
        vacancy_assessment = _assess_vacancy_probability(
            latest_review_date=latest_review_date,
            website_status=website_status,
            status=details["status"],
            reviews_count=details["reviews_count"]
        )
        details["vacancy_assessment"] = vacancy_assessment
        
        # Log vacancy assessment
        vacancy_flag = vacancy_assessment["vacancy_flag"]
        if vacancy_flag == "High Vacancy Probability":
            logger.warning(f"     🚨 VACANCY FLAG: {vacancy_flag}")
            for reason in vacancy_assessment["reasons"]:
                logger.warning(f"        - {reason}")
        elif vacancy_flag == "Medium Vacancy Risk":
            logger.info(f"     ⚠️ VACANCY FLAG: {vacancy_flag}")
            for reason in vacancy_assessment["reasons"]:
                logger.info(f"        - {reason}")
        else:
            logger.info(f"     ✅ VACANCY FLAG: {vacancy_flag}")
    
    return details


def _fetch_reviews(
    data_id: str,
    api_key: str,
    max_reviews: int = 10,
) -> List[Dict]:
    """
    Fetch reviews for a place using its data_id.
    
    Internal helper function that calls the ScrapingDog Reviews API.
    
    Args:
        data_id: The data_id from search results (NOT place_id)
        api_key: ScrapingDog API key
        max_reviews: Maximum reviews to return
        
    Returns:
        List of review dicts
    """
    params = {
        "api_key": api_key,
        "data_id": data_id,
    }
    
    try:
        response = requests.get(
            GOOGLE_MAPS_REVIEWS_ENDPOINT,
            params=params,
            timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        
    except Exception as e:
        logger.debug(f"  Failed to fetch reviews: {e}")
        return []
    
    # Parse reviews from response
    reviews_data = data.get("reviews", [])
    
    reviews = []
    for rev in reviews_data[:max_reviews]:
        try:
            review = {
                "rating": rev.get("rating", 0),
                "text": rev.get("text", "")[:500],  # Truncate long reviews
                "date": rev.get("relative_date", rev.get("date", "")),
                "author": rev.get("author", {}).get("name", "Anonymous"),
            }
            reviews.append(review)
        except Exception:
            continue
    
    return reviews


# =============================================================================
# FUNCTION 3: GET BRAND HIGH PERFORMERS
# =============================================================================

def get_brand_high_performers(
    brand: str,
    city: str,
    min_rating: float = HIGH_PERFORMER_MIN_RATING,
    min_reviews: int = HIGH_PERFORMER_MIN_REVIEWS,
) -> Dict:
    """
    Find top-performing brand locations based on rating and review volume.
    
    Workflow:
    1. Search for the brand in the specified city
    2. Filter results: Keep only stores with rating > min_rating AND reviews > min_reviews
    3. Return GeoJSON of the winners
    
    This identifies "High Engagement" locations that are both popular (many reviews)
    and well-rated, indicating strong performance.
    
    Args:
        brand: Brand name to search (e.g., "Starbucks", "McDonald's", "Zara")
        city: City to search in (e.g., "Tokyo", "Barcelona", "Mexico City")
        min_rating: Minimum rating threshold (default 4.2)
        min_reviews: Minimum reviews threshold (default 100)
        
    Returns:
        GeoJSON FeatureCollection of high performers:
        {
            "type": "FeatureCollection",
            "metadata": {
                "brand": "Starbucks",
                "city": "Tokyo",
                "total_found": 25,
                "high_performers": 8,
                "criteria": {"min_rating": 4.2, "min_reviews": 100}
            },
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [139.7031, 35.6612]},
                "properties": {
                    "name": "Starbucks Shibuya",
                    "address": "1-2-3 Shibuya, Tokyo",
                    "rating": 4.5,
                    "reviews_count": 284,
                    "performance_tier": "High Engagement",
                    "place_id": "ChIJ..."
                }
            }, ...]
        }
        
    Example:
        >>> winners = get_brand_high_performers("Starbucks", "Tokyo")
        >>> print(f"Found {winners['metadata']['high_performers']} high performers")
        >>> for f in winners['features'][:3]:
        ...     p = f['properties']
        ...     print(f"  🏆 {p['name']}: {p['rating']}⭐ ({p['reviews_count']} reviews)")
    """
    logger.info("=" * 60)
    logger.info(f"🏆 Finding high performers: '{brand}' in '{city}'")
    logger.info(f"   Criteria: rating > {min_rating}, reviews > {min_reviews}")
    logger.info("=" * 60)
    
    # Step 1: Search for the brand
    search_result = search_places(brand, city, limit=40)  # Get more results to filter
    
    if not search_result.get("success"):
        return _empty_geojson(
            f"{brand} in {city}",
            search_result.get("error", "Search failed")
        )
    
    places = search_result.get("places", [])
    total_found = len(places)
    
    if not places:
        return _empty_geojson(
            f"{brand} in {city}",
            f"No {brand} locations found in {city}"
        )
    
    logger.info(f"  📍 Total locations found: {total_found}")
    
    # Step 2: Filter for high performers
    high_performers = []
    for place in places:
        rating = place.get("rating")
        reviews = place.get("reviews_count", 0)
        
        # Skip places without rating data
        if rating is None:
            continue
        
        # Apply thresholds
        if rating >= min_rating and reviews >= min_reviews:
            high_performers.append(place)
    
    logger.info(f"  🏆 High performers (rating >= {min_rating}, reviews >= {min_reviews}): {len(high_performers)}")
    
    # Step 3: Convert to GeoJSON
    features = []
    for place in high_performers:
        # Skip places without coordinates
        if place.get("lat") is None or place.get("lon") is None:
            continue
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [place["lon"], place["lat"]]
            },
            "properties": {
                "name": place.get("name", "Unknown"),
                "address": place.get("address", ""),
                "rating": place.get("rating"),
                "reviews_count": place.get("reviews_count", 0),
                "type": place.get("type", ""),
                "phone": place.get("phone", ""),
                "place_id": place.get("place_id", ""),
                "data_id": place.get("data_id", ""),
                "performance_tier": "High Engagement",
                "marker-color": "#FFD700",  # Gold for winners
                "marker-symbol": "star",
            }
        }
        features.append(feature)
    
    # Sort by reviews (most popular first)
    features.sort(key=lambda f: f["properties"]["reviews_count"], reverse=True)
    
    # Log top performers
    if features:
        logger.info(f"  🥇 Top performers:")
        for f in features[:5]:
            p = f["properties"]
            logger.info(f"     {p['name']}: {p['rating']}⭐ ({p['reviews_count']} reviews)")
    
    return {
        "type": "FeatureCollection",
        "metadata": {
            "brand": brand,
            "city": city,
            "query": f"{brand} in {city}",
            "total_found": total_found,
            "high_performers": len(features),
            "criteria": {
                "min_rating": min_rating,
                "min_reviews": min_reviews,
            },
            "source": "ScrapingDog Google Maps",
        },
        "features": features,
    }


# =============================================================================
# FUNCTION 4: COMPETITOR WEAKNESS ANALYSIS (Displacement Strategy)
# =============================================================================

def _categorize_complaint(review_text: str) -> Tuple[str, List[str]]:
    """
    Categorize a complaint review into a category and extract matched keywords.
    
    Args:
        review_text: The review text to analyze
        
    Returns:
        Tuple of (category_name, list of matched keywords)
    """
    text_lower = review_text.lower()
    matched_keywords = []
    category_scores = {cat: 0 for cat in COMPLAINT_CATEGORIES}
    
    # Find all matching keywords and score categories
    for category, keywords in COMPLAINT_CATEGORIES.items():
        for keyword in keywords:
            if keyword in text_lower:
                category_scores[category] += 1
                if keyword not in matched_keywords:
                    matched_keywords.append(keyword)
    
    # Find the category with highest score
    if max(category_scores.values()) > 0:
        best_category = max(category_scores, key=category_scores.get)
    else:
        best_category = "General"
    
    return best_category, matched_keywords


def _calculate_vulnerability_score(
    rating: float,
    negative_reviews: List[Dict],
    total_reviews: int,
    complaint_categories: Dict[str, int]
) -> int:
    """
    Calculate a vulnerability score from 1-10 based on multiple factors.
    
    Scoring:
    - Base score from rating (lower rating = higher score)
    - Bonus for high proportion of negative reviews
    - Bonus for concentrated complaints in one category
    
    Args:
        rating: Average rating (1-5)
        negative_reviews: List of negative review dicts
        total_reviews: Total review count
        complaint_categories: Dict of category -> count
        
    Returns:
        Vulnerability score (1-10, where 10 is most vulnerable)
    """
    score = 0
    
    # Rating component (0-4 points)
    # rating 1.0 = 4 points, rating 4.0 = 0 points
    if rating:
        rating_score = max(0, (4.0 - rating)) * (4 / 3)  # Scale to 0-4
        score += rating_score
    else:
        score += 2  # Unknown rating gets moderate score
    
    # Negative review proportion (0-3 points)
    if total_reviews > 0 and negative_reviews:
        negative_ratio = len(negative_reviews) / min(total_reviews, 20)  # Cap at 20 reviews analyzed
        score += negative_ratio * 3
    
    # Complaint concentration (0-3 points)
    # If complaints are concentrated in one category, it's a systemic issue
    if complaint_categories:
        max_category_count = max(complaint_categories.values())
        total_complaints = sum(complaint_categories.values())
        if total_complaints > 0:
            concentration = max_category_count / total_complaints
            score += concentration * 3
    
    # Clamp to 1-10 range
    return max(1, min(10, round(score)))


def _extract_top_complaint(complaint_categories: Dict[str, int], negative_reviews: List[Dict]) -> str:
    """
    Extract the most common complaint as a human-readable string.
    
    Args:
        complaint_categories: Dict of category -> count
        negative_reviews: List of negative review dicts with 'keywords' field
        
    Returns:
        Human-readable complaint string (e.g., "Slow service", "Overpriced")
    """
    if not complaint_categories:
        return "General dissatisfaction"
    
    # Find top category
    top_category = max(complaint_categories, key=complaint_categories.get)
    
    # Find most common keyword in that category
    keyword_counts = {}
    for review in negative_reviews:
        for kw in review.get("keywords", []):
            # Check if keyword belongs to top category
            if kw in COMPLAINT_CATEGORIES.get(top_category, []):
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
    
    if keyword_counts:
        top_keyword = max(keyword_counts, key=keyword_counts.get)
        # Capitalize and format
        return f"{top_keyword.capitalize()} ({top_category})"
    
    return top_category


def analyze_competitor_weaknesses(
    brand_name: str,
    city: str,
    limit: int = 5,
    max_rating: float = VULNERABILITY_RATING_THRESHOLD,
    reviews_per_location: int = 20,
) -> Dict:
    """
    Analyze competitor weaknesses for displacement opportunities.
    
    Finds vulnerable competitor locations (rating < 4.0) and analyzes their
    negative reviews to identify specific pain points that can be exploited.
    
    Use this to find where a competitor is failing, so you can steal their customers.
    
    Workflow:
    1. Search for {brand_name} locations in {city}
    2. Filter for vulnerable locations (rating < max_rating)
    3. Fetch recent reviews for each vulnerable location
    4. Extract negative reviews (1-2 stars or complaint keywords)
    5. Categorize complaints and calculate vulnerability scores
    6. Return GeoJSON with actionable intelligence
    
    Args:
        brand_name: Competitor brand to analyze (e.g., "Starbucks", "McDonald's")
        city: City to search in (e.g., "Barcelona", "Mexico City")
        limit: Maximum number of vulnerable locations to analyze (default 5)
        max_rating: Rating threshold - locations below this are "vulnerable" (default 4.0)
        reviews_per_location: Number of reviews to analyze per location (default 20)
        
    Returns:
        GeoJSON FeatureCollection of vulnerable locations:
        {
            "type": "FeatureCollection",
            "metadata": {
                "brand": "Starbucks",
                "city": "Barcelona",
                "total_found": 25,
                "vulnerable_count": 5,
                "analysis_summary": {
                    "most_common_complaints": ["Service", "Price"],
                    "avg_vulnerability_score": 7.2,
                    "total_negative_reviews": 45
                }
            },
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": "Starbucks Las Ramblas",
                    "address": "La Rambla 123, Barcelona",
                    "rating": 3.2,
                    "reviews_count": 156,
                    "vulnerability_score": 8,
                    "top_complaint": "Slow service",
                    "complaint_breakdown": {
                        "Service": 12,
                        "Price": 8,
                        "Cleanliness": 3
                    },
                    "sample_complaints": [
                        "Waited 20 minutes for a simple coffee",
                        "Rude staff, never coming back"
                    ],
                    "displacement_opportunity": "High",
                    "marker-color": "#FF4444"
                }
            }, ...]
        }
        
    Example:
        >>> vulnerabilities = analyze_competitor_weaknesses("Starbucks", "Barcelona", limit=5)
        >>> print(f"Found {vulnerabilities['metadata']['vulnerable_count']} weak spots")
        >>> for f in vulnerabilities['features']:
        ...     p = f['properties']
        ...     print(f"  🎯 {p['name']}: Score {p['vulnerability_score']}/10 - {p['top_complaint']}")
    """
    logger.info("=" * 60)
    logger.info(f"🎯 Analyzing competitor weaknesses: '{brand_name}' in '{city}'")
    logger.info(f"   Targeting locations with rating < {max_rating}")
    logger.info("=" * 60)
    
    try:
        api_key = _get_api_key()
    except ValueError as e:
        logger.error(f"  ❌ {e}")
        return _empty_geojson(f"{brand_name} in {city}", str(e))
    
    # Step 1: Search for the brand
    logger.info(f"  📍 Step 1: Searching for {brand_name} locations...")
    search_result = search_places(brand_name, city, limit=40)
    
    if not search_result.get("success"):
        return _empty_geojson(
            f"{brand_name} in {city}",
            search_result.get("error", "Search failed")
        )
    
    places = search_result.get("places", [])
    total_found = len(places)
    
    if not places:
        return _empty_geojson(
            f"{brand_name} in {city}",
            f"No {brand_name} locations found in {city}"
        )
    
    logger.info(f"     Found {total_found} total locations")
    
    # Step 2: Filter for vulnerable locations
    logger.info(f"  🔍 Step 2: Filtering for vulnerable locations (rating < {max_rating})...")
    vulnerable_places = []
    for place in places:
        rating = place.get("rating")
        if rating is not None and rating < max_rating:
            vulnerable_places.append(place)
    
    if not vulnerable_places:
        logger.info(f"     No vulnerable locations found (all have rating >= {max_rating})")
        return {
            "type": "FeatureCollection",
            "metadata": {
                "brand": brand_name,
                "city": city,
                "total_found": total_found,
                "vulnerable_count": 0,
                "message": f"No vulnerable locations found - all {brand_name} locations have rating >= {max_rating}",
                "source": "ScrapingDog Google Maps",
            },
            "features": [],
        }
    
    # Sort by rating (worst first) and limit
    vulnerable_places.sort(key=lambda x: x.get("rating", 5))
    vulnerable_places = vulnerable_places[:limit]
    
    logger.info(f"     Found {len(vulnerable_places)} vulnerable locations")
    
    # Step 3 & 4: Fetch and analyze reviews for each vulnerable location
    logger.info(f"  📝 Step 3: Analyzing reviews for {len(vulnerable_places)} vulnerable locations...")
    
    features = []
    all_category_counts = {cat: 0 for cat in COMPLAINT_CATEGORIES}
    total_negative_reviews = 0
    vulnerability_scores = []
    
    for i, place in enumerate(vulnerable_places):
        place_name = place.get("name", "Unknown")
        data_id = place.get("data_id", "")
        rating = place.get("rating", 0)
        
        logger.info(f"     [{i+1}/{len(vulnerable_places)}] Analyzing: {place_name} ({rating}⭐)")
        
        # Fetch reviews
        if data_id:
            reviews = _fetch_reviews(data_id, api_key, reviews_per_location)
        else:
            reviews = []
        
        # Filter for negative reviews
        negative_reviews = []
        complaint_categories = {cat: 0 for cat in COMPLAINT_CATEGORIES}
        
        for review in reviews:
            review_rating = review.get("rating", 3)
            review_text = review.get("text", "")
            
            # Check if negative by rating
            is_negative_rating = review_rating in NEGATIVE_REVIEW_STARS
            
            # Check if negative by keywords
            text_lower = review_text.lower()
            has_complaint_keyword = any(kw in text_lower for kw in COMPLAINT_KEYWORDS)
            
            if is_negative_rating or has_complaint_keyword:
                # Categorize the complaint
                category, keywords = _categorize_complaint(review_text)
                complaint_categories[category] += 1
                all_category_counts[category] += 1
                
                negative_reviews.append({
                    "rating": review_rating,
                    "text": review_text[:200],  # Truncate for storage
                    "category": category,
                    "keywords": keywords,
                    "date": review.get("date", ""),
                })
        
        total_negative_reviews += len(negative_reviews)
        
        # Filter out zero-count categories
        complaint_categories = {k: v for k, v in complaint_categories.items() if v > 0}
        
        # Calculate vulnerability score
        vulnerability_score = _calculate_vulnerability_score(
            rating=rating,
            negative_reviews=negative_reviews,
            total_reviews=place.get("reviews_count", 0),
            complaint_categories=complaint_categories
        )
        vulnerability_scores.append(vulnerability_score)
        
        # Extract top complaint
        top_complaint = _extract_top_complaint(complaint_categories, negative_reviews)
        
        # Determine displacement opportunity level
        if vulnerability_score >= 8:
            displacement_opportunity = "High"
            marker_color = "#FF0000"  # Red
        elif vulnerability_score >= 5:
            displacement_opportunity = "Medium"
            marker_color = "#FFA500"  # Orange
        else:
            displacement_opportunity = "Low"
            marker_color = "#FFFF00"  # Yellow
        
        # Sample complaints (top 3 most illustrative)
        sample_complaints = [
            r["text"][:100] + "..." if len(r["text"]) > 100 else r["text"]
            for r in negative_reviews[:3]
        ]
        
        logger.info(f"        Vulnerability: {vulnerability_score}/10, Top complaint: {top_complaint}")
        
        # Build feature
        if place.get("lat") is not None and place.get("lon") is not None:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [place["lon"], place["lat"]]
                },
                "properties": {
                    "name": place_name,
                    "address": place.get("address", ""),
                    "rating": rating,
                    "reviews_count": place.get("reviews_count", 0),
                    "vulnerability_score": vulnerability_score,
                    "top_complaint": top_complaint,
                    "complaint_breakdown": complaint_categories,
                    "negative_reviews_analyzed": len(negative_reviews),
                    "sample_complaints": sample_complaints,
                    "displacement_opportunity": displacement_opportunity,
                    "place_id": place.get("place_id", ""),
                    "data_id": data_id,
                    "marker-color": marker_color,
                    "marker-symbol": "cross",
                }
            }
            features.append(feature)
    
    # Sort by vulnerability score (highest first)
    features.sort(key=lambda f: f["properties"]["vulnerability_score"], reverse=True)
    
    # Calculate summary statistics
    all_category_counts = {k: v for k, v in all_category_counts.items() if v > 0}
    most_common_complaints = sorted(all_category_counts.keys(), key=lambda k: all_category_counts[k], reverse=True)[:3]
    avg_vulnerability = sum(vulnerability_scores) / len(vulnerability_scores) if vulnerability_scores else 0
    
    logger.info(f"  ✅ Analysis complete!")
    logger.info(f"     Vulnerable locations: {len(features)}")
    logger.info(f"     Avg vulnerability score: {avg_vulnerability:.1f}/10")
    logger.info(f"     Most common complaints: {most_common_complaints}")
    logger.info(f"     Total negative reviews analyzed: {total_negative_reviews}")
    
    return {
        "type": "FeatureCollection",
        "metadata": {
            "brand": brand_name,
            "city": city,
            "query": f"{brand_name} in {city}",
            "total_found": total_found,
            "vulnerable_count": len(features),
            "criteria": {
                "max_rating": max_rating,
                "reviews_analyzed_per_location": reviews_per_location,
            },
            "analysis_summary": {
                "most_common_complaints": most_common_complaints,
                "all_complaint_counts": all_category_counts,
                "avg_vulnerability_score": round(avg_vulnerability, 1),
                "total_negative_reviews": total_negative_reviews,
            },
            "source": "ScrapingDog Google Maps",
        },
        "features": features,
    }


# =============================================================================
# FUNCTION 5: QUALITATIVE DATA FETCHER (Voice of the Customer)
# =============================================================================

def summarize_sentiment(reviews_list: List[str]) -> Dict:
    """
    Summarize sentiment from a list of review texts using keyword counting.
    
    Counts occurrences of positive, negative, and neutral sentiment keywords
    to provide a quick sentiment overview without requiring an LLM.
    
    Args:
        reviews_list: List of review text strings
        
    Returns:
        Dict with sentiment analysis:
        {
            "total_reviews": 25,
            "keyword_counts": {
                "safe": 5,
                "quiet": 3,
                "expensive": 8,
                ...
            },
            "sentiment_breakdown": {
                "positive": 15,
                "negative": 8,
                "neutral": 2
            },
            "sentiment_score": 0.65,  # -1 to 1 scale
            "top_positive": ["friendly", "clean", "safe"],
            "top_negative": ["expensive", "crowded", "slow"],
            "vibe_summary": "Generally positive with price concerns"
        }
        
    Example:
        >>> reviews = ["Great park, very safe", "Too crowded on weekends", "Love the quiet trails"]
        >>> sentiment = summarize_sentiment(reviews)
        >>> print(f"Sentiment score: {sentiment['sentiment_score']}")
    """
    if not reviews_list:
        return {
            "total_reviews": 0,
            "keyword_counts": {},
            "sentiment_breakdown": {"positive": 0, "negative": 0, "neutral": 0},
            "sentiment_score": 0,
            "top_positive": [],
            "top_negative": [],
            "vibe_summary": "No reviews to analyze"
        }
    
    # Combine all reviews into lowercase text
    all_text = " ".join(reviews_list).lower()
    
    # Count keyword occurrences
    keyword_counts = {}
    sentiment_totals = {"positive": 0, "negative": 0, "neutral": 0}
    
    for keyword, sentiment in SENTIMENT_KEYWORDS.items():
        # Count occurrences (handle multi-word keywords)
        count = all_text.count(keyword.lower())
        if count > 0:
            keyword_counts[keyword] = count
            sentiment_totals[sentiment] += count
    
    # Calculate sentiment score (-1 to 1)
    total_sentiment_words = sentiment_totals["positive"] + sentiment_totals["negative"]
    if total_sentiment_words > 0:
        sentiment_score = (sentiment_totals["positive"] - sentiment_totals["negative"]) / total_sentiment_words
    else:
        sentiment_score = 0
    
    # Get top positive and negative keywords
    positive_keywords = {k: v for k, v in keyword_counts.items() if SENTIMENT_KEYWORDS.get(k) == "positive"}
    negative_keywords = {k: v for k, v in keyword_counts.items() if SENTIMENT_KEYWORDS.get(k) == "negative"}
    
    top_positive = sorted(positive_keywords.keys(), key=lambda k: positive_keywords[k], reverse=True)[:5]
    top_negative = sorted(negative_keywords.keys(), key=lambda k: negative_keywords[k], reverse=True)[:5]
    
    # Generate vibe summary
    if sentiment_score > 0.5:
        vibe = "Very positive"
    elif sentiment_score > 0.2:
        vibe = "Generally positive"
    elif sentiment_score > -0.2:
        vibe = "Mixed"
    elif sentiment_score > -0.5:
        vibe = "Generally negative"
    else:
        vibe = "Very negative"
    
    # Add specific concerns to summary
    concerns = []
    if "expensive" in top_negative or "overpriced" in top_negative or "pricey" in top_negative:
        concerns.append("price concerns")
    if "crowded" in top_negative or "busy" in keyword_counts:
        concerns.append("can be crowded")
    if "dangerous" in top_negative or "unsafe" in top_negative or "sketchy" in top_negative:
        concerns.append("safety concerns")
    if "dirty" in top_negative or "filthy" in top_negative:
        concerns.append("cleanliness issues")
    if "loud" in top_negative or "noisy" in top_negative:
        concerns.append("noise issues")
    
    if concerns:
        vibe_summary = f"{vibe} with {', '.join(concerns[:2])}"
    else:
        vibe_summary = vibe
    
    return {
        "total_reviews": len(reviews_list),
        "keyword_counts": keyword_counts,
        "sentiment_breakdown": sentiment_totals,
        "sentiment_score": round(sentiment_score, 2),
        "top_positive": top_positive,
        "top_negative": top_negative,
        "vibe_summary": vibe_summary
    }


def fetch_qualitative_data(
    query: str,
    location: str,
    limit: int = 5,
    reviews_per_place: int = 10,
    include_sentiment: bool = True,
) -> Dict:
    """
    Get the 'Voice of the Customer' for any search term.
    
    A general-purpose review fetcher that works for any query - specific businesses,
    categories (Parks, Bars, Restaurants), landmarks, or amenities (Subway Stations).
    Use this to understand the local vibe and what people are saying.
    
    Args:
        query: What to search for (e.g., "Parks", "The Ritz", "Subway Station", "Coffee shops")
        location: Location to search in (e.g., "Brooklyn", "Barcelona", "Shibuya Tokyo")
        limit: Number of places to analyze (default 5)
        reviews_per_place: Number of reviews to fetch per place (default 10)
        include_sentiment: Whether to include sentiment analysis (default True)
        
    Returns:
        Dict with qualitative data:
        {
            "success": True,
            "query": "Parks",
            "location": "Brooklyn",
            "places_analyzed": 5,
            "total_reviews_collected": 48,
            "places": [
                {
                    "name": "Prospect Park",
                    "address": "Brooklyn, NY",
                    "rating": 4.7,
                    "reviews_count": 12500,
                    "lat": 40.6602,
                    "lon": -73.9690,
                    "reviews": [
                        "Beautiful park, great for running",
                        "Safe at night near the main paths",
                        "Love the dog-friendly areas",
                        ...
                    ],
                    "local_sentiment": {...}  # Per-place sentiment if include_sentiment=True
                },
                ...
            ],
            "aggregate_sentiment": {
                "sentiment_score": 0.72,
                "vibe_summary": "Very positive",
                "top_positive": ["safe", "beautiful", "clean"],
                "top_negative": ["crowded", "busy"]
            },
            "all_reviews": ["review1", "review2", ...]  # Flat list for LLM processing
        }
        
    Example:
        >>> # Understand the park vibe in Brooklyn
        >>> parks = fetch_qualitative_data("Parks", "Brooklyn", limit=5)
        >>> print(f"Vibe: {parks['aggregate_sentiment']['vibe_summary']}")
        >>> print(f"Top concerns: {parks['aggregate_sentiment']['top_negative']}")
        
        >>> # Research a specific hotel chain
        >>> hotels = fetch_qualitative_data("Marriott", "Manhattan", limit=3)
        
        >>> # Understand subway station quality
        >>> transit = fetch_qualitative_data("Subway Station", "Tokyo", limit=5)
    """
    logger.info("=" * 60)
    logger.info(f"🎤 Fetching qualitative data: '{query}' in '{location}'")
    logger.info(f"   Analyzing top {limit} places, {reviews_per_place} reviews each")
    logger.info("=" * 60)
    
    try:
        api_key = _get_api_key()
    except ValueError as e:
        logger.error(f"  ❌ {e}")
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "location": location,
            "places": [],
            "all_reviews": []
        }
    
    # Step 1: Search for places
    logger.info(f"  📍 Step 1: Searching for '{query}' in '{location}'...")
    search_result = search_places(query, location, limit=limit * 2)  # Get extra in case some have no reviews
    
    if not search_result.get("success"):
        return {
            "success": False,
            "error": search_result.get("error", "Search failed"),
            "query": query,
            "location": location,
            "places": [],
            "all_reviews": []
        }
    
    places = search_result.get("places", [])
    
    if not places:
        return {
            "success": True,
            "query": query,
            "location": location,
            "places_analyzed": 0,
            "total_reviews_collected": 0,
            "places": [],
            "all_reviews": [],
            "message": f"No places found for '{query}' in '{location}'"
        }
    
    logger.info(f"     Found {len(places)} places")
    
    # Step 2: Fetch reviews for each place
    logger.info(f"  📝 Step 2: Fetching reviews for top {limit} places...")
    
    analyzed_places = []
    all_reviews = []
    places_with_reviews = 0
    
    for i, place in enumerate(places):
        if places_with_reviews >= limit:
            break
        
        place_name = place.get("name", "Unknown")
        data_id = place.get("data_id", "")
        
        logger.info(f"     [{i+1}] {place_name}...")
        
        # Fetch reviews
        if data_id:
            reviews = _fetch_reviews(data_id, api_key, reviews_per_place)
        else:
            reviews = []
        
        # Extract review texts
        review_texts = [r.get("text", "") for r in reviews if r.get("text")]
        
        if not review_texts:
            logger.info(f"         No reviews found, skipping")
            continue
        
        places_with_reviews += 1
        all_reviews.extend(review_texts)
        
        # Build place data
        place_data = {
            "name": place_name,
            "address": place.get("address", ""),
            "rating": place.get("rating"),
            "reviews_count": place.get("reviews_count", 0),
            "lat": place.get("lat"),
            "lon": place.get("lon"),
            "type": place.get("type", ""),
            "place_id": place.get("place_id", ""),
            "reviews": review_texts,
        }
        
        # Add per-place sentiment if requested
        if include_sentiment and review_texts:
            place_data["local_sentiment"] = summarize_sentiment(review_texts)
        
        analyzed_places.append(place_data)
        logger.info(f"         Collected {len(review_texts)} reviews")
    
    logger.info(f"  ✅ Collected {len(all_reviews)} total reviews from {len(analyzed_places)} places")
    
    # Step 3: Aggregate sentiment across all reviews
    result = {
        "success": True,
        "query": query,
        "location": location,
        "places_analyzed": len(analyzed_places),
        "total_reviews_collected": len(all_reviews),
        "places": analyzed_places,
        "all_reviews": all_reviews,  # Flat list for LLM processing
    }
    
    if include_sentiment and all_reviews:
        logger.info(f"  📊 Step 3: Analyzing aggregate sentiment...")
        aggregate_sentiment = summarize_sentiment(all_reviews)
        result["aggregate_sentiment"] = aggregate_sentiment
        logger.info(f"     Vibe: {aggregate_sentiment['vibe_summary']}")
        logger.info(f"     Score: {aggregate_sentiment['sentiment_score']}")
        logger.info(f"     Top positive: {aggregate_sentiment['top_positive'][:3]}")
        logger.info(f"     Top negative: {aggregate_sentiment['top_negative'][:3]}")
    
    return result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_place_summary(place_id: str) -> str:
    """
    Get a quick text summary of a place for display.
    
    Args:
        place_id: Google Maps place_id or data_id
        
    Returns:
        Formatted string summary
    """
    details = get_place_details(place_id, include_reviews=False)
    
    if not details.get("success"):
        return f"❌ Could not fetch details: {details.get('error', 'Unknown error')}"
    
    rating_str = f"{details['rating']}⭐" if details.get('rating') else "No rating"
    reviews_str = f"({details.get('reviews_count', 0)} reviews)"
    status = details.get('status', 'Unknown')
    
    return f"""📍 {details['name']}
   {details.get('address', 'No address')}
   ⭐ {rating_str} {reviews_str}
   📞 {details.get('phone', 'No phone')}
   🔄 Status: {status}"""


def places_to_geojson(places: List[Dict]) -> Dict:
    """
    Convert a list of places to GeoJSON FeatureCollection.
    
    Args:
        places: List of place dicts from search_places
        
    Returns:
        GeoJSON FeatureCollection
    """
    features = []
    for place in places:
        if place.get("lat") is None or place.get("lon") is None:
            continue
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [place["lon"], place["lat"]]
            },
            "properties": {
                "name": place.get("name", "Unknown"),
                "address": place.get("address", ""),
                "rating": place.get("rating"),
                "reviews_count": place.get("reviews_count", 0),
                "type": place.get("type", ""),
                "place_id": place.get("place_id", ""),
            }
        }
        features.append(feature)
    
    return {
        "type": "FeatureCollection",
        "features": features,
    }


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🔍 Google Maps Scraper Tools - Test Suite")
    print("=" * 70)
    
    # Check API key
    try:
        api_key = _get_api_key()
        print("\n✅ API key configured")
    except ValueError as e:
        print(f"\n❌ {e}")
        print("Please set SCRAPINGDOG_API_KEY in your environment")
        exit(1)
    
    # Test 1: Search places
    print("\n" + "-" * 70)
    print("--- Test 1: Search Places ---")
    print("-" * 70)
    
    result = search_places("coffee shop", "Barcelona")
    
    print(f"\n✅ Search result:")
    print(f"   Query: {result.get('query')}")
    print(f"   Found: {result.get('count')} places")
    
    if result.get('places'):
        print(f"\n   Sample places:")
        for p in result['places'][:5]:
            rating_str = f"{p['rating']}⭐" if p.get('rating') else "No rating"
            print(f"   - {p['name']}: {rating_str} ({p.get('reviews_count', 0)} reviews)")
    
    # Test 2: Get place details with vacancy detection (if we have results)
    if result.get('places'):
        print("\n" + "-" * 70)
        print("--- Test 2: Get Place Details + Vacancy Detection ---")
        print("-" * 70)
        
        first_place = result['places'][0]
        place_id = first_place.get('place_id') or first_place.get('data_id')
        
        if place_id:
            details = get_place_details(place_id, include_reviews=True, max_reviews=3, check_vacancy=True)
            
            if details.get('success'):
                print(f"\n✅ Place details:")
                print(f"   Name: {details['name']}")
                print(f"   Address: {details.get('address', 'N/A')}")
                print(f"   Rating: {details.get('rating')}⭐ ({details.get('reviews_count', 0)} reviews)")
                print(f"   Status: {details.get('status', 'Unknown')}")
                print(f"   Phone: {details.get('phone', 'N/A')}")
                print(f"   Website: {details.get('website', 'N/A')}")
                
                # Website status
                ws = details.get('website_status', {})
                if ws.get('reachable') is True:
                    print(f"   Website Status: ✅ Reachable (HTTP {ws.get('status_code')})")
                elif ws.get('reachable') is False:
                    print(f"   Website Status: ❌ {ws.get('error', 'Unreachable')}")
                else:
                    print(f"   Website Status: ⚪ No website listed")
                
                # Latest review date
                print(f"   Latest Review: {details.get('latest_review_date', 'N/A')}")
                
                # Vacancy assessment
                va = details.get('vacancy_assessment', {})
                vacancy_flag = va.get('vacancy_flag', 'Unknown')
                if vacancy_flag == "High Vacancy Probability":
                    print(f"\n   🚨 VACANCY FLAG: {vacancy_flag}")
                elif vacancy_flag == "Medium Vacancy Risk":
                    print(f"\n   ⚠️ VACANCY FLAG: {vacancy_flag}")
                else:
                    print(f"\n   ✅ VACANCY FLAG: {vacancy_flag}")
                
                print(f"   Confidence: {va.get('confidence', 'N/A')}")
                print(f"   Reasons:")
                for reason in va.get('reasons', []):
                    print(f"      - {reason}")
                
                if details.get('reviews'):
                    print(f"\n   Recent reviews:")
                    for rev in details['reviews'][:3]:
                        stars = "⭐" * rev.get('rating', 0)
                        text = rev.get('text', '')[:80]
                        print(f"   {stars} \"{text}...\" - {rev.get('date', 'N/A')}")
            else:
                print(f"\n❌ Failed to get details: {details.get('error')}")
    
    # Test 3: High performers
    print("\n" + "-" * 70)
    print("--- Test 3: Brand High Performers ---")
    print("-" * 70)
    
    winners = get_brand_high_performers("Starbucks", "Barcelona", min_rating=4.0, min_reviews=50)
    
    metadata = winners.get('metadata', {})
    features = winners.get('features', [])
    
    print(f"\n✅ High performers search:")
    print(f"   Brand: {metadata.get('brand')}")
    print(f"   City: {metadata.get('city')}")
    print(f"   Total found: {metadata.get('total_found', 0)}")
    print(f"   High performers: {metadata.get('high_performers', 0)}")
    print(f"   Criteria: rating >= {metadata.get('criteria', {}).get('min_rating')}, "
          f"reviews >= {metadata.get('criteria', {}).get('min_reviews')}")
    
    if features:
        print(f"\n   🏆 Top performers:")
        for f in features[:5]:
            p = f['properties']
            print(f"   - {p['name']}: {p['rating']}⭐ ({p['reviews_count']} reviews)")
    
    # Test 4: Competitor weakness analysis
    print("\n" + "-" * 70)
    print("--- Test 4: Competitor Weakness Analysis (Displacement) ---")
    print("-" * 70)
    
    vulnerabilities = analyze_competitor_weaknesses("Starbucks", "Barcelona", limit=3, max_rating=4.0)
    
    metadata = vulnerabilities.get('metadata', {})
    features = vulnerabilities.get('features', [])
    summary = metadata.get('analysis_summary', {})
    
    print(f"\n🎯 Competitor weakness analysis:")
    print(f"   Brand: {metadata.get('brand')}")
    print(f"   City: {metadata.get('city')}")
    print(f"   Total found: {metadata.get('total_found', 0)}")
    print(f"   Vulnerable locations: {metadata.get('vulnerable_count', 0)}")
    
    if summary:
        print(f"\n   📊 Analysis Summary:")
        print(f"   Avg Vulnerability Score: {summary.get('avg_vulnerability_score', 'N/A')}/10")
        print(f"   Total Negative Reviews: {summary.get('total_negative_reviews', 0)}")
        print(f"   Most Common Complaints: {', '.join(summary.get('most_common_complaints', []))}")
        
        all_counts = summary.get('all_complaint_counts', {})
        if all_counts:
            print(f"\n   📋 Complaint Breakdown:")
            for cat, count in sorted(all_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"      - {cat}: {count}")
    
    if features:
        print(f"\n   🎯 Vulnerable Locations (sorted by vulnerability):")
        for f in features:
            p = f['properties']
            print(f"\n   📍 {p['name']}")
            print(f"      Rating: {p['rating']}⭐ | Vulnerability: {p['vulnerability_score']}/10")
            print(f"      Top Complaint: {p['top_complaint']}")
            print(f"      Displacement Opportunity: {p['displacement_opportunity']}")
            if p.get('sample_complaints'):
                print(f"      Sample Reviews:")
                for complaint in p['sample_complaints'][:2]:
                    print(f"         💬 \"{complaint[:60]}...\"")
    
    # Test 5: Sentiment analysis (standalone)
    print("\n" + "-" * 70)
    print("--- Test 5: Sentiment Analysis (summarize_sentiment) ---")
    print("-" * 70)
    
    test_reviews = [
        "Great park, very safe and clean. Love the dog-friendly areas!",
        "Beautiful trails but can get crowded on weekends",
        "Too expensive for parking, but the views are amazing",
        "Quiet and peaceful during weekday mornings",
        "A bit dangerous after dark, stay on main paths",
        "Friendly staff, clean restrooms, perfect for families"
    ]
    
    sentiment = summarize_sentiment(test_reviews)
    
    print(f"\n📊 Sentiment Analysis (from {len(test_reviews)} test reviews):")
    print(f"   Vibe Summary: {sentiment['vibe_summary']}")
    print(f"   Sentiment Score: {sentiment['sentiment_score']} (scale: -1 to 1)")
    print(f"   Breakdown: +{sentiment['sentiment_breakdown']['positive']} / "
          f"-{sentiment['sentiment_breakdown']['negative']} / "
          f"~{sentiment['sentiment_breakdown']['neutral']}")
    print(f"\n   Top Positive Keywords: {', '.join(sentiment['top_positive'][:5])}")
    print(f"   Top Negative Keywords: {', '.join(sentiment['top_negative'][:5])}")
    
    if sentiment['keyword_counts']:
        print(f"\n   All Keywords Found:")
        for kw, count in sorted(sentiment['keyword_counts'].items(), key=lambda x: x[1], reverse=True)[:10]:
            polarity = SENTIMENT_KEYWORDS.get(kw, 'unknown')
            emoji = "✅" if polarity == "positive" else ("❌" if polarity == "negative" else "⚪")
            print(f"      {emoji} {kw}: {count}")
    
    # Test 6: Qualitative data fetcher
    print("\n" + "-" * 70)
    print("--- Test 6: Qualitative Data Fetcher (Voice of the Customer) ---")
    print("-" * 70)
    
    vibe = fetch_qualitative_data("Parks", "Barcelona", limit=3, reviews_per_place=5)
    
    print(f"\n🎤 Voice of the Customer for 'Parks' in 'Barcelona':")
    print(f"   Places analyzed: {vibe.get('places_analyzed', 0)}")
    print(f"   Total reviews: {vibe.get('total_reviews_collected', 0)}")
    
    if vibe.get('aggregate_sentiment'):
        agg = vibe['aggregate_sentiment']
        print(f"\n   📊 Aggregate Sentiment:")
        print(f"   Vibe: {agg['vibe_summary']}")
        print(f"   Score: {agg['sentiment_score']}")
        print(f"   Top Positive: {', '.join(agg['top_positive'][:3])}")
        print(f"   Top Negative: {', '.join(agg['top_negative'][:3])}")
    
    if vibe.get('places'):
        print(f"\n   📍 Places with reviews:")
        for place in vibe['places'][:3]:
            print(f"\n   {place['name']} ({place.get('rating', 'N/A')}⭐)")
            if place.get('local_sentiment'):
                ls = place['local_sentiment']
                print(f"      Local vibe: {ls['vibe_summary']}")
            if place.get('reviews'):
                print(f"      Sample review: \"{place['reviews'][0][:80]}...\"")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)
