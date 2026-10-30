#!/usr/bin/env python3
"""
Cascade Multi-Resolution Search
================================

4-stage filtering cascade across H3 resolutions 5 → 8 → 10 for location search.

=============================================================================
COLUMN TYPES IN THE MATRIX (from build_global_matrix.py)
=============================================================================

| Column Type       | Count | What It Tells You                              |
|-------------------|-------|------------------------------------------------|
| h3_index          | 1     | Which hexagon - unique ID of this spot         |
| *_count           | 226   | What's here - POI/feature counts IN this hex   |
| *_walk_min        | 223   | Walking time - minutes to walk to nearest      |
| *_cycle_min       | 220   | Biking time - minutes to bike to nearest       |
| *_drive_min       | 218   | Driving time - minutes to drive to nearest     |
| *_score           | 218   | Convenience score - 0-10 decay (0=unreachable) |
| *_in_hex_m2       | 12    | Land use - square meters in this hex           |
| *_avg_area_m2     | 4     | Average size - typical size of features        |
| avg_building_height| 1    | Building height in meters                      |
| avg_floors        | 1     | Building floors - stories                      |
| building_density  | 1     | Built-up % - coverage by buildings             |

=============================================================================
HOW COLUMNS ARE USED IN EACH STAGE
=============================================================================

STAGE 1 - SUMMATIVE (Res 5): "What's in this city zone?"
  Method: SUM columns → rank → keep top 25%
  Columns:
    - *_count      → density of POIs (cafe_count, restaurant_count)
    - *_in_hex_m2  → land use area (park_in_hex_m2, residential_in_hex_m2)
    - building_*   → built environment metrics
  
STAGE 2 - MULTIPLICATIVE (Res 8): "Are ALL requested features accessible?"
  Method: MULTIPLY scores → product=0 means eliminated
  Columns:
    - *_score for ALL summative features + driving_must_haves
    - Scale: 0-10 (0=unreachable, 10=in-hex)
  Key insight: pub_score × pharmacy_score → if EITHER is 0, product=0 → eliminated
  Purpose: Filters out hexes where requested features aren't actually accessible
  
STAGE 3 - MULTIPLICATIVE (Res 10): "Can I walk there in ~15 min?"
  Method: MULTIPLY scores → product=0 means eliminated
  Columns:
    - *_score      → 0-10 with proper decay curves (0/NULL=unreachable)
    - {transit}_score → metro_station_score, train_station_score, etc.
    - {green}_score   → park_score, forest_score, etc.
  Key insight: metro_station_score × park_score → BOTH must be walkable

STAGE 4 - SUMMATIVE (Res 10): "How good is this spot?"
  Method: SUM counts → percentile rank → heatmap color
  Columns:
    - *_count      → density ranking (more cafes = better)
    - *_score      → could also sum scores for proximity ranking

=============================================================================
THE MAGIC OF MULTIPLICATION
=============================================================================

Why multiply instead of filter?

  Traditional: WHERE hospital_drive_min < 40 AND subway_walk_min < 15
  Problem: Hard cutoffs, binary yes/no

  Multiplicative: score = hospital_score × subway_score × cafe_score
  Benefits:
    - If ANY is 0 (unreachable) → total = 0 → naturally eliminated
    - If ALL are high → total is high → better ranking
    - Scores decay with distance, so closer = higher product

  Score scale (from build_global_matrix.py):
    k=0:          score = 10  (feature IN the hex)
    k=decay_knee: score = 1   (still reachable but far)
    k=max_k:      score = 0   (unreachable, beyond propagation range)

See docs/CASCADE_SEARCH.md for full documentation.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Tuple, AsyncGenerator
from pathlib import Path

import h3
import pandas as pd
import duckdb

# Import area insights for cluster generation
from backend.tools.tools_area_insights import generate_area_insights, clusters_to_json

logger = logging.getLogger(__name__)

# =============================================================================
# PATHS
# =============================================================================

# Matrix directory - use London matrix (4,094 hexes) instead of Hoxton (10 hexes)
MATRIX_DIR = Path(__file__).parent.parent.parent / "output" / "earth_matrix_london"

# =============================================================================
# COLUMN MAPPING LAYER
# =============================================================================

# Transit aliases: human terms → column prefix
# NOTE: Column names in the matrix are based on Overture category names
TRANSIT_ALIASES = {
    # Subway/Tube/Metro → maps to metro_station (Overture category)
    "tube": "metro_station",
    "tube station": "metro_station", 
    "underground": "metro_station",
    "metro": "metro_station",
    "metro station": "metro_station",
    "subway": "metro_station",
    "subway station": "metro_station",
    # Train
    "train": "train_station",
    "train station": "train_station",
    "railway": "train_station",
    "railway station": "train_station",
    "rail": "train_station",
    # Bus
    "bus": "bus_station",
    "bus station": "bus_station",
    "bus stop": "bus_station",
    # Tram
    "tram": "tram_stop",
    "tram stop": "tram_stop",
    "streetcar": "tram_stop",
    # Light rail
    "light rail": "light_rail_station",
    "light_rail": "light_rail_station",
    "light rail station": "light_rail_station",
    "dlr": "light_rail_station",
    "overground": "light_rail_station",
    # Ferry
    "ferry": "ferry_terminal",
    "ferry terminal": "ferry_terminal",
    "boat": "ferry_terminal",
    # Airport
    "airport": "airport",
    "flight": "airport",
}

# Green feature aliases
GREEN_ALIASES = {
    "park": "park",
    "parks": "park",
    "green space": "park",
    "pocket park": "park_small",
    "small park": "park_small",
    "decent park": "park_20k",
    "decent-sized park": "park_20k",
    "good park": "park_20k",
    "large park": "park_2m",
    "big park": "park_2m",
    "major park": "park_20m",
    "huge park": "park_20m",
    "forest": "forest",
    "woods": "forest",
    "woodland": "forest",
    "beach": "beach",
    "seaside": "beach",
    "nature reserve": "nature_reserve",
    "nature": "nature_reserve",
    "protected area": "nature_reserve",
}

# Blue feature aliases  
BLUE_ALIASES = {
    "lake": "lake",
    "pond": "lake",
    "large lake": "lake_2m",
    "big lake": "lake_2m",
    "river": "river",
    "stream": "river",
    "coast": "coastline",
    "coastline": "coastline",
    "seafront": "coastline",
    "waterfront": "coastline",
    "marina": "marina",
    "harbour": "marina",
    "harbor": "marina",
}

# POI aliases (common variations)
POI_ALIASES = {
    # Coffee
    "coffee": "cafe",
    "coffee shop": "coffee_shop",
    "coffee shops": "coffee_shop",
    "coffeeshop": "coffee_shop",
    "specialty coffee": "specialty_coffee",
    "third wave coffee": "third_wave_coffee",
    # Bars
    "pub": "pub",
    "pubs": "pub",
    "wine bar": "wine_bar",
    "cocktail bar": "cocktail_bar",
    "cocktail lounge": "cocktail_bar",
    "rooftop bar": "rooftop_bar",
    "beer garden": "beer_garden",
    "nightclub": "nightclub",
    "club": "nightclub",
    # Food
    "restaurant": "restaurant",
    "restaurants": "restaurant",
    "sushi": "sushi_restaurant",
    "sushi restaurant": "sushi_restaurant",
    "ramen": "ramen_restaurant",
    "ramen shop": "ramen_restaurant",
    "izakaya": "izakaya",
    "italian": "italian_restaurant",
    "italian restaurant": "italian_restaurant",
    # Health
    "hospital": "hospital",
    "hospitals": "hospital",
    "pharmacy": "pharmacy",
    "chemist": "pharmacy",
    "drugstore": "pharmacy",
    "doctor": "doctor",
    "gp": "doctor",
    "dentist": "dentist",
    "pediatrician": "pediatrician",
    "children's hospital": "childrens_hospital",
    # Education
    "school": "school",
    "schools": "school",
    "primary school": "elementary_school",
    "elementary school": "elementary_school",
    "nursery": "nursery",
    "kindergarten": "kindergarten",
    "university": "university",
    "college": "college",
    "library": "library",
    # Fitness
    "gym": "gym",
    "gyms": "gym",
    "fitness": "fitness_center",
    "yoga": "yoga_studio",
    "yoga studio": "yoga_studio",
    "climbing gym": "climbing_gym",
    "bouldering": "bouldering_gym",
    "swimming pool": "swimming_pool",
    "pool": "swimming_pool",
    "tennis": "tennis_court",
    "tennis court": "tennis_court",
    # Retail
    "supermarket": "supermarket",
    "grocery": "grocery_store",
    "grocery store": "grocery_store",
    "convenience store": "convenience_store",
    "corner shop": "convenience_store",
    "farmers market": "farmers_market",
    "organic grocery": "organic_grocery",
    # EV
    "ev charging": "ev_charging_station",
    "ev charger": "ev_charging_station",
    "electric vehicle charging": "ev_charging_station",
    "tesla supercharger": "tesla_supercharger",
    # Other
    "coworking": "coworking_space",
    "coworking space": "coworking_space",
    "playground": "playground",
    "dog park": "dog_park",
}

# Road aliases
ROAD_ALIASES = {
    "pedestrian": "pedestrian",
    "pedestrian street": "pedestrian",
    "pedestrian zone": "pedestrian",
    "bike lane": "cycleway",
    "bike path": "cycleway",
    "cycleway": "cycleway",
    "cycle path": "cycleway",
    "footpath": "footway",
    "footway": "footway",
    "living street": "living_street",
    "motorway": "motorway_road",
    "highway": "motorway_road",
    "trunk road": "trunk_road",
    "main road": "primary_road",
    "primary road": "primary_road",
    "secondary road": "secondary_road",
}


def normalize_feature(feature: str, feature_type: str = "auto") -> str:
    """
    Normalize a feature name from Gemini output to actual column prefix.
    
    Args:
        feature: Raw feature string from Gemini (e.g., "Tube station", "coffee shops")
        feature_type: One of "transit", "green", "blue", "poi", "road", "auto"
        
    Returns:
        Normalized column prefix (e.g., "metro_station", "cafe")
    """
    # Lowercase and strip
    f = feature.lower().strip()
    
    # Try specific alias dict first
    if feature_type == "transit" or feature_type == "auto":
        if f in TRANSIT_ALIASES:
            return TRANSIT_ALIASES[f]
    
    if feature_type == "green" or feature_type == "auto":
        if f in GREEN_ALIASES:
            return GREEN_ALIASES[f]
            
    if feature_type == "blue" or feature_type == "auto":
        if f in BLUE_ALIASES:
            return BLUE_ALIASES[f]
            
    if feature_type == "poi" or feature_type == "auto":
        if f in POI_ALIASES:
            return POI_ALIASES[f]
            
    if feature_type == "road" or feature_type == "auto":
        if f in ROAD_ALIASES:
            return ROAD_ALIASES[f]
    
    # If not found in aliases, return as-is with underscores
    return f.replace(" ", "_").replace("-", "_")


def get_valid_poi_columns() -> set:
    """Get set of all valid POI column prefixes from config."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "retail_intelligence_config",
        Path(__file__).parent.parent / "etl" / "global" / "retail_intelligence_config.py"
    )
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return set(config.POI_CATEGORIES_L3.keys())


def get_valid_transit_columns() -> set:
    """Get set of valid transit column prefixes (matching Overture categories)."""
    return {"metro_station", "train_station", "bus_station", "tram_stop", 
            "light_rail_station", "ferry_terminal", "airport"}


def get_valid_green_columns() -> set:
    """Get set of valid green column prefixes (including size tiers)."""
    return {"park", "park_small", "park_20k", "park_2m", "park_20m",
            "forest", "beach", "nature_reserve"}


def get_valid_blue_columns() -> set:
    """Get set of valid blue column prefixes."""
    return {"lake", "lake_2m", "river", "coastline"}


def get_valid_land_use_columns() -> set:
    """Get set of valid land use column prefixes."""
    # Inline list to avoid import issues with 'global' folder name
    return {
        "residential", "commercial", "industrial", "retail", "office",
        "park", "forest", "recreation_ground", "farmland", "vineyard",
        "orchard", "meadow", "grassland", "scrub", "heath",
        "quarry", "landfill", "construction", "brownfield",
        "cemetery", "allotments", "beach", "military",
        "education", "healthcare", "religious",
        "nature_reserve", "protected_area", "national_park",
    }


def get_valid_road_presence_columns() -> set:
    """Get set of valid road presence columns."""
    return {"pedestrian", "cycleway", "footway", "living_street"}


def get_valid_road_proximity_columns() -> set:
    """Get set of valid road proximity column prefixes."""
    return {"motorway_road", "trunk_road", "primary_road", "secondary_road"}


def validate_and_build_columns(gemini_output: dict, stage: str) -> Dict[str, List[str]]:
    """
    Validate Gemini output and build actual column names.
    
    Args:
        gemini_output: The parsed JSON from Gemini
        stage: One of "summative", "driving", "walking"
        
    Returns:
        Dict with keys: "valid_columns", "invalid_features", "warnings"
    """
    valid_columns = []
    invalid_features = []
    warnings = []
    
    valid_pois = get_valid_poi_columns()
    valid_transit = get_valid_transit_columns()
    valid_green = get_valid_green_columns()
    valid_blue = get_valid_blue_columns()
    valid_land_use = get_valid_land_use_columns()
    valid_road_presence = get_valid_road_presence_columns()
    valid_road_proximity = get_valid_road_proximity_columns()
    
    if stage == "summative":
        # POI features → _count columns
        for poi in gemini_output.get("poi_features", []):
            normalized = normalize_feature(poi, "poi")
            if normalized in valid_pois:
                valid_columns.append(f"{normalized}_count")
            else:
                invalid_features.append(poi)
                # Try fuzzy match
                warnings.append(f"Unknown POI '{poi}' (normalized: {normalized})")
        
        # Land use → _count and _in_hex_m2
        for lu in gemini_output.get("land_use_features", []):
            normalized = normalize_feature(lu, "poi")  # land use uses same normalization
            if normalized in valid_land_use:
                valid_columns.append(f"{normalized}_count")
                valid_columns.append(f"{normalized}_in_hex_m2")
            else:
                invalid_features.append(lu)
        
        # Water → _count
        for w in gemini_output.get("water_features", []):
            normalized = normalize_feature(w, "blue")
            # Water types: lake, river, sea, pond
            valid_columns.append(f"{normalized}_count")
        
        # Buildings
        if gemini_output.get("include_buildings", False):
            valid_columns.extend(["building_count", "building_density", 
                                  "avg_building_height", "avg_floors"])
        
        # Road presence
        for r in gemini_output.get("road_presence", []):
            normalized = normalize_feature(r, "road")
            if normalized in valid_road_presence:
                valid_columns.append(f"{normalized}_in_hex")
            else:
                invalid_features.append(r)
    
    elif stage == "driving":
        col_type = gemini_output.get("poi_column_type", "drive_min")
        
        # POI features → _drive_min or _score
        for poi in gemini_output.get("must_have_pois", []):
            normalized = normalize_feature(poi, "poi")
            if normalized in valid_pois:
                valid_columns.append(f"{normalized}_{col_type}")
            else:
                invalid_features.append(poi)
        
        # Transit → _cycle_min
        for t in gemini_output.get("must_have_transit", []):
            normalized = normalize_feature(t, "transit")
            if normalized in valid_transit:
                valid_columns.append(f"{normalized}_cycle_min")
            else:
                invalid_features.append(t)
        
        # Green → _cycle_min
        for g in gemini_output.get("must_have_green", []):
            normalized = normalize_feature(g, "green")
            if normalized in valid_green:
                valid_columns.append(f"{normalized}_cycle_min")
            else:
                invalid_features.append(g)
        
        # Blue → _cycle_min
        for b in gemini_output.get("must_have_blue", []):
            normalized = normalize_feature(b, "blue")
            if normalized in valid_blue:
                valid_columns.append(f"{normalized}_cycle_min")
            else:
                invalid_features.append(b)
    
    elif stage == "walking":
        # STRICT: Transit → _walk_min
        for t in gemini_output.get("must_have_transit", []):
            normalized = normalize_feature(t, "transit")
            if normalized in valid_transit:
                valid_columns.append(f"{normalized}_walk_min")
            else:
                invalid_features.append(t)
        
        # STRICT: Green → _walk_min
        for g in gemini_output.get("must_have_green", []):
            normalized = normalize_feature(g, "green")
            if normalized in valid_green:
                valid_columns.append(f"{normalized}_walk_min")
            else:
                invalid_features.append(g)
        
        # STRICT: Blue → _walk_min
        for b in gemini_output.get("must_have_blue", []):
            normalized = normalize_feature(b, "blue")
            if normalized in valid_blue:
                valid_columns.append(f"{normalized}_walk_min")
            else:
                invalid_features.append(b)
        
        # LENIENT: POI categories → _walk_min (grouped by category, OR logic)
        # Returns list of lists - each inner list is OR'd together
        lenient_groups = []
        for category in gemini_output.get("prefer_poi_categories", []):
            group_cols = []
            features = category.get("features", [])
            for poi in features:
                normalized = normalize_feature(poi, "poi")
                if normalized in valid_pois:
                    group_cols.append(f"{normalized}_walk_min")
                else:
                    invalid_features.append(poi)
            if group_cols:
                lenient_groups.append(group_cols)
        
        # Return lenient groups separately
        return {
            "strict_columns": valid_columns,
            "lenient_groups": lenient_groups,
            "invalid_features": invalid_features,
            "warnings": warnings,
        }
    
    return {
        "valid_columns": valid_columns,
        "invalid_features": invalid_features,
        "warnings": warnings,
    }


# =============================================================================
# CASCADE SEARCH IMPLEMENTATION  
# =============================================================================

def load_parquet(resolution: int, area_name: str = "LONDON") -> pd.DataFrame:
    """Load parquet file for given resolution."""
    # Try new naming pattern first (earth_matrix_maxed_res*.parquet)
    parquet_path = MATRIX_DIR / f"earth_matrix_maxed_res{resolution}.parquet"
    
    # Fall back to old pattern (TEST_*_res*.parquet) for backwards compatibility
    if not parquet_path.exists():
        parquet_path = MATRIX_DIR / f"{area_name}_res{resolution}.parquet"
    
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet not found: {parquet_path}")
    
    logger.info(f"Loading {parquet_path}")
    return pd.read_parquet(parquet_path)


def stage1_summative_filter(
    df: pd.DataFrame,
    columns: List[str],
    top_percentile: float = 0.25
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Stage 1: Summative density scoring at Res 5.
    
    Args:
        df: Res 5 dataframe
        columns: List of _count columns to sum
        top_percentile: Keep top N% (default 25%)
        
    Returns:
        (filtered_df, scores)
    """
    # Filter to columns that exist
    existing_cols = [c for c in columns if c in df.columns]
    if not existing_cols:
        logger.warning(f"No valid columns found from {columns}")
        return df, pd.Series(index=df.index, data=0)
    
    # Fill NaN with 0 and sum
    scores = df[existing_cols].fillna(0).sum(axis=1)
    
    # Get threshold for top percentile
    threshold = scores.quantile(1 - top_percentile)
    
    # Filter
    mask = scores >= threshold
    filtered_df = df[mask].copy()
    filtered_df["_score"] = scores[mask]
    
    logger.info(f"Stage 1: {len(df)} → {len(filtered_df)} hexes (top {top_percentile*100:.0f}%)")
    
    return filtered_df, scores


def _convert_to_reachability_score(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """
    Convert various column types to a 0/positive reachability score for multiplication.
    
    Column types:
    - _score columns: Already 0-10, use as-is (0 = unreachable)
    - _walk_min/_cycle_min/_drive_min columns: 999 = unreachable, else reachable
      Convert: < 999 → (1000 - value) so closer = higher; 999 → 0
    
    Returns:
        DataFrame with converted values suitable for multiplication
    """
    result = pd.DataFrame(index=df.index)
    
    for col in columns:
        if col not in df.columns:
            continue
            
        if col.endswith('_score'):
            # _score columns: 0-10, already correct (0 = unreachable)
            result[col] = df[col].fillna(0)
        elif '_min' in col:
            # _walk_min, _cycle_min, _drive_min: 999 = unreachable, else minutes
            # Convert: reachable (<999) → positive value; unreachable (999) → 0
            vals = df[col].fillna(999)
            # Invert so closer = higher score, 999 → 0
            result[col] = vals.apply(lambda x: max(0, 1000 - x) if x < 999 else 0)
        else:
            # Unknown column type, treat as-is
            result[col] = df[col].fillna(0)
    
    return result


def stage2_driving_multiplicative(
    df: pd.DataFrame,
    parent_hexes: List[str],
    score_columns: List[str]
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Stage 2: Multiplicative scoring at Res 8.
    
    The PRODUCT of scores naturally eliminates hexes where ANY score is 0.
    Supports both _score columns (0-10) and _min columns (999 = unreachable).
    
    Args:
        df: Res 8 dataframe  
        parent_hexes: List of Res 5 hex IDs that passed Stage 1
        score_columns: List of columns to multiply (e.g., hospital_score, subway_walk_min)
        
    Returns:
        (dataframe with _mult_score, multiplicative_scores)
    """
    # Filter to children of parent hexes
    df = df.copy()
    df["_parent"] = df["h3_index"].apply(lambda x: h3.cell_to_parent(x, 5))
    df = df[df["_parent"].isin(parent_hexes)]
    
    if len(df) == 0:
        logger.warning("No Res 8 hexes found within parent hexes")
        return df, pd.Series()
    
    # Filter to columns that exist
    existing_cols = [c for c in score_columns if c in df.columns]
    if not existing_cols:
        logger.info(f"Stage 2: No driving constraints, passing all {len(df)} hexes")
        df["_mult_score"] = 1.0
        return df, df["_mult_score"]
    
    # Convert all columns to reachability scores (0 = unreachable)
    reach_scores = _convert_to_reachability_score(df, existing_cols)
    
    # MULTIPLY all converted scores
    # Any 0 → product = 0 → hex eliminated
    mult_score = reach_scores.prod(axis=1)
    
    df["_mult_score"] = mult_score
    
    # Keep hexes where product > 0 (natural filtering through multiplication)
    filtered_df = df[mult_score > 0].copy()
    
    logger.info(f"Stage 2: {len(df)} → {len(filtered_df)} hexes (mult product > 0)")
    logger.info(f"  Columns: {existing_cols}")
    
    return filtered_df, mult_score[mult_score > 0]


def stage3_walking_multiplicative(
    df: pd.DataFrame,
    parent_hexes: List[str],
    score_columns: List[str]
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Stage 3: Multiplicative scoring at Res 10.
    
    Same logic as Stage 2 - MULTIPLY scores, zeros eliminate naturally.
    Supports both _score columns (0-10) and _walk_min columns (999 = unreachable).
    
    Args:
        df: Res 10 dataframe
        parent_hexes: List of Res 8 hex IDs that passed Stage 2
        score_columns: List of columns to multiply (transit, green, POIs)
        
    Returns:
        (dataframe with _mult_score, multiplicative_scores)
    """
    # Filter to children of parent hexes
    df = df.copy()
    df["_parent"] = df["h3_index"].apply(lambda x: h3.cell_to_parent(x, 8))
    df = df[df["_parent"].isin(parent_hexes)]
    
    if len(df) == 0:
        logger.warning("No Res 10 hexes found within parent hexes")
        return df, pd.Series()
    
    # Filter to columns that exist
    existing_cols = [c for c in score_columns if c in df.columns]
    if not existing_cols:
        logger.info(f"Stage 3: No walking constraints, passing all {len(df)} hexes")
        df["_mult_score"] = 1.0
        return df, df["_mult_score"]
    
    # Convert all columns to reachability scores (0 = unreachable)
    reach_scores = _convert_to_reachability_score(df, existing_cols)
    
    # MULTIPLY all converted scores
    mult_score = reach_scores.prod(axis=1)
    
    df["_mult_score"] = mult_score
    
    # Keep hexes where product > 0
    filtered_df = df[mult_score > 0].copy()
    
    logger.info(f"Stage 3: {len(df)} → {len(filtered_df)} hexes (mult product > 0)")
    logger.info(f"  Columns: {existing_cols}")
    
    return filtered_df, mult_score[mult_score > 0]


def stage4_amenity_scoring(
    df: pd.DataFrame,
    columns: List[str],
    curve_power: float = 2.5
) -> pd.DataFrame:
    """
    Stage 4: Final amenity scoring at Res 10 for heatmap.
    
    Uses a POWER CURVE for more stringent color distribution:
    - Linear: 50th percentile → 50% color intensity
    - Power 2: 50th percentile → 25% color intensity (sqrt(0.5)² = 0.25)
    - Power 3: 50th percentile → 12.5% color intensity
    
    This makes the heatmap more selective - only top results get bright colors.
    
    Args:
        df: Filtered Res 10 dataframe from Stage 3
        columns: List of _count columns to sum for scoring
        curve_power: Exponent for color curve (default 2.5 = stringent)
            1.0 = linear, 2.0 = quadratic, 3.0 = cubic
        
    Returns:
        Dataframe with _score, _percentile (raw), and _curved (for display) columns
    """
    import numpy as np
    
    # Filter to columns that exist
    existing_cols = [c for c in columns if c in df.columns]
    if not existing_cols:
        logger.warning(f"No valid columns found from {columns}")
        df["_score"] = 0
        df["_percentile"] = 50
        df["_curved"] = 50
        return df
    
    # Sum scores
    df = df.copy()
    df["_score"] = df[existing_cols].fillna(0).sum(axis=1)
    
    # Raw percentile rank (0-100)
    df["_percentile"] = df["_score"].rank(pct=True) * 100
    
    # CURVED percentile for display - power function makes it more stringent
    # Only top percentiles get bright colors
    # Formula: curved = (raw/100)^power * 100
    df["_curved"] = np.power(df["_percentile"] / 100, curve_power) * 100
    
    logger.info(f"Stage 4: Scored {len(df)} hexes")
    logger.info(f"  Raw scores: {df['_score'].min():.0f} - {df['_score'].max():.0f}")
    logger.info(f"  Curved profile: power={curve_power} (50th pctl → {(0.5**curve_power)*100:.0f}% intensity)")
    
    return df


async def cascade_search(
    summative_columns: List[str],
    driving_score_columns: List[str],
    walking_score_columns: List[str],
    scoring_columns: List[str],
    area_name: str = "LONDON",
    top_percentile: float = 0.25
) -> AsyncGenerator[dict, None]:
    """
    Execute full cascade search with progressive visualization updates.
    
    Stage 1: SUM of _count columns → top 25%
    Stage 2: MULTIPLY _score columns → product=0 eliminated
    Stage 3: MULTIPLY _score columns → product=0 eliminated
    Stage 4: SUM of _count columns → heatmap ranking
    
    Yields StreamEvent dicts for each stage completion.
    """
    
    # =================================================================
    # STAGE 1: Res 5 Summative - BRIGHT spotlight on top 25%
    # =================================================================
    yield {"type": "status", "message": "Stage 1: Coarse density filter (Res 5)..."}
    
    df5 = load_parquet(5, area_name)
    df5_filtered, scores5 = stage1_summative_filter(df5, summative_columns, top_percentile)
    res5_hexes = df5_filtered["h3_index"].tolist()
    
    # Calculate bounding box for camera hug
    if res5_hexes:
        all_lats = []
        all_lngs = []
        for hex_id in res5_hexes:
            try:
                boundary = h3.cell_to_boundary(hex_id)
                for lat, lng in boundary:
                    all_lats.append(lat)
                    all_lngs.append(lng)
            except:
                pass
        
        if all_lats and all_lngs:
            # Add 10% buffer
            lat_range = max(all_lats) - min(all_lats)
            lng_range = max(all_lngs) - min(all_lngs)
            buffer_pct = 0.1
            
            # Format: [min_lon, min_lat, max_lon, max_lat]
            fit_bounds = [
                min(all_lngs) - lng_range * buffer_pct,  # min_lon (west)
                min(all_lats) - lat_range * buffer_pct,  # min_lat (south)
                max(all_lngs) + lng_range * buffer_pct,  # max_lon (east)
                max(all_lats) + lat_range * buffer_pct,  # max_lat (north)
            ]
            
            # Emit map control to fit bounds - camera hugs Stage 1 results
            yield {
                "type": "map_control",
                "fit_bounds": fit_bounds,
                "padding": 50,  # pixels
            }
    
    # Stage 1: Res 5 at full visibility (0.5 opacity)
    yield {
        "type": "layer_update",
        "layer_id": "cascade_res5",
        "layer_type": "h3_grid",
        "data": [{"hex": h, "value": 50} for h in res5_hexes],
        "count": len(res5_hexes),
        "viz_config": {
            "label": f"Stage 1: Top {int(top_percentile*100)}% City Zones ({len(res5_hexes)})",
            "color_by": "value",
            "opacity": 0.5,
        }
    }
    
    # =================================================================
    # STAGE 2: Res 8 Driving - MULTIPLY _score columns
    # Product=0 means unreachable → naturally eliminated
    # =================================================================
    yield {"type": "status", "message": "Stage 2: Driving multiplicative filter (Res 8)..."}
    
    df8 = load_parquet(8, area_name)
    df8_filtered, mult_scores8 = stage2_driving_multiplicative(df8, res5_hexes, driving_score_columns)
    res8_hexes = df8_filtered["h3_index"].tolist() if len(df8_filtered) > 0 else []
    
    if len(res8_hexes) > 0:
        # DIM Res 5 (re-emit with lower opacity)
        yield {
            "type": "layer_update",
            "layer_id": "cascade_res5",  # Same ID = REPLACE
            "layer_type": "h3_grid",
            "data": [{"hex": h, "value": 20} for h in res5_hexes],
            "count": len(res5_hexes),
            "viz_config": {
                "label": f"Stage 1: City Zones (dimmed)",
                "color_by": "value",
                "opacity": 0.2,  # DIMMED
            }
        }
        
        # SPOTLIGHT Res 8
        yield {
            "type": "layer_update", 
            "layer_id": "cascade_res8",
            "layer_type": "h3_grid",
            "data": [{"hex": h, "value": 70} for h in res8_hexes],
            "count": len(res8_hexes),
            "viz_config": {
                "label": f"Stage 2: Driving Pass ({len(res8_hexes)})",
                "color_by": "value",
                "opacity": 0.6,  # BRIGHT
            }
        }
    
    # =================================================================
    # STAGE 3: Res 10 Walking - MULTIPLY _score columns
    # Product=0 means unreachable → naturally eliminated
    # =================================================================
    yield {"type": "status", "message": "Stage 3: Walking multiplicative filter (Res 10)..."}
    
    df10 = load_parquet(10, area_name)
    df10_filtered, mult_scores10 = stage3_walking_multiplicative(df10, res8_hexes, walking_score_columns)
    
    # =================================================================
    # STAGE 4: Final Scoring - DIM all previous, HEATMAP on Res 10
    # =================================================================
    yield {"type": "status", "message": "Stage 4: Amenity scoring..."}
    
    df10_scored = stage4_amenity_scoring(df10_filtered, scoring_columns)
    
    if len(df10_scored) > 0:
        # DIM Res 5 even more
        yield {
            "type": "layer_update",
            "layer_id": "cascade_res5",
            "layer_type": "h3_grid",
            "data": [{"hex": h, "value": 10} for h in res5_hexes],
            "count": len(res5_hexes),
            "viz_config": {
                "label": f"City Zones (background)",
                "color_by": "value",
                "opacity": 0.1,  # VERY DIM
            }
        }
        
        # DIM Res 8
        if len(res8_hexes) > 0:
            yield {
                "type": "layer_update",
                "layer_id": "cascade_res8",
                "layer_type": "h3_grid",
                "data": [{"hex": h, "value": 30} for h in res8_hexes],
                "count": len(res8_hexes),
                "viz_config": {
                    "label": f"Driving Pass (background)",
                    "color_by": "value",
                    "opacity": 0.15,  # DIMMED
                }
            }
        
        # BRIGHT HEATMAP on Res 10
        heatmap_data = []
        for _, row in df10_scored.iterrows():
            heatmap_data.append({
                "hex": row["h3_index"],
                "value": row["_percentile"],  # Percentile for coloring
                "score": row["_score"],
            })
        
        yield {
            "type": "layer_update",
            "layer_id": "cascade_res10_heatmap",
            "layer_type": "h3_grid",
            "data": heatmap_data,
            "count": len(heatmap_data),
            "viz_config": {
                "label": f"🎯 Final: {len(heatmap_data)} candidate hexes",
                "color_by": "value",
                "color_scale": "plasma",
                "opacity": 0.8,  # BRIGHTEST
            }
        }
    
    # Final summary
    yield {
        "type": "cascade_complete",
        "summary": {
            "res5_input": len(df5),
            "res5_output": len(df5_filtered),
            "res8_output": len(df8_filtered),
            "res10_output": len(df10_scored),
            "top_score": df10_scored["_score"].max() if len(df10_scored) > 0 else 0,
            "avg_score": df10_scored["_score"].mean() if len(df10_scored) > 0 else 0,
        }
    }


# =============================================================================
# TOOL FUNCTION FOR AGENT
# =============================================================================

def tool_cascade_search(
    summative_features: List[str],
    driving_must_haves: Optional[List[str]] = None,
    walking_transit: Optional[List[str]] = None,
    walking_green: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Multi-resolution cascade search across H3 resolutions 5, 8, 10.
    
    Uses different column types for each stage:
    
    STAGE 1 & 4 (SUMMATIVE - density ranking):
        Column: *_count (e.g., cafe_count, restaurant_count)
        Method: SUM all counts → higher = more amenities
        
    STAGE 2 (MULTIPLICATIVE - accessibility filter at Res 8):
        Column: *_score for ALL summative features + driving_must_haves
        Scale: 0-10 where 0/NULL=unreachable, 10=in-hex
        Method: MULTIPLY scores → any 0 eliminates the hex
        Purpose: Ensures ALL requested features are accessible, not just present
        
    STAGE 3 (MULTIPLICATIVE - walking accessibility at Res 10):
        Column: *_score (e.g., metro_station_score, park_score)
        Scale: 0-10 where 0/NULL=unreachable, 10=in-hex (proper decay curves)
        Method: MULTIPLY scores → any 0 eliminates the hex
    
    Results are sorted by score before any truncation, ensuring the BEST
    candidates are shown regardless of geographic H3 index ordering.
    
    Args:
        summative_features: POIs for density ranking AND accessibility filter
            → Uses *_count for ranking, *_score for Stage 2 filter
        driving_must_haves: Additional POIs requiring driving access (hospital, etc.)
            → Uses *_score columns, MULTIPLIED (0/NULL = eliminated)
        walking_transit: Transit requiring walking access (subway, train, bus)
            → Uses *_score columns, MULTIPLIED (0/NULL = eliminated)
        walking_green: Green spaces requiring walking access (park, forest, beach)
            → Uses *_score columns, MULTIPLIED (0/NULL = eliminated)
        
    Returns:
        Cascade results with progressive map visualization
    """
    # Fixed config
    area_name = "LONDON"
    top_percentile = 0.25
    
    # =========================================================================
    # COLUMN MAPPING: Features → Columns by Stage
    # =========================================================================
    #
    # SUMMATIVE stages (1, 4): Use _count columns for RANKING
    #   cafe → cafe_count
    #   Method: SUM(cafe_count + pub_count + ...) → density score
    #
    # MULTIPLICATIVE stages (2, 3): Use _score columns for FILTERING
    #   Stage 2: ALL summative features → pub_score, pharmacy_score, etc.
    #   Stage 3: Transit/Green features → metro_station_score, park_score
    #   Method: MULTIPLY → any 0/NULL kills the product → hex eliminated
    #
    # Stage 2 ensures ALL user-requested features are ACCESSIBLE
    # Stage 3 ensures walking-distance features are WALKABLE
    #
    # Results sorted by score before truncation so BEST hexes show first
    #
    # =========================================================================
    
    # Stage 1 & 4: _count columns for SUMMATIVE density ranking
    # "How many cafes/pubs/restaurants are in this area?"
    summative_cols = []
    for f in summative_features:
        normalized = normalize_feature(f, "poi")
        summative_cols.append(f"{normalized}_count")
    
    # Stage 2: _score columns for MULTIPLICATIVE accessibility filter (Res 8)
    # ALL user-requested features must be accessible (score > 0)
    # This filters out hexes that appeared in Stage 1 by coincidence
    # (e.g., a park at the edge of a hex doesn't mean the whole hex is "near a park")
    accessibility_score_cols = []
    
    # Add ALL summative features as accessibility requirements
    for f in summative_features:
        normalized = normalize_feature(f, "poi")
        accessibility_score_cols.append(f"{normalized}_score")
    
    # Also add any explicit driving_must_haves (hospital, airport, etc.)
    if driving_must_haves:
        for f in driving_must_haves:
            normalized = normalize_feature(f, "poi")
            col = f"{normalized}_score"
            if col not in accessibility_score_cols:
                accessibility_score_cols.append(col)
    
    # Stage 3: _score columns for MULTIPLICATIVE walking filter (Res 10)
    # Transit and green features that must be walkable
    walking_score_cols = []
    if walking_transit:
        for t in walking_transit:
            normalized = normalize_feature(t, "transit")
            walking_score_cols.append(f"{normalized}_score")
    if walking_green:
        for g in walking_green:
            normalized = normalize_feature(g, "green")
            walking_score_cols.append(f"{normalized}_score")
    
    logger.info(f"📊 Cascade column mapping:")
    logger.info(f"  Stage 1/4 (SUM _count):      {summative_cols}")
    logger.info(f"  Stage 2 (MULT _score):       {accessibility_score_cols}")
    logger.info(f"  Stage 3 (MULT _score):       {walking_score_cols}")
    
    # =========================================================================
    # RUN CASCADE SYNCHRONOUSLY with delays for animation
    # =========================================================================
    import time
    
    try:
        # STAGE 1: Res 5 summative
        logger.info("🔍 Stage 1: Coarse filter (Res 5)...")
        df5 = load_parquet(5, area_name)
        df5_filtered, _ = stage1_summative_filter(df5, summative_cols, top_percentile)
        res5_hexes = df5_filtered["h3_index"].tolist()
        logger.info(f"✅ Stage 1: {len(df5)} → {len(res5_hexes)} hexes (top 25%)")
        time.sleep(0.5)  # Pause for animation
        
        # STAGE 2: Res 8 multiplicative - accessibility filter for ALL user features
        logger.info("🎯 Stage 2: Accessibility filter (Res 8)...")
        df8 = load_parquet(8, area_name)
        df8_filtered, _ = stage2_driving_multiplicative(df8, res5_hexes, accessibility_score_cols)
        
        # If no accessibility constraints, use all children of res5
        if len(df8_filtered) == 0 and not accessibility_score_cols:
            df8_filtered = df8[df8["h3_index"].apply(lambda x: h3.cell_to_parent(x, 5)).isin(res5_hexes)].copy()
            df8_filtered["_mult_score"] = 1.0
        
        # Sort by multiplicative score (best first) before any truncation
        # This ensures we show the BEST hexes regardless of H3 index ordering
        if len(df8_filtered) > 0 and "_mult_score" in df8_filtered.columns:
            df8_filtered = df8_filtered.sort_values("_mult_score", ascending=False)
        
        res8_hexes = df8_filtered["h3_index"].tolist() if len(df8_filtered) > 0 else []
        logger.info(f"✅ Stage 2: → {len(res8_hexes)} hexes (sorted by score)")
        time.sleep(0.5)  # Pause for animation
        
        # STAGE 3: Res 10 multiplicative
        logger.info("🚶 Stage 3: Walking filter (Res 10)...")
        df10 = load_parquet(10, area_name)
        df10_filtered, _ = stage3_walking_multiplicative(df10, res8_hexes, walking_score_cols)
        
        # If no walking constraints, use all children of res8
        if len(df10_filtered) == 0 and not walking_score_cols:
            df10_filtered = df10[df10["h3_index"].apply(lambda x: h3.cell_to_parent(x, 8)).isin(res8_hexes)].copy()
            df10_filtered["_mult_score"] = 1.0
        
        # Sort by multiplicative score (best first) before any truncation
        if len(df10_filtered) > 0 and "_mult_score" in df10_filtered.columns:
            df10_filtered = df10_filtered.sort_values("_mult_score", ascending=False)
        
        logger.info(f"✅ Stage 3: → {len(df10_filtered)} hexes (sorted by score)")
        time.sleep(0.5)  # Pause for animation
        
        # STAGE 4: Final scoring
        logger.info("📊 Stage 4: Amenity scoring...")
        df10_scored = stage4_amenity_scoring(df10_filtered, summative_cols)
        time.sleep(0.5)
        
        # Build heatmap data using CURVED values for stringent color distribution
        # Sort by score (descending) so truncation keeps BEST hexes, not arbitrary H3 order
        heatmap_data = []
        for _, row in df10_scored.sort_values("_score", ascending=False).iterrows():
            heatmap_data.append({
                "hex": row["h3_index"],
                "value": row["_curved"],  # Curved for display (power function)
                "percentile": row["_percentile"],  # Raw percentile
                "score": row["_score"],  # Raw amenity sum
            })
        
        logger.info(f"📊 Heatmap data sorted by score: top={heatmap_data[0]['score'] if heatmap_data else 0}, bottom={heatmap_data[-1]['score'] if heatmap_data else 0}")
        
        summary = {
            "res5_input": len(df5),
            "res5_output": len(res5_hexes),
            "res8_output": len(res8_hexes),
            "res10_output": len(df10_scored),
        }
        
        logger.info(f"🎯 Cascade complete: {summary}")
        
        # =====================================================================
        # BUILD PROGRESSIVE STAGES for animated visualization
        # Each stage is a layer_update that will be emitted with delays
        # =====================================================================
        
        # Stage 1 layer: Res 5 spotlight (bright)
        stage1_layer = {
            "layer_id": "cascade_res5",
            "type": "h3_grid",
            "data": [{"hex": h, "value": 80} for h in res5_hexes],
            "count": len(res5_hexes),
            "viz_config": {
                "label": f"Stage 1: Top 25% City Zones ({len(res5_hexes)})",
                "color_by": "value",
                "color_scale": "viridis",
                "opacity": 0.6,
            }
        }
        
        # Stage 2 layer: Res 5 dimmed + Res 8 spotlight
        stage2_layers = [
            {
                "layer_id": "cascade_res5",  # Replace stage 1
                "type": "h3_grid", 
                "data": [{"hex": h, "value": 30} for h in res5_hexes],
                "count": len(res5_hexes),
                "viz_config": {
                    "label": f"City Zones (dimmed)",
                    "color_by": "value",
                    "color_scale": "greys",
                    "opacity": 0.2,
                }
            },
            {
                "layer_id": "cascade_res8",
                "type": "h3_grid",
                "data": [{"hex": h, "value": 70} for h in res8_hexes[:5000]],  # Limit for perf
                "count": len(res8_hexes),
                "viz_config": {
                    "label": f"Stage 2: Driving Pass ({len(res8_hexes)})",
                    "color_by": "value",
                    "color_scale": "viridis",
                    "opacity": 0.5,
                }
            }
        ]
        
        # Stage 4 layer: Final heatmap (brightest)
        stage4_layer = {
            "layer_id": "cascade_final",
            "type": "h3_grid",
            "data": heatmap_data[:10000],  # Limit for performance
            "count": len(heatmap_data),
            "viz_config": {
                "label": f"🎯 Best Spots ({len(heatmap_data)})",
                "color_by": "value",
                "color_scale": "plasma",
                "opacity": 0.8,
            }
        }
        
        # =================================================================
        # YIELD EVENTS DIRECTLY FOR REAL-TIME STREAMING
        # Each yield goes straight to SSE - delays happen HERE in tool
        # =================================================================
        STAGE_DELAY = 2.0  # seconds between stages
        
        logger.info("🎬 STREAMING 3 stages with real-time delays...")
        
        # --- STAGE 1: Emit immediately ---
        logger.info("🎬 [YIELD] Stage 1...")
        yield {
            "type": "layer_update",
            "data": stage1_layer
        }
        yield {"type": "thought", "data": "🔍 Stage 1: Spotlighting top city zones..."}
        
        # --- WAIT ---
        import time
        logger.info(f"   ⏱️ Sleeping {STAGE_DELAY}s...")
        time.sleep(STAGE_DELAY)
        
        # --- STAGE 2: Emit after delay ---
        logger.info("🎬 [YIELD] Stage 2...")
        for layer in stage2_layers:
            yield {
                "type": "layer_update", 
                "data": layer
            }
        yield {"type": "thought", "data": "🚗 Stage 2: Filtering by driving access..."}
        
        # --- WAIT ---
        logger.info(f"   ⏱️ Sleeping {STAGE_DELAY}s...")
        time.sleep(STAGE_DELAY)
        
        # --- STAGE 4: Final heatmap ---
        logger.info("🎬 [YIELD] Stage 4 (final)...")
        yield {
            "type": "layer_update",
            "data": stage4_layer
        }
        yield {"type": "thought", "data": "🎯 Stage 4: Final heatmap!"}
        
        # --- AREA INSIGHTS: Generate clusters + descriptions from RES8 ---
        # Using res8 directly gives us more granular travel time data
        logger.info("🧠 Generating area insights from res8...")
        yield {"type": "thought", "data": "🧠 Analyzing top areas and generating descriptions..."}
        
        try:
            # Get user query context (combine all features into a query string)
            user_query_parts = []
            if summative_features:
                user_query_parts.append(f"near {', '.join(summative_features[:5])}")
            if walking_transit:
                user_query_parts.append(f"walkable to {', '.join(walking_transit[:3])}")
            if walking_green:
                user_query_parts.append(f"close to {', '.join(walking_green[:3])}")
            user_query = "Area " + " and ".join(user_query_parts) if user_query_parts else "Best matching areas"
            
            # Combine all user columns (summative + walking) for better matching
            all_user_cols = summative_cols + walking_score_cols
            
            # Run area insights pipeline using RES8 DATA DIRECTLY
            # This gives us actual _walk_min/_cycle_min/_drive_min values
            clusters = generate_area_insights(
                df_res8=df8_filtered,  # Use res8 directly - more granular travel times
                user_columns=all_user_cols,  # All columns user cared about
                user_query=user_query,
                max_clusters=100,
                max_cluster_size=20,  # Limit adjacent hexes per cluster (~14 km² max)
                generate_descriptions=True  # Use Gemini 2.5 Flash Lite
            )
            
            # Emit area insights event
            logger.info(f"🔍 DEBUG: clusters generated: {len(clusters) if clusters else 0}")
            if clusters:
                insights_payload = {
                    "clusters": clusters_to_json(clusters),
                    "count": len(clusters),
                    "user_query": user_query,
                }
                logger.info(f"✅ YIELDING area_insights event with {len(clusters)} clusters")
                yield {
                    "type": "area_insights",
                    "data": insights_payload,
                }
                logger.info(f"✅ Generated insights for {len(clusters)} clusters")
            else:
                logger.warning("⚠️ No clusters generated - skipping area_insights event")
            
        except Exception as e:
            logger.error(f"Area insights failed: {e}", exc_info=True)
            # Don't fail the whole cascade, just skip insights
        
        # --- FINAL RESULT (for LLM to summarize) ---
        yield {
            "type": "cascade_complete",
            "success": True,
            "summary": summary,
            "message": f"🎯 Found {len(heatmap_data)} locations matching criteria"
        }
        
    except FileNotFoundError as e:
        logger.error(f"Parquet not found: {e}")
        return {
            "type": "error",
            "success": False,
            "error": f"Matrix data not found: {e}",
            "message": "❌ Hoxton matrix data not loaded. Run build_global_matrix.py first."
        }
    except Exception as e:
        logger.error(f"Cascade failed: {e}", exc_info=True)
        return {
            "type": "error", 
            "success": False,
            "error": str(e),
            "message": f"❌ Cascade search failed: {e}"
        }


# =============================================================================
# GEMINI STRUCTURED OUTPUT SCHEMAS
# =============================================================================

SUMMATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "poi_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "POI types for density scoring (e.g., cafe, restaurant, gym)"
        },
        "land_use_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Land use types (e.g., park, residential)"
        },
        "water_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Water types (e.g., lake, river)"
        },
        "include_buildings": {
            "type": "boolean",
            "description": "Include building_count, building_density"
        },
        "road_presence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Road presence types (e.g., pedestrian, cycleway)"
        }
    },
    "required": ["poi_features"]
}

DRIVING_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have_pois": {
            "type": "array",
            "items": {"type": "string"},
            "description": "POIs that MUST be within driving distance (e.g., hospital, university)"
        },
        "poi_column_type": {
            "type": "string",
            "enum": ["drive_min", "cycle_min", "score"],
            "description": "Column type: drive_min (hard), score (soft decay)"
        },
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Transit types within cycling distance"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Large green spaces (park_2m, forest)"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Water features (lake_2m, coastline)"
        }
    },
    "required": ["must_have_pois"]
}

WALKING_SCHEMA = {
    "type": "object",
    "properties": {
        "must_have_transit": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Transit MUST be walkable (subway, train, bus)"
        },
        "must_have_green": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Green space MUST be walkable (park, park_20k)"
        },
        "must_have_blue": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Water MUST be walkable (lake, river, coastline)"
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
    "required": []
}


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(level=logging.INFO)
    
    # Test column mapping
    print("\n=== Testing Column Mapping ===")
    
    test_features = [
        ("tube", "transit"),
        ("Tube station", "transit"),
        ("coffee shops", "poi"),
        ("decent park", "green"),
        ("coastline", "blue"),
        ("hospital", "poi"),
    ]
    
    for feature, ftype in test_features:
        normalized = normalize_feature(feature, ftype)
        print(f"  {feature!r:25} → {normalized}")
    
    # Test validation
    print("\n=== Testing Validation ===")
    
    gemini_summative = {
        "poi_features": ["cafe", "coffee_shop", "bar", "restaurant"],
        "land_use_features": ["park"],
        "include_buildings": True,
    }
    
    result = validate_and_build_columns(gemini_summative, "summative")
    print(f"  Summative columns: {result['valid_columns']}")
    
    gemini_walking = {
        "must_have_transit": ["subway"],
        "must_have_green": ["park_20k"],
        "prefer_poi_categories": [
            {"category_name": "coffee", "features": ["cafe", "coffee_shop"]},
        ]
    }
    
    result = validate_and_build_columns(gemini_walking, "walking")
    print(f"  Walking strict: {result['strict_columns']}")
    print(f"  Walking lenient: {result['lenient_groups']}")
    
    print("\n✅ Mapping layer tests passed!")
    
    # Test full cascade with Hoxton parquets
    print("\n=== Testing Full Cascade (Hoxton) ===")
    
    async def test_cascade():
        summative_cols = ["cafe_count", "coffee_shop_count", "bar_count", "restaurant_count", "park_count"]
        driving_cols = ["hospital_drive_min"]
        walking_strict = ["subway_station_walk_min", "park_walk_min"]
        walking_lenient = [["cafe_walk_min", "coffee_shop_walk_min"]]
        scoring_cols = ["cafe_count", "coffee_shop_count", "bar_count", "restaurant_count"]
        
        events = []
        async for event in cascade_search(
            summative_columns=summative_cols,
            driving_columns=driving_cols,
            walking_strict=walking_strict,
            walking_lenient=walking_lenient,
            scoring_columns=scoring_cols,
            area_name="LONDON"
        ):
            events.append(event)
            if event.get("type") == "status":
                print(f"  📍 {event['message']}")
            elif event.get("type") == "layer_update":
                layer = event["layer"]
                data_count = len(layer.get("data", []))
                print(f"  🗺️  Layer '{layer['id']}': {data_count} hexes")
            elif event.get("type") == "cascade_complete":
                summary = event["summary"]
                print(f"\n  ✅ CASCADE COMPLETE:")
                print(f"     Res 5: {summary['res5_input']} → {summary['res5_output']} hexes")
                print(f"     Res 8: {summary['res8_output']} hexes")
                print(f"     Res 10: {summary['res10_output']} hexes")
                print(f"     Top score: {summary['top_score']:.1f}")
    
    asyncio.run(test_cascade())

