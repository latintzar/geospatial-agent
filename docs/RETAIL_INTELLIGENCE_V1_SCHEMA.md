# Retail Intelligence v1 Schema

## Overview

**Retail Intelligence** is a lean, focused Earth Matrix schema optimized for **retail site selection**. It captures the "DNA" of locations with ~120 columns instead of 444, reducing global compute costs by 70%+ while retaining 90%+ of retail-relevant signals.

---

## Target Use Case

| Aspect | Description |
|--------|-------------|
| **Primary Users** | Fast-growing retail brands, site selection teams |
| **Goal** | Find new store locations by analyzing DNA of successful ones |
| **Method** | NL search + vector similarity matching |
| **Key Question** | "Where are streets similar to our best-performing stores?" |

---

## Design Principles

1. **Foot Traffic Over Features** - Cafes matter more than coastlines
2. **Vibe Over Volume** - Lifestyle signals over raw counts
3. **Accessibility Over Aesthetics** - Transit and parking over parks
4. **80/20 Rule** - 20% of features capture 80% of retail value

---

## Schema Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ RETAIL INTELLIGENCE v1 - SCHEMA OVERVIEW                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ SECTION A: POI SIGNALS (~147 columns)                                       │
│ ├── A1: Foot Traffic POIs (5 categories × 5 cols = 25)                      │
│ ├── A2: Transit Access POIs (4 categories × 5 cols = 20)                    │
│ ├── A3: Retail Ecosystem POIs (5 categories × 5 cols = 25)                  │
│ ├── A4: Lifestyle/Vibe POIs (6 categories × 5 cols = 30)                    │
│ ├── A5: Culture/Entertainment POIs (4 categories × 5 cols = 20)             │
│ ├── A6: Essential Services POIs (5 categories × 5 cols = 25)                │
│ └── A7: Top-Level Aggregates (22 categories × 1 col = 22)                   │
│                                                                             │
│ SECTION B: BUILT ENVIRONMENT (~19 columns)                                  │
│ ├── B1: Buildings (4 cols)                                                  │
│ ├── B2: Land Use (5 classes × 2 cols = 10)                                  │
│ └── B3: Transportation (5 cols)                                             │
│                                                                             │
│ SECTION C: ACCESSIBILITY & PREMIUM (~21 columns)                            │
│ ├── C1: Parking & EV (4 cols)                                               │
│ ├── C2: Green Premium - Parks (7 cols)                                      │
│ └── C3: Blue Premium - Beaches & Water (10 cols)                            │
│                                                                             │
│ TOTAL: ~210 columns                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Section A: POI Signals

### A1: Foot Traffic POIs (25 columns)

These are the strongest indicators of walkable, high-traffic areas.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `cafe` | `categories.primary = 'cafe'` | Coffee culture = walkability, remote workers | 5 |
| `restaurant` | `categories.primary = 'restaurant'` | Dining destination, evening traffic | 5 |
| `bar` | `categories.primary = 'bar'` | Nightlife, social scene | 5 |
| `fast_food` | `categories.primary LIKE '%fast_food%'` | Quick service, high turnover | 5 |
| `bakery` | `categories.primary = 'bakery'` | Morning foot traffic, neighborhood feel | 5 |

**Column Pattern (per category):**
```
{category}_count        → Count in this hex
{category}_walk_min     → Walking minutes to nearest
{category}_cycle_min    → Cycling minutes to nearest  
{category}_drive_min    → Driving minutes to nearest
{category}_score        → 0-10 decay score for ranking
```

**SQL for matching:**
```sql
-- Cafe matching (includes coffee shops, tea rooms)
categories.primary IN ('cafe', 'coffee_shop', 'tea_room', 'coffee_roaster')

-- Restaurant matching
categories.primary = 'restaurant' OR categories.primary LIKE '%_restaurant'

-- Bar matching (includes pubs, nightclubs)
categories.primary IN ('bar', 'pub', 'nightclub', 'lounge', 'beer_bar', 
                       'wine_bar', 'cocktail_bar', 'sports_bar')

-- Fast food matching
categories.primary IN ('fast_food_restaurant', 'burger_restaurant', 
                       'pizza_restaurant', 'doner_kebab', 'hot_dog_restaurant')

-- Bakery matching
categories.primary IN ('bakery', 'patisserie', 'bagel_shop', 'donut_shop')
```

---

### A2: Transit Access POIs (20 columns)

How people get to the location - critical for catchment area.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `subway` | `categories.primary = 'subway_station'` | Urban commuter access | 5 |
| `train` | `categories.primary = 'train_station'` | Regional/intercity access | 5 |
| `bus` | `categories.primary = 'bus_station'` | Local transit | 5 |
| `airport` | `categories.primary = 'airport'` | Tourist/business travel | 5 |

**SQL for matching:**
```sql
-- Subway/Metro (includes underground, tube, metro)
categories.primary IN ('subway_station', 'metro_station', 'underground_station')

-- Train
categories.primary IN ('train_station', 'railway_station', 'railway_halt')

-- Bus
categories.primary IN ('bus_station', 'bus_stop')

-- Airport (include terminals)
categories.primary IN ('airport', 'airport_terminal', 'airline_ticket_agency')
```

---

### A3: Retail Ecosystem POIs (25 columns)

Complementary retail and anchor tenants.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `supermarket` | `categories.primary = 'supermarket'` | Anchor tenant, daily traffic | 5 |
| `shopping_mall` | `categories.primary = 'shopping_mall'` | Major destination | 5 |
| `convenience` | `categories.primary = 'convenience_store'` | Neighborhood retail | 5 |
| `clothing` | `categories.primary LIKE '%clothing%'` | Fashion retail cluster | 5 |
| `electronics` | `categories.primary LIKE '%electronics%'` | Tech retail cluster | 5 |

**SQL for matching:**
```sql
-- Supermarket (includes grocery)
categories.primary IN ('supermarket', 'grocery_store', 'food', 'farmers_market')

-- Shopping mall
categories.primary IN ('shopping_mall', 'shopping_center', 'department_store', 
                       'outlet_mall', 'shopping')

-- Convenience store
categories.primary IN ('convenience_store', 'drugstore', 'newsagent')

-- Clothing
categories.primary LIKE '%clothing%' OR categories.primary IN 
  ('fashion', 'boutique', 'shoe_store', 'lingerie_store')

-- Electronics
categories.primary IN ('electronics_store', 'computer_store', 'mobile_phone_store')
```

---

### A4: Lifestyle/Vibe POIs (30 columns)

Character and demographic signals.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `gym` | `categories.primary = 'gym'` | Health-conscious, active lifestyle | 5 |
| `yoga` | `categories.primary = 'yoga_studio'` | Wellness, higher income | 5 |
| `spa` | `categories.primary = 'spa'` | Premium lifestyle, self-care | 5 |
| `beauty_salon` | `categories.primary = 'beauty_salon'` | Personal care frequency | 5 |
| `nail_salon` | `categories.primary = 'nail_salon'` | Regular services | 5 |
| `barber` | `categories.primary = 'barber'` | Traditional/male demographics | 5 |

**SQL for matching:**
```sql
-- Gym/Fitness
categories.primary IN ('gym', 'fitness_center', 'health_club', 'crossfit',
                       'boxing_gym', 'martial_arts', 'pilates')

-- Yoga/Wellness
categories.primary IN ('yoga_studio', 'meditation_center', 'wellness_center')

-- Spa
categories.primary IN ('spa', 'health_spa', 'day_spa', 'massage', 'sauna')

-- Beauty salon
categories.primary IN ('beauty_salon', 'hair_salon', 'makeup_artist')

-- Nail salon
categories.primary IN ('nail_salon', 'manicure', 'pedicure')

-- Barber
categories.primary IN ('barber', 'barbershop')
```

---

### A5: Culture/Entertainment POIs (20 columns)

Quality of life and experience economy.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `cinema` | `categories.primary = 'cinema'` | Entertainment destination | 5 |
| `museum` | `categories.primary = 'museum'` | Cultural/tourist area | 5 |
| `art_gallery` | `categories.primary = 'art_gallery'` | Creative/artsy vibe | 5 |
| `theater` | `categories.primary LIKE '%theater%'` | Performing arts | 5 |

**SQL for matching:**
```sql
-- Cinema
categories.primary IN ('cinema', 'movie_theater', 'drive_in_theater')

-- Museum
categories.primary IN ('museum', 'science_museum', 'art_museum', 
                       'history_museum', 'childrens_museum')

-- Art gallery
categories.primary IN ('art_gallery', 'gallery', 'exhibition_space')

-- Theater/Performing arts
categories.primary IN ('theater', 'performing_arts', 'opera_house', 
                       'concert_hall', 'comedy_club', 'music_venue')
```

---

### A6: Essential Services POIs (25 columns)

Baseline commercial activity indicators.

| Category | Overture Match | Retail Signal | Columns |
|----------|----------------|---------------|---------|
| `bank` | `categories.primary = 'bank'` | Commercial activity center | 5 |
| `atm` | `categories.primary = 'atm'` | Cash access points | 5 |
| `pharmacy` | `categories.primary = 'pharmacy'` | Daily needs, health | 5 |
| `hospital` | `categories.primary = 'hospital'` | Major anchor, employee base | 5 |
| `post_office` | `categories.primary = 'post_office'` | Civic hub | 5 |

**SQL for matching:**
```sql
-- Bank
categories.primary IN ('bank', 'bank_credit_union', 'credit_union')

-- ATM
categories.primary IN ('atm', 'atms', 'cash_machine')

-- Pharmacy
categories.primary IN ('pharmacy', 'drugstore', 'chemist')

-- Hospital
categories.primary IN ('hospital', 'medical_center', 'emergency_room', 
                       'urgent_care_clinic', 'clinic')

-- Post office
categories.primary IN ('post_office', 'postal_service')
```

---

### A7: Top-Level Aggregates (22 columns)

High-level category counts for broad characterization.

| Category | Column | Description |
|----------|--------|-------------|
| eat_and_drink | `cat_eatanddrink_count` | Total food/drink POIs |
| accommodation | `cat_accommodation_count` | Hotels, hostels |
| active_life | `cat_activelife_count` | Sports, fitness |
| arts_and_entertainment | `cat_artsandentertainment_count` | Entertainment venues |
| attractions_and_activities | `cat_attractions_count` | Tourist spots |
| automotive | `cat_automotive_count` | Car-related |
| beauty_and_spa | `cat_beautyandspa_count` | Personal care |
| business_to_business | `cat_b2b_count` | B2B services |
| education | `cat_education_count` | Schools, universities |
| financial_service | `cat_financial_count` | Banks, insurance |
| health_and_medical | `cat_health_count` | Healthcare |
| home_service | `cat_homeservice_count` | Home services |
| mass_media | `cat_media_count` | Media companies |
| pets | `cat_pets_count` | Pet services |
| private_establishments | `cat_private_count` | Corporate |
| professional_services | `cat_professional_count` | Professional services |
| public_service_and_government | `cat_government_count` | Government |
| real_estate | `cat_realestate_count` | Real estate |
| religious_organization | `cat_religious_count` | Religious |
| retail | `cat_retail_count` | Retail stores |
| structure_and_geography | `cat_structure_count` | Landmarks |
| travel | `cat_travel_count` | Travel services |

**Total A7:** 22 columns (count only, no travel time)

---

## Section B: Built Environment

### B1: Buildings (4 columns)

| Column | Description | Retail Signal |
|--------|-------------|---------------|
| `building_density` | Buildings per hex | Urbanization level |
| `avg_building_height` | Mean height (m) | Urban vs suburban |
| `urban_volume` | Total built volume (m³) | Development intensity |
| `avg_floors` | Average floor count | Commercial potential |

**Source:** `theme = 'buildings'`, `type = 'building'`

---

### B2: Land Use (10 columns)

Only the 5 most retail-relevant land use classes:

| Class | Columns | Retail Signal |
|-------|---------|---------------|
| `commercial` | count, area_m2 | Business district |
| `residential` | count, area_m2 | Population catchment |
| `retail` | count, area_m2 | Shopping zones |
| `industrial` | count, area_m2 | Avoid signal (usually) |
| `park` | count, area_m2 | Quality of life, foot traffic |

**Excluded (low retail value):**
- forest, farmland, vineyard (rural)
- military, cemetery, quarry (special use)
- recreation_ground, golf_course (specific)
- meadow, grass, orchard (agricultural)

---

### B3: Transportation (5 columns)

| Column | Description | Retail Signal |
|--------|-------------|---------------|
| `road_density` | Roads per hex | Car accessibility |
| `major_road_density` | Primary/secondary roads | Main arterial access |
| `pedestrian_density` | Footways, paths | Walkability |
| `cycleway_density` | Bike infrastructure | Cycle-friendly |
| `parking_density` | Parking areas | Driving destination |

**Source:** `theme = 'transportation'`, `type = 'segment'`

---

## Section C: Accessibility & Premium Features

### C1: Parking & EV (4 columns)

| Column | Description | Retail Signal |
|--------|-------------|---------------|
| `parking_count` | Parking facilities | Driving destination |
| `parking_walk_min` | Walk to nearest | Parking convenience |
| `ev_charging_count` | EV charging stations | Future-ready, eco-conscious |
| `ev_charging_walk_min` | Walk to nearest charger | EV driver catchment |

**Source:** Infrastructure + POIs

---

### C2: Green Premium - Parks (7 columns)

Parks are high-value signals: foot traffic, quality of life, property values.

| Column | Description | Retail Signal |
|--------|-------------|---------------|
| `park_count` | Distinct parks in/touching hex | Variety of green spaces |
| `park_in_hex_m2` | Total park area in hex | Green space presence |
| `park_avg_area_m2` | Average size of nearby parks | Pocket parks vs destination parks |
| `park_walk_min` | Walk to nearest park (any size) | Immediate green access |
| `park_cycle_min` | Cycle to nearest park | Larger catchment |
| `park_20k_walk_min` | Walk to park ≥20,000 m² | "Real" park (not traffic island) |
| `park_20k_cycle_min` | Cycle to park ≥20,000 m² | Cycling to real parks |

**Size Tiers:**
- `any` = Any size park
- `20k` = ≥20,000 m² = A proper park (Central Park is 3.4M m²)

**Source:** `theme = 'base'`, `type = 'land_use'`, `class = 'park'`

**SQL for hex fill:**
```sql
SELECT 
    polygon_id,
    ST_Area_Spheroid(geometry) as polygon_area_m2,
    h3_polygon_to_cells(geometry, 12) as hex_array
FROM land_use WHERE class = 'park'
```

---

### C3: Blue Premium - Beaches & Water (10 columns)

Coastal and waterfront locations command premium - tourism, lifestyle, seasonal traffic.

| Column | Description | Retail Signal |
|--------|-------------|---------------|
| `beach_count` | Beaches in/touching hex | Coastal location |
| `beach_in_hex_m2` | Beach area in hex | Direct beachfront |
| `beach_avg_area_m2` | Average beach size | Beach destination size |
| `beach_walk_min` | Walk to nearest beach | Beach proximity |
| `beach_cycle_min` | Cycle to nearest beach | Beach catchment |
| `beach_drive_min` | Drive to nearest beach | Coastal appeal (tourists) |
| `water_nearby` | Boolean: any water within 500m | General waterfront |
| `waterfront` | Boolean: directly on water body | Premium waterfront |
| `lake_walk_min` | Walk to nearest lake | Lake access |
| `coastline_walk_min` | Walk to sea/ocean | Ocean coastal access |

**Source:** 
- Beach: `class = 'beach'` (land_use) or `natural:beach` tag
- Water: `theme = 'base'`, `type = 'water'`

**SQL for beach travel time (buffer rings):**
```sql
-- Create 500m buffer around beach polygons
WITH beach_buffer AS (
    SELECT ST_Buffer(geometry, 500) as buffer_500m,
           ST_Buffer(geometry, 1000) as buffer_1km
    FROM land_use WHERE class = 'beach'
)
-- Fill buffer rings with H3 hexes
SELECT h3_polygon_to_cells(buffer_500m, 12) as walk_6min_hexes
FROM beach_buffer
```

---

## Complete Column List

```python
RETAIL_INTELLIGENCE_V1_COLUMNS = {
    # =========================================================================
    # A1: FOOT TRAFFIC POIs (25 columns)
    # =========================================================================
    "cafe_count", "cafe_walk_min", "cafe_cycle_min", "cafe_drive_min", "cafe_score",
    "restaurant_count", "restaurant_walk_min", "restaurant_cycle_min", "restaurant_drive_min", "restaurant_score",
    "bar_count", "bar_walk_min", "bar_cycle_min", "bar_drive_min", "bar_score",
    "fast_food_count", "fast_food_walk_min", "fast_food_cycle_min", "fast_food_drive_min", "fast_food_score",
    "bakery_count", "bakery_walk_min", "bakery_cycle_min", "bakery_drive_min", "bakery_score",
    
    # =========================================================================
    # A2: TRANSIT ACCESS POIs (20 columns)
    # =========================================================================
    "subway_count", "subway_walk_min", "subway_cycle_min", "subway_drive_min", "subway_score",
    "train_count", "train_walk_min", "train_cycle_min", "train_drive_min", "train_score",
    "bus_count", "bus_walk_min", "bus_cycle_min", "bus_drive_min", "bus_score",
    "airport_count", "airport_walk_min", "airport_cycle_min", "airport_drive_min", "airport_score",
    
    # =========================================================================
    # A3: RETAIL ECOSYSTEM POIs (25 columns)
    # =========================================================================
    "supermarket_count", "supermarket_walk_min", "supermarket_cycle_min", "supermarket_drive_min", "supermarket_score",
    "shopping_mall_count", "shopping_mall_walk_min", "shopping_mall_cycle_min", "shopping_mall_drive_min", "shopping_mall_score",
    "convenience_count", "convenience_walk_min", "convenience_cycle_min", "convenience_drive_min", "convenience_score",
    "clothing_count", "clothing_walk_min", "clothing_cycle_min", "clothing_drive_min", "clothing_score",
    "electronics_count", "electronics_walk_min", "electronics_cycle_min", "electronics_drive_min", "electronics_score",
    
    # =========================================================================
    # A4: LIFESTYLE/VIBE POIs (30 columns)
    # =========================================================================
    "gym_count", "gym_walk_min", "gym_cycle_min", "gym_drive_min", "gym_score",
    "yoga_count", "yoga_walk_min", "yoga_cycle_min", "yoga_drive_min", "yoga_score",
    "spa_count", "spa_walk_min", "spa_cycle_min", "spa_drive_min", "spa_score",
    "beauty_salon_count", "beauty_salon_walk_min", "beauty_salon_cycle_min", "beauty_salon_drive_min", "beauty_salon_score",
    "nail_salon_count", "nail_salon_walk_min", "nail_salon_cycle_min", "nail_salon_drive_min", "nail_salon_score",
    "barber_count", "barber_walk_min", "barber_cycle_min", "barber_drive_min", "barber_score",
    
    # =========================================================================
    # A5: CULTURE/ENTERTAINMENT POIs (20 columns)
    # =========================================================================
    "cinema_count", "cinema_walk_min", "cinema_cycle_min", "cinema_drive_min", "cinema_score",
    "museum_count", "museum_walk_min", "museum_cycle_min", "museum_drive_min", "museum_score",
    "art_gallery_count", "art_gallery_walk_min", "art_gallery_cycle_min", "art_gallery_drive_min", "art_gallery_score",
    "theater_count", "theater_walk_min", "theater_cycle_min", "theater_drive_min", "theater_score",
    
    # =========================================================================
    # A6: ESSENTIAL SERVICES POIs (25 columns)
    # =========================================================================
    "bank_count", "bank_walk_min", "bank_cycle_min", "bank_drive_min", "bank_score",
    "atm_count", "atm_walk_min", "atm_cycle_min", "atm_drive_min", "atm_score",
    "pharmacy_count", "pharmacy_walk_min", "pharmacy_cycle_min", "pharmacy_drive_min", "pharmacy_score",
    "hospital_count", "hospital_walk_min", "hospital_cycle_min", "hospital_drive_min", "hospital_score",
    "post_office_count", "post_office_walk_min", "post_office_cycle_min", "post_office_drive_min", "post_office_score",
    
    # =========================================================================
    # A7: TOP-LEVEL AGGREGATES (22 columns - count only)
    # =========================================================================
    "cat_eatanddrink_count",
    "cat_accommodation_count",
    "cat_activelife_count",
    "cat_artsandentertainment_count",
    "cat_attractions_count",
    "cat_automotive_count",
    "cat_beautyandspa_count",
    "cat_b2b_count",
    "cat_education_count",
    "cat_financial_count",
    "cat_health_count",
    "cat_homeservice_count",
    "cat_media_count",
    "cat_pets_count",
    "cat_private_count",
    "cat_professional_count",
    "cat_government_count",
    "cat_realestate_count",
    "cat_religious_count",
    "cat_retail_count",
    "cat_structure_count",
    "cat_travel_count",
    
    # =========================================================================
    # B1: BUILDINGS (4 columns)
    # =========================================================================
    "building_density",
    "avg_building_height",
    "urban_volume",
    "avg_floors",
    
    # =========================================================================
    # B2: LAND USE (10 columns)
    # =========================================================================
    "commercial_count", "commercial_area_m2",
    "residential_count", "residential_area_m2",
    "retail_land_count", "retail_land_area_m2",
    "industrial_count", "industrial_area_m2",
    "park_count", "park_area_m2",
    
    # =========================================================================
    # B3: TRANSPORTATION (5 columns)
    # =========================================================================
    "road_density",
    "major_road_density",
    "pedestrian_density",
    "cycleway_density",
    "parking_density",
    
    # =========================================================================
    # C1: PARKING & EV (4 columns)
    # =========================================================================
    "parking_count",
    "parking_walk_min",
    "ev_charging_count",
    "ev_charging_walk_min",
    
    # =========================================================================
    # C2: GREEN PREMIUM - PARKS (7 columns)
    # =========================================================================
    "park_count",           # Distinct parks in hex
    "park_in_hex_m2",       # Total park area
    "park_avg_area_m2",     # Average park size
    "park_walk_min",        # Walk to nearest park
    "park_cycle_min",       # Cycle to nearest park
    "park_20k_walk_min",    # Walk to "real" park (≥20k m²)
    "park_20k_cycle_min",   # Cycle to "real" park
    
    # =========================================================================
    # C3: BLUE PREMIUM - BEACHES & WATER (10 columns)
    # =========================================================================
    "beach_count",          # Beaches in hex
    "beach_in_hex_m2",      # Beach area in hex
    "beach_avg_area_m2",    # Average beach size
    "beach_walk_min",       # Walk to beach
    "beach_cycle_min",      # Cycle to beach
    "beach_drive_min",      # Drive to beach
    "water_nearby",         # Boolean: water within 500m
    "waterfront",           # Boolean: directly on water
    "lake_walk_min",        # Walk to nearest lake
    "coastline_walk_min",   # Walk to coastline
}

# TOTAL: ~210 columns
```

---

## Compute Savings Analysis

| Component | Full v5 | Retail Intelligence v1 | Reduction |
|-----------|---------|------------------------|-----------|
| POI Specific Categories | 35 | 29 | -17% |
| POI Specific Columns | 175 | 145 | -17% |
| POI Top-Level Columns | 110 | 22 | -80% |
| Land Use Classes | 20 | 5 | -75% |
| Land Use Columns | 60 | 10 | -83% |
| Infrastructure K-ring | 30 | 4 | -87% |
| Water/Natural | 67 | 20 | -70% |
| **TOTAL COLUMNS** | **~444** | **~210** | **-53%** |

### Green & Blue Premium (NEW)

| Feature | Columns | Compute Method |
|---------|---------|----------------|
| Parks (hex fill) | 3 | Polygon fill at res 12 |
| Parks (travel time) | 4 | Buffer rings (walk, cycle) |
| Beaches (hex fill) | 3 | Polygon fill at res 12 |
| Beaches (travel time) | 3 | Buffer rings (walk, cycle, drive) |
| Water (proximity) | 4 | Buffer rings for lake/coastline |
| **SUBTOTAL** | **17** | +2 polygon fills, +2 buffer ring calcs |

### Processing Reduction

| Operation | Full v5 | Retail v1 | Savings |
|-----------|---------|-----------|---------|
| Polygon fills (land use) | 20 classes | 5 classes | 75% |
| Buffer ring calculations | 10 features | 1 feature (park) | 90% |
| K-ring propagation | 41 features | 29 features | 29% |
| **S3 read (water theme)** | Full | Minimal | ~95% |
| **S3 read (infrastructure)** | Full | Minimal | ~90% |

### Cost Estimate

| Geography | Full v5 | Retail v1 | Savings |
|-----------|---------|-----------|---------|
| France | $30-40 | **$10-15** | 65% |
| Western Europe | $150-200 | **$50-75** | 65% |
| Europe + US | $400-500 | **$150-200** | 60% |
| **Global** | $1,500-2,500 | **$500-800** | 65% |

*Note: Includes Green & Blue Premium (parks + beaches + water) which adds ~15% compute vs minimal schema.*

---

## DNA Matching Algorithm

With this schema, each hex has a ~167-dimensional vector. Site selection works by:

### 1. Analyze Successful Locations

```python
# Get DNA vectors for top-performing stores
successful_dna = matrix.filter(h3_index IN successful_store_hexes).mean()
```

### 2. Find Similar Locations

```python
# Cosine similarity search
from sklearn.metrics.pairwise import cosine_similarity

candidates = matrix.filter(
    # Pre-filter for basics
    cafe_count > 0 AND
    subway_walk_min < 10 AND
    building_density > 50
)

# Compute similarity
similarity = cosine_similarity(candidates.dna_vector, successful_dna)

# Rank by similarity
results = candidates.order_by(similarity.desc()).limit(100)
```

### 3. NL Query Examples

| Query | Filter Logic |
|-------|--------------|
| "Like our SoHo store" | Cosine similarity to SoHo hex DNA |
| "High foot traffic near transit" | `cafe_count > 5 AND subway_walk_min < 5` |
| "Upscale wellness neighborhood" | `spa_count > 0 AND yoga_count > 0 AND gym_score > 5` |
| "Suburban with parking" | `residential_area_m2 > 50000 AND parking_count > 0` |
| "University town" | `cat_education_count > 5 AND bar_count > 3` |

---

## Multi-Resolution Strategy

| Resolution | Hex Size | Use Case | Key Columns |
|------------|----------|----------|-------------|
| **Res 5** | ~253 km² | Regional analysis | All drive_min columns |
| **Res 8** | ~0.74 km² | City/district | drive_min, cycle_min |
| **Res 10** | ~0.02 km² | Neighborhood | cycle_min, walk_min |
| **Res 11** | ~0.002 km² | Street-level | walk_min, counts |

### Cascading Search

```
1. Res 5 → "Cities with retail potential" (top 25%)
           Filter: cat_retail_count > P75, airport_drive_min < 60
           
2. Res 8 → "Districts within those cities" (top 25% of Res 5 results)
           Filter: subway_cycle_min < 15, shopping_mall_drive_min < 10
           
3. Res 10 → "Neighborhoods" (top 25% of Res 8 results)
            Filter: cafe_walk_min < 5, gym_score > 5
            
4. Res 11 → "Exact streets" (final ranking)
            Rank by: cosine_similarity(dna, successful_store_dna)
```

---

## Implementation Priority

### Phase 1: Core POIs (Week 1)
- [ ] A1: Foot Traffic (cafe, restaurant, bar, fast_food, bakery)
- [ ] A2: Transit (subway, train, bus, airport)
- [ ] A3: Retail Ecosystem (supermarket, mall, convenience, clothing, electronics)

### Phase 2: Lifestyle + Essentials (Week 1-2)
- [ ] A4: Lifestyle (gym, yoga, spa, beauty, nail, barber)
- [ ] A5: Culture (cinema, museum, gallery, theater)
- [ ] A6: Essentials (bank, atm, pharmacy, hospital, post_office)

### Phase 3: Built Environment (Week 2)
- [ ] A7: Top-level aggregates
- [ ] B1: Buildings
- [ ] B2: Land Use (5 classes)
- [ ] B3: Transportation

### Phase 4: Accessibility (Week 2)
- [ ] C1: Parking
- [ ] C2: EV Charging
- [ ] C3: Green Space

### Phase 5: Multi-Resolution (Week 3)
- [ ] Build Res 12 base layer
- [ ] Aggregate to Res 5, 8, 10, 11
- [ ] Test cascading search

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `backend/etl/build_retail_matrix.py` | New ETL script |
| `backend/etl/retail_intelligence_config.py` | Schema configuration |
| `docs/RETAIL_INTELLIGENCE_V1_SCHEMA.md` | This document |
| `backend/tools/overture_schema.py` | Add RETAIL_POI_CATEGORIES |

---

*Document Version: 1.0*
*Created: 2024-12-21*
*Author: Leo ETL Pipeline*

