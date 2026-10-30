#!/usr/bin/env python3
"""
Area Insights Engine
====================

Generates AI-powered descriptions for top-scoring area clusters.

Pipeline:
1. Aggregate res10 scores → res8 (sum user columns per parent h8)
2. Cluster adjacent h8 hexes using Union-Find
3. Select top 100 clusters by total score
4. For each cluster: select user columns + top 10 other columns
5. Generate one-liner descriptions using Gemini 2.5 Flash Lite

Uses GOOGLE_AI_API_KEY (puedo_casa project) for Gemini API calls.
"""

import os
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

import h3
import pandas as pd
import numpy as np

# Import Gemini client
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Gemini model for cheap description generation
DESCRIPTION_MODEL = "gemini-2.5-flash-lite"

# Max clusters to process (balance between coverage and API cost)
MAX_CLUSTERS = 100

# Max hexes per cluster (prevents oversized "super-clusters")
# Typical res8 hex ~0.7 km² → 20 hexes ≈ 14 km² neighborhood
MAX_CLUSTER_SIZE = 20

# Column selection for descriptions
TOP_DENSITY_COLS = 10   # Top N _count/_m2 columns
TOP_TRAVEL_COLS = 10    # Top N _walk_min/_cycle_min/_drive_min columns


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class AreaCluster:
    """A cluster of adjacent H3 res8 hexagons."""
    cluster_id: str
    hexes: List[str]  # H3 res8 hex IDs
    centroid: Tuple[float, float]  # (lng, lat)
    total_score: float
    hex_scores: Dict[str, float]  # hex_id -> score
    column_scores: Dict[str, float]  # column_name -> aggregated score
    description: Optional[str] = None
    top_columns: List[Dict[str, Any]] = field(default_factory=list)  # [{"name": str, "value": float, "is_user": bool}]


# =============================================================================
# UNION-FIND FOR CLUSTERING
# =============================================================================

class UnionFind:
    """Union-Find data structure for clustering adjacent hexes with size limit."""
    
    def __init__(self, max_size: int = MAX_CLUSTER_SIZE):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}
        self.size: Dict[str, int] = {}  # Track cluster sizes
        self.max_size = max_size
    
    def find(self, x: str) -> str:
        """Find root with path compression."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self.size[x] = 1
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def get_size(self, x: str) -> int:
        """Get the size of the cluster containing x."""
        root = self.find(x)
        return self.size.get(root, 1)
    
    def union(self, x: str, y: str) -> bool:
        """
        Union by rank, respecting max cluster size.
        
        Returns:
            True if union was performed, False if skipped due to size limit.
        """
        px, py = self.find(x), self.find(y)
        if px == py:
            return True  # Already in same cluster
        
        # Check if combined size would exceed limit
        combined_size = self.size.get(px, 1) + self.size.get(py, 1)
        if combined_size > self.max_size:
            return False  # Skip union - would create oversized cluster
        
        # Union by rank
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        
        # Update size
        self.size[px] = combined_size
        
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1
        
        return True
    
    def get_clusters(self) -> Dict[str, List[str]]:
        """Get all clusters as {root: [members]}."""
        clusters: Dict[str, List[str]] = {}
        for x in self.parent:
            root = self.find(x)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(x)
        return clusters


# =============================================================================
# STEP 1: PREPARE RES8 DATA (no aggregation needed - use res8 directly)
# =============================================================================

def prepare_res8_data(
    df_res8: pd.DataFrame,
    user_columns: List[str],
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """
    Prepare res8 data for clustering and description generation.
    
    Args:
        df_res8: DataFrame with res8 hexes (directly from Stage 2 or loaded)
        user_columns: Columns the user specifically requested (for scoring)
        
    Returns:
        (df_res8, density_columns, travel_columns)
    """
    logger.info(f"Preparing {len(df_res8)} res8 hexes...")
    
    df = df_res8.copy()
    
    # Identify column types
    all_cols = [c for c in df.columns if c not in ["h3_index", "_score", "_percentile", "_curved", "_mult_score", "_parent"]]
    numeric_cols = [c for c in all_cols if df[c].dtype in ['float64', 'int64', 'float32', 'int32']]
    
    # DENSITY columns: Only _count (POI counts - meaningful for user)
    # EXCLUDE _m2 and _avg_area columns (land areas - not useful for descriptions)
    density_cols = [c for c in numeric_cols if "_count" in c and "_m2" not in c and "_avg_area" not in c]
    
    # TRAVEL TIME columns: _walk_min, _cycle_min, _drive_min (how to get there)
    travel_cols = [c for c in numeric_cols if "_walk_min" in c or "_cycle_min" in c or "_drive_min" in c]
    
    logger.info(f"  Density columns (_count): {len(density_cols)}")
    logger.info(f"  Travel time columns (_min): {len(travel_cols)}")
    
    # Calculate user score for clustering/ranking
    existing_user_cols = [c for c in user_columns if c in df.columns]
    if existing_user_cols:
        df["_user_score"] = df[existing_user_cols].fillna(0).sum(axis=1)
    else:
        df["_user_score"] = 0
    
    logger.info(f"  User columns matched: {len(existing_user_cols)}/{len(user_columns)}")
    
    return df, density_cols, travel_cols


# =============================================================================
# STEP 2: CLUSTER ADJACENT HEXES
# =============================================================================

def cluster_adjacent_hexes(
    df_res8: pd.DataFrame,
    score_column: str = "_user_score",
    max_cluster_size: int = MAX_CLUSTER_SIZE
) -> List[AreaCluster]:
    """
    Cluster adjacent res8 hexes using Union-Find with size limit.
    
    Args:
        df_res8: DataFrame with res8 hexes
        score_column: Column to use for scoring
        max_cluster_size: Maximum hexes per cluster (prevents oversized super-clusters)
        
    Returns:
        List of AreaCluster objects (unsorted)
    """
    logger.info(f"Clustering {len(df_res8)} res8 hexes (max size: {max_cluster_size})...")
    
    # Get set of all hex IDs for fast lookup
    hex_ids = set(df_res8["h3_index"].tolist())
    hex_scores = dict(zip(df_res8["h3_index"], df_res8[score_column]))
    
    # Build Union-Find structure with size limit
    uf = UnionFind(max_size=max_cluster_size)
    
    for hex_id in hex_ids:
        # Initialize this hex
        uf.find(hex_id)
        
        # Get neighbors (k=1 ring, excluding self)
        try:
            neighbors = set(h3.grid_disk(hex_id, 1)) - {hex_id}
        except Exception as e:
            logger.warning(f"Failed to get neighbors for {hex_id}: {e}")
            continue
        
        # Union with neighbors that are also in our set
        for neighbor in neighbors:
            if neighbor in hex_ids:
                uf.union(hex_id, neighbor)
    
    # Get clusters
    raw_clusters = uf.get_clusters()
    logger.info(f"  Found {len(raw_clusters)} clusters")
    
    # Build AreaCluster objects
    clusters = []
    for i, (root, members) in enumerate(raw_clusters.items()):
        # Calculate total score
        total = sum(hex_scores.get(h, 0) for h in members)
        
        # Calculate centroid (average of hex centroids)
        lats, lngs = [], []
        for hex_id in members:
            try:
                lat, lng = h3.cell_to_latlng(hex_id)
                lats.append(lat)
                lngs.append(lng)
            except:
                pass
        
        centroid = (
            sum(lngs) / len(lngs) if lngs else 0,
            sum(lats) / len(lats) if lats else 0
        )
        
        # Get per-hex scores
        member_scores = {h: hex_scores.get(h, 0) for h in members}
        
        clusters.append(AreaCluster(
            cluster_id=f"cluster_{i:03d}",
            hexes=members,
            centroid=centroid,
            total_score=total,
            hex_scores=member_scores,
            column_scores={},  # Will be filled later
        ))
    
    logger.info(f"  Built {len(clusters)} AreaCluster objects")
    return clusters


# =============================================================================
# STEP 3: SELECT TOP 100 CLUSTERS
# =============================================================================

def select_top_clusters(
    clusters: List[AreaCluster],
    max_clusters: int = MAX_CLUSTERS
) -> List[AreaCluster]:
    """
    Select top N clusters by total score.
    
    Args:
        clusters: List of all clusters
        max_clusters: Maximum number to return
        
    Returns:
        Top clusters sorted by total_score descending
    """
    # Sort by total score descending
    sorted_clusters = sorted(clusters, key=lambda c: c.total_score, reverse=True)
    
    # Take top N
    top = sorted_clusters[:max_clusters]
    
    logger.info(f"Selected top {len(top)} clusters (from {len(clusters)} total)")
    if top:
        logger.info(f"  Score range: {top[-1].total_score:.1f} - {top[0].total_score:.1f}")
        logger.info(f"  Hex counts: {min(len(c.hexes) for c in top)} - {max(len(c.hexes) for c in top)}")
    
    return top


# =============================================================================
# STEP 4: SELECT TOP COLUMNS FOR EACH CLUSTER
# =============================================================================

def select_columns_for_cluster(
    cluster: AreaCluster,
    df_res8: pd.DataFrame,
    user_columns: List[str],
    density_columns: List[str],
    travel_columns: List[str],
    max_density: int = TOP_DENSITY_COLS,
    max_travel: int = TOP_TRAVEL_COLS
) -> AreaCluster:
    """
    Select top density columns + top travel time columns for a cluster.
    
    PRIORITY ORDER:
    1. User columns FIRST (always included if they have data)
    2. Then fill remaining slots with top non-user columns
    
    Two separate rankings:
    - DENSITY (what's here): Top N _count/_m2 columns by value (higher = better)
    - TRAVEL (accessibility): Top N _walk/_cycle/_drive_min columns by value (lower = better)
    
    Args:
        cluster: The cluster to process
        df_res8: Full res8 DataFrame  
        user_columns: Columns user specifically requested (PRIORITIZED)
        density_columns: All _count/_m2 columns
        travel_columns: All _walk_min/_cycle_min/_drive_min columns
        max_density: Max density columns to include
        max_travel: Max travel time columns to include
        
    Returns:
        Updated cluster with column_scores and top_columns filled
    """
    # Get rows for this cluster's hexes
    cluster_df = df_res8[df_res8["h3_index"].isin(cluster.hexes)]
    
    if len(cluster_df) == 0:
        return cluster
    
    # Calculate aggregated values for each column across cluster
    # DENSITY (_count): Use SUM - total amenities in the area
    # TRAVEL (_min): Use MIN - best accessibility (closest)
    col_agg = {}
    
    for col in density_columns:
        if col in cluster_df.columns:
            sum_val = cluster_df[col].sum()
            if not pd.isna(sum_val) and sum_val > 0:
                col_agg[col] = sum_val
    
    for col in travel_columns:
        if col in cluster_df.columns:
            # Filter out 999/unreachable values before taking min
            valid_vals = cluster_df[col][cluster_df[col] < 900]
            if len(valid_vals) > 0:
                min_val = valid_vals.min()
                if not pd.isna(min_val):
                    col_agg[col] = min_val
    
    cluster.column_scores = col_agg
    
    # Separate user columns into density vs travel
    user_col_set = set(user_columns)
    user_density = [c for c in user_columns if c in density_columns and c in col_agg]
    user_travel = [c for c in user_columns if c in travel_columns and c in col_agg]
    
    # Build top_columns list with two categories
    top_cols = []
    added_cols = set()
    
    # === DENSITY COLUMNS ===
    # 1. User density columns FIRST (always included, marked with ★)
    for col in user_density:
        val = col_agg[col]
        top_cols.append({
            "name": col,
            "value": round(val, 0),  # Whole numbers for counts (SUM)
            "category": "density",
            "is_user": True
        })
        added_cols.add(col)
    
    # 2. Fill remaining density slots with top non-user columns
    remaining_density = max_density - len(user_density)
    if remaining_density > 0:
        density_scores = [
            (c, col_agg.get(c, 0)) 
            for c in density_columns 
            if c in col_agg and c not in added_cols and col_agg.get(c, 0) > 0
        ]
        density_scores.sort(key=lambda x: x[1], reverse=True)
        
        for col, val in density_scores[:remaining_density]:
            top_cols.append({
                "name": col,
                "value": round(val, 0),  # Whole numbers for counts (SUM)
                "category": "density",
                "is_user": False
            })
            added_cols.add(col)
    
    # === TRAVEL TIME COLUMNS ===
    # 1. User travel columns FIRST (always included, marked with ★)
    for col in user_travel:
        val = col_agg[col]
        if val < 900:  # Only if reachable
            top_cols.append({
                "name": col,
                "value": round(val, 1),  # Minutes with 1 decimal (MIN)
                "category": "travel",
                "is_user": True
            })
            added_cols.add(col)
    
    # 2. Fill remaining travel slots with top non-user columns
    remaining_travel = max_travel - len([c for c in user_travel if col_agg.get(c, 999) < 900])
    if remaining_travel > 0:
        travel_scores = [
            (c, col_agg.get(c, 999)) 
            for c in travel_columns 
            if c in col_agg and c not in added_cols and col_agg.get(c, 999) < 900
        ]
        travel_scores.sort(key=lambda x: x[1])  # Ascending - lower is better
        
        for col, val in travel_scores[:remaining_travel]:
            top_cols.append({
                "name": col,
                "value": round(val, 1),  # Minutes with 1 decimal (MIN)
                "category": "travel",
                "is_user": False
            })
            added_cols.add(col)
    
    cluster.top_columns = top_cols
    
    return cluster


# =============================================================================
# STEP 5: GENERATE DESCRIPTIONS WITH GEMINI
# =============================================================================

def _format_density_column(col: str) -> str:
    """Convert density column name to human-readable format."""
    name = col.replace("_count", "s").replace("_in_hex_m2", " (m²)").replace("_avg_area_m2", " avg size")
    name = name.replace("_", " ")
    return name.title()


def _format_travel_column(col: str, value: float) -> str:
    """Convert travel column to human-readable format with time."""
    # Extract POI name and travel mode
    if "_walk_min" in col:
        poi = col.replace("_walk_min", "").replace("_", " ").title()
        return f"{poi}: {value:.0f} min walk"
    elif "_cycle_min" in col:
        poi = col.replace("_cycle_min", "").replace("_", " ").title()
        return f"{poi}: {value:.0f} min cycle"
    elif "_drive_min" in col:
        poi = col.replace("_drive_min", "").replace("_", " ").title()
        return f"{poi}: {value:.0f} min drive"
    else:
        return f"{col}: {value:.0f}"


def _build_description_prompt(
    cluster: AreaCluster,
    user_query: str
) -> str:
    """Build the prompt for generating a cluster description."""
    
    # Separate density and travel columns
    density_cols = [c for c in cluster.top_columns if c.get("category") == "density"]
    travel_cols = [c for c in cluster.top_columns if c.get("category") == "travel"]
    
    # Format DENSITY section (what's here)
    density_lines = []
    for col_info in density_cols[:8]:
        name = _format_density_column(col_info["name"])
        user_flag = " ★" if col_info.get("is_user") else ""
        density_lines.append(f"  - {name}: {col_info['value']:.0f}{user_flag}")
    
    # Format TRAVEL TIME section (how accessible)
    travel_lines = []
    for col_info in travel_cols[:8]:
        formatted = _format_travel_column(col_info["name"], col_info["value"])
        user_flag = " ★" if col_info.get("is_user") else ""
        travel_lines.append(f"  - {formatted}{user_flag}")
    
    density_text = "\n".join(density_lines) if density_lines else "  (no density data)"
    travel_text = "\n".join(travel_lines) if travel_lines else "  (no travel data)"
    
    prompt = f"""You are a helpful real estate assistant. Given a user's search criteria and an area's data, write ONE sentence (max 35 words) explaining why this area matches what they're looking for.

Be specific about numbers. Highlight 2-3 key features. Don't say "this area" - describe it directly.

User wants: "{user_query}"

TOTAL AMENITIES IN THIS AREA (summed across all hexes):
{density_text}

BEST ACCESSIBILITY (minimum travel time to nearest):
{travel_text}

(★ = user priority)
Area size: {len(cluster.hexes)} hex{"es" if len(cluster.hexes) > 1 else ""} ({"small pocket" if len(cluster.hexes) == 1 else "neighborhood-sized" if len(cluster.hexes) < 5 else "larger zone"})

Write a single compelling sentence (no quotes):"""
    
    return prompt


def generate_descriptions_batch(
    clusters: List[AreaCluster],
    user_query: str,
    max_workers: int = 5
) -> List[AreaCluster]:
    """
    Generate descriptions for all clusters using Gemini 2.5 Flash Lite.
    
    Uses thread pool for parallel API calls (Gemini client is synchronous).
    
    Args:
        clusters: List of clusters to describe
        user_query: The user's original search query
        max_workers: Number of parallel threads for API calls
        
    Returns:
        Clusters with descriptions filled in
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    
    logger.info(f"Generating descriptions for {len(clusters)} clusters...")
    logger.info(f"  Model: {DESCRIPTION_MODEL}")
    logger.info(f"  User query: {user_query[:100]}...")
    
    # Initialize Gemini client with flash-lite model
    try:
        client = GeminiClient(model=DESCRIPTION_MODEL)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        # Return clusters without descriptions
        for c in clusters:
            c.description = "Area matching your criteria."
        return clusters
    
    def generate_single(cluster: AreaCluster) -> AreaCluster:
        """Generate description for a single cluster (sync)."""
        prompt = _build_description_prompt(cluster, user_query)
        
        try:
            response = client.call(
                prompt=prompt,
                temperature=0.7,  # Slightly creative
                max_tokens=100,
                model=DESCRIPTION_MODEL
            )
            
            if response.success and response.text:
                # Clean up the response
                desc = response.text.strip()
                # Remove quotes if present
                if desc.startswith('"') and desc.endswith('"'):
                    desc = desc[1:-1]
                cluster.description = desc
            else:
                logger.warning(f"Failed to generate description for {cluster.cluster_id}: {response.error}")
                cluster.description = "Area matching your search criteria."
                
        except Exception as e:
            logger.error(f"Error generating description for {cluster.cluster_id}: {e}")
            cluster.description = "Area matching your search criteria."
        
        return cluster
    
    # Process with thread pool for parallelism
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_cluster = {executor.submit(generate_single, c): c for c in clusters}
        
        # Collect results as they complete
        for future in as_completed(future_to_cluster):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                cluster = future_to_cluster[future]
                logger.error(f"Task failed for {cluster.cluster_id}: {e}")
                cluster.description = "Area matching your search criteria."
                results.append(cluster)
    
    logger.info(f"  Generated {len([c for c in results if c.description])} descriptions")
    
    return results


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def generate_area_insights(
    df_res8: pd.DataFrame,
    user_columns: List[str],
    user_query: str,
    max_clusters: int = MAX_CLUSTERS,
    max_cluster_size: int = MAX_CLUSTER_SIZE,
    generate_descriptions: bool = True
) -> List[AreaCluster]:
    """
    Full pipeline: prepare res8 → cluster → select top → select columns → describe.
    
    Uses res8 data DIRECTLY (no aggregation from res10). This provides:
    - More granular travel time data from k-ring propagation
    - Actual _walk_min/_cycle_min/_drive_min values (not averaged scores)
    
    Args:
        df_res8: DataFrame with res8 hexes (from Stage 2 of cascade, or loaded directly)
        user_columns: Columns user specifically requested
        user_query: The user's original search query
        max_clusters: Maximum clusters to return
        max_cluster_size: Max hexes per cluster (prevents oversized super-clusters)
        generate_descriptions: Whether to call Gemini for descriptions
        
    Returns:
        List of AreaCluster objects with descriptions
    """
    logger.info("=" * 60)
    logger.info("AREA INSIGHTS PIPELINE (res8 direct)")
    logger.info("=" * 60)
    
    # Step 1: Prepare res8 data and identify column types
    df_res8, density_columns, travel_columns = prepare_res8_data(df_res8, user_columns)
    
    if len(df_res8) == 0:
        logger.warning("No res8 hexes in data")
        return []
    
    # Step 2: Cluster adjacent hexes with size limit
    all_clusters = cluster_adjacent_hexes(df_res8, max_cluster_size=max_cluster_size)
    
    if len(all_clusters) == 0:
        logger.warning("No clusters found")
        return []
    
    # Step 3: Select top clusters by user score
    top_clusters = select_top_clusters(all_clusters, max_clusters)
    
    # Step 4: Select top density + travel columns for each cluster
    for cluster in top_clusters:
        select_columns_for_cluster(
            cluster, df_res8, user_columns,
            density_columns, travel_columns
        )
    
    # Step 5: Generate descriptions (uses thread pool for parallel API calls)
    if generate_descriptions:
        top_clusters = generate_descriptions_batch(top_clusters, user_query)
    
    logger.info("=" * 60)
    logger.info(f"PIPELINE COMPLETE: {len(top_clusters)} clusters")
    logger.info("=" * 60)
    
    return top_clusters


# =============================================================================
# SERIALIZATION
# =============================================================================

def clusters_to_json(clusters: List[AreaCluster]) -> List[Dict[str, Any]]:
    """Convert clusters to JSON-serializable format."""
    return [
        {
            "clusterId": c.cluster_id,
            "hexes": c.hexes,
            "centroid": list(c.centroid),
            "totalScore": c.total_score,
            "description": c.description,
            "topColumns": c.top_columns,
        }
        for c in clusters
    ]


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Testing Area Insights Engine (LONDON res8 data) ===\n")
    
    # Load REAL res8 parquet from London matrix build (4,094 hexes)
    from pathlib import Path
    matrix_dir = Path(__file__).parent.parent.parent / "output" / "earth_matrix_london"
    res8_file = matrix_dir / "earth_matrix_maxed_res8.parquet"
    
    if not res8_file.exists():
        print(f"ERROR: Real parquet not found at {res8_file}")
        print("Run build_global_matrix.py first to generate test data")
        exit(1)
    
    df_res8 = pd.read_parquet(res8_file)
    print(f"Loaded REAL res8 data: {len(df_res8)} hexes, {len(df_res8.columns)} columns")
    
    # Show what columns exist
    walk_cols = [c for c in df_res8.columns if '_walk_min' in c]
    count_cols = [c for c in df_res8.columns if '_count' in c]
    print(f"  _walk_min columns: {len(walk_cols)}")
    print(f"  _count columns: {len(count_cols)}")
    
    # Use columns that actually exist in the real data
    # Note: transit columns are named *_station_walk_min (e.g., metro_station_walk_min)
    user_cols = ["cafe_count", "metro_station_walk_min", "park_walk_min"]
    user_query = "walkable area with coffee shops near a tube station and parks"
    
    # Run pipeline
    clusters = generate_area_insights(
        df_res8=df_res8,
        user_columns=user_cols,
        user_query=user_query,
        max_clusters=5,
        generate_descriptions=True  # Will use Gemini
    )
    
    print(f"\n=== Results: {len(clusters)} clusters ===\n")
    
    for cluster in clusters[:3]:
        print(f"Cluster {cluster.cluster_id}:")
        print(f"  Hexes: {len(cluster.hexes)}")
        print(f"  Total score: {cluster.total_score:.1f}")
        print(f"  Centroid: {cluster.centroid}")
        print(f"  Description: {cluster.description}")
        print(f"  Top columns:")
        for col in cluster.top_columns[:8]:
            cat = col.get("category", "?")
            user_flag = " ★" if col.get("is_user") else ""
            print(f"    [{cat}] {col['name']}: {col['value']}{user_flag}")
        print()
    
    # Test JSON serialization
    json_output = clusters_to_json(clusters)
    print(f"JSON serializable: {len(json.dumps(json_output))} chars")

