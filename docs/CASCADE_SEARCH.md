# Cascade Multi-Resolution Search

## Overview

The cascade search is a multi-resolution filtering algorithm that progressively narrows down candidate hexagons from city-scale (res 5) to street-level (res 10), using different scoring methods at each stage.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     MULTI-RESOLUTION CASCADE SEARCH                          │
│                                                                              │
│  User Query → Gemini Feature Extraction → 4-Stage Cascade → Heatmap         │
│                                                                              │
│  Stage 1 (Res 5)  │ SUMMATIVE    │ "What's in this city zone?"  │ Top 25%   │
│  Stage 2 (Res 8)  │ MULTIPLICATIVE│ "Can I drive there?"        │ 0 = dead  │
│  Stage 3 (Res 10) │ MULTIPLICATIVE│ "Can I walk there?"         │ 0 = dead  │
│  Stage 4 (Res 10) │ SUMMATIVE    │ "How good is this spot?"     │ Heatmap   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Why Multi-Resolution?

| Resolution | Edge Length | Use Case | Example |
|------------|-------------|----------|---------|
| **Res 5** | ~8.5 km | City districts | "Is this part of London promising?" |
| **Res 8** | ~461 m | Driving neighborhoods | "Can I reach a hospital in 40 min?" |
| **Res 10** | ~66 m | Walking blocks | "Is there a café within 10 min walk?" |

---

## The 4 Stages

### Stage 1: Coarse Filter (Res 5) — SUMMATIVE

**Purpose:** Quickly eliminate 75% of the area by identifying city zones with the right *density* of amenities.

**Method:** `score = Σ(count columns)` → Take top 25%

**Why summative?** At city scale, we care about "how many cafés are in this district" — it's additive. A district with 100 cafés is better than one with 10.

**Column types used:**
- `{poi}_count` — e.g., `cafe_count`, `restaurant_count`
- `{land_use}_count` — e.g., `park_count`
- `{land_use}_in_hex_m2` — e.g., `park_in_hex_m2`
- `building_count`, `building_density`

**Output:** Spotlight effect on map (grey out everything outside top 25%)

---

### Stage 2: Driving Distance Filter (Res 8) — MULTIPLICATIVE

**Purpose:** Within the top city zones, filter to areas where essential services are within driving distance (~40 min).

**Method:** `mask = (col_a > 0) AND (col_b > 0) AND ...` — **ZERO = ELIMINATED**

**Why multiplicative?** If you need a hospital within driving distance and there isn't one, that location is non-negotiable — it's out. You can't compensate for zero hospitals by having more cafés.

**Column types used:**
- `{poi}_drive_min` — e.g., `hospital_drive_min` (must be < 999)
- `{poi}_score` — e.g., `hospital_score` (0-10, decays with distance)
- `{transit}_cycle_min` — e.g., `train_cycle_min`
- `{green}_cycle_min` — e.g., `park_2m_cycle_min` (large parks)
- `{road}_walk_min` — e.g., `motorway_road_walk_min`

**Output:** Overlay of driving-accessible hexes

---

### Stage 3: Walking Distance Filter (Res 10) — MULTIPLICATIVE

**Purpose:** Within driving-accessible areas, filter to hexes where daily amenities are walkable (~5-15 min).

**Method:** Same multiplicative — **ZERO = ELIMINATED**

**Why multiplicative?** You said "walkable to tube" — if there's no tube walkable, it's out. Non-negotiable.

**Column types used:**
- `{poi}_walk_min` — e.g., `cafe_walk_min`, `supermarket_walk_min`
- `{transit}_walk_min` — e.g., `subway_walk_min`
- `{green}_walk_min` — e.g., `park_walk_min`, `park_20k_walk_min`
- `{blue}_walk_min` — e.g., `lake_walk_min`, `coastline_walk_min`

**Output:** Narrowed candidate hexes

---

## ⚠️ DRIVING vs WALKING: The Hard Decisions

### The Core Question: WHEN do we use multiplicative (AND) vs summative (ADD)?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  MULTIPLICATIVE = "I NEED this, no exceptions"     → Zero kills the hex    │
│  SUMMATIVE      = "More is better, but flexible"   → Zero just lowers score│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Stage 2 (Driving) — CURRENT LOGIC

**What we're checking:** Can you DRIVE/CYCLE to essential amenities?

| If user says... | We filter on... | Column used | Why multiplicative? |
|-----------------|-----------------|-------------|---------------------|
| "near a hospital" | `hospital_drive_min > 0` | `hospital_drive_min` | **HARD NEED** — medical access is non-negotiable |
| "access to airport" | `airport_cycle_min > 0` | `airport_cycle_min` | **HARD NEED** — you need it or you don't |
| "near a big park" | `park_2m_cycle_min > 0` | `park_2m_cycle_min` | **HARD NEED** — if you asked for it specifically |

**⚠️ RISK OF OVER-CONSTRAINING:**
- If user says "coffee shops, park, hospital" and we make ALL multiplicative for driving stage...
- ...we eliminate hexes that have hospitals but no large parks within cycling distance
- **Solution:** Only driving-stage filter on things that MAKE SENSE for driving (hospital, airport, university, major shopping)
- Don't filter driving-stage on cafés — those are walking-stage concerns

### Stage 3 (Walking) — CURRENT LOGIC  

**What we're checking:** Can you WALK to daily amenities?

| If user says... | We filter on... | Column used | Why multiplicative? |
|-----------------|-----------------|-------------|---------------------|
| "walkable to tube" | `subway_walk_min > 0` | `subway_walk_min` | **HARD NEED** — explicit request |
| "near coffee shops" | `cafe_walk_min > 0` | `cafe_walk_min` | **⚠️ DEBATABLE** — see below |
| "near a park" | `park_walk_min > 0` | `park_walk_min` | **⚠️ DEBATABLE** — see below |

**⚠️ RISK OF OVER-CONSTRAINING:**
```
User: "lively neighborhood with cafes, pubs, near a park"

STRICT interpretation (current):
  - cafe_walk_min > 0 AND pub_walk_min > 0 AND park_walk_min > 0
  - Result: Only hexes where ALL THREE are walkable
  - Problem: Kills hex that has 50 cafes and 20 pubs but park is 12 min walk (value=0 at edge)

LENIENT interpretation (alternative):
  - (cafe_walk_min > 0 OR pub_walk_min > 0) AND park_walk_min > 0  
  - Result: At least one of cafe/pub, plus park
  - Less strict, more results
```

### 🔧 TUNING OPTIONS (Implementation Decision Needed)

| Option | Logic | Effect |
|--------|-------|--------|
| **STRICT** | ALL selected walking features must be > 0 | Fewest results, highest quality matches |
| **CATEGORY-LENIENT** | At least ONE per category > 0 | "cafe OR coffee_shop > 0" — same category grouped |
| **THRESHOLD** | Sum of walk_mins < X | "Total walking effort under 30 min" |
| **HYBRID** | Transit = STRICT, POI = LENIENT | "Must have tube, cafés are nice-to-have" |

### 📋 CURRENT DECISION (To Implement)

```
DRIVING (Stage 2):
  - Filter: STRICT multiplicative
  - ONLY for: hospital, airport, train_station, university, shopping_mall
  - NOT for: cafes, restaurants, bars (those are walking-stage)
  
WALKING (Stage 3):  
  - Transit: STRICT (subway_walk_min > 0 if requested)
  - POI: CATEGORY-LENIENT (cafe OR coffee_shop > 0, not cafe AND coffee_shop)
  - Green/Blue: STRICT if explicitly requested ("must be near a park")
```

### Why This Matters

```
Too strict  → "No results found" → User frustrated
Too lenient → Returns everything → Useless heatmap
```

**The Gemini prompt should guide this:**
- "Must have" / "need" / "require" → STRICT
- "Nice to have" / "prefer" / "ideally" → LENIENT (goes to Stage 4 scoring, not Stage 3 filter)

---

### Stage 4: Amenity Scoring (Res 10) — SUMMATIVE

**Purpose:** Among surviving hexes, rank them by amenity richness for the final heatmap.

**Method:** `score = Σ(count columns)` → Percentile rank → Color intensity

**Why summative again?** Now we're ranking — more cafés = better spot. The multiplicative filters ensured baseline access; now we optimize for density.

**Column types used:** Same as Stage 1 (count columns)

**Output:** Final heatmap with color intensity = amenity score

---

## Complete Column Schema Reference

### Overview: All Column Types

| Category | Pattern | Count | Stages |
|----------|---------|-------|--------|
| POI Counts | `{poi}_count` | 1,081 | 1, 4 (summative) |
| POI Walk Time | `{poi}_walk_min` | 1,081 | 3 (walking) |
| POI Cycle Time | `{poi}_cycle_min` | 1,081 | 2, 3 |
| POI Drive Time | `{poi}_drive_min` | 1,081 | 2 (driving) |
| POI Score | `{poi}_score` | 1,081 | 2 (driving) |
| Land Use Count | `{land_use}_count` | 28 | 1, 4 |
| Land Use Area | `{land_use}_in_hex_m2` | 28 | 1, 4 |
| Land Use Avg | `{land_use}_avg_area_m2` | 28 | 1, 4 |
| Water Count | `{water}_count` | 4 | 1, 4 |
| Water Area | `{water}_in_hex_m2` | 4 | 1, 4 |
| Buildings | 4 columns | 4 | 1, 4 |
| Transit Walk | `{transit}_walk_min` | 7 | 3 (walking) |
| Transit Cycle | `{transit}_cycle_min` | 7 | 2 (driving) |
| Green Walk | `{green}_walk_min` | 9 | 3 (walking) |
| Green Cycle | `{green}_cycle_min` | 9 | 2 (driving) |
| Blue Walk | `{blue}_walk_min` | 5 | 3 (walking) |
| Blue Cycle | `{blue}_cycle_min` | 5 | 2 (driving) |
| Road Presence | `{road}_in_hex` | 4 | 1, 4 (binary) |
| Road Proximity | `{road}_road_walk_min` | 4 | 2, 3 |
| **TOTAL** | | **~5,760** | |

---

### SUMMATIVE Columns (Stage 1 & 4)

Used for additive density scoring.

#### POI Counts (1,081 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{poi}_count` | `cafe_count` | Number of POIs in hex |

**POI Categories (1,081 L3 types):**
- Restaurants (77): `restaurant`, `italian_restaurant`, `sushi_restaurant`, `ramen_restaurant`, ...
- Bars (43): `bar`, `wine_bar`, `cocktail_bar`, `pub`, `nightclub`, ...
- Cafes (30): `cafe`, `coffee_shop`, `bakery`, `patisserie`, ...
- Health (93): `hospital`, `pharmacy`, `dentist`, `clinic`, `urgent_care`, ...
- Retail (175): `supermarket`, `convenience_store`, `clothing_store`, ...
- Education (53): `school`, `university`, `library`, `kindergarten`, ...
- Fitness (74): `gym`, `yoga_studio`, `swimming_pool`, `tennis_court`, ...
- Entertainment (70): `cinema`, `museum`, `theater`, `arcade`, ...
- Accommodation (34): `hotel`, `hostel`, `airbnb`, ...
- Financial (31): `bank`, `atm`, `accountant`, ...
- Automotive (30): `gas_station`, `car_wash`, `auto_repair`, ...
- Beauty/Spa (55): `hair_salon`, `spa`, `nail_salon`, ...
- Professional (44): `lawyer`, `architect`, `coworking_space`, ...
- Home Service (56): `plumber`, `electrician`, `cleaning_service`, ...
- Public Service (43): `post_office`, `police_station`, `library`, ...
- Religious (33): `church`, `mosque`, `synagogue`, ...
- Travel/Transit (42): `airport`, `train_station`, `car_rental`, ...
- Real Estate (20): `real_estate_agency`, `apartment_complex`, ...
- Food Specialty (51): `sushi`, `ramen`, `food_truck`, ...

#### Land Use (28 classes × 3 columns = 84 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{land_use}_count` | `park_count` | Number of polygons |
| `{land_use}_in_hex_m2` | `park_in_hex_m2` | Area coverage in m² |
| `{land_use}_avg_area_m2` | `park_avg_area_m2` | Avg polygon size |

**Land Use Classes:**
```
residential, commercial, industrial, retail, office,
park, forest, recreation_ground, farmland, vineyard,
orchard, meadow, grassland, scrub, heath,
quarry, landfill, construction, brownfield,
cemetery, allotments, beach, military,
education, healthcare, religious,
nature_reserve, protected_area, national_park
```

#### Water (4 types × 2 columns = 8 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{water}_count` | `lake_count` | Number of water features |
| `{water}_in_hex_m2` | `lake_in_hex_m2` | Water area coverage |

**Water Types:** `lake`, `river`, `pond`, `sea`

#### Buildings (4 columns)

| Column | Description |
|--------|-------------|
| `building_count` | Number of buildings in hex |
| `building_density` | Total footprint area m² |
| `avg_building_height` | Average height in meters |
| `avg_floors` | Average number of floors |

#### Road Presence (4 columns) — BINARY

| Column | Description |
|--------|-------------|
| `pedestrian_in_hex` | Has pedestrian street (0/1) |
| `cycleway_in_hex` | Has bike path (0/1) |
| `footway_in_hex` | Has footpath (0/1) |
| `living_street_in_hex` | Has living street (0/1) |

---

### MULTIPLICATIVE Columns — DRIVING (Stage 2)

Used for driving distance hard cutoffs. **ZERO = ELIMINATED**

#### POI Driving Distances (1,081 × 3 = 3,243 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{poi}_drive_min` | `hospital_drive_min` | Drive time to nearest (minutes) |
| `{poi}_cycle_min` | `hospital_cycle_min` | Cycle time to nearest (minutes) |
| `{poi}_score` | `hospital_score` | Proximity score (0-10, decays) |

**Note:** `_score` provides softer cutoff than `_drive_min`. Score=0 means unreachable, Score=10 means in-hex.

#### Transit Cycling (7 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{transit}_cycle_min` | `train_cycle_min` | Cycle time to transit |

**Transit Types:** `subway`, `train`, `bus`, `tram`, `light_rail`, `ferry`, `airport`

#### Green Features Cycling (9 columns)

| Column | Size Threshold |
|--------|----------------|
| `park_cycle_min` | Any park |
| `park_small_cycle_min` | ≤20,000 m² |
| `park_20k_cycle_min` | ≥20,000 m² |
| `park_2m_cycle_min` | ≥2,000,000 m² |
| `park_20m_cycle_min` | ≥20,000,000 m² |
| `forest_cycle_min` | Any forest |
| `beach_cycle_min` | Any beach |
| `nature_reserve_cycle_min` | Any nature reserve |

#### Blue Features Cycling (5 columns)

| Column | Description |
|--------|-------------|
| `lake_cycle_min` | Any lake |
| `lake_2m_cycle_min` | Large lakes ≥2M m² |
| `river_cycle_min` | Any river |
| `coastline_cycle_min` | Coastline |

#### Road Proximity (4 columns)

| Column | Description |
|--------|-------------|
| `motorway_road_walk_min` | Walk time to motorway |
| `trunk_road_walk_min` | Walk time to trunk road |
| `primary_road_walk_min` | Walk time to primary road |
| `secondary_road_walk_min` | Walk time to secondary road |

---

### MULTIPLICATIVE Columns — WALKING (Stage 3)

Used for walking distance hard cutoffs. **ZERO = ELIMINATED**

#### POI Walking Distances (1,081 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{poi}_walk_min` | `cafe_walk_min` | Walk time to nearest (minutes) |

#### Transit Walking (7 columns)

| Pattern | Example | Description |
|---------|---------|-------------|
| `{transit}_walk_min` | `subway_walk_min` | Walk time to transit |

**Transit Types:** `subway`, `train`, `bus`, `tram`, `light_rail`, `ferry`, `airport`

#### Green Features Walking (9 columns)

| Column | Size Threshold |
|--------|----------------|
| `park_walk_min` | Any park |
| `park_small_walk_min` | ≤20,000 m² (pocket parks) |
| `park_20k_walk_min` | ≥20,000 m² (decent parks) |
| `park_2m_walk_min` | ≥2,000,000 m² (large parks) |
| `park_20m_walk_min` | ≥20,000,000 m² (major parks) |
| `forest_walk_min` | Any forest |
| `beach_walk_min` | Any beach |
| `nature_reserve_walk_min` | Any nature reserve |

#### Blue Features Walking (5 columns)

| Column | Description |
|--------|-------------|
| `lake_walk_min` | Any lake |
| `lake_2m_walk_min` | Large lakes ≥2M m² |
| `river_walk_min` | Any river |
| `coastline_walk_min` | Coastline |

#### Road Proximity (can also use in Stage 3)

| Column | Description |
|--------|-------------|
| `motorway_road_walk_min` | Walk time to motorway |
| `trunk_road_walk_min` | Walk time to trunk road |
| `primary_road_walk_min` | Walk time to primary road |
| `secondary_road_walk_min` | Walk time to secondary road |

---

## Gemini Structured Output Schemas

Three separate schemas restrict Gemini's output to valid column prefixes for each stage.

### Schema 1: Summative Features (Stage 1 & 4)

Generates count/area columns for density scoring.

```python
SUMMATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "poi_features": {
            "type": "array",
            "items": {"type": "string", "enum": [*POI_CATEGORIES_L3.keys()]},
            "description": "POI types → generates {poi}_count"
        },
        "land_use_features": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "residential", "commercial", "industrial", "retail", "office",
                "park", "forest", "recreation_ground", "farmland", "vineyard",
                "orchard", "meadow", "grassland", "scrub", "heath",
                "quarry", "landfill", "construction", "brownfield",
                "cemetery", "allotments", "beach", "military",
                "education", "healthcare", "religious",
                "nature_reserve", "protected_area", "national_park"
            ]},
            "description": "Land use → generates {land_use}_count, {land_use}_in_hex_m2"
        },
        "water_features": {
            "type": "array",
            "items": {"type": "string", "enum": ["lake", "river", "pond", "sea"]},
            "description": "Water → generates {water}_count, {water}_in_hex_m2"
        },
        "include_buildings": {
            "type": "boolean",
            "description": "Include building_count, building_density, avg_building_height, avg_floors"
        },
        "road_presence": {
            "type": "array",
            "items": {"type": "string", "enum": ["pedestrian", "cycleway", "footway", "living_street"]},
            "description": "Road presence → generates {road}_in_hex (binary)"
        }
    }
}
```

**Example output:**
```json
{
    "poi_features": ["cafe", "coffee_shop", "bar", "restaurant"],
    "land_use_features": ["park"],
    "water_features": [],
    "include_buildings": true,
    "road_presence": ["pedestrian"]
}
```

**Generated columns:**
- `cafe_count`, `coffee_shop_count`, `bar_count`, `restaurant_count`
- `park_count`, `park_in_hex_m2`
- `building_count`, `building_density`, `avg_building_height`, `avg_floors`
- `pedestrian_in_hex`

---

### Schema 2: Driving Features (Stage 2)

Selects columns for driving-distance hard cutoffs. **Only include TRUE non-negotiables here.**

```python
DRIVING_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have_pois": {
            "type": "array",
            "items": {"type": "string", "enum": [
                # ONLY big-ticket items that require driving
                "hospital", "airport", "train_station", "university", 
                "shopping_mall", "ikea", "costco", "major_supermarket"
            ]},
            "description": "POIs that MUST be within driving distance — zero = eliminated"
        },
        "poi_column_type": {
            "type": "string",
            "enum": ["drive_min", "cycle_min", "score"],
            "description": "drive_min = hard cutoff, score = softer decay"
        },
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "subway", "train", "bus", "tram", "light_rail", "ferry", "airport"
            ]},
            "description": "Transit that MUST be cycleable — zero = eliminated"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "park_2m", "park_20m", "forest", "nature_reserve"
            ]},
            "description": "Large green spaces — only if explicitly required"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "lake_2m", "coastline"
            ]},
            "description": "Large water features — only if explicitly required"
        }
    }
}
```

**⚠️ GUIDANCE FOR GEMINI:**
- ONLY put things here the user said "must have", "need", "require"
- Do NOT put cafes, restaurants, bars here — those are walking concerns
- When in doubt, LEAVE IT OUT — over-constraining kills results
```

**Example: "need hospital and train access within driving distance, ideally near a big park"**
```json
{
    "must_have_pois": ["hospital"],         // "need" = strict
    "poi_column_type": "drive_min",
    "must_have_transit": ["train"],         // "train access" = strict
    "must_have_green": [],                  // "ideally" = NOT strict, skip
    "must_have_blue": []
}
```

**Resulting filter:** `hospital_drive_min > 0 AND train_cycle_min > 0`
- Note: "ideally near big park" goes to Stage 4 scoring, NOT Stage 2 filtering

---

### Schema 3: Walking Features (Stage 3)

Selects columns for walking-distance filtering. **Split into MUST-HAVE vs NICE-TO-HAVE.**

```python
WALKING_SCHEMA = {
    "type": "object",
    "properties": {
        # ─────────────────────────────────────────────────────────────
        # STRICT: Zero in ANY of these = hex eliminated
        # ─────────────────────────────────────────────────────────────
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "subway", "train", "bus", "tram", "light_rail"
            ]},
            "description": "Transit MUST be walkable — 'walkable to tube' = strict"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "park", "park_small", "park_20k", "park_2m",
                "forest", "beach", "nature_reserve"
            ]},
            "description": "Green space MUST be walkable — only if user said 'need'"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "lake", "river", "coastline"
            ]},
            "description": "Water MUST be walkable — only if user said 'need'"
        },
        
        # ─────────────────────────────────────────────────────────────
        # LENIENT: At least ONE in this category > 0
        # ─────────────────────────────────────────────────────────────
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
                }
            },
            "description": "POI categories where AT LEAST ONE must be walkable"
        }
    }
}
```

**Example: "lively area with cafes and pubs, walkable to tube, near a park"**

```json
{
    "must_have_transit": ["subway"],           // STRICT: tube is non-negotiable
    "must_have_green": ["park"],               // STRICT: explicitly said "near a park"  
    "must_have_blue": [],                      // Not mentioned
    "prefer_poi_categories": [                 // LENIENT: at least ONE of these
        {
            "category_name": "coffee",
            "features": ["cafe", "coffee_shop"]  // cafe_walk_min > 0 OR coffee_shop_walk_min > 0
        },
        {
            "category_name": "nightlife", 
            "features": ["pub", "bar"]           // pub_walk_min > 0 OR bar_walk_min > 0
        }
    ]
}
```

**Resulting filter logic:**
```python
(subway_walk_min > 0)                           # STRICT
AND (park_walk_min > 0)                         # STRICT  
AND (cafe_walk_min > 0 OR coffee_shop_walk_min > 0)   # LENIENT
AND (pub_walk_min > 0 OR bar_walk_min > 0)            # LENIENT
```

**⚠️ GUIDANCE FOR GEMINI:**
- Transit: Almost always STRICT if mentioned ("walkable to X")
- Green/Blue: STRICT only if user said "need", "must", "require"
- POIs: Almost always LENIENT — group similar types (cafe/coffee_shop, pub/bar)
- When in doubt, put in `prefer_poi_categories` not `must_have`

---

## Complete Example

**User Query:** *"Lively neighborhood with coffee shops, near a decent park, tube access, and within driving distance of a hospital"*

### Gemini Feature Extraction

**Stage 1 & 4 (Summative) — What to RANK on:**
```json
{
    "poi_features": ["cafe", "coffee_shop", "bar", "restaurant"],
    "land_use_features": ["park"],
    "water_features": [],
    "include_buildings": false,
    "road_presence": []
}
```

**Stage 2 (Driving) — What MUST be driveable:**
```json
{
    "must_have_pois": ["hospital"],        // "within driving distance" = STRICT
    "poi_column_type": "drive_min",
    "must_have_transit": [],
    "must_have_green": [],
    "must_have_blue": []
}
```
☝️ Note: Cafes NOT here — they're a walking concern, not driving.

**Stage 3 (Walking) — What MUST be walkable:**
```json
{
    "must_have_transit": ["subway"],       // "tube access" = STRICT
    "must_have_green": ["park_20k"],       // "near a decent park" = STRICT (20k = decent size)
    "must_have_blue": [],
    "prefer_poi_categories": [             // "lively with coffee shops" = LENIENT
        {
            "category_name": "coffee",
            "features": ["cafe", "coffee_shop"]
        }
    ]
}
```

### Column Selection (NOT generation — columns exist in parquet)

| Stage | Operation | Columns Selected |
|-------|-----------|------------------|
| 1 (Summative) | SUM then SORT | `cafe_count + coffee_shop_count + bar_count + restaurant_count + park_count` |
| 2 (Driving) | FILTER where > 0 | `hospital_drive_min` |
| 3 (Walking) | FILTER where > 0 | `subway_walk_min AND park_20k_walk_min AND (cafe_walk_min OR coffee_shop_walk_min)` |
| 4 (Scoring) | SUM then RANK | `cafe_count + coffee_shop_count + bar_count + restaurant_count` |

### Cascade Execution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1 (Res 5) — SUMMATIVE RANKING                                         │
│ ════════════════════════════════════                                         │
│ 1,000 hexes                                                                  │
│    ↓ SUM(cafe_count + coffee_shop_count + bar_count + restaurant_count)     │
│    ↓ SORT descending                                                         │
│    ↓ TAKE top 25%                                                            │
│ 250 hexes survive                                                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2 (Res 8) — DRIVING HARD FILTER                                        │
│ ══════════════════════════════════════                                       │
│ 250 × ~49 children = 12,250 hexes                                            │
│    ↓ FILTER: hospital_drive_min > 0                                          │
│    ↓ (Zero hospital access = ELIMINATED, no exceptions)                      │
│ ~8,000 hexes survive                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3 (Res 10) — WALKING HARD + LENIENT FILTER                             │
│ ════════════════════════════════════════════════                             │
│ 8,000 × ~49 children = 392,000 hexes                                         │
│    ↓ FILTER (STRICT):  subway_walk_min > 0                                   │
│    ↓ FILTER (STRICT):  park_20k_walk_min > 0                                 │
│    ↓ FILTER (LENIENT): (cafe_walk_min > 0 OR coffee_shop_walk_min > 0)       │
│    ↓                                                                          │
│ ~50,000 hexes survive                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4 (Res 10) — SUMMATIVE SCORING FOR HEATMAP                             │
│ ════════════════════════════════════════════════                             │
│ 50,000 surviving hexes                                                        │
│    ↓ SUM(cafe_count + coffee_shop_count + bar_count + restaurant_count)     │
│    ↓ PERCENTILE RANK (0-100)                                                 │
│    ↓ MAP to color intensity                                                  │
│ Final heatmap                                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Visualization Output

| Event | Layer ID | Effect |
|-------|----------|--------|
| Stage 1 complete | `res5_spotlight` | Grey mask outside top 25% city zones |
| Stage 2 complete | `res8_driving` | Overlay driving-accessible areas (plasma colormap) |
| Stage 3 complete | `res10_candidates` | Narrow to walkable candidates |
| Stage 4 complete | `res10_final` | Final heatmap with amenity score intensity |

---

## Data Files

The cascade search uses pre-computed parquet files at each resolution:

```
output/earth_matrix_temp/matrix/
├── TEST_HOXTON_res5.parquet   # ~8.5km hexes (city districts)
├── TEST_HOXTON_res8.parquet   # ~461m hexes (neighborhoods)
└── TEST_HOXTON_res10.parquet  # ~66m hexes (blocks)
```

Each parquet contains the full Earth Matrix schema with ~5,700+ columns per hex.

---

## H3 Parent-Child Relationships

The cascade leverages H3's hierarchical structure:

```python
import h3

# Get parent at coarser resolution
res5_hex = h3.cell_to_parent(res10_hex, 5)

# Get all children at finer resolution
res10_children = h3.cell_to_children(res8_hex, 10)  # ~49 children
```

| Parent Res | Child Res | Children per Parent |
|------------|-----------|---------------------|
| 5 | 8 | ~343 |
| 8 | 10 | ~49 |
| 10 | 11 | ~7 |

---

## Implementation Notes

1. **No hardcoded thresholds** — Gemini selects features, code generates column suffixes
2. **Progressive visualization** — Each stage emits `layer_update` SSE events
3. **Memory efficient** — Only load one resolution parquet at a time
4. **Interruptible** — Each stage is independent; can checkpoint between stages
5. **Schema-restricted** — Gemini enums prevent hallucinated column names

---

## Files

| File | Purpose |
|------|---------|
| `backend/tools/tools_cascade_search.py` | Core cascade search implementation |
| `backend/etl/global/retail_intelligence_config.py` | Column schema definitions |
| `backend/etl/global/build_global_matrix.py` | Matrix ETL (how columns are built) |
| `docs/CASCADE_SEARCH.md` | This documentation |

