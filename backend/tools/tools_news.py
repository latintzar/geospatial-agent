"""
Visual & Sentiment Intelligence Engine (GDELT 2.0 API Suite)

A powerful news intelligence tool leveraging GDELT's GEO 2.0 and DOC 2.0 APIs
for visual evidence gathering, narrative analysis, and sentiment tracking.

GDELT Coverage:
- 100+ languages, 250,000+ news sources worldwide
- Updates every 15 minutes
- Image recognition tags (flood, fire, military, protest, etc.)
- Tone/sentiment analysis (-10 to +10 scale)

Usage:
    from tools_news import fetch_visual_risk, fetch_news_narrative, fetch_sentiment_trends
    
    # 1. Find PHOTOGRAPHIC PROOF of events
    images = fetch_visual_risk(bbox=(30, -5, 42, 12), risk_type='flood')
    
    # 2. See WHERE events are happening
    hotspots = fetch_news_narrative("food security", mode='point')
    
    # 3. See WHO is controlling the story
    sources = fetch_news_narrative("food security", mode='source')
    
    # 4. Long-term trend analysis (Hedge Fund style)
    trends = fetch_sentiment_trends("cocoa prices")

System Prompt Context:
    'Use fetch_visual_risk to find PHOTOGRAPHIC PROOF of events (Floods, Riots). Seeing is believing.'
    'Use fetch_news_narrative(mode="source") to see which countries are controlling the story.'
    'Use fetch_sentiment_trends for long-term analysis (Hedge Fund style).'

API Reference:
- GEO 2.0: https://blog.gdeltproject.org/gdelt-geo-2-0-api-debuts/
- DOC 2.0: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- GitHub: https://github.com/gdelt/gdelt.github.io
"""

import requests
import json
import re
import logging
from html import unescape
from typing import Optional, List, Dict, Tuple, Union
from urllib.parse import urlencode, quote
from shapely.geometry import Point, box, shape

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

# =============================================================================
# GDELT API CONFIGURATION
# =============================================================================

GDELT_GEO_ENDPOINT = "https://api.gdeltproject.org/api/v2/geo/geo"
GDELT_DOC_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMEOUT = 30  # seconds

# Risk type to keyword queries (GDELT image tags don't always return results)
# Using keyword queries which reliably return geolocated articles with images
RISK_QUERIES = {
    'flood': '(flood OR flooding OR "heavy rain" OR "water damage")',
    'conflict': '(military OR conflict OR war OR soldiers OR "armed forces")',
    'fire': '(fire OR wildfire OR "forest fire" OR flames OR blaze)',
    'protest': '(protest OR demonstration OR rally OR "civil unrest" OR riot)',
    'disaster': '(disaster OR earthquake OR tsunami OR hurricane OR typhoon)',
    'drought': '(drought OR "water shortage" OR "crop failure" OR "dry conditions")',
    'general': '(protest OR disaster OR flood OR fire OR conflict)',
}

# Tone thresholds for color coding
TONE_NEGATIVE_THRESHOLD = -5
TONE_POSITIVE_THRESHOLD = 5


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_tone_color(tone: float) -> str:
    """Convert tone score to hex color for map visualization."""
    if tone < TONE_NEGATIVE_THRESHOLD:
        return '#FF4444'  # Red - negative
    elif tone > TONE_POSITIVE_THRESHOLD:
        return '#44FF44'  # Green - positive
    else:
        return '#FFFF44'  # Yellow - neutral


def _get_tone_label(tone: float) -> str:
    """Convert tone score to human-readable label."""
    if tone < -7:
        return 'Very Negative'
    elif tone < TONE_NEGATIVE_THRESHOLD:
        return 'Negative'
    elif tone > 7:
        return 'Very Positive'
    elif tone > TONE_POSITIVE_THRESHOLD:
        return 'Positive'
    else:
        return 'Neutral'


def _parse_html_articles(html: str) -> List[Dict]:
    """Extract article URLs and titles from GDELT embedded HTML."""
    articles = []
    links = re.findall(r'<a href="([^"]+)"[^>]*title="([^"]+)"', html)
    
    for url, title in links:
        articles.append({
            'url': url,
            'title': unescape(title),
        })
    
    return articles


def _filter_to_bbox(features: List[Dict], bbox: Tuple[float, float, float, float]) -> List[Dict]:
    """Filter GeoJSON features to strictly be inside a bounding box."""
    bbox_polygon = box(*bbox)  # (min_lon, min_lat, max_lon, max_lat)
    filtered = []
    
    for feature in features:
        try:
            geom = feature.get('geometry')
            if not geom:
                continue
            
            point = shape(geom)
            if bbox_polygon.contains(point):
                filtered.append(feature)
                
        except Exception:
            continue
    
    return filtered


def _empty_geojson(query: str, reason: str) -> Dict:
    """Return an empty but valid GeoJSON FeatureCollection."""
    return {
        'type': 'FeatureCollection',
        'metadata': {
            'query': query,
            'reason': reason,
            'source': 'GDELT 2.0',
        },
        'features': [],
    }


# =============================================================================
# FUNCTION 1: VISUAL RISK DETECTION
# =============================================================================

def fetch_visual_risk(
    bbox: Tuple[float, float, float, float],
    risk_type: str = 'general',
    hours: int = 24,
    max_points: int = 250,
) -> Dict:
    """
    Find PHOTOGRAPHIC PROOF of risk events using GDELT's image recognition.
    
    GDELT's Vision API tags images with recognized content (flood, fire, military, etc.)
    This function returns geolocated news with associated images for visual verification.
    
    "Seeing is believing" - Use this to find visual evidence of events.
    
    Args:
        bbox: Bounding box (min_lon, min_lat, max_lon, max_lat)
        risk_type: Type of risk to detect:
                   'flood' - Flooding, water damage
                   'conflict' - Military, police, weapons
                   'fire' - Fires, smoke
                   'protest' - Protests, demonstrations
                   'disaster' - Natural disasters, destruction
                   'drought' - Drought conditions
                   'general' - Mixed risk indicators
        hours: Time window (1-24 hours)
        max_points: Maximum number of points to return
        
    Returns:
        GeoJSON FeatureCollection with image URLs:
        {
            "type": "FeatureCollection",
            "metadata": {...},
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": "Location Name",
                    "image_url": "https://...",
                    "article_count": 15,
                    "articles": [{"url": "...", "title": "..."}],
                    "risk_type": "flood"
                }
            }, ...]
        }
        
    Example:
        >>> # Find flood images in East Africa
        >>> result = fetch_visual_risk(
        ...     bbox=(30, -5, 42, 12),
        ...     risk_type='flood',
        ...     hours=24
        ... )
        >>> for f in result['features'][:3]:
        ...     print(f['properties']['image_url'])
    """
    logger.info("=" * 60)
    logger.info(f"🖼️  Fetching Visual Risk Evidence: {risk_type}")
    logger.info("=" * 60)
    
    # Get keyword query for risk type
    risk_query = RISK_QUERIES.get(risk_type, RISK_QUERIES['general'])
    logger.info(f"  📷 Query: {risk_query[:50]}...")
    logger.info(f"  📍 Bbox: {bbox}")
    
    # Clamp hours
    hours = max(1, min(24, hours))
    timespan_minutes = hours * 60
    
    # Build API parameters - use pointdata mode for geographic detail
    # Note: RISK_QUERIES already include parentheses, don't double-wrap
    params = {
        'query': risk_query,
        'format': 'geojson',
        'mode': 'pointdata',
        'timespan': f'{timespan_minutes}min',
        'maxpoints': max_points,
    }
    
    try:
        url = f"{GDELT_GEO_ENDPOINT}?{urlencode(params)}"
        logger.info(f"  📡 Requesting GDELT GEO 2.0 API...")
        
        response = requests.get(url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
    except Exception as e:
        logger.error(f"  ❌ API request failed: {e}")
        return _empty_geojson(risk_query, str(e))
    
    features = data.get('features', [])
    original_count = len(features)
    logger.info(f"  📥 Received {original_count} locations")
    
    if original_count == 0:
        return _empty_geojson(risk_query, "No visual evidence found")
    
    # Filter strictly to bbox using Shapely
    features = _filter_to_bbox(features, bbox)
    logger.info(f"  🎯 After bbox filter: {len(features)} locations")
    
    # Process and enrich features with image URLs
    processed_features = []
    images_found = 0
    
    for feature in features:
        try:
            props = feature.get('properties', {})
            
            # Extract image URL
            image_url = props.get('shareimage', '')
            if image_url:
                images_found += 1
            
            # Parse articles from HTML
            html = props.get('html', '')
            articles = _parse_html_articles(html)
            
            # Get article count
            article_count = int(props.get('count', len(articles)))
            
            # Build enriched properties
            enriched_props = {
                'name': props.get('name', 'Unknown Location'),
                'image_url': image_url,
                'article_count': article_count,
                'articles': articles[:5],  # Top 5 articles
                'risk_type': risk_type,
                'has_visual_evidence': bool(image_url),
            }
            
            processed_features.append({
                'type': 'Feature',
                'geometry': feature.get('geometry'),
                'properties': enriched_props,
            })
            
        except Exception as e:
            logger.debug(f"  Skipped feature: {e}")
            continue
    
    # Sort by article count (most coverage first)
    processed_features.sort(key=lambda x: x['properties']['article_count'], reverse=True)
    
    logger.info(f"  ✅ Processed {len(processed_features)} locations, {images_found} with images")
    
    return {
        'type': 'FeatureCollection',
        'metadata': {
            'risk_type': risk_type,
            'query': risk_query,
            'bbox': bbox,
            'hours': hours,
            'total_locations': len(processed_features),
            'locations_with_images': images_found,
            'source': 'GDELT GEO 2.0',
        },
        'features': processed_features,
    }


# =============================================================================
# FUNCTION 2: NEWS NARRATIVE ANALYSIS
# =============================================================================

def fetch_news_narrative(
    query: str,
    mode: str = 'point',
    hours: int = 24,
    max_points: int = 250,
) -> Dict:
    """
    Analyze news narrative - WHERE it's happening or WHO is reporting it.
    
    Two modes:
    - 'point': Geographic hotspots - WHERE are events occurring?
    - 'source': Source countries - WHO is controlling the narrative?
    
    The 'source' mode is especially powerful for understanding media bias
    and seeing which countries are amplifying certain stories.
    
    Args:
        query: Search query (supports GDELT syntax)
        mode: Analysis mode:
              'point' - Where is it happening? (Geographic points)
              'source' - Who is reporting it? (Country-level analysis)
        hours: Time window (1-24 hours)
        max_points: Maximum locations to return
        
    Returns:
        GeoJSON FeatureCollection with tone-coded features:
        {
            "type": "FeatureCollection",
            "metadata": {...},
            "features": [{
                "properties": {
                    "name": "Location/Country",
                    "article_count": 150,
                    "tone_color": "#FF4444",  # Red=Negative, Yellow=Neutral, Green=Positive
                    "tone_label": "Negative",
                    "articles": [...]
                }
            }, ...]
        }
        
    Example:
        >>> # Where is food security news happening?
        >>> hotspots = fetch_news_narrative("food security", mode='point')
        
        >>> # Which countries are reporting on climate change?
        >>> sources = fetch_news_narrative("climate change", mode='source')
    """
    logger.info("=" * 60)
    logger.info(f"📰 Fetching News Narrative: '{query}' (mode={mode})")
    logger.info("=" * 60)
    
    # Validate mode
    if mode not in ('point', 'source'):
        mode = 'point'
    
    # Map mode to GDELT API mode
    api_mode = 'pointdata' if mode == 'point' else 'sourcecountry'
    
    # Clamp hours
    hours = max(1, min(24, hours))
    timespan_minutes = hours * 60
    
    # Build API parameters
    params = {
        'query': query,
        'format': 'geojson',
        'mode': api_mode,
        'timespan': f'{timespan_minutes}min',
        'maxpoints': max_points,
    }
    
    logger.info(f"  🔍 Query: {query}")
    logger.info(f"  📊 Mode: {mode} ({api_mode})")
    
    try:
        url = f"{GDELT_GEO_ENDPOINT}?{urlencode(params)}"
        logger.info(f"  📡 Requesting GDELT GEO 2.0 API...")
        
        response = requests.get(url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
    except Exception as e:
        logger.error(f"  ❌ API request failed: {e}")
        return _empty_geojson(query, str(e))
    
    features = data.get('features', [])
    logger.info(f"  📥 Received {len(features)} {'locations' if mode == 'point' else 'source countries'}")
    
    if not features:
        return _empty_geojson(query, "No news found")
    
    # Process features
    processed_features = []
    total_articles = 0
    
    # Also fetch tone data for sentiment analysis
    tone_data = _fetch_tone_for_query(query, hours)
    avg_tone = tone_data.get('avg_tone', 0)
    
    for feature in features:
        try:
            props = feature.get('properties', {})
            
            # Parse articles from HTML first (needed for accurate count)
            html = props.get('html', '')
            articles = _parse_html_articles(html)
            
            # Get article count (field name differs by mode)
            if mode == 'source':
                # Source mode 'value' is a proportion, not count
                # Count articles from HTML instead
                article_count = len(articles)
                name = props.get('name', props.get('name_formal', 'Unknown'))
            else:
                article_count = int(props.get('count', len(articles)))
                name = props.get('name', 'Unknown')
            
            total_articles += article_count
            
            # Calculate tone color based on average
            # Since we don't have per-location tone, use global average
            tone_color = _get_tone_color(avg_tone)
            tone_label = _get_tone_label(avg_tone)
            
            # Determine marker size based on article count
            if article_count >= 100:
                marker_size = 'large'
            elif article_count >= 50:
                marker_size = 'medium'
            else:
                marker_size = 'small'
            
            enriched_props = {
                'name': name,
                'article_count': article_count,
                'tone_color': tone_color,
                'tone_label': tone_label,
                'marker-color': tone_color,
                'marker-size': marker_size,
                'articles': articles[:5],
                'image_url': props.get('shareimage', ''),
            }
            
            # Add country-specific fields for source mode
            if mode == 'source':
                enriched_props['country_code'] = props.get('gnscc', '')
                enriched_props['formal_name'] = props.get('name_formal', '')
            
            processed_features.append({
                'type': 'Feature',
                'geometry': feature.get('geometry'),
                'properties': enriched_props,
            })
            
        except Exception as e:
            logger.debug(f"  Skipped feature: {e}")
            continue
    
    # Sort by article count
    processed_features.sort(key=lambda x: x['properties']['article_count'], reverse=True)
    
    logger.info(f"  ✅ Processed {len(processed_features)} entries, {total_articles} total articles")
    logger.info(f"  📊 Overall sentiment: {tone_label} (avg tone: {avg_tone:.1f})")
    
    return {
        'type': 'FeatureCollection',
        'metadata': {
            'query': query,
            'mode': mode,
            'hours': hours,
            'total_locations': len(processed_features),
            'total_articles': total_articles,
            'avg_tone': round(avg_tone, 2),
            'tone_label': tone_label,
            'sentiment_data': tone_data,
            'source': 'GDELT GEO 2.0',
        },
        'features': processed_features,
    }


def _fetch_tone_for_query(query: str, hours: int) -> Dict:
    """Helper to fetch tone data for a query."""
    try:
        params = {
            'query': query,
            'mode': 'tonechart',
            'format': 'json',
            'timespan': f'{hours}h',
        }
        
        url = f"{GDELT_DOC_ENDPOINT}?{urlencode(params)}"
        response = requests.get(url, timeout=15)
        
        if not response.ok:
            return {'avg_tone': 0, 'distribution': {}}
        
        data = response.json()
        tone_chart = data.get('tonechart', [])
        
        if not tone_chart:
            return {'avg_tone': 0, 'distribution': {}}
        
        # Calculate weighted average tone
        total_count = 0
        weighted_sum = 0
        negative = 0
        neutral = 0
        positive = 0
        
        for bin_data in tone_chart:
            tone_bin = bin_data.get('bin', 0)
            count = bin_data.get('count', 0)
            total_count += count
            weighted_sum += tone_bin * count
            
            if tone_bin < TONE_NEGATIVE_THRESHOLD:
                negative += count
            elif tone_bin > TONE_POSITIVE_THRESHOLD:
                positive += count
            else:
                neutral += count
        
        avg_tone = weighted_sum / total_count if total_count > 0 else 0
        
        return {
            'avg_tone': round(avg_tone, 2),
            'total_articles': total_count,
            'distribution': {
                'negative': negative,
                'neutral': neutral,
                'positive': positive,
            },
            'percentages': {
                'negative': round(negative / total_count * 100, 1) if total_count else 0,
                'neutral': round(neutral / total_count * 100, 1) if total_count else 0,
                'positive': round(positive / total_count * 100, 1) if total_count else 0,
            }
        }
        
    except Exception:
        return {'avg_tone': 0, 'distribution': {}}


# =============================================================================
# FUNCTION 3: SENTIMENT TRENDS (HEDGE FUND STYLE)
# =============================================================================

def fetch_sentiment_trends(
    query: str,
    timespan: str = '3months',
) -> Dict:
    """
    Long-term sentiment trend analysis for strategic intelligence.
    
    Combines GDELT's TimelineVol (volume over time) and ToneChart (emotional
    distribution) to provide hedge-fund-style trend analysis.
    
    Use this to understand:
    - Is coverage rising or falling?
    - Is sentiment becoming more polarized?
    - What's the overall emotional trajectory?
    
    Args:
        query: Search query
        timespan: Time period for analysis:
                  '24h', '7days', '1month', '3months', '1year'
        
    Returns:
        Trend analysis summary:
        {
            "query": "...",
            "trend_summary": "Rising + Increasingly Negative",
            "volume_trend": "Rising",
            "sentiment_trend": "Negative",
            "polarization": "High",
            "volume_data": {...},
            "sentiment_data": {...},
            "key_insights": [...]
        }
        
    Example:
        >>> trends = fetch_sentiment_trends("cocoa prices", timespan='3months')
        >>> print(trends['trend_summary'])
        'Stable volume, Increasingly Negative sentiment'
    """
    logger.info("=" * 60)
    logger.info(f"📈 Fetching Sentiment Trends: '{query}'")
    logger.info("=" * 60)
    
    logger.info(f"  ⏰ Timespan: {timespan}")
    
    # Fetch volume timeline
    volume_data = _fetch_volume_timeline(query, timespan)
    
    # Fetch tone distribution
    tone_data = _fetch_tone_distribution(query, timespan)
    
    # Analyze trends
    volume_trend = _analyze_volume_trend(volume_data)
    sentiment_trend = _analyze_sentiment_trend(tone_data)
    polarization = _analyze_polarization(tone_data)
    
    # Generate summary
    trend_summary = f"{volume_trend['label']} volume, {sentiment_trend['label']} sentiment"
    
    # Generate key insights
    insights = []
    
    if volume_trend['direction'] == 'rising':
        insights.append(f"📈 Coverage is RISING ({volume_trend['change_pct']:.0f}% increase)")
    elif volume_trend['direction'] == 'falling':
        insights.append(f"📉 Coverage is FALLING ({abs(volume_trend['change_pct']):.0f}% decrease)")
    else:
        insights.append("➡️ Coverage volume is STABLE")
    
    if sentiment_trend['avg_tone'] < TONE_NEGATIVE_THRESHOLD:
        insights.append(f"⚠️ NEGATIVE sentiment dominates (avg tone: {sentiment_trend['avg_tone']:.1f})")
    elif sentiment_trend['avg_tone'] > TONE_POSITIVE_THRESHOLD:
        insights.append(f"✅ POSITIVE sentiment dominates (avg tone: {sentiment_trend['avg_tone']:.1f})")
    else:
        insights.append(f"➡️ Sentiment is NEUTRAL (avg tone: {sentiment_trend['avg_tone']:.1f})")
    
    if polarization['level'] == 'high':
        insights.append(f"🔴 HIGH POLARIZATION detected ({polarization['ratio']:.1f}x spread)")
    elif polarization['level'] == 'medium':
        insights.append(f"🟡 MODERATE polarization ({polarization['ratio']:.1f}x spread)")
    
    # Add distribution insight
    dist = tone_data.get('distribution', {})
    if dist:
        dominant = max(dist.items(), key=lambda x: x[1])[0]
        insights.append(f"📊 Dominant sentiment: {dominant.upper()} ({dist[dominant]} articles)")
    
    logger.info(f"  ✅ Trend: {trend_summary}")
    logger.info(f"  📊 Polarization: {polarization['level']}")
    
    return {
        'query': query,
        'timespan': timespan,
        'trend_summary': trend_summary,
        'volume_trend': volume_trend,
        'sentiment_trend': sentiment_trend,
        'polarization': polarization,
        'volume_data': volume_data,
        'sentiment_data': tone_data,
        'key_insights': insights,
        'source': 'GDELT DOC 2.0',
    }


def _fetch_volume_timeline(query: str, timespan: str) -> Dict:
    """Fetch volume over time data."""
    try:
        params = {
            'query': query,
            'mode': 'timelinevol',
            'format': 'json',
            'timespan': timespan,
        }
        
        url = f"{GDELT_DOC_ENDPOINT}?{urlencode(params)}"
        response = requests.get(url, timeout=DEFAULT_TIMEOUT)
        
        if not response.ok:
            return {'timeline': [], 'total': 0}
        
        data = response.json()
        timeline = data.get('timeline', [])
        
        # Calculate total
        total = sum(entry.get('value', 0) for entry in timeline if isinstance(entry, dict))
        
        return {
            'timeline': timeline,
            'total': total,
            'data_points': len(timeline),
        }
        
    except Exception as e:
        logger.debug(f"Volume timeline error: {e}")
        return {'timeline': [], 'total': 0}


def _fetch_tone_distribution(query: str, timespan: str) -> Dict:
    """Fetch tone distribution data."""
    try:
        params = {
            'query': query,
            'mode': 'tonechart',
            'format': 'json',
            'timespan': timespan,
        }
        
        url = f"{GDELT_DOC_ENDPOINT}?{urlencode(params)}"
        response = requests.get(url, timeout=DEFAULT_TIMEOUT)
        
        if not response.ok:
            return {'tone_chart': [], 'avg_tone': 0, 'distribution': {}}
        
        data = response.json()
        tone_chart = data.get('tonechart', [])
        
        # Calculate statistics
        total_count = 0
        weighted_sum = 0
        negative = 0
        neutral = 0
        positive = 0
        
        for bin_data in tone_chart:
            tone_bin = bin_data.get('bin', 0)
            count = bin_data.get('count', 0)
            total_count += count
            weighted_sum += tone_bin * count
            
            if tone_bin < TONE_NEGATIVE_THRESHOLD:
                negative += count
            elif tone_bin > TONE_POSITIVE_THRESHOLD:
                positive += count
            else:
                neutral += count
        
        avg_tone = weighted_sum / total_count if total_count > 0 else 0
        
        return {
            'tone_chart': tone_chart,
            'avg_tone': round(avg_tone, 2),
            'total_articles': total_count,
            'distribution': {
                'negative': negative,
                'neutral': neutral,
                'positive': positive,
            },
            'percentages': {
                'negative': round(negative / total_count * 100, 1) if total_count else 0,
                'neutral': round(neutral / total_count * 100, 1) if total_count else 0,
                'positive': round(positive / total_count * 100, 1) if total_count else 0,
            }
        }
        
    except Exception as e:
        logger.debug(f"Tone distribution error: {e}")
        return {'tone_chart': [], 'avg_tone': 0, 'distribution': {}}


def _analyze_volume_trend(volume_data: Dict) -> Dict:
    """Analyze volume trend direction."""
    timeline = volume_data.get('timeline', [])
    
    if len(timeline) < 2:
        return {'direction': 'stable', 'label': 'Stable', 'change_pct': 0}
    
    # Compare first half to second half
    mid = len(timeline) // 2
    first_half = sum(entry.get('value', 0) for entry in timeline[:mid] if isinstance(entry, dict))
    second_half = sum(entry.get('value', 0) for entry in timeline[mid:] if isinstance(entry, dict))
    
    if first_half == 0:
        return {'direction': 'rising' if second_half > 0 else 'stable', 'label': 'Rising', 'change_pct': 100}
    
    change_pct = ((second_half - first_half) / first_half) * 100
    
    if change_pct > 20:
        return {'direction': 'rising', 'label': 'Rising', 'change_pct': change_pct}
    elif change_pct < -20:
        return {'direction': 'falling', 'label': 'Falling', 'change_pct': change_pct}
    else:
        return {'direction': 'stable', 'label': 'Stable', 'change_pct': change_pct}


def _analyze_sentiment_trend(tone_data: Dict) -> Dict:
    """Analyze overall sentiment."""
    avg_tone = tone_data.get('avg_tone', 0)
    
    if avg_tone < TONE_NEGATIVE_THRESHOLD:
        label = 'Negative'
    elif avg_tone > TONE_POSITIVE_THRESHOLD:
        label = 'Positive'
    else:
        label = 'Neutral'
    
    return {
        'avg_tone': avg_tone,
        'label': label,
        'distribution': tone_data.get('distribution', {}),
    }


def _analyze_polarization(tone_data: Dict) -> Dict:
    """Analyze sentiment polarization."""
    dist = tone_data.get('distribution', {})
    
    negative = dist.get('negative', 0)
    neutral = dist.get('neutral', 0)
    positive = dist.get('positive', 0)
    
    # Calculate polarization ratio (extreme vs center)
    extreme = negative + positive
    center = neutral
    
    if center == 0:
        ratio = extreme if extreme > 0 else 0
    else:
        ratio = extreme / center
    
    if ratio > 2:
        level = 'high'
    elif ratio > 0.5:
        level = 'medium'
    else:
        level = 'low'
    
    return {
        'level': level,
        'ratio': round(ratio, 2),
        'extreme_count': extreme,
        'neutral_count': center,
    }


# =============================================================================
# FUNCTION 4: DEVELOPMENT SIGNALS (GENTRIFICATION/OPPORTUNITY TRACKING)
# =============================================================================

def fetch_development_signals(
    location_name: str,
    max_points: int = 100,
) -> Dict:
    """
    Track future development and investment signals for a location.
    
    Searches for news about new construction, zoning approvals, groundbreakings,
    and development projects. Useful for identifying gentrification, retail
    opportunity, or infrastructure expansion.
    
    This is a "leading indicator" - it shows WHERE development is coming,
    not where it currently exists.
    
    Args:
        location_name: Location to search near (e.g., "Brooklyn", "Lagos", "Mexico City")
        max_points: Maximum number of development signals to return
        
    Returns:
        GeoJSON FeatureCollection of development signals:
        {
            "type": "FeatureCollection",
            "metadata": {...},
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": "Location Name",
                    "label": "Development Signal",
                    "article_url": "https://...",
                    "article_title": "New Mixed-Use Development...",
                    "tone": 3.2,
                    "tone_label": "Positive"
                }
            }, ...]
        }
        
    Example:
        >>> # Find development signals in Brooklyn
        >>> signals = fetch_development_signals("Brooklyn, New York")
        >>> print(f"Found {len(signals['features'])} development signals")
    """
    logger.info("=" * 60)
    logger.info(f"🏗️  Fetching Development Signals: '{location_name}'")
    logger.info("=" * 60)
    
    # Build the development-focused query
    # Search for intent to build, approvals, new construction
    development_keywords = (
        '("groundbreaking" OR "zoning approval" OR "new construction" OR '
        '"mixed-use" OR "opening soon" OR "real estate development" OR '
        '"new building" OR "development project" OR "construction begins" OR '
        '"retail space" OR "commercial development")'
    )
    
    # Combine with location
    query = f'{development_keywords} near:"{location_name}"'
    logger.info(f"  🔍 Query: {query[:80]}...")
    
    # Use 3 months timespan - development news is slow
    timespan = '3months'
    
    # Build API parameters
    params = {
        'query': query,
        'format': 'geojson',
        'mode': 'pointdata',
        'timespan': timespan,
        'maxpoints': max_points,
    }
    
    try:
        url = f"{GDELT_GEO_ENDPOINT}?{urlencode(params)}"
        logger.info(f"  📡 Requesting GDELT GEO 2.0 API (3 month window)...")
        
        response = requests.get(url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
    except Exception as e:
        logger.error(f"  ❌ API request failed: {e}")
        return _empty_geojson(query, str(e))
    
    features = data.get('features', [])
    logger.info(f"  📥 Received {len(features)} potential signals")
    
    if not features:
        return _empty_geojson(query, f"No development signals found near {location_name}")
    
    # Process and filter features
    # Tone filter: avgtonality > -2 (ignore cancelled/failed projects)
    processed_features = []
    filtered_out = 0
    
    for feature in features:
        try:
            props = feature.get('properties', {})
            
            # Parse articles from HTML
            html = props.get('html', '')
            articles = _parse_html_articles(html)
            
            # Get first article URL and title
            article_url = articles[0]['url'] if articles else ''
            article_title = articles[0]['title'] if articles else props.get('name', 'Development Signal')
            
            # Get tone - filter out negative (cancelled/failed projects)
            # GDELT doesn't always include tone in pointdata, so default to 0 (neutral)
            tone = 0  # Default neutral
            
            # Try to extract tone from props if available
            if 'urltone' in props:
                try:
                    tone = float(props['urltone'])
                except (ValueError, TypeError):
                    pass
            
            # Filter: Only keep positive/neutral signals (tone > -2)
            if tone <= -2:
                filtered_out += 1
                continue
            
            # Build enriched properties
            enriched_props = {
                'name': props.get('name', 'Unknown Location'),
                'label': 'Development Signal',
                'article_url': article_url,
                'article_title': article_title,
                'articles': articles[:3],
                'article_count': int(props.get('count', len(articles))),
                'tone': round(tone, 1),
                'tone_label': _get_tone_label(tone),
                'marker-color': '#00AAFF',  # Blue for development
                'marker-symbol': 'building',
            }
            
            processed_features.append({
                'type': 'Feature',
                'geometry': feature.get('geometry'),
                'properties': enriched_props,
            })
            
        except Exception as e:
            logger.debug(f"  Skipped feature: {e}")
            continue
    
    # Sort by article count (most covered developments first)
    processed_features.sort(key=lambda x: x['properties']['article_count'], reverse=True)
    
    logger.info(f"  ✅ Processed {len(processed_features)} development signals")
    logger.info(f"  🚫 Filtered out {filtered_out} negative/cancelled projects")
    
    return {
        'type': 'FeatureCollection',
        'metadata': {
            'location': location_name,
            'query': query,
            'timespan': timespan,
            'total_signals': len(processed_features),
            'filtered_negative': filtered_out,
            'source': 'GDELT GEO 2.0',
            'description': 'Development signals (groundbreakings, zoning approvals, new construction)',
        },
        'features': processed_features,
    }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_risk_types() -> List[Dict]:
    """Get available risk types for visual risk detection."""
    return [
        {'type': 'flood', 'description': 'Flooding, water damage, heavy rain'},
        {'type': 'conflict', 'description': 'Military, police, weapons, soldiers'},
        {'type': 'fire', 'description': 'Fires, smoke, flames'},
        {'type': 'protest', 'description': 'Protests, demonstrations, crowds'},
        {'type': 'disaster', 'description': 'Natural disasters, destruction'},
        {'type': 'drought', 'description': 'Drought conditions, dry landscapes'},
        {'type': 'general', 'description': 'Mixed risk indicators'},
    ]


def get_quick_summary(query: str, hours: int = 24) -> Dict:
    """Get a quick news summary for a query."""
    # Get narrative data
    narrative = fetch_news_narrative(query, mode='source', hours=hours)
    
    # Extract key info
    metadata = narrative.get('metadata', {})
    features = narrative.get('features', [])
    
    top_sources = [
        f['properties']['name'] 
        for f in features[:5]
    ]
    
    return {
        'query': query,
        'hours': hours,
        'total_articles': metadata.get('total_articles', 0),
        'sentiment': metadata.get('tone_label', 'Unknown'),
        'avg_tone': metadata.get('avg_tone', 0),
        'top_sources': top_sources,
        'coverage_countries': len(features),
    }


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🎯 Visual & Sentiment Intelligence Engine - Test Suite")
    print("=" * 70)
    
    print(f"\n📷 Available Risk Types:")
    for rt in get_risk_types():
        print(f"  - {rt['type']:10} : {rt['description']}")
    
    # Test 1: Visual Risk Detection
    print("\n" + "-" * 70)
    print("--- Test 1: Visual Risk Detection (Floods in Southeast Asia) ---")
    print("-" * 70)
    
    # Southeast Asia bbox
    bbox = (95, 5, 110, 25)
    result = fetch_visual_risk(bbox=bbox, risk_type='flood', hours=24)
    
    metadata = result.get('metadata', {})
    features = result.get('features', [])
    
    print(f"\n✅ Found {len(features)} locations")
    print(f"   With images: {metadata.get('locations_with_images', 0)}")
    
    if features:
        print(f"\n   Top locations:")
        for f in features[:3]:
            props = f['properties']
            img_status = "📷" if props.get('has_visual_evidence') else "❌"
            print(f"   {img_status} {props['name']}: {props['article_count']} articles")
            if props.get('image_url'):
                print(f"      Image: {props['image_url'][:60]}...")
    
    # Test 2: News Narrative (Point Mode)
    print("\n" + "-" * 70)
    print("--- Test 2: News Narrative - WHERE is it happening? ---")
    print("-" * 70)
    
    result = fetch_news_narrative("food security", mode='point', hours=24)
    
    metadata = result.get('metadata', {})
    features = result.get('features', [])
    
    print(f"\n✅ Found {len(features)} hotspots")
    print(f"   Total articles: {metadata.get('total_articles', 0)}")
    print(f"   Sentiment: {metadata.get('tone_label', 'N/A')} (tone: {metadata.get('avg_tone', 0)})")
    
    if features:
        print(f"\n   Top hotspots:")
        for f in features[:5]:
            props = f['properties']
            print(f"   {props['name']}: {props['article_count']} articles")
    
    # Test 3: News Narrative (Source Mode)
    print("\n" + "-" * 70)
    print("--- Test 3: News Narrative - WHO is reporting? ---")
    print("-" * 70)
    
    result = fetch_news_narrative("climate change", mode='source', hours=24)
    
    features = result.get('features', [])
    
    print(f"\n✅ {len(features)} countries reporting")
    
    if features:
        print(f"\n   Top source countries:")
        for f in features[:5]:
            props = f['properties']
            print(f"   🌍 {props['name']}: {props['article_count']} articles")
    
    # Test 4: Sentiment Trends
    print("\n" + "-" * 70)
    print("--- Test 4: Sentiment Trends (Hedge Fund Style) ---")
    print("-" * 70)
    
    result = fetch_sentiment_trends("cocoa prices", timespan='3months')
    
    print(f"\n📈 Trend Analysis for 'cocoa prices':")
    print(f"   Summary: {result.get('trend_summary', 'N/A')}")
    print(f"   Polarization: {result.get('polarization', {}).get('level', 'N/A')}")
    
    print(f"\n   Key Insights:")
    for insight in result.get('key_insights', []):
        print(f"   {insight}")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)
