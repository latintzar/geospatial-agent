"""
K-Ring Propagation for POI Travel Times
========================================

This module implements k-ring based propagation for calculating travel times
from point features (POIs) to all nearby hexes.

Algorithm:
    1. For each POI hex, set travel_time = 0
    2. For k = 1 to MAX_RINGS:
       a. Get ring of neighbors at distance k
       b. Calculate travel time based on k × edge_length / speed
       c. Update if lower than existing (keep minimum)
       d. Calculate decay score and update if higher (keep maximum)

Complexity: O(P × K × 6K) where P = POI count, K = max rings
            Linear in POI count since rings are O(k) not O(k²)

Example:
    >>> from propagation.kring import propagate_from_pois
    >>> cafe_hexes = {'8a2a1072b59ffff', '8a2a1072b5bffff', ...}
    >>> results = propagate_from_pois(cafe_hexes, resolution=11, category='cafe')
    >>> print(results['8a2a1072b59ffff'])
    {'cafe_walk_min': 0, 'cafe_cycle_min': 0, 'cafe_drive_min': 0, 'cafe_score': 10}
"""

from typing import Dict, Set, Optional
import logging

try:
    import h3
except ImportError:
    h3 = None
    
log = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# H3 edge lengths in meters for each resolution
H3_EDGE_LENGTHS = {
    0: 1107712,   # ~1100 km
    1: 418676,    # ~420 km
    2: 158244,    # ~158 km
    3: 59810,     # ~60 km
    4: 22606,     # ~23 km
    5: 8544,      # ~8.5 km
    6: 3229,      # ~3.2 km
    7: 1220,      # ~1.2 km
    8: 461,       # ~460 m
    9: 174,       # ~174 m
    10: 66,       # ~66 m
    11: 25,       # ~25 m
    12: 9,        # ~9 m
    13: 3,        # ~3 m
    14: 1,        # ~1 m
    15: 0.5,      # ~0.5 m
}

# Travel speeds in meters per minute
TRAVEL_SPEEDS = {
    'walk': 83,     # 5 km/h = 83.3 m/min
    'cycle': 250,   # 15 km/h = 250 m/min
    'drive': 833,   # 50 km/h = 833.3 m/min
}

# Maximum ring distance for propagation
MAX_RINGS = 10


# =============================================================================
# DECAY SCORE
# =============================================================================

def get_decay_score(k: int) -> float:
    """
    Calculate two-phase linear decay score.
    
    The score represents "how close" a hex is to a feature:
        k=0  → 10 (at the source)
        k=7  → 1  (still within walking distance)
        k=10 → 0  (edge of influence)
    
    This creates a smooth falloff that prioritizes proximity while
    still acknowledging more distant features.
    
    Args:
        k: Ring distance from source (0 = at source)
        
    Returns:
        Score between 0.0 and 10.0
        
    Example:
        >>> get_decay_score(0)
        10.0
        >>> get_decay_score(7)
        1.0
        >>> get_decay_score(10)
        0.0
    """
    if k <= 0:
        return 10.0
    elif k <= 7:
        # Linear decay from 10 to 1 over k=0 to k=7
        return 10.0 - (9.0 * k / 7.0)
    elif k <= 10:
        # Linear decay from 1 to 0 over k=7 to k=10
        return max(0.0, 1.0 - (k - 7) / 3.0)
    else:
        return 0.0


# =============================================================================
# K-RING PROPAGATION
# =============================================================================

def propagate_from_pois(
    poi_hexes: Set[str],
    resolution: int,
    category: str,
    existing_matrix: Optional[Dict[str, Dict]] = None,
    max_rings: int = MAX_RINGS,
) -> Dict[str, Dict]:
    """
    Propagate travel times from POI hexes using k-ring expansion.
    
    For each POI, we expand outward in concentric rings, calculating
    travel time based on distance and keeping the minimum time to
    any POI of this category.
    
    Args:
        poi_hexes: Set of H3 hex IDs containing POIs
        resolution: H3 resolution level (5, 8, 10, or 11)
        category: Category name (e.g., 'cafe', 'gym')
        existing_matrix: Optional existing results to update in-place
        max_rings: Maximum ring distance to propagate (default: 10)
        
    Returns:
        Dictionary mapping hex_id → {category_walk_min, category_cycle_min, 
                                     category_drive_min, category_score}
        
    Example:
        >>> cafe_hexes = {'8a2a1072b59ffff', '8a2a1072b5bffff'}
        >>> results = propagate_from_pois(cafe_hexes, 11, 'cafe')
        >>> results['8a2a1072b59ffff']['cafe_walk_min']
        0.0
    """
    if h3 is None:
        raise ImportError("h3 library required: pip install h3")
    
    results = existing_matrix if existing_matrix is not None else {}
    
    if not poi_hexes:
        return results
    
    edge_m = H3_EDGE_LENGTHS.get(resolution, 25)
    
    walk_col = f'{category}_walk_min'
    cycle_col = f'{category}_cycle_min'
    drive_col = f'{category}_drive_min'
    score_col = f'{category}_score'
    
    # k=0: POI hexes themselves
    for poi_hex in poi_hexes:
        if poi_hex not in results:
            results[poi_hex] = {}
        results[poi_hex][walk_col] = 0.0
        results[poi_hex][cycle_col] = 0.0
        results[poi_hex][drive_col] = 0.0
        results[poi_hex][score_col] = 10.0
    
    # k=1 to max_rings: expanding rings
    for k in range(1, max_rings + 1):
        distance_m = k * edge_m
        walk_min = distance_m / TRAVEL_SPEEDS['walk']
        cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
        drive_min = distance_m / TRAVEL_SPEEDS['drive']
        score = get_decay_score(k)
        
        for poi_hex in poi_hexes:
            try:
                ring = h3.grid_ring(poi_hex, k)
                for neighbor in ring:
                    if neighbor not in results:
                        results[neighbor] = {}
                    
                    # Keep minimum travel time
                    old_walk = results[neighbor].get(walk_col, 999.0)
                    results[neighbor][walk_col] = min(old_walk, walk_min)
                    
                    old_cycle = results[neighbor].get(cycle_col, 999.0)
                    results[neighbor][cycle_col] = min(old_cycle, cycle_min)
                    
                    old_drive = results[neighbor].get(drive_col, 999.0)
                    results[neighbor][drive_col] = min(old_drive, drive_min)
                    
                    # Keep maximum score
                    old_score = results[neighbor].get(score_col, 0.0)
                    results[neighbor][score_col] = max(old_score, score)
                    
            except Exception as e:
                # Invalid hex or h3 error, skip
                log.debug(f"Skipping hex {poi_hex} at k={k}: {e}")
                continue
    
    return results


def calculate_travel_time(
    distance_m: float,
    mode: str = 'walk',
) -> float:
    """
    Calculate travel time in minutes for a given distance.
    
    Args:
        distance_m: Distance in meters
        mode: Travel mode ('walk', 'cycle', or 'drive')
        
    Returns:
        Travel time in minutes
        
    Example:
        >>> calculate_travel_time(500, 'walk')
        6.02  # ~6 minutes to walk 500m
    """
    speed = TRAVEL_SPEEDS.get(mode, TRAVEL_SPEEDS['walk'])
    return distance_m / speed


def rings_to_travel_time(
    k: int,
    resolution: int,
    mode: str = 'walk',
) -> float:
    """
    Convert k-ring distance to travel time.
    
    Args:
        k: Ring distance
        resolution: H3 resolution
        mode: Travel mode
        
    Returns:
        Estimated travel time in minutes
        
    Example:
        >>> rings_to_travel_time(5, 11, 'walk')
        1.5  # ~1.5 minutes to walk across 5 res-11 hexes
    """
    edge_m = H3_EDGE_LENGTHS.get(resolution, 25)
    distance_m = k * edge_m
    return calculate_travel_time(distance_m, mode)

