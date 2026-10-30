"""
Overture Maps Schema Context
============================

This module contains the official Overture Maps schema definitions extracted from:
- https://docs.overturemaps.org/schema
- https://github.com/OvertureMaps/schema

This is used by the Agent to translate natural language queries into correct SQL.

Reference: https://docs.overturemaps.org/getting-data/athena-aws/
"""

# =============================================================================
# OVERTURE SCHEMA CONTEXT - For Agent System Prompt
# =============================================================================

OVERTURE_SCHEMA_CONTEXT = """
## OVERTURE MAPS SCHEMA REFERENCE (v2025.12)

You are querying the Overture Maps database via AWS Athena.
Table: `overture.release.v2025_12_17_0`
Partitioned by: `theme` and `type`

### CRITICAL QUERY RULES
1. ALWAYS filter by `theme` AND `type` for partition pruning
2. Geometry is BINARY - use `ST_GeomFromBinary(geometry)` to convert
3. BBox filter: `bbox.xmin >= X AND bbox.xmax <= X AND bbox.ymin >= Y AND bbox.ymax <= Y`
4. Names are nested: `names.primary` for main name, `names.common` for translations

---

### THEME: base
Contains foundational map features: land use, water bodies, infrastructure.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `land_use` | Parks, forests, residential areas | Polygon/MultiPolygon | `class`, `subtype`, `surface`, `names.primary` |
| `land` | Continents, islands | Polygon/MultiPolygon | `class`, `subtype` |
| `water` | Rivers, lakes, oceans | Polygon/LineString | `class`, `subtype`, `is_salt`, `is_intermittent` |
| `infrastructure` | Bridges, piers, towers, airports | Point/LineString/Polygon | `class`, `subtype` |

**Land Use Classes**: `park`, `forest`, `residential`, `commercial`, `industrial`, `retail`, 
`cemetery`, `grass`, `meadow`, `farmland`, `orchard`, `vineyard`, `quarry`, `landfill`,
`military`, `recreation_ground`, `sports_centre`, `golf_course`, `stadium`

**Example - Parks over 20,000m² in London:**
```sql
SELECT names.primary, ST_Area(ST_GeomFromBinary(geometry)) * 111319 * 111319 * COS(RADIANS(51.5)) AS area_m2
FROM overture.release.v2025_12_17_0
WHERE theme = 'base' AND type = 'land_use' AND class = 'park'
  AND bbox.xmin >= -0.5 AND bbox.xmax <= 0.3
  AND bbox.ymin >= 51.2 AND bbox.ymax <= 51.7
  AND ST_Area(ST_GeomFromBinary(geometry)) * 111319 * 111319 * COS(RADIANS(51.5)) > 20000
ORDER BY area_m2 DESC
```

---

### THEME: places
Points of Interest (POIs) - restaurants, cafes, shops, stations, etc.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `place` | POI location | Point | `categories.primary`, `categories.alternate`, `confidence`, `addresses`, `phones`, `websites` |

**Categories (examples)**: `restaurant`, `cafe`, `bar`, `hotel`, `hospital`, `school`, `university`,
`bank`, `atm`, `pharmacy`, `supermarket`, `convenience_store`, `gas_station`, `parking`,
`subway_station`, `train_station`, `bus_station`, `airport`, `park`, `museum`, `cinema`, `gym`

**Example - Cafes in London:**
```sql
SELECT names.primary, categories.primary,
       ST_X(ST_GeomFromBinary(geometry)) AS lon,
       ST_Y(ST_GeomFromBinary(geometry)) AS lat
FROM overture.release.v2025_12_17_0
WHERE theme = 'places' AND type = 'place' AND categories.primary = 'cafe'
  AND bbox.xmin >= -0.5 AND bbox.xmax <= 0.3
  AND bbox.ymin >= 51.2 AND bbox.ymax <= 51.7
LIMIT 100
```

---

### THEME: buildings
Building footprints and 3D building parts.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `building` | Building footprint | Polygon | `height`, `num_floors`, `class`, `subtype`, `roof_shape`, `roof_color` |
| `building_part` | 3D building component | Polygon | `height`, `num_floors`, `min_height`, `min_floor` |

**Example - Tall buildings (>50m) in London:**
```sql
SELECT names.primary, height, num_floors
FROM overture.release.v2025_12_17_0
WHERE theme = 'buildings' AND type = 'building' AND height > 50
  AND bbox.xmin >= -0.5 AND bbox.xmax <= 0.3
  AND bbox.ymin >= 51.2 AND bbox.ymax <= 51.7
ORDER BY height DESC
```

---

### THEME: transportation
Roads, railways, paths, and network connectivity.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `segment` | Road/path/rail line | LineString | `class`, `subtype`, `subclass`, `surface`, `names.primary`, `speed_limits`, `access_restrictions` |
| `connector` | Intersection/junction | Point | (topology only) |

**Segment Subtypes**: `road`, `rail`, `water`

**Road Classes (hierarchy)**: `motorway`, `trunk`, `primary`, `secondary`, `tertiary`, 
`residential`, `service`, `living_street`, `pedestrian`, `footway`, `cycleway`, `path`, `track`

**Example - Primary roads starting with 'Si' in London:**
```sql
SELECT names.primary, class, subclass
FROM overture.release.v2025_12_17_0
WHERE theme = 'transportation' AND type = 'segment'
  AND subtype = 'road' AND class IN ('primary', 'secondary')
  AND names.primary LIKE 'Si%'
  AND bbox.xmin >= -0.5 AND bbox.xmax <= 0.3
  AND bbox.ymin >= 51.2 AND bbox.ymax <= 51.7
```

---

### THEME: divisions
Administrative boundaries and populated places.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `division` | Admin area (POINT with population) | Point | `subtype`, `population`, `country`, `names.primary`, `capital_division_ids` |
| `division_area` | Admin boundary (POLYGON) | Polygon/MultiPolygon | `subtype`, `country`, `names.primary` |
| `division_boundary` | Border line | LineString | `subtype` |

**Division Subtypes (hierarchy, most specific first)**:
1. `neighborhood` - Neighborhood
2. `macrohood` - Group of neighborhoods  
3. `locality` - City/Town/Village ← MOST COMMON FOR CITIES
4. `localadmin` - Local administrative unit
5. `county` - County
6. `macrocounty` - Group of counties
7. `region` - State/Province
8. `macroregion` - Group of regions
9. `country` - Country
10. `dependency` - Dependent territory

**IMPORTANT**: To find a city like "London":
- Use `division` (Point) with `population` to identify the famous city (highest population)
- Use `division_area` (Polygon) for the actual boundary
- Filter by `subtype = 'locality'` for cities

**Example - Find London, UK (not London, Texas):**
```sql
-- Step 1: Find the most populous "London" (Point with population)
SELECT names.primary, subtype, population, country
FROM overture.release.v2025_12_17_0
WHERE theme = 'divisions' AND type = 'division'
  AND LOWER(names.primary) = LOWER('London')
  AND subtype IN ('locality', 'localadmin')
ORDER BY population DESC NULLS LAST
LIMIT 1
-- Result: London, GB, population=8908083

-- Step 2: Get the polygon boundary
SELECT names.primary, ST_AsText(ST_GeomFromBinary(geometry)) AS geometry_wkt
FROM overture.release.v2025_12_17_0
WHERE theme = 'divisions' AND type = 'division_area'
  AND LOWER(names.primary) = LOWER('London')
  AND country = 'GB'
```

---

### THEME: addresses
Geocoded address points.

| Type | Description | Geometry | Key Properties |
|------|-------------|----------|----------------|
| `address` | Address point | Point | `country`, `postcode`, `street`, `number`, `unit`, `address_levels`, `postal_city` |

**Example - Addresses on Baker Street:**
```sql
SELECT number, street, postcode
FROM overture.release.v2025_12_17_0
WHERE theme = 'addresses' AND type = 'address'
  AND LOWER(street) LIKE '%baker street%'
  AND bbox.xmin >= -0.5 AND bbox.xmax <= 0.3
  AND bbox.ymin >= 51.2 AND bbox.ymax <= 51.7
```

---

### SPATIAL OPERATIONS IN ATHENA (Presto/Trino)

**Convert geometry:**
```sql
ST_GeomFromBinary(geometry)  -- Binary to Geometry
ST_AsText(geometry)          -- Geometry to WKT
ST_AsBinary(geometry)        -- Geometry to Binary
```

**Extract coordinates:**
```sql
ST_X(ST_GeomFromBinary(geometry))  -- Longitude (for Points)
ST_Y(ST_GeomFromBinary(geometry))  -- Latitude (for Points)
```

**Area calculation (approximate, for lat/lon):**
```sql
-- Area in m² (approximate at given latitude)
ST_Area(ST_GeomFromBinary(geometry)) * 111319 * 111319 * COS(RADIANS(latitude))
```

**Distance calculation:**
```sql
-- Distance in degrees (multiply by ~111319 for meters at equator)
ST_Distance(geom1, geom2)
```

**Spatial predicates:**
```sql
ST_Contains(polygon, point)
ST_Intersects(geom1, geom2)
ST_Within(geom1, geom2)
```

**Proximity query (cafes within ~50m of stations):**
```sql
SELECT c.names.primary AS cafe, s.names.primary AS station,
       ST_Distance(ST_GeomFromBinary(c.geometry), ST_GeomFromBinary(s.geometry)) * 111319 AS distance_m
FROM overture.release.v2025_12_17_0 c
JOIN overture.release.v2025_12_17_0 s 
  ON ST_Distance(ST_GeomFromBinary(c.geometry), ST_GeomFromBinary(s.geometry)) < 0.0005  -- ~50m
WHERE c.theme = 'places' AND c.type = 'place' AND c.categories.primary = 'cafe'
  AND s.theme = 'places' AND s.type = 'place' AND s.categories.primary = 'subway_station'
  AND c.bbox.xmin >= -0.2 AND c.bbox.xmax <= 0.0  -- Central London
  AND c.bbox.ymin >= 51.4 AND c.bbox.ymax <= 51.6
  AND s.bbox.xmin >= -0.2 AND s.bbox.xmax <= 0.0
  AND s.bbox.ymin >= 51.4 AND s.bbox.ymax <= 51.6
```

---

### NAMES STRUCTURE
```
names: {
  primary: "The White House",        -- Main/localized name (required if named)
  common: {                          -- Translations (optional)
    de: "Weißes Haus",
    es: "Casa Blanca",
    fr: "Maison Blanche"
  },
  rules: [                           -- Name variants (optional)
    {variant: "official", value: "..."},
    {variant: "alternate", value: "..."},
    {variant: "short", value: "..."}
  ]
}
```

### BBOX STRUCTURE
```
bbox: {
  xmin: -0.1278,  -- Min longitude
  xmax: -0.1277,  -- Max longitude  
  ymin: 51.5074,  -- Min latitude
  ymax: 51.5075   -- Max latitude
}
```

---

### QUERY PATTERNS SUMMARY

| User Intent | Theme | Type | Key Filter |
|-------------|-------|------|------------|
| Parks (polygons) | base | land_use | `class = 'park'` |
| Parks (POIs) | places | place | `categories.primary = 'park'` |
| Cafes | places | place | `categories.primary = 'cafe'` |
| Restaurants | places | place | `categories.primary = 'restaurant'` |
| Subway stations | places | place | `categories.primary = 'subway_station'` |
| Train stations | places | place | `categories.primary = 'train_station'` |
| Roads | transportation | segment | `subtype = 'road'` |
| Primary roads | transportation | segment | `class = 'primary'` |
| Buildings | buildings | building | - |
| Tall buildings | buildings | building | `height > N` |
| City boundary | divisions | division_area | `subtype = 'locality'` |
| City (by pop) | divisions | division | `subtype = 'locality'` ORDER BY population |
| Country | divisions | division_area | `subtype = 'country'` |
| Addresses | addresses | address | `street LIKE '%...'` |
| Rivers | base | water | `class = 'river'` |
| Lakes | base | water | `class = 'lake'` |
| Forests | base | land_use | `class = 'forest'` |
"""

# =============================================================================
# THEME/TYPE MAPPINGS - Programmatic Access
# =============================================================================

OVERTURE_THEMES = {
    "base": {
        "description": "Foundational map features",
        "types": {
            "land_use": {
                "geometry": "Polygon/MultiPolygon",
                "classes": ["park", "forest", "residential", "commercial", "industrial", 
                           "retail", "cemetery", "grass", "meadow", "farmland", "military",
                           "recreation_ground", "sports_centre", "golf_course", "stadium"],
                "key_properties": ["class", "subtype", "surface", "names.primary"]
            },
            "land": {
                "geometry": "Polygon/MultiPolygon", 
                "classes": ["continent", "island", "islet"],
                "key_properties": ["class", "subtype"]
            },
            "water": {
                "geometry": "Polygon/LineString/MultiPolygon",
                "classes": ["river", "lake", "ocean", "sea", "pond", "reservoir", "stream"],
                "key_properties": ["class", "subtype", "is_salt", "is_intermittent"]
            },
            "infrastructure": {
                "geometry": "Point/LineString/Polygon",
                "classes": ["bridge", "pier", "tower", "airport", "aeroway", "dam"],
                "key_properties": ["class", "subtype"]
            }
        }
    },
    "places": {
        "description": "Points of Interest (POIs)",
        "types": {
            "place": {
                "geometry": "Point",
                "categories": ["restaurant", "cafe", "bar", "hotel", "hospital", "school",
                              "university", "bank", "atm", "pharmacy", "supermarket",
                              "convenience_store", "gas_station", "parking", "subway_station",
                              "train_station", "bus_station", "airport", "park", "museum",
                              "cinema", "gym", "library", "post_office", "police", "fire_station"],
                "key_properties": ["categories.primary", "categories.alternate", "confidence",
                                  "addresses", "phones", "websites", "brand"]
            }
        }
    },
    "buildings": {
        "description": "Building footprints and 3D parts",
        "types": {
            "building": {
                "geometry": "Polygon",
                "key_properties": ["height", "num_floors", "class", "subtype", 
                                  "roof_shape", "roof_color", "facade_color"]
            },
            "building_part": {
                "geometry": "Polygon",
                "key_properties": ["height", "num_floors", "min_height", "min_floor"]
            }
        }
    },
    "transportation": {
        "description": "Roads, railways, and connectivity",
        "types": {
            "segment": {
                "geometry": "LineString",
                "subtypes": ["road", "rail", "water"],
                "road_classes": ["motorway", "trunk", "primary", "secondary", "tertiary",
                                "residential", "service", "living_street", "pedestrian",
                                "footway", "cycleway", "path", "track", "unclassified"],
                "key_properties": ["class", "subtype", "subclass", "surface", "names.primary",
                                  "speed_limits", "access_restrictions", "width_rules"]
            },
            "connector": {
                "geometry": "Point",
                "key_properties": []  # Topology only
            }
        }
    },
    "divisions": {
        "description": "Administrative boundaries",
        "types": {
            "division": {
                "geometry": "Point",
                "subtypes": ["neighborhood", "macrohood", "locality", "localadmin", 
                            "county", "macrocounty", "region", "macroregion", 
                            "country", "dependency"],
                "key_properties": ["subtype", "population", "country", "names.primary",
                                  "capital_division_ids", "hierarchies"]
            },
            "division_area": {
                "geometry": "Polygon/MultiPolygon",
                "subtypes": ["neighborhood", "macrohood", "locality", "localadmin",
                            "county", "macrocounty", "region", "macroregion",
                            "country", "dependency"],
                "key_properties": ["subtype", "country", "names.primary"]
            },
            "division_boundary": {
                "geometry": "LineString",
                "key_properties": ["subtype"]
            }
        }
    },
    "addresses": {
        "description": "Geocoded address points",
        "types": {
            "address": {
                "geometry": "Point",
                "key_properties": ["country", "postcode", "street", "number", 
                                  "unit", "address_levels", "postal_city"]
            }
        }
    }
}

# Subtype hierarchy for divisions (lower = more specific, higher priority)
DIVISION_SUBTYPE_PRIORITY = {
    "neighborhood": 1,
    "macrohood": 2,
    "locality": 3,      # Cities/Towns - MOST COMMON
    "localadmin": 4,
    "borough": 5,
    "county": 6,
    "macrocounty": 7,
    "region": 8,        # States/Provinces
    "macroregion": 9,
    "country": 10,
    "dependency": 11,
}

# Common category mappings for user intent
CATEGORY_ALIASES = {
    # Food & Drink
    "coffee": "cafe",
    "coffee shop": "cafe",
    "restaurant": "restaurant",
    "food": "restaurant",
    "bar": "bar",
    "pub": "bar",
    
    # Transit
    "tube": "subway_station",
    "metro": "subway_station",
    "underground": "subway_station",
    "subway": "subway_station",
    "train": "train_station",
    "railway": "train_station",
    "bus": "bus_station",
    
    # Services
    "hospital": "hospital",
    "clinic": "hospital",
    "pharmacy": "pharmacy",
    "drugstore": "pharmacy",
    "bank": "bank",
    "atm": "atm",
    
    # Shopping
    "supermarket": "supermarket",
    "grocery": "supermarket",
    "shop": "convenience_store",
    "store": "convenience_store",
    
    # Recreation
    "park": "park",
    "gym": "gym",
    "fitness": "gym",
    "cinema": "cinema",
    "movie": "cinema",
    "museum": "museum",
    "library": "library",
}

# Road class hierarchy
ROAD_CLASS_HIERARCHY = {
    "motorway": 1,
    "trunk": 2,
    "primary": 3,
    "secondary": 4,
    "tertiary": 5,
    "residential": 6,
    "service": 7,
    "living_street": 8,
    "pedestrian": 9,
    "footway": 10,
    "cycleway": 11,
    "path": 12,
    "track": 13,
}

# =============================================================================
# COMPLETE OVERTURE SCHEMA CATEGORY TREE
# Source: https://github.com/OvertureMaps/schema (Downloaded 2024-12-21)
# =============================================================================

"""
================================================================================
OVERTURE MAPS COMPLETE CATEGORY TREE - TABLE OF CONTENTS
================================================================================

THEME 1: PLACES (POIs) - 2,118 total categories
├── 1.  EAT_AND_DRINK         (3 L2)    → restaurant, bar, cafe
├── 2.  ACCOMMODATION         (16 L2)   → hotel, hostel, resort...
├── 3.  ACTIVE_LIFE           (4 L2)    → sports_and_fitness, venues...
├── 4.  ARTS_AND_ENTERTAINMENT (52 L2)  → cinema, casino, music_venue...
├── 5.  ATTRACTIONS_AND_ACTIVITIES (68 L2) → museum, park, beach, zoo...
├── 6.  AUTOMOTIVE            (17 L2)   → gas_station, car_dealer...
├── 7.  BEAUTY_AND_SPA        (27 L2)   → hair_salon, massage, nail_salon...
├── 8.  BUSINESS_TO_BUSINESS  (11 L2)   → B2B services...
├── 9.  EDUCATION             (16 L2)   → school, university, tutoring...
├── 10. FINANCIAL_SERVICE     (21 L2)   → bank, atm, insurance...
├── 11. HEALTH_AND_MEDICAL    (89 L2)   → hospital, doctor, pharmacy...
├── 12. HOME_SERVICE          (78 L2)   → plumber, electrician, cleaning...
├── 13. MASS_MEDIA            (6 L2)    → news, print_media...
├── 14. PETS                  (6 L2)    → veterinarian, pet_adoption...
├── 15. PRIVATE_ESTABLISHMENTS (4 L2)   → corporate_office...
├── 16. PROFESSIONAL_SERVICES (155 L2)  → lawyer, architect, IT...
├── 17. PUBLIC_SERVICE_AND_GOVERNMENT (38 L2) → library, post_office, police...
├── 18. REAL_ESTATE           (21 L2)   → apartments, real_estate_agent...
├── 19. RELIGIOUS_ORGANIZATION (11 L2)  → church, mosque, temple...
├── 20. RETAIL                (21 L2)   → pharmacy, shopping, food...
├── 21. STRUCTURE_AND_GEOGRAPHY (17 L2) → bridge, mountain, river...
├── 22. TRAVEL                (17 L2)   → airport, tours, transportation...

THEME 2: BASE
├── 2.1 LAND_USE (118 classes)  → park, forest, residential, commercial...
├── 2.2 WATER (35 classes)      → river, lake, ocean, pond...
├── 2.3 INFRASTRUCTURE (164 classes) → bridge, airport, railway_station...
├── 2.4 LAND (3 classes)        → continent, island, islet

THEME 3: TRANSPORTATION
├── 3.1 SEGMENT (road_classes: 14) → motorway, primary, residential...
├── 3.2 SEGMENT (rail_classes: 12) → rail, subway, tram...
├── 3.3 CONNECTOR (topology only)

THEME 4: BUILDINGS
├── 4.1 BUILDING (footprints with height, floors, class)
├── 4.2 BUILDING_PART (3D components)

THEME 5: DIVISIONS
├── 5.1 DIVISION (10 subtypes) → locality, region, country...
├── 5.2 DIVISION_AREA (polygons)
├── 5.3 DIVISION_BOUNDARY (lines)

THEME 6: ADDRESSES
├── 6.1 ADDRESS (geocoded points)

================================================================================
"""

# -----------------------------------------------------------------------------
# THEME 1: PLACES - Complete POI Category Tree (22 Top-Level + 697 Level-2)
# -----------------------------------------------------------------------------

POI_CATEGORIES = {
    # -------------------------------------------------------------------------
    # 1. EAT_AND_DRINK (3 Level-2 categories, ~200 total with L3+)
    # -------------------------------------------------------------------------
    "eat_and_drink": {
        "description": "Restaurants, bars, cafes, and food/drink establishments",
        "level_2": ["restaurant", "bar", "cafe"],
        "key_subcategories": {
            "restaurant": [
                "afghan_restaurant", "african_restaurant", "american_restaurant", "asian_restaurant",
                "barbecue_restaurant", "breakfast_and_brunch_restaurant", "burger_restaurant",
                "caribbean_restaurant", "chinese_restaurant", "diner", "fast_food_restaurant",
                "french_restaurant", "german_restaurant", "greek_restaurant", "indian_restaurant",
                "italian_restaurant", "japanese_restaurant", "korean_restaurant", "latin_american_restaurant",
                "mediterranean_restaurant", "mexican_restaurant", "middle_eastern_restaurant",
                "pizza_restaurant", "seafood_restaurant", "steakhouse", "sushi_restaurant",
                "thai_restaurant", "vegan_restaurant", "vegetarian_restaurant", "vietnamese_restaurant"
            ],
            "bar": [
                "airport_lounge", "beach_bar", "beer_bar", "beer_garden", "brewery", "champagne_bar",
                "cidery", "cocktail_bar", "dive_bar", "hookah_bar", "hotel_bar", "irish_pub",
                "juice_bar", "karaoke_bar", "lounge", "mezcaleria", "nightclub", "pub", "sake_bar",
                "speakeasy", "sports_bar", "tiki_bar", "whisky_bar", "wine_bar", "distillery"
            ],
            "cafe": [
                "bagel_shop", "bakery", "bubble_tea", "coffee_roaster", "coffee_shop", 
                "dessert_shop", "donut_shop", "gelato_shop", "ice_cream_shop", "internet_cafe",
                "patisserie", "tea_room"
            ]
        }
    },
    
    # -------------------------------------------------------------------------
    # 2. ACCOMMODATION (16 Level-2 categories)
    # -------------------------------------------------------------------------
    "accommodation": {
        "description": "Hotels, hostels, resorts, and other lodging",
        "level_2": [
            "bed_and_breakfast", "cabin", "campground", "cottage", "guest_house",
            "health_retreats", "holiday_rental_home", "hostel", "hotel", "inn",
            "lodge", "motel", "mountain_huts", "resort", "rv_park", "service_apartments"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 3. ACTIVE_LIFE (4 Level-2 categories)
    # -------------------------------------------------------------------------
    "active_life": {
        "description": "Sports, fitness, and recreation",
        "level_2": [
            "sports_and_fitness_instruction", "sports_and_recreation_rental_and_services",
            "sports_and_recreation_venue", "sports_club_and_league"
        ],
        "key_subcategories": {
            "sports_and_recreation_venue": [
                "archery_range", "basketball_court", "batting_cage", "beach_volleyball",
                "bowling_alley", "boxing_gym", "climbing_gym", "cricket_ground", "crossfit",
                "cycling_studio", "dance_studio", "diving_center", "dojo", "driving_range",
                "fencing_center", "fitness_center", "golf_course", "gymnastics_center",
                "hockey_rink", "ice_skating_rink", "kickboxing", "martial_arts", "outdoor_pool",
                "pilates", "pool_hall", "racquetball_court", "rowing_club", "rugby_club",
                "running_track", "sailing_club", "shooting_range", "skating_rink", "ski_lodge",
                "soccer_field", "squash_court", "swimming_pool", "tennis_court", "trampoline_park",
                "volleyball_court", "weight_room", "yoga_studio"
            ]
        }
    },
    
    # -------------------------------------------------------------------------
    # 4. ARTS_AND_ENTERTAINMENT (52 Level-2 categories)
    # -------------------------------------------------------------------------
    "arts_and_entertainment": {
        "description": "Entertainment venues, arts, and cultural spaces",
        "level_2": [
            "adult_entertainment", "arcade", "auditorium", "bar_crawl", "betting_center",
            "bingo_hall", "bookmakers", "cabaret", "carousel", "casino",
            "chamber_of_handicraft", "choir", "cinema", "circus", "club_crawl",
            "comedy_club", "country_club", "country_dance_hall", "dance_club", "dinner_theater",
            "eatertainment", "escape_rooms", "exhibition_and_trade_center", "farm", "festival",
            "glass_blowing", "indoor_playcenter", "internet_cafe", "jazz_and_blues", "karaoke",
            "laser_tag", "makerspace", "marching_band", "music_venue", "musical_band_orchestras_and_symphonies",
            "opera_and_ballet", "paint_and_sip", "paintball", "performing_arts", "planetarium",
            "rodeo", "salsa_club", "social_club", "stadium_arena", "studio_taping",
            "supernatural_reading", "theaters_and_performance_venues", "ticket_sales", "topic_concert_venue",
            "virtual_reality_center", "water_park", "wildlife_sanctuary"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 5. ATTRACTIONS_AND_ACTIVITIES (68 Level-2 categories)
    # -------------------------------------------------------------------------
    "attractions_and_activities": {
        "description": "Tourist attractions, outdoor activities, landmarks",
        "level_2": [
            "amusement_park", "aquarium", "architecture", "art_gallery", "atv_rentals_and_tours",
            "axe_throwing", "backpacking_area", "beach", "beach_combing_area", "boat_rental_and_training",
            "boating_places", "bobsledding_field", "botanical_garden", "bungee_jumping_center", "canyon",
            "castle", "cave", "challenge_courses_center", "cliff_jumping_center", "climbing_service",
            "crater", "cultural_center", "fishing_charter", "flyboarding_rental", "fort",
            "fountain", "go_kart_track", "haunted_house", "high_gliding_center", "horseback_riding_service",
            "hot_air_balloons_tour", "hot_springs", "jet_skis_rental", "kiteboarding_instruction", "lake",
            "landmark_and_historical_building", "lighthouse", "lookout", "marina", "monument",
            "mountain_bike_parks", "museum", "observatory", "paddleboard_rental", "palace",
            "parasailing_ride_service", "park", "plaza", "rafting_kayaking_area", "rock_climbing_spot",
            "ruin", "sailing_area", "sand_dune", "scavenger_hunts_provider", "sculpture_statue",
            "ski_area", "skyline", "sledding_rental", "snorkeling", "snorkeling_equipment_rental",
            "snowboarding_center", "stargazing_area", "street_art", "surfing", "trail",
            "waterfall", "ziplining_center", "zoo"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 6. AUTOMOTIVE (17 Level-2 categories)
    # -------------------------------------------------------------------------
    "automotive": {
        "description": "Vehicle sales, parts, repair, and fuel",
        "level_2": [
            "aircraft_dealer", "aircraft_parts_and_supplies", "aircraft_services_and_repair",
            "auto_company", "automobile_leasing", "automotive_dealer", "automotive_parts_and_accessories",
            "automotive_repair", "automotive_services_and_repair", "boat_dealer", "boat_parts_and_accessories",
            "boat_service_and_repair", "car_buyer", "electric_vehicle_charging_station", "gas_station",
            "motorcycle_manufacturer", "truck_stop"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 7. BEAUTY_AND_SPA (27 Level-2 categories)
    # -------------------------------------------------------------------------
    "beauty_and_spa": {
        "description": "Salons, spas, and personal care",
        "level_2": [
            "acne_treatment", "aromatherapy", "barber", "beauty_salon", "eyebrow_service",
            "eyelash_service", "foot_care", "hair_extensions", "hair_loss_center", "hair_removal",
            "hair_replacement", "hair_salon", "health_spa", "image_consultant", "makeup_artist",
            "massage", "nail_salon", "onsen", "permanent_makeup", "public_bath_houses",
            "skin_care", "spas", "tanning_salon", "tattoo_and_piercing", "teeth_whitening",
            "turkish_baths"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 8. BUSINESS_TO_BUSINESS (11 Level-2 categories)
    # -------------------------------------------------------------------------
    "business_to_business": {
        "description": "B2B services and commercial operations",
        "level_2": [
            "b2b_agriculture_and_food", "b2b_energy_and_mining", "b2b_medical_support_services",
            "b2b_science_and_technology", "business", "business_advertising", "business_equipment_and_supply",
            "business_manufacturing_and_supply", "business_storage_and_transportation",
            "business_to_business_services", "commercial_industrial"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 9. EDUCATION (16 Level-2 categories)
    # -------------------------------------------------------------------------
    "education": {
        "description": "Schools, universities, and educational services",
        "level_2": [
            "adult_education", "board_of_education_offices", "campus_building", "college_counseling",
            "college_university", "educational_camp", "educational_research_institute", "educational_services",
            "private_tutor", "school", "school_district_offices", "specialty_school",
            "student_union", "tasting_classes", "test_preparation", "tutoring_center"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 10. FINANCIAL_SERVICE (21 Level-2 categories)
    # -------------------------------------------------------------------------
    "financial_service": {
        "description": "Banks, ATMs, insurance, and financial advisors",
        "level_2": [
            "accountant", "atms", "bank_credit_union", "brokers", "business_banking_service",
            "business_financing", "check_cashing_payday_loans", "coin_dealers", "collection_agencies",
            "credit_and_debt_counseling", "currency_exchange", "debt_relief_services", "financial_advising",
            "holding_companies", "installment_loans", "insurance_agency", "investing",
            "investment_management_company", "money_transfer_services", "tax_services", "trusts"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 11. HEALTH_AND_MEDICAL (89 Level-2 categories)
    # -------------------------------------------------------------------------
    "health_and_medical": {
        "description": "Hospitals, clinics, doctors, and healthcare",
        "level_2": [
            "abortion_clinic", "abuse_and_addiction_treatment", "acupuncture", "aesthetician",
            "alcohol_and_drug_treatment_center", "alternative_medicine", "ambulance_and_ems_services",
            "animal_assisted_therapy", "assisted_living_facility", "ayurveda", "behavior_analyst",
            "blood_and_plasma_donation_center", "body_contouring", "cancer_treatment_center",
            "cannabis_clinic", "cannabis_collective", "childrens_hospital", "chiropractor",
            "colonics", "community_health_center", "concierge_medicine", "counseling_and_mental_health",
            "cryotherapy", "dental_hygienist", "dentist", "diagnostic_services", "dialysis_clinic",
            "dietitian", "doctor", "doula", "emergency_room", "environmental_medicine",
            "eye_care_clinic", "float_spa", "halfway_house", "halotherapy", "health_and_wellness_club",
            "health_coach", "health_department", "health_insurance_office", "hospice", "hospital",
            "hydrotherapy", "hypnosis_hypnotherapy", "iv_hydration", "lactation_services",
            "laser_eye_surgery_lasik", "lice_treatment", "massage_therapy", "maternity_centers",
            "medical_cannabis_referral", "medical_center", "medical_service_organizations",
            "medical_transportation", "memory_care", "midwife", "nurse_practitioner", "nutritionist",
            "occupational_medicine", "occupational_therapy", "optometrist", "organ_and_tissue_donor_service",
            "orthotics", "oxygen_bar", "paternity_tests_and_services", "personal_care_service",
            "physical_therapy", "placenta_encapsulation_service", "podiatry", "prenatal_perinatal_care",
            "prosthetics", "prosthodontist", "psychomotor_therapist", "public_health_clinic",
            "reflexology", "rehabilitation_center", "reiki", "sauna", "skilled_nursing",
            "sleep_specialist", "speech_therapist", "sperm_clinic", "surgical_center",
            "traditional_chinese_medicine", "ultrasound_imaging_center", "urgent_care_clinic",
            "weight_loss_center", "wellness_program", "womens_health_clinic"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 12. HOME_SERVICE (78 Level-2 categories)
    # -------------------------------------------------------------------------
    "home_service": {
        "description": "Home repair, maintenance, and improvement services",
        "level_2": [
            "artificial_turf", "bathroom_remodeling", "bathtub_and_sink_repairs", "cabinet_sales_service",
            "carpenter", "carpet_cleaning", "carpet_installation", "ceiling_and_roofing_repair_and_service",
            "childproofing", "chimney_service", "closet_remodeling", "contractor",
            "countertop_installation", "damage_restoration", "deck_and_railing_sales_service",
            "demolition_service", "door_sales_service", "drywall_services", "electrician",
            "excavation_service", "exterior_design", "fence_and_gate_sales_service", "fire_protection_service",
            "fireplace_service", "firewood", "foundation_repair", "furniture_assembly",
            "garage_door_service", "glass_and_mirror_sales_service", "grout_service", "gutter_service",
            "handyman", "holiday_decorating", "home_automation", "home_cleaning", "home_energy_auditor",
            "home_inspector", "home_network_installation", "home_security", "home_window_tinting",
            "house_sitting", "hvac_services", "insulation_installation", "interior_design",
            "irrigation", "key_and_locksmith", "kitchen_remodeling", "landscaping",
            "lighting_fixtures_and_equipment", "masonry_concrete", "mobile_home_repair", "movers",
            "packing_services", "painting", "patio_covers", "plasterer", "plumbing",
            "pool_and_hot_tub_services", "pool_cleaning", "pressure_washing", "refinishing_services",
            "security_systems", "shades_and_blinds", "shutters", "siding", "solar_installation",
            "solar_panel_cleaning", "structural_engineer", "stucco_services", "television_service_providers",
            "tiling", "wallpaper_installers", "washer_and_dryer_repair_service", "water_heater_installation_repair",
            "water_purification_services", "waterproofing", "window_washing", "windows_installation"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 13. MASS_MEDIA (6 Level-2 categories)
    # -------------------------------------------------------------------------
    "mass_media": {
        "description": "News, media, and publications",
        "level_2": [
            "media_critic", "media_news_company", "media_news_website", "media_restoration_service",
            "print_media", "theatrical_productions"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 14. PETS (6 Level-2 categories)
    # -------------------------------------------------------------------------
    "pets": {
        "description": "Pet care, veterinary, and animal services",
        "level_2": [
            "animal_rescue_service", "animal_shelter", "horse_boarding", "pet_adoption",
            "pet_services", "veterinarian"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 15. PRIVATE_ESTABLISHMENTS_AND_CORPORATES (4 Level-2 categories)
    # -------------------------------------------------------------------------
    "private_establishments_and_corporates": {
        "description": "Corporate offices and private businesses",
        "level_2": [
            "corporate_entertainment_services", "corporate_gift_supplier", "corporate_office",
            "private_equity_firm"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 16. PROFESSIONAL_SERVICES (155 Level-2 categories)
    # -------------------------------------------------------------------------
    "professional_services": {
        "description": "Professional, technical, and business services",
        "level_2": [
            "3d_printing_service", "acoustical_consultant", "adoption_services", "advertising_agency",
            "after_school_program", "air_duct_cleaning_service", "antenna_service", "appliance_repair_service",
            "appraisal_services", "architect", "architectural_designer", "art_restoration_service",
            "awning_supplier", "bail_bonds_service", "bank_equipment_service", "bike_repair_maintenance",
            "billing_services", "bookbinding", "bookkeeper", "bus_rentals", "business_consulting",
            "calligraphy", "car_broker", "career_counseling", "carpet_dyeing", "cemeteries",
            "certification_agency", "child_care_and_day_care", "cleaning_services", "clock_repair_service",
            "commercial_printer", "commercial_refrigeration", "commissioned_artist", "community_book_boxes",
            "community_gardens", "computer_hardware_company", "construction_services", "copywriting_service",
            "courier_and_delivery_services", "crane_services", "customs_broker", "delegated_driver_service",
            "diamond_dealer", "digitizing_services", "donation_center", "duplication_services",
            "e_commerce_service", "editorial_services", "elder_care_planning", "electrical_consultant",
            "electronics_repair_shop", "elevator_service", "emergency_service", "employment_agencies",
            "engraving", "environmental_abatement_services", "environmental_testing", "event_planning",
            "farm_equipment_repair_service", "feng_shui", "fingerprinting_service", "food_and_beverage_consultant",
            "forestry_service", "fortune_telling_service", "funeral_services_and_cemeteries",
            "furniture_rental_service", "furniture_repair", "furniture_reupholstery", "genealogists",
            "generator_installation_repair", "goldsmith", "graphic_designer", "gunsmith",
            "hazardous_waste_disposal", "hydraulic_repair_service", "hydro_jetting", "ice_supplier",
            "immigration_assistance_services", "indoor_landscaping", "internet_marketing_service",
            "internet_service_provider", "it_service_and_computer_repair", "jewelry_repair_service",
            "junk_removal_and_hauling", "junkyard", "knife_sharpening", "laboratory", "laundry_services",
            "lawn_mower_repair_service", "lawyer", "legal_services", "life_coach", "lottery_ticket",
            "machine_and_tool_rentals", "machine_shop", "mailbox_center", "marketing_agency",
            "matchmaker", "mediator", "merchandising_service", "metal_detector_services",
            "misting_system_services", "mobility_equipment_services", "mooring_service",
            "music_production_services", "musical_instrument_services", "nanny_services", "notary_public",
            "package_locker", "packaging_contractors_and_service", "patent_law", "payroll_services",
            "personal_assistant", "pest_control_service", "powder_coating_service", "printing_services",
            "private_investigation", "product_design", "propane_supplier", "public_adjuster",
            "public_relations", "record_label", "recording_and_rehearsal_studio", "recycling_center",
            "sandblasting_service", "screen_printing_t_shirt_printing", "security_services",
            "septic_services", "sewing_and_alterations", "shipping_center", "shoe_repair",
            "shoe_shining_service", "shredding_services", "sign_making", "snow_removal_service",
            "snuggle_service", "social_media_agency", "software_development", "storage_facility",
            "talent_agency", "taxidermist", "telephone_services", "tenant_and_eviction_law",
            "tent_house_supplier", "translation_services", "tv_mounting", "typing_services",
            "utility_service", "video_film_production", "watch_repair_service", "water_delivery",
            "web_designer", "well_drilling", "wildlife_control", "writing_service"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 17. PUBLIC_SERVICE_AND_GOVERNMENT (38 Level-2 categories)
    # -------------------------------------------------------------------------
    "public_service_and_government": {
        "description": "Government offices, public services, and civic buildings",
        "level_2": [
            "armed_forces_branch", "central_government_office", "chambers_of_commerce", "children_hall",
            "civic_center", "community_center", "community_services", "courthouse",
            "department_of_motor_vehicles", "department_of_social_service", "embassy",
            "family_service_center", "federal_government_offices", "fire_department", "government_services",
            "immigration_and_naturalization", "jail_and_prison", "law_enforcement", "library",
            "local_and_state_government_offices", "low_income_housing", "national_security_services",
            "office_of_vital_records", "organization", "pension", "police_department",
            "political_party_office", "post_office", "public_toilet", "public_utility_company",
            "railway_service", "registry_office", "retirement_home", "scout_hall", "tax_office",
            "town_hall", "unemployment_office", "weather_station"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 18. REAL_ESTATE (21 Level-2 categories)
    # -------------------------------------------------------------------------
    "real_estate": {
        "description": "Property, housing, and real estate services",
        "level_2": [
            "apartments", "art_space_rental", "builders", "commercial_real_estate", "condominium",
            "display_home_center", "estate_liquidation", "holiday_park", "home_staging",
            "homeowner_association", "housing_cooperative", "kitchen_incubator", "mobile_home_dealer",
            "mobile_home_park", "mortgage_broker", "property_management", "real_estate_agent",
            "real_estate_investment", "real_estate_service", "shared_office_space", "university_housing"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 19. RELIGIOUS_ORGANIZATION (11 Level-2 categories)
    # -------------------------------------------------------------------------
    "religious_organization": {
        "description": "Places of worship and religious institutions",
        "level_2": [
            "buddhist_temple", "church_cathedral", "convents_and_monasteries", "hindu_temple",
            "mission", "mosque", "religious_destination", "shinto_shrines", "sikh_temple",
            "synagogue", "temple"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 20. RETAIL (21 Level-2 categories)
    # -------------------------------------------------------------------------
    "retail": {
        "description": "Shops, stores, and retail establishments",
        "level_2": [
            "auto_parts_and_supply_store", "beverage_store", "boat_parts_and_supply_store",
            "carpet_store", "distillery", "drugstore", "flooring_store", "food",
            "health_market", "hearing_aid_provider", "herb_and_spice_shop", "honey_farm_shop",
            "meat_shop", "olive_oil", "party_supply", "pharmacy", "popcorn_shop",
            "seafood_market", "shopping", "tire_shop", "water_store"
        ],
        "key_subcategories": {
            "shopping": [
                "antique_shop", "art_supply", "baby_store", "bag_shop", "bike_shop",
                "book_store", "bridal_shop", "candle_store", "cards_and_stationery",
                "clothing_store", "comic_book_store", "computer_store", "cosmetics_store",
                "craft_store", "department_store", "discount_store", "electronics_store",
                "fabric_store", "florist", "furniture_store", "garden_center", "gift_shop",
                "grocery_store", "hardware_store", "hobby_shop", "home_decor", "jewelry_store",
                "kitchen_store", "leather_goods", "lingerie_store", "luggage_store",
                "maternity_store", "mobile_phone_store", "music_store", "office_supply",
                "optical_store", "outdoor_gear", "pawn_shop", "perfume_store", "pet_store",
                "record_store", "secondhand_store", "shoe_store", "souvenir_shop",
                "sporting_goods", "supermarket", "thrift_store", "tobacco_shop", "toy_store",
                "trophy_shop", "vintage_store", "watch_store", "wine_shop"
            ],
            "food": [
                "bakery", "butcher", "candy_store", "cheese_shop", "chocolate_shop",
                "coffee_beans", "deli", "farmers_market", "fish_market", "frozen_yogurt",
                "fruit_vegetable_market", "gourmet_food", "health_food_store", "ice_cream_shop",
                "organic_store", "specialty_food", "tea_shop", "wine_shop"
            ]
        }
    },
    
    # -------------------------------------------------------------------------
    # 21. STRUCTURE_AND_GEOGRAPHY (17 Level-2 categories)
    # -------------------------------------------------------------------------
    "structure_and_geography": {
        "description": "Natural and man-made geographic features",
        "level_2": [
            "bridge", "canal", "dam", "desert", "forest", "geologic_formation", "island",
            "mountain", "natural_hot_springs", "nature_reserve", "pier", "public_plaza",
            "quay", "river", "skyscraper", "tower", "weir"
        ]
    },
    
    # -------------------------------------------------------------------------
    # 22. TRAVEL (17 Level-2 categories)
    # -------------------------------------------------------------------------
    "travel": {
        "description": "Travel, transportation, and tourism services",
        "level_2": [
            "agriturismo", "airline_ticket_agency", "airport", "bus_ticket_agency",
            "country_house", "houseboat", "railway_ticket_agent", "rental_service",
            "rest_stop", "road_structures_and_services", "ryokan", "self_catering_accommodation",
            "ski_resort", "tours", "transportation", "travel_services", "vacation_rental_agents"
        ]
    }
}

# Flat list of all 22 top-level POI categories
POI_TOP_LEVEL_CATEGORIES = list(POI_CATEGORIES.keys())

# -----------------------------------------------------------------------------
# THEME 2: BASE - Land Use Classes (118 total)
# Source: schema/base/land_use.yaml
# -----------------------------------------------------------------------------

LAND_USE_SUBTYPES = [
    "agriculture", "aquaculture", "campground", "cemetery", "construction",
    "developed", "education", "entertainment", "golf", "grass", "horticulture",
    "landfill", "managed", "medical", "military", "park", "pedestrian",
    "protected", "recreation", "religious", "residential", "resource_extraction",
    "transportation", "winter_sports"
]

LAND_USE_CLASSES = [
    # Agriculture & Rural (12)
    "aboriginal_land", "allotments", "animal_keeping", "farmland", "farmyard",
    "greenhouse_horticulture", "logging", "orchard", "plant_nursery", "salt_pond",
    "vineyard", "aquaculture",
    
    # Military (9)
    "barracks", "base", "bunker", "danger_area", "military", "military_hospital",
    "military_school", "naval_base", "nuclear_explosion_site", "range", "training_area", "trench",
    
    # Recreation & Sports (23)
    "beach_resort", "camp_site", "dog_park", "downhill", "driving_range", "fairway",
    "fatbike", "golf_course", "grass", "green", "hike", "ice_skate", "lateral_water_hazard",
    "meadow", "nordic", "obstacle_course", "pitch", "playground", "recreation_ground",
    "rough", "ski_jump", "skitour", "sled", "sleigh", "snow_park", "stadium",
    "tee", "theme_park", "track", "water_hazard", "water_park", "winter_sports",
    
    # Protected & Natural (10)
    "forest", "national_park", "natural_monument", "nature_reserve", "park",
    "protected", "protected_landscape_seascape", "species_management_area",
    "state_park", "strict_nature_reserve", "wilderness_area", "zoo",
    
    # Urban & Developed (20)
    "brownfield", "clinic", "college", "commercial", "connection", "construction",
    "doctors", "education", "flowerbed", "garden", "garages", "greenfield",
    "highway", "hospital", "industrial", "institutional", "kindergarten",
    "marina", "music_school", "pedestrian", "plaza", "quarry", "railway",
    "religious", "residential", "resort", "retail", "school", "schoolyard",
    "static_caravan", "traffic_island", "university", "village_green", "works",
    
    # Cemetery (3)
    "cemetery", "grave_yard", "landfill",
    
    # Other (2)
    "airfield", "peat_cutting"
]

# -----------------------------------------------------------------------------
# THEME 2: BASE - Water Classes (35 total)
# Source: schema/base/water.yaml
# -----------------------------------------------------------------------------

WATER_SUBTYPES = [
    "canal", "human_made", "lake", "ocean", "physical", "pond", "reservoir",
    "river", "spring", "stream", "wastewater", "water"
]

WATER_CLASSES = [
    # Natural Bodies (12)
    "bay", "lake", "lagoon", "ocean", "oxbow", "pond", "reservoir", "river",
    "sea", "strait", "stream", "waterfall",
    
    # Human-Made (10)
    "basin", "canal", "ditch", "dock", "drain", "fish_pass", "fishpond",
    "moat", "reflecting_pool", "salt_pond", "sewage", "swimming_pool",
    "water_storage",
    
    # Geological Features (6)
    "blowhole", "cape", "geyser", "hot_spring", "shoal", "spring",
    "tidal_channel",
    
    # Generic (3)
    "fairway", "wastewater", "water"
]

# -----------------------------------------------------------------------------
# THEME 2: BASE - Infrastructure Classes (164 total)
# Source: schema/base/infrastructure.yaml
# -----------------------------------------------------------------------------

INFRASTRUCTURE_SUBTYPES = [
    "aerialway", "airport", "barrier", "bridge", "communication", "emergency",
    "manhole", "pedestrian", "pier", "power", "quay", "recreation", "tower",
    "transit", "transportation", "utility", "waste_management", "water"
]

INFRASTRUCTURE_CLASSES = [
    # Airport & Aviation (13)
    "aerialway_station", "airport", "airport_gate", "airstrip", "apron",
    "helipad", "heliport", "international_airport", "launchpad", "military_airport",
    "municipal_airport", "private_airport", "regional_airport", "runway",
    "seaplane_airport", "stopway", "taxilane", "taxiway", "terminal",
    
    # Transit & Stations (12)
    "bus_route", "bus_station", "bus_stop", "ferry_terminal", "platform",
    "railway_halt", "railway_station", "stop", "stop_position", "subway_station",
    
    # Roads & Traffic (10)
    "crossing", "motorway_junction", "parking", "parking_entrance", "parking_space",
    "pedestrian_crossing", "toll_booth", "traffic_signals", "give_way",
    
    # Power & Energy (10)
    "cable", "cable_distribution", "generator", "minor_line", "power_line",
    "power_pole", "power_tower", "pylon", "substation", "transformer",
    
    # Communication (6)
    "communication_line", "communication_pole", "communication_tower",
    "mobile_phone_tower", "radar", "street_cabinet",
    
    # Bridges & Structures (10)
    "aqueduct", "boardwalk", "bridge", "bridge_support", "cantilever",
    "covered", "movable", "trestle", "viaduct",
    
    # Barriers & Fences (22)
    "barrier", "block", "bollard", "bump_gate", "bus_trap", "cable_barrier",
    "cattle_grid", "chain", "city_wall", "cycle_barrier", "ditch", "fence",
    "full-height_turnstile", "gate", "guard_rail", "hampshire_gate", "handrail",
    "hedge", "height_restrictor", "jersey_barrier", "kerb", "kissing_gate",
    "lift_gate", "retaining_wall", "sally_port", "stile", "swing_gate", "wall",
    
    # Aerialways (10)
    "cable_car", "chair_lift", "drag_lift", "gondola", "goods", "j-bar",
    "magic_carpet", "mixed_lift", "platter", "rope_tow", "t-bar", "zip_line",
    
    # Towers (9)
    "bell_tower", "cooling", "lighting", "minaret", "observation",
    "portal", "watchtower", "water_tower",
    
    # Utilities (12)
    "catenary_mast", "cutline", "dam", "drain", "fire_hydrant", "hose",
    "manhole", "pipeline", "sewer", "utility_pole", "weir",
    
    # Amenities (22)
    "artwork", "atm", "bench", "bicycle_parking", "bicycle_rental", "border_control",
    "breakwater", "camp_site", "charging_station", "diving", "drinking_water",
    "entrance", "fountain", "gasometer", "information", "insulator", "milestone",
    "monitoring", "motorcycle_parking", "picnic_table", "pier", "plant",
    "planter", "post_box", "quay", "recycling", "reservoir_covered",
    "roller_coaster", "silo", "siren", "storage_tank", "street_lamp", "switch",
    "toilets", "vending_machine", "viewpoint", "waste_basket", "waste_disposal",
    
    # Other
    "connection", "defensive", "heliostat", "lightning_protection"
]

# -----------------------------------------------------------------------------
# THEME 3: TRANSPORTATION - Segment Classes
# Source: schema/transportation/segment.yaml
# -----------------------------------------------------------------------------

ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service", "pedestrian", "footway",
    "cycleway", "path", "track"
]

RAIL_CLASSES = [
    "rail", "subway", "tram", "light_rail", "narrow_gauge", "funicular",
    "monorail", "miniature", "preserved", "tourist"
]

WATER_TRANSPORT_CLASSES = [
    "ferry"
]

# -----------------------------------------------------------------------------
# SUMMARY COUNTS
# -----------------------------------------------------------------------------

SCHEMA_SUMMARY = {
    "places": {
        "top_level_categories": 22,
        "level_2_categories": 697,
        "total_categories": 2118
    },
    "base": {
        "land_use_subtypes": 24,
        "land_use_classes": 118,
        "water_subtypes": 12,
        "water_classes": 35,
        "infrastructure_subtypes": 18,
        "infrastructure_classes": 164
    },
    "transportation": {
        "road_classes": 14,
        "rail_classes": 10,
        "water_transport_classes": 1
    }
}


def get_theme_type_for_query(user_intent: str) -> tuple:
    """
    Map user intent to Overture theme and type.
    
    Args:
        user_intent: Natural language description like "parks", "cafes", "roads"
        
    Returns:
        Tuple of (theme, type, additional_filter)
    """
    intent_lower = user_intent.lower()
    
    # Parks (land use polygons vs POI points)
    if "park" in intent_lower and ("area" in intent_lower or "polygon" in intent_lower or "green" in intent_lower or "m2" in intent_lower or "hectare" in intent_lower):
        return ("base", "land_use", "class = 'park'")
    
    # Land use types
    if any(x in intent_lower for x in ["forest", "wood"]):
        return ("base", "land_use", "class = 'forest'")
    if "residential" in intent_lower:
        return ("base", "land_use", "class = 'residential'")
    if "commercial" in intent_lower:
        return ("base", "land_use", "class = 'commercial'")
    if "industrial" in intent_lower:
        return ("base", "land_use", "class = 'industrial'")
    
    # Water
    if any(x in intent_lower for x in ["river", "stream"]):
        return ("base", "water", "class = 'river'")
    if any(x in intent_lower for x in ["lake", "pond"]):
        return ("base", "water", "class = 'lake'")
    
    # Roads
    if any(x in intent_lower for x in ["road", "street", "highway"]):
        return ("transportation", "segment", "subtype = 'road'")
    if "motorway" in intent_lower:
        return ("transportation", "segment", "class = 'motorway'")
    if "primary road" in intent_lower:
        return ("transportation", "segment", "class = 'primary'")
    
    # Buildings
    if "building" in intent_lower:
        if "tall" in intent_lower or "high" in intent_lower:
            return ("buildings", "building", "height > 30")
        return ("buildings", "building", None)
    
    # Divisions
    if any(x in intent_lower for x in ["city", "town", "boundary", "admin"]):
        return ("divisions", "division_area", "subtype = 'locality'")
    if any(x in intent_lower for x in ["country", "nation"]):
        return ("divisions", "division_area", "subtype = 'country'")
    if any(x in intent_lower for x in ["region", "state", "province"]):
        return ("divisions", "division_area", "subtype = 'region'")
    
    # Addresses
    if "address" in intent_lower:
        return ("addresses", "address", None)
    
    # Default: check if it's a known POI category
    for alias, category in CATEGORY_ALIASES.items():
        if alias in intent_lower:
            return ("places", "place", f"categories.primary = '{category}'")
    
    # Fallback to places
    return ("places", "place", None)
