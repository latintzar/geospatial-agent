#!/usr/bin/env python3
"""
Test Gemini Structured Output for Cascade Search Schemas
========================================================

Tests that Gemini can output valid JSON matching our cascade search schemas.
"""

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load env
leo_root = Path(__file__).parent.parent
load_dotenv(leo_root / ".env.local")
load_dotenv(Path(__file__).parent / ".env", override=True)

# GEMINI_API_KEY_HELLO is the Google AI Studio key (starts with AIza)
API_KEY = os.getenv("GEMINI_API_KEY_HELLO") or ""
MODEL = "gemini-2.5-flash"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

# ============================================================================
# SCHEMAS FROM CASCADE_SEARCH.md
# ============================================================================

SUMMATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "poi_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "POI types for density scoring"
        },
        "land_use_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Land use types"
        },
        "water_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Water types"
        },
        "include_buildings": {
            "type": "boolean",
            "description": "Include building metrics"
        },
        "road_presence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Road presence types"
        }
    },
    "required": ["poi_features", "land_use_features", "include_buildings"]
}

DRIVING_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have_pois": {
            "type": "array",
            "items": {"type": "string"},
            "description": "POIs that MUST be within driving distance"
        },
        "poi_column_type": {
            "type": "string",
            "enum": ["drive_min", "cycle_min", "score"],
            "description": "Which column suffix to use"
        },
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Transit that MUST be cycleable"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Large green spaces"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Large water features"
        }
    },
    "required": ["must_have_pois", "poi_column_type"]
}

WALKING_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Transit MUST be walkable"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Green space MUST be walkable"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Water MUST be walkable"
        },
        "prefer_poi_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category_name": {"type": "string"},
                    "features": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["category_name", "features"]
            },
            "description": "POI categories where at least ONE must be walkable"
        }
    },
    "required": ["must_have_transit", "prefer_poi_categories"]
}


def call_with_schema(prompt: str, schema: dict, schema_name: str, max_retries: int = 3) -> dict:
    """Call Gemini with structured output schema."""
    
    body = {
        "contents": [{
            "role": "user",
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
    }
    
    print(f"\n{'='*60}")
    print(f"Testing: {schema_name}")
    print(f"{'='*60}")
    print(f"Prompt: {prompt[:100]}...")
    
    for attempt in range(max_retries):
        response = requests.post(
            ENDPOINT,
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=60
        )
        
        if response.status_code == 503:
            wait = 2 ** attempt
            print(f"⏳ Model overloaded, retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        break
    
    if not response.ok:
        print(f"❌ HTTP Error: {response.status_code}")
        print(response.text[:500])
        return {}
    
    data = response.json()
    
    # Extract the text (which should be JSON)
    candidates = data.get("candidates", [])
    if not candidates:
        print("❌ No candidates")
        return {}
    
    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    
    try:
        result = json.loads(text)
        print(f"✅ Valid JSON returned!")
        print(f"Result: {json.dumps(result, indent=2)}")
        return result
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        print(f"Raw text: {text[:500]}")
        return {}


def test_summative():
    """Test Stage 1 & 4: Summative feature extraction."""
    prompt = """
    Extract features for SUMMATIVE SCORING from this query:
    "I want a lively neighborhood with lots of cafes, bars, and restaurants. 
    Near a park would be nice. Good building density."
    
    ONLY include features mentioned or implied by the user.
    For poi_features, use specific types like: cafe, coffee_shop, bar, pub, restaurant, etc.
    For land_use_features, use types like: park, forest, residential, commercial, etc.
    """
    
    result = call_with_schema(prompt, SUMMATIVE_SCHEMA, "SUMMATIVE_SCHEMA")
    
    # Validate
    assert "poi_features" in result, "Missing poi_features"
    assert isinstance(result.get("poi_features"), list), "poi_features not a list"
    assert len(result.get("poi_features", [])) > 0, "poi_features empty"
    print("✅ Validation passed!")
    return result


def test_driving():
    """Test Stage 2: Driving feature extraction."""
    prompt = """
    Extract features for DRIVING DISTANCE FILTERING from this query:
    "I need to be within driving distance of a hospital. 
    Train access would be good for commuting."
    
    ONLY include things the user said they NEED or MUST have.
    - must_have_pois: things like hospital, airport, university, shopping_mall
    - poi_column_type: use "drive_min" for hard cutoff, "score" for softer
    - must_have_transit: things like train, subway, airport
    - must_have_green: large parks like park_2m, forest (only if explicitly needed)
    - must_have_blue: coastline, lake_2m (only if explicitly needed)
    """
    
    result = call_with_schema(prompt, DRIVING_SCHEMA, "DRIVING_SCHEMA")
    
    # Validate
    assert "must_have_pois" in result, "Missing must_have_pois"
    assert "hospital" in result.get("must_have_pois", []), "Should include hospital"
    print("✅ Validation passed!")
    return result


def test_walking():
    """Test Stage 3: Walking feature extraction."""
    prompt = """
    Extract features for WALKING DISTANCE FILTERING from this query:
    "Walkable to the tube, with coffee shops and pubs nearby. Near a decent park."
    
    - must_have_transit: transit that MUST be walkable (subway, train, bus, etc.)
    - must_have_green: green spaces that MUST be walkable (park, park_20k, forest, etc.)
    - must_have_blue: water that MUST be walkable (leave empty if not mentioned)
    - prefer_poi_categories: group similar POIs (e.g., {"category_name": "coffee", "features": ["cafe", "coffee_shop"]})
      This is LENIENT - at least ONE in the category must be walkable
    """
    
    result = call_with_schema(prompt, WALKING_SCHEMA, "WALKING_SCHEMA")
    
    # Validate
    assert "must_have_transit" in result, "Missing must_have_transit"
    transit = result.get("must_have_transit", [])
    assert any(t in transit for t in ["subway", "tube", "underground"]), f"Should include tube/subway, got: {transit}"
    assert "prefer_poi_categories" in result, "Missing prefer_poi_categories"
    assert len(result.get("prefer_poi_categories", [])) > 0, "Should have POI categories"
    print("✅ Validation passed!")
    return result


def test_full_query():
    """Test extracting all three schemas from one complex query."""
    query = """
    I'm looking for a lively neighborhood in London with:
    - Lots of coffee shops, bars, and restaurants (walkable)
    - Near a decent-sized park (walking distance)
    - Tube access (must be walkable)
    - Within driving distance of a hospital (non-negotiable)
    - Good building density
    """
    
    print("\n" + "="*60)
    print("FULL QUERY TEST")
    print("="*60)
    print(f"Query: {query}")
    
    # Test each schema
    summative = call_with_schema(
        f"Extract SUMMATIVE features (what to RANK on - counts & density):\n{query}",
        SUMMATIVE_SCHEMA,
        "Summative (Stage 1 & 4)"
    )
    
    driving = call_with_schema(
        f"Extract DRIVING MUST-HAVES (things that MUST be within driving distance):\n{query}",
        DRIVING_SCHEMA,
        "Driving (Stage 2)"
    )
    
    walking = call_with_schema(
        f"Extract WALKING requirements (transit STRICT, POIs LENIENT):\n{query}",
        WALKING_SCHEMA,
        "Walking (Stage 3)"
    )
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Summative POIs: {summative.get('poi_features', [])}")
    print(f"Driving must-haves: {driving.get('must_have_pois', [])}")
    print(f"Walking transit: {walking.get('must_have_transit', [])}")
    print(f"Walking POI categories: {[c.get('category_name') for c in walking.get('prefer_poi_categories', [])]}")


def test_niche_queries():
    """Test with niche/specific feature requests."""
    
    print("\n" + "="*60)
    print("🎯 NICHE QUERY TESTS")
    print("="*60)
    
    # Test 1: Foodie neighborhood
    foodie_query = """
    I want a foodie paradise:
    - Walkable to sushi restaurants, ramen shops, and izakayas
    - Near a wine bar and cocktail bars
    - Farmers market nearby
    - Independent bookshops would be nice
    - Artisan bakeries and patisseries
    - Specialty coffee roasters, not just chains
    """
    
    result = call_with_schema(
        f"""Extract SUMMATIVE features for density scoring.
        Use SPECIFIC POI types like: sushi_restaurant, ramen_restaurant, izakaya, 
        wine_bar, cocktail_bar, farmers_market, bookstore, bakery, patisserie, 
        coffee_roaster, specialty_coffee, etc.
        Query: {foodie_query}""",
        SUMMATIVE_SCHEMA,
        "🍣 Foodie Summative"
    )
    print(f"Foodie POIs: {result.get('poi_features', [])}")
    
    # Test 2: Active lifestyle
    active_query = """
    Active lifestyle area:
    - Must have a yoga studio walkable
    - Climbing gym or bouldering wall
    - Running trails or large park for jogging (2km+ park)
    - Cycling infrastructure (bike lanes)
    - Swimming pool access
    - Tennis courts would be a plus
    - Near the coast or river for paddleboarding
    """
    
    result = call_with_schema(
        f"""Extract WALKING features.
        Use specific types: yoga_studio, climbing_gym, bouldering, swimming_pool, 
        tennis_court, etc.
        For green use size tiers: park, park_20k, park_2m (for large parks)
        For blue: coastline, river, lake
        Query: {active_query}""",
        WALKING_SCHEMA,
        "🏃 Active Walking"
    )
    print(f"Active transit: {result.get('must_have_transit', [])}")
    print(f"Active green: {result.get('must_have_green', [])}")
    print(f"Active blue: {result.get('must_have_blue', [])}")
    print(f"Active POI categories: {result.get('prefer_poi_categories', [])}")
    
    # Test 3: Family with kids
    family_query = """
    Family-friendly area for kids:
    - Good primary schools and nurseries nearby
    - Playgrounds walkable
    - Pediatrician/children's hospital within driving distance
    - Family restaurants, not just bars
    - Library with children's section
    - Swimming pool for kids lessons
    - Safe streets - prefer pedestrian zones and living streets
    """
    
    result = call_with_schema(
        f"""Extract SUMMATIVE features.
        Use specific types: primary_school, nursery, kindergarten, playground, 
        pediatrician, children_hospital, family_restaurant, library, swimming_pool
        For road_presence use: pedestrian, living_street
        Query: {family_query}""",
        SUMMATIVE_SCHEMA,
        "👨‍👩‍👧 Family Summative"
    )
    print(f"Family POIs: {result.get('poi_features', [])}")
    print(f"Family road presence: {result.get('road_presence', [])}")
    
    # Test 4: Remote worker / Digital nomad
    remote_query = """
    Perfect for remote work:
    - Coworking spaces walkable
    - Fast wifi cafes (specialty coffee shops)
    - Quiet residential area (not commercial/industrial)
    - Good restaurants for lunch breaks
    - Gym nearby for midday workouts
    - Beer garden or rooftop bar for after work
    - Must have fiber broadband (high building density areas)
    """
    
    result = call_with_schema(
        f"""Extract SUMMATIVE features.
        Use specific types: coworking_space, cafe, specialty_coffee, restaurant, 
        gym, beer_garden, rooftop_bar
        For land_use: residential (prefer), avoid commercial, industrial
        include_buildings: true for density
        Query: {remote_query}""",
        SUMMATIVE_SCHEMA,
        "💻 Remote Worker Summative"
    )
    print(f"Remote POIs: {result.get('poi_features', [])}")
    print(f"Remote land use: {result.get('land_use_features', [])}")
    print(f"Include buildings: {result.get('include_buildings')}")
    
    # Test 5: Eco-conscious
    eco_query = """
    Sustainable living:
    - Near a farmers market and organic grocery stores
    - Electric vehicle charging stations
    - Bike share stations nearby
    - Good cycling infrastructure (bike lanes)
    - Near nature reserve or protected area
    - Composting facilities or zero-waste shops
    - Solar panel installers in the area
    """
    
    result = call_with_schema(
        f"""Extract DRIVING features (things within driving/cycling distance).
        Use specific types: farmers_market, organic_grocery, ev_charging_station,
        bike_share, nature_reserve
        For green: nature_reserve, forest, park_2m
        Query: {eco_query}""",
        DRIVING_SCHEMA,
        "🌱 Eco Driving"
    )
    print(f"Eco must-haves: {result.get('must_have_pois', [])}")
    print(f"Eco green: {result.get('must_have_green', [])}")
    
    # Test 6: Nightlife / Party area
    nightlife_query = """
    Best nightlife area:
    - Clubs and nightclubs
    - Late-night bars and cocktail lounges
    - Live music venues
    - Comedy clubs
    - Karaoke bars
    - After-hours food - kebab shops, 24hr diners
    - Easy night bus or Uber access
    """
    
    result = call_with_schema(
        f"""Extract SUMMATIVE features for nightlife density.
        Use specific types: nightclub, club, cocktail_bar, cocktail_lounge, 
        live_music_venue, comedy_club, karaoke, karaoke_bar, kebab_shop, 
        late_night_restaurant, diner
        Query: {nightlife_query}""",
        SUMMATIVE_SCHEMA,
        "🎉 Nightlife Summative"
    )
    print(f"Nightlife POIs: {result.get('poi_features', [])}")
    
    # Test 7: Luxury / High-end
    luxury_query = """
    Upscale area:
    - Michelin star restaurants
    - High-end boutiques and designer stores
    - Art galleries
    - Private members clubs
    - Luxury spa and wellness centers
    - Fine wine merchants
    - Concierge services
    - Near a marina or yacht club
    """
    
    result = call_with_schema(
        f"""Extract SUMMATIVE features.
        Use specific types: fine_dining, michelin_restaurant, luxury_boutique,
        designer_store, art_gallery, private_club, luxury_spa, wellness_center,
        wine_merchant, concierge, marina, yacht_club
        Query: {luxury_query}""",
        SUMMATIVE_SCHEMA,
        "💎 Luxury Summative"
    )
    print(f"Luxury POIs: {result.get('poi_features', [])}")
    
    result = call_with_schema(
        f"""Extract WALKING features for luxury area.
        Blue features like marina, coastline for waterfront
        Query: {luxury_query}""",
        WALKING_SCHEMA,
        "💎 Luxury Walking"
    )
    print(f"Luxury blue: {result.get('must_have_blue', [])}")


if __name__ == "__main__":
    print("Testing Gemini Structured Output for Cascade Search")
    print("="*60)
    
    if not API_KEY:
        print("❌ No API key found!")
        exit(1)
    
    print("API key configured")
    print(f"Model: {MODEL}")
    
    # Run basic tests
    test_summative()
    test_driving()
    test_walking()
    test_full_query()
    
    # Run niche tests
    test_niche_queries()
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED!")
    print("="*60)

