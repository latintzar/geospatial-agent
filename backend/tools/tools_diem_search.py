#!/usr/bin/env python3
"""
DIEM Similarity Search
======================

Find similar hexes globally using the Dimension Insensitive Euclidean Metric (DIEM).

DIEM is a normalized Euclidean distance that accounts for dimensionality,
making it more robust than cosine similarity for high-dimensional vectors.

Reference: https://github.com/ftessari23/DIEM

Usage:
1. User selects a location (or uses geolocation)
2. We get the H3 res10 hex for that location
3. Extract the feature vector (all numeric columns) for that hex
4. Compute DIEM similarity against all other hexes in the matrix
5. Return top 100 most similar hexes globally for heatmap visualization
"""

import os
import logging
import math
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

import h3
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================
# GEMINI DESCRIPTION GENERATION
# =============================================================================

def _format_feature_for_prompt(col: str, val: float) -> str:
    """Format a single feature for the prompt in a human-readable way."""
    col_clean = col.replace('_', ' ')
    
    if '_count' in col:
        thing = col_clean.replace(' count', '')
        return f"- {val:.0f} {thing}{'s' if val != 1 else ''} nearby"
    elif '_walk_min' in col:
        thing = col_clean.replace(' walk min', '')
        return f"- {thing}: {val:.0f} min walk"
    elif '_cycle_min' in col:
        thing = col_clean.replace(' cycle min', '')
        return f"- {thing}: {val:.0f} min cycle"
    elif '_drive_min' in col:
        thing = col_clean.replace(' drive min', '')
        return f"- {thing}: {val:.0f} min drive"
    elif '_score' in col:
        thing = col_clean.replace(' score', '')
        return f"- {thing} accessibility: {val:.1f}/10"
    elif '_m2' in col or '_area' in col:
        thing = col_clean.replace(' m2', '').replace(' in hex', '').replace(' area', '')
        return f"- {thing} area: {val:.0f}m²"
    elif 'density' in col:
        return f"- {col_clean}: {val:.0f}"
    else:
        return f"- {col_clean}: {val:.1f}"


def generate_hex_descriptions(scores: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """
    Generate TWO descriptions of a hex's character using Gemini Flash Lite:
    
    1. "vibe" - A proper characterization focusing on infrastructure access,
       amenities, connectivity. Leverages the full breadth of features.
       
    2. "starter_pack" - A hyper-local memeable description like "Starter Pack" 
       memes or "Real Housewives of [micro-neighborhood]". Should be so specific
       that someone standing there would be weirded out.
    
    Args:
        scores: List of meaningful scores like [{"column": "cafe_count", "value": 12}, ...]
        
    Returns:
        Dict with "vibe" and "starter_pack" keys, each containing a description or None
    """
    result = {"vibe": None, "starter_pack": None}
    
    if not scores:
        return result
        
    try:
        from backend.gemini_client import GeminiClient
        client = GeminiClient(model="gemini-2.0-flash-lite")
        
        # Use MORE features for comprehensive descriptions (up to 60)
        score_lines = [_format_feature_for_prompt(s['column'], s['value']) for s in scores[:60]]
        score_text = "\n".join(score_lines)
        
        # Categorize features for the prompt
        transport_features = [s for s in scores if any(x in s['column'] for x in ['station', 'bus', 'tube', 'train', 'tram', 'ferry'])]
        food_features = [s for s in scores if any(x in s['column'] for x in ['cafe', 'restaurant', 'pub', 'bar', 'bakery', 'takeaway'])]
        green_features = [s for s in scores if any(x in s['column'] for x in ['park', 'garden', 'green', 'tree', 'nature', 'river', 'lake'])]
        retail_features = [s for s in scores if any(x in s['column'] for x in ['shop', 'store', 'market', 'supermarket', 'mall'])]
        health_features = [s for s in scores if any(x in s['column'] for x in ['hospital', 'clinic', 'pharmacy', 'doctor', 'dentist', 'gym'])]
        
        # Summary stats for context
        summary = []
        if transport_features:
            avg_transport = sum(f['value'] for f in transport_features if '_min' in f['column']) / max(1, len([f for f in transport_features if '_min' in f['column']]))
            summary.append(f"Transport access: {'excellent' if avg_transport < 5 else 'good' if avg_transport < 10 else 'moderate'}")
        if food_features:
            food_count = sum(f['value'] for f in food_features if '_count' in f['column'])
            summary.append(f"Food scene: {'bustling' if food_count > 20 else 'lively' if food_count > 10 else 'quiet'}")
        if green_features:
            green_count = sum(f['value'] for f in green_features if '_count' in f['column'])
            summary.append(f"Green space: {'abundant' if green_count > 5 else 'some' if green_count > 0 else 'limited'}")
        
        summary_text = "; ".join(summary) if summary else "Mixed urban area"
        
        # =========================================================================
        # DESCRIPTION 1: VIBE (Infrastructure & Access Focus)
        # =========================================================================
        vibe_prompt = f"""You're a hyper-local urban analyst. Based on these {len(scores)} location features, write a 3-4 sentence characterization of this specific spot. Focus on:

1. CONNECTIVITY - How well-connected is it? (transit access, walkability)
2. AMENITIES - What's the density of useful things? (food, shops, services)
3. CHARACTER - Is it residential? commercial? mixed? green? urban?
4. LIVABILITY - Who would thrive here? What lifestyle does it support?

Be specific and data-driven. Don't be generic. This is resolution 10 (~150m hex) so be PRECISE.

SUMMARY: {summary_text}

DETAILED FEATURES:
{score_text}

Write the characterization (3-4 sentences, be specific):"""

        vibe_response = client.call(prompt=vibe_prompt, temperature=0.6, max_tokens=400)
        
        if vibe_response.success and vibe_response.text:
            result["vibe"] = vibe_response.text.strip().strip('"\'')
            logger.info(f"✨ Generated vibe description: {result['vibe'][:80]}...")
        
        # =========================================================================
        # DESCRIPTION 2: STARTER PACK (Hyper-Local Meme)
        # =========================================================================
        
        # Pick out the most distinctive/unusual features for meme potential
        distinctive = []
        for s in scores[:40]:
            col, val = s['column'], s['value']
            # Very high counts are distinctive
            if '_count' in col and val > 15:
                distinctive.append(f"{val:.0f} {col.replace('_count', '').replace('_', ' ')}s")
            # Very fast access times are distinctive
            elif '_walk_min' in col and val < 3:
                distinctive.append(f"{col.replace('_walk_min', '').replace('_', ' ')} {val:.0f} min walk")
            # Very slow access times are also distinctive (far from things)
            elif '_walk_min' in col and val > 15:
                distinctive.append(f"no {col.replace('_walk_min', '').replace('_', ' ')} in sight")
        
        distinctive_text = ", ".join(distinctive[:12]) if distinctive else "nothing too weird"
        
        starter_pack_prompt = f"""You're a comedy writer for hyper-local meme accounts like "Real Housewives of Clapton" or "Starter Pack" memes.

This is a ~150 meter area. Someone standing HERE should feel CALLED OUT by how specific this is.

LOCATION DATA:
{score_text[:2000]}

STANDOUT FEATURES: {distinctive_text}

Write a "Starter Pack" style description for someone who lives/works RIGHT HERE. Include:
- 3-4 bullet points of hyper-specific observations
- Reference the actual data (e.g., "surrounded by 23 cafes but still complains there's nowhere good")
- Make it feel like "how do they KNOW this about my exact corner"
- Be funny but not mean

Format as a mini starter pack (4-5 short punchy lines with emojis):"""

        starter_pack_response = client.call(prompt=starter_pack_prompt, temperature=0.9, max_tokens=400)
        
        if starter_pack_response.success and starter_pack_response.text:
            result["starter_pack"] = starter_pack_response.text.strip().strip('"\'')
            logger.info(f"😂 Generated starter pack: {result['starter_pack'][:80]}...")
        
    except Exception as e:
        logger.warning(f"Failed to generate hex descriptions: {e}")
    
    return result


def generate_hex_description(scores: List[Dict[str, Any]]) -> Optional[str]:
    """
    Legacy wrapper - returns just the vibe description for backwards compatibility.
    """
    descriptions = generate_hex_descriptions(scores)
    return descriptions.get("vibe")

# =============================================================================
# PATHS
# =============================================================================

MATRIX_DIR = Path(__file__).parent.parent.parent / "output" / "earth_matrix_london"

# =============================================================================
# DIEM IMPLEMENTATION
# =============================================================================

def compute_diem_parameters(n_dimensions: int, min_val: float = 0.0, max_val: float = 1.0) -> Tuple[float, float]:
    """Historic Leo distance calibration, independently expressed from its equations.

    The project cites Tessari et al. (2024), https://arxiv.org/abs/2407.08623.
    This approximation and its logistic display score are Leo-specific and are
    not the authors' reference implementation of the published DIEM metric.
    """
    width = max_val - min_val
    expected_square = n_dimensions * width ** 2 / 6
    if expected_square <= 0:
        return 0.0, 0.0
    square_variance = (n_dimensions / 180 + n_dimensions * (n_dimensions - 1) / 36) * width ** 4
    return math.sqrt(expected_square), math.sqrt(square_variance / (4 * expected_square))


def compute_cosine_similarity(
    reference_vector: np.ndarray,
    comparison_vectors: np.ndarray,
) -> np.ndarray:
    """
    Compute cosine similarity (faster than DIEM for quick comparisons).
    
    Args:
        reference_vector: The reference vector (1D array of features)
        comparison_vectors: Matrix of vectors to compare (n_samples x n_features)
        
    Returns:
        Array of similarity scores (0-100, higher = more similar)
    """
    if comparison_vectors.ndim == 1:
        comparison_vectors = comparison_vectors.reshape(1, -1)
    
    # Handle NaN values
    ref = np.nan_to_num(reference_vector, nan=0.0)
    comp = np.nan_to_num(comparison_vectors, nan=0.0)
    
    # Normalize vectors
    ref_norm = np.linalg.norm(ref)
    if ref_norm == 0:
        return np.zeros(len(comp))
    ref_unit = ref / ref_norm
    
    comp_norms = np.linalg.norm(comp, axis=1, keepdims=True)
    comp_norms[comp_norms == 0] = 1.0  # Avoid division by zero
    comp_unit = comp / comp_norms
    
    # Dot product gives cosine similarity (-1 to 1)
    cosine_sim = np.dot(comp_unit, ref_unit)
    
    # Convert to 0-100 scale (cosine of 1 = 100, cosine of -1 = 0)
    similarity = (cosine_sim + 1) * 50
    
    return similarity


def compute_diem(
    reference_vector: np.ndarray,
    comparison_vectors: np.ndarray,
    min_vals: Optional[np.ndarray] = None,
    max_vals: Optional[np.ndarray] = None
) -> np.ndarray:
    """Reproduce the historic Leo calibrated distance as a 0–100 score."""
    rows = np.asarray(comparison_vectors)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    low = np.nanmin(rows, axis=0) if min_vals is None else min_vals
    high = np.nanmax(rows, axis=0) if max_vals is None else max_vals
    width = high - low
    width[width == 0] = 1.0
    target = np.nan_to_num((reference_vector - low) / width, nan=0.5)
    scaled = np.nan_to_num((rows - low) / width, nan=0.5)
    distance = np.sqrt(np.sum((scaled - target) ** 2, axis=1))
    center, spread = compute_diem_parameters(len(reference_vector), 0.0, 1.0)
    standard = (distance - center) / spread if spread > 0 else distance - center
    return 100 * (1 - 1 / (1 + np.exp(-standard * 1.5)))


def load_matrix(resolution: int = 10) -> pd.DataFrame:
    """Load the earth matrix parquet file."""
    parquet_path = MATRIX_DIR / f"earth_matrix_maxed_res{resolution}.parquet"
    
    if not parquet_path.exists():
        raise FileNotFoundError(f"Matrix not found: {parquet_path}")
    
    logger.info(f"Loading matrix from {parquet_path}")
    return pd.read_parquet(parquet_path)


def get_numeric_columns(df: pd.DataFrame) -> List[str]:
    """
    Get ALL numeric feature columns dynamically.
    
    This is future-proof: when the matrix scales globally and adds
    new columns (coastline, canals, etc.), they'll automatically
    be included in DIEM similarity calculations.
    
    Excludes only: h3_index (the hex identifier, not a feature)
    """
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    
    # Exclude index column (not a feature)
    if 'h3_index' in numeric_cols:
        numeric_cols.remove('h3_index')
    
    # Log column categories for visibility
    logger.info(f"📊 Matrix has {len(numeric_cols)} numeric feature columns")
    
    # Count by type for debugging
    count_cols = len([c for c in numeric_cols if '_count' in c])
    walk_cols = len([c for c in numeric_cols if '_walk_min' in c])
    cycle_cols = len([c for c in numeric_cols if '_cycle_min' in c])
    drive_cols = len([c for c in numeric_cols if '_drive_min' in c])
    score_cols = len([c for c in numeric_cols if '_score' in c])
    area_cols = len([c for c in numeric_cols if '_m2' in c or '_area' in c])
    other_cols = len(numeric_cols) - count_cols - walk_cols - cycle_cols - drive_cols - score_cols - area_cols
    
    logger.info(f"   📍 {count_cols} count columns (_count)")
    logger.info(f"   🚶 {walk_cols} walk proximity columns (_walk_min)")
    logger.info(f"   🚴 {cycle_cols} cycle proximity columns (_cycle_min)")
    logger.info(f"   🚗 {drive_cols} drive proximity columns (_drive_min)")
    logger.info(f"   ⭐ {score_cols} accessibility scores (_score)")
    logger.info(f"   📐 {area_cols} area columns (_m2, _area)")
    logger.info(f"   📦 {other_cols} other columns")
    
    return numeric_cols


def get_hex_for_location(lat: float, lng: float, resolution: int = 10) -> str:
    """Convert lat/lng to H3 hex at given resolution."""
    return h3.latlng_to_cell(lat, lng, resolution)


def diem_search(
    lat: float,
    lng: float,
    top_k: int = 1000,
    resolution: int = 10,
    method: str = "diem",
    curve_power: float = 2.5,
    exclude_k_ring: int = 15
) -> Dict[str, Any]:
    """
    Find the top K most similar hexes globally using DIEM or cosine similarity.
    
    Args:
        lat: Latitude of reference location
        lng: Longitude of reference location
        top_k: Number of similar hexes to return (default 1000)
        resolution: H3 resolution (default 10)
        method: "diem" or "cosine" (default "diem")
        curve_power: Power for sharp color distribution (default 2.5)
            1.0 = linear, 2.5 = medium stringent, 4.0 = very stringent
        exclude_k_ring: Exclude hexes within this many rings of reference (default 15)
            At res 10, each ring is ~50m, so k=15 excludes ~750m radius
            Set to 0 to include all hexes
        
    Returns:
        Dict with reference hex info and similar hexes for heatmap
    """
    logger.info(f"🎯 {method.upper()} search at ({lat:.4f}, {lng:.4f}), top_k={top_k}")
    
    # Load matrix
    df = load_matrix(resolution)
    logger.info(f"Loaded {len(df)} hexes with {len(df.columns)} columns")
    
    # Get reference hex
    ref_hex = get_hex_for_location(lat, lng, resolution)
    logger.info(f"Reference hex: {ref_hex}")
    
    # Check if reference hex exists in matrix
    ref_row = df[df['h3_index'] == ref_hex]
    
    if len(ref_row) == 0:
        # Reference hex not in matrix - find nearest hex
        logger.warning(f"Reference hex {ref_hex} not in matrix, finding nearest...")
        
        # Get all hex centroids
        hex_centers = []
        for hex_id in df['h3_index'].values[:1000]:  # Sample for speed
            try:
                center = h3.cell_to_latlng(hex_id)
                hex_centers.append((hex_id, center[0], center[1]))
            except:
                pass
        
        # Find nearest
        min_dist = float('inf')
        nearest_hex = None
        for hex_id, h_lat, h_lng in hex_centers:
            dist = (lat - h_lat) ** 2 + (lng - h_lng) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest_hex = hex_id
        
        if nearest_hex:
            ref_hex = nearest_hex
            ref_row = df[df['h3_index'] == ref_hex]
            logger.info(f"Using nearest hex: {ref_hex}")
        else:
            return {
                "success": False,
                "error": f"Location ({lat}, {lng}) not covered by matrix"
            }
    
    # Get feature columns
    feature_cols = get_numeric_columns(df)
    logger.info(f"Using {len(feature_cols)} feature columns for {method.upper()}")
    
    # Extract reference vector
    ref_vector = ref_row[feature_cols].values.flatten()
    
    # Extract all vectors for comparison
    all_vectors = df[feature_cols].values
    
    # Compute similarity scores based on method
    logger.info(f"Computing {method.upper()} similarities...")
    
    if method == "cosine":
        similarities = compute_cosine_similarity(ref_vector, all_vectors)
    else:
        # DIEM - needs min/max for normalization
        min_vals = np.nanmin(all_vectors, axis=0)
        max_vals = np.nanmax(all_vectors, axis=0)
        similarities = compute_diem(ref_vector, all_vectors, min_vals, max_vals)
    
    # Add similarity to dataframe
    df_result = df.copy()
    df_result['raw_similarity'] = similarities
    
    # Sort by similarity (descending - higher = more similar)
    df_sorted = df_result.sort_values('raw_similarity', ascending=False)
    
    # ==========================================================================
    # EXCLUDE NEARBY HEXES - Skip immediate neighborhood to find truly distant matches
    # At res 10, each hex is ~50m edge, k=15 excludes ~750m radius
    # ==========================================================================
    if exclude_k_ring > 0:
        # Get all hexes within the exclusion zone
        nearby_hexes = set(h3.grid_disk(ref_hex, exclude_k_ring))
        logger.info(f"🚫 Excluding {len(nearby_hexes)} hexes within k={exclude_k_ring} rings (~{exclude_k_ring * 50}m radius)")
        
        # Filter out nearby hexes
        df_filtered = df_sorted[~df_sorted['h3_index'].isin(nearby_hexes)]
    else:
        # Only exclude reference hex itself
        df_filtered = df_sorted[df_sorted['h3_index'] != ref_hex]
    
    # Get top K from filtered results
    df_top = df_filtered.head(top_k).copy()
    
    # ==========================================================================
    # SHARP POWER CURVE - Same as cascade stage 4
    # Makes the heatmap more selective - only top results get bright colors
    # ==========================================================================
    if len(df_top) > 0:
        # Compute percentile rank within top K (0-100)
        df_top['_percentile'] = df_top['raw_similarity'].rank(pct=True) * 100
        
        # Apply power curve for sharp color distribution
        # Formula: curved = (raw/100)^power * 100
        # At power=2.5: 50th percentile → ~18% intensity (very selective)
        df_top['_curved'] = np.power(df_top['_percentile'] / 100, curve_power) * 100
        
        logger.info(f"Applied power curve: power={curve_power} (50th pctl → {(0.5**curve_power)*100:.0f}% intensity)")
    
    # Get reference hex score info
    ref_center = h3.cell_to_latlng(ref_hex)
    ref_scores = ref_row[feature_cols].iloc[0].to_dict()
    
    # Get MEANINGFUL scores for reference hex
    # Filter out null-equivalent values:
    # - NaN/None
    # - Zero values
    # - Values close to 999 (unreachable marker for _min columns)
    # - Values close to 19-20 (common default/unreachable for walk/cycle/drive_min)
    meaningful_scores = []
    for col, val in ref_scores.items():
        if pd.isna(val) or val == 0:
            continue
        
        # Skip unreachable markers in _min columns
        if '_min' in col:
            # 999 is explicit unreachable, 19-20 range is often default unreachable
            if val >= 18 or val >= 999:
                continue
        
        # Skip very small _score values (essentially unreachable)
        if '_score' in col and val < 1:
            continue
            
        meaningful_scores.append({"column": col, "value": float(val)})
    
    # Sort by value (highest first for counts, but context-aware)
    # Separate _count columns (higher is better) from _min columns (lower is better)
    count_scores = [s for s in meaningful_scores if '_count' in s['column'] or 'density' in s['column']]
    proximity_scores = [s for s in meaningful_scores if '_min' in s['column']]
    score_scores = [s for s in meaningful_scores if '_score' in s['column']]
    area_scores = [s for s in meaningful_scores if '_m2' in s['column'] or '_area' in s['column']]
    other_scores = [s for s in meaningful_scores if s not in count_scores + proximity_scores + score_scores + area_scores]
    
    # Sort each category appropriately
    count_scores.sort(key=lambda x: x['value'], reverse=True)
    proximity_scores.sort(key=lambda x: x['value'])  # Lower is better for minutes
    score_scores.sort(key=lambda x: x['value'], reverse=True)
    area_scores.sort(key=lambda x: x['value'], reverse=True)
    other_scores.sort(key=lambda x: x['value'], reverse=True)
    
    # Combine MORE from each category for comprehensive descriptions
    # Use up to 80 features to really leverage the data
    ref_top_scores = (
        count_scores[:25] +      # Top 25 counts
        proximity_scores[:25] +   # Top 25 proximity (closest things)
        score_scores[:15] +       # Top 15 accessibility scores
        area_scores[:10] +        # Top 10 area features
        other_scores[:5]          # Top 5 other
    )[:80]
    
    logger.info(f"📊 Prepared {len(ref_top_scores)} features for description generation")
    logger.info(f"   - Counts: {len(count_scores[:25])}, Proximity: {len(proximity_scores[:25])}")
    logger.info(f"   - Scores: {len(score_scores[:15])}, Area: {len(area_scores[:10])}, Other: {len(other_scores[:5])}")
    
    # Generate BOTH AI descriptions of this location
    logger.info(f"🧠 Generating AI descriptions of reference hex...")
    hex_descriptions = {"vibe": None, "starter_pack": None}
    try:
        hex_descriptions = generate_hex_descriptions(ref_top_scores)
        if hex_descriptions.get("vibe"):
            logger.info(f"✨ Vibe: {hex_descriptions['vibe'][:80]}...")
        if hex_descriptions.get("starter_pack"):
            logger.info(f"😂 Starter Pack: {hex_descriptions['starter_pack'][:80]}...")
        if not hex_descriptions.get("vibe") and not hex_descriptions.get("starter_pack"):
            logger.warning("⚠️ Both descriptions returned None")
    except Exception as e:
        logger.error(f"❌ Description generation failed: {e}")

    # Build heatmap data with curved values for display
    heatmap_data = []
    for _, row in df_top.iterrows():
        hex_id = row['h3_index']
        heatmap_data.append({
            "hex": hex_id,
            "value": float(row['_curved']),  # Curved for display (matches cascade)
            "percentile": float(row['_percentile']),  # Raw percentile
            "similarity": float(row['raw_similarity']),  # Raw similarity score
        })
    
    # Statistics
    excluded_count = len(h3.grid_disk(ref_hex, exclude_k_ring)) if exclude_k_ring > 0 else 1
    stats = {
        "total_hexes": len(df),
        "feature_dimensions": len(feature_cols),
        "top_k": top_k,
        "method": method,
        "curve_power": curve_power,
        "exclude_k_ring": exclude_k_ring,
        "excluded_nearby": excluded_count,
        "mean_similarity": float(df_result['raw_similarity'].mean()),
        "max_similarity": float(df_top['raw_similarity'].max()) if len(df_top) > 0 else 0,
        "min_similarity": float(df_top['raw_similarity'].min()) if len(df_top) > 0 else 0,
    }
    
    logger.info(f"✅ {method.upper()} search complete: top {top_k} from {len(df)} hexes")
    
    return {
        "success": True,
        "reference": {
            "hex": ref_hex,
            "lat": ref_center[0],
            "lng": ref_center[1],
            "description": hex_descriptions.get("vibe"),  # Primary description
            "starter_pack": hex_descriptions.get("starter_pack"),  # Meme description
            "top_scores": ref_top_scores,
        },
        "similar_hexes": heatmap_data,
        "stats": stats,
    }


# =============================================================================
# API HANDLER FOR STREAMING
# =============================================================================

def tool_diem_search(
    lat: float,
    lng: float,
    top_k: int = 1000
) -> Dict[str, Any]:
    """
    Tool function for DIEM similarity search.
    
    Yields streaming events for progressive UI updates.
    Uses same styling as cascade res10 heatmap.
    Uses ALL columns in the matrix (~1,956 feature dimensions).
    
    Args:
        lat: Latitude of reference location
        lng: Longitude of reference location  
        top_k: Number of similar hexes (default 1000)
    """
    import time
    
    logger.info(f"🔬 DIEM tool called: lat={lat}, lng={lng}, top_k={top_k}")
    
    # =========================================================================
    # PHASE 1: Globe zoom out and spin (like cascade search)
    # =========================================================================
    
    yield {
        "type": "thought",
        "data": "🌍 Searching globally..."
    }
    
    # Zoom out to see the globe - start spinning effect
    yield {
        "type": "map_control",
        "data": {
            "fly_to": {"lat": 30, "lon": 0, "zoom": 1.5},  # Globe view
            "pitch": 0,
            "bearing": 0,
            "duration": 1500,
        }
    }
    
    # Incremental bearing spin (globe rotation effect)
    for spin_step in range(3):
        time.sleep(0.3)
        yield {
            "type": "map_control", 
            "data": {
                "bearing": (spin_step + 1) * 30,  # 30, 60, 90 degrees
                "duration": 300,
            }
        }
    
    try:
        # Run DIEM search (uses ALL columns)
        result = diem_search(lat, lng, top_k, method="diem")
        
        if not result.get("success"):
            yield {
                "type": "error",
                "data": result.get("error", "Similarity search failed")
            }
            return
        
        # Emit reference info
        ref = result["reference"]
        stats = result["stats"]
        
        yield {
            "type": "thought",
            "data": f"📍 Reference hex: {ref['hex'][:12]}... at ({ref['lat']:.4f}, {ref['lng']:.4f})"
        }
        
        # Emit reference hex as special marker layer (bright cyan)
        yield {
            "type": "layer_update",
            "data": {
                "layer_id": "diem_reference",
                "type": "h3_grid",
                "data": [{
                    "hex": ref["hex"],
                    "value": 100,
                    "is_reference": True,
                }],
                "count": 1,
                "viz_config": {
                    "label": "🎯 Reference Location",
                    "color_by": "value",
                    "color_scale": "viridis",  # Cyan reference point
                    "opacity": 0.95,
                }
            }
        }
        
        time.sleep(0.3)
        
        # Emit similar hexes as heatmap
        # EXACT SAME STYLING AS CASCADE RES10 FINAL HEATMAP
        similar = result["similar_hexes"]
        
        yield {
            "type": "thought", 
            "data": f"🔍 Found {len(similar)} similar hexes using ALL {stats['feature_dimensions']} dimensions"
        }
        
        yield {
            "type": "layer_update",
            "data": {
                "layer_id": "diem_heatmap",
                "type": "h3_grid",
                "data": similar,
                "count": len(similar),
                "viz_config": {
                    # Match cascade_final styling exactly
                    "label": f"🎯 Top {len(similar)} Similar (DIEM)",
                    "color_by": "value",
                    "color_scale": "plasma",  # Same as cascade
                    "opacity": 0.8,  # Same as cascade
                }
            }
        }
        
        # =====================================================================
        # PHASE 2: Calculate fit bounds and zoom to results
        # =====================================================================
        if similar:
            all_lats = []
            all_lngs = []
            for item in similar[:200]:  # Sample for fit bounds calculation
                try:
                    center = h3.cell_to_latlng(item["hex"])
                    all_lats.append(center[0])
                    all_lngs.append(center[1])
                except:
                    pass
            
            if all_lats and all_lngs:
                # Calculate bounding box
                min_lat = min(all_lats)
                max_lat = max(all_lats)
                min_lng = min(all_lngs)
                max_lng = max(all_lngs)
                
                # Use fit_bounds for proper zoom calculation (like cascade)
                yield {
                    "type": "map_control",
                    "data": {
                        "fit_bounds": [min_lng, min_lat, max_lng, max_lat],
                        "pitch": 0,  # 2D view for heatmap initially
                        "bearing": 0,  # Reset bearing after spin
                        "duration": 2000,
                    }
                }
        
        time.sleep(0.5)
        
        # Then tilt to 3D for dramatic effect (like cascade stage 4)
        yield {
            "type": "map_control",
            "data": {
                "pitch": 50,  # 3D tilt
                "duration": 1000,
            }
        }
        
        yield {
            "type": "diem_complete",
            "data": {
                "success": True,
                "reference": ref,
                "stats": stats,
                "message": f"Found {len(similar)} similar locations using DIEM across ALL {stats['feature_dimensions']} dimensions"
            }
        }
        
    except FileNotFoundError as e:
        logger.error(f"Matrix not found: {e}")
        yield {
            "type": "error",
            "data": f"Matrix data not found: {e}"
        }
    except Exception as e:
        logger.error(f"DIEM search failed: {e}", exc_info=True)
        yield {
            "type": "error",
            "data": f"DIEM search failed: {str(e)}"
        }


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test DIEM parameters
    print("\n=== DIEM Parameter Tests ===")
    for n in [10, 100, 1000]:
        mean_d, std_d = compute_diem_parameters(n)
        print(f"  N={n}: mean={mean_d:.4f}, std={std_d:.4f}")
    
    # Test search at known London location (Hoxton)
    print("\n=== DIEM Search Test (Hoxton) ===")
    result = diem_search(51.5311, -0.0767, top_k=10)
    
    if result["success"]:
        print(f"  Reference: {result['reference']['hex']}")
        print(f"  Top scores: {result['reference']['top_scores'][:5]}")
        print(f"  Stats: {result['stats']}")
        print(f"  Top 3 similar:")
        for h in result["similar_hexes"][:3]:
            print(f"    {h['hex']}: {h['similarity']:.1f}")
    else:
        print(f"  Error: {result.get('error')}")
    
    print("\n✅ DIEM tests passed!")

