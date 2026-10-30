"""
Edge Detection and Propagation for Polygon Travel Times
========================================================

This module implements edge-based propagation for calculating travel times
from polygonal features (parks, beaches, etc.) to all nearby hexes.

Unlike POI propagation which starts from point centroids, polygon propagation
starts from the EDGES of the polygon, giving accurate travel times to the
nearest part of the polygon.

Algorithms:
    
    Edge Detection:
        An edge hex is one where at least one k=1 neighbor is NOT in the polygon.
        Interior hexes have all 6 neighbors inside the polygon.
        
    Edge Propagation:
        1. Find all edge hexes of the polygon
        2. For k = 1 to MAX_RINGS:
           a. Expand from ALL edge hexes simultaneously
           b. Exclude hexes inside the polygon
           c. Calculate travel time and update if lower

Example:
    >>> from propagation.edge import find_edge_hexes, propagate_from_edges
    >>> park_hexes = set(df['h3_index'])  # From polygon fill
    >>> edges = find_edge_hexes(park_hexes)
    >>> results = propagate_from_edges(edges, park_hexes, park_area=50000, resolution=11)
"""

from typing import Dict, Set, Optional
import logging

try:
    import h3
except ImportError:
    h3 = None

from .kring import H3_EDGE_LENGTHS, TRAVEL_SPEEDS, MAX_RINGS

log = logging.getLogger(__name__)


# =============================================================================
# EDGE DETECTION
# =============================================================================

def find_edge_hexes(polygon_hexes: Set[str]) -> Set[str]:
    """
    Find hexes on the boundary of a polygon fill.
    
    An edge hex is one where at least one of its 6 immediate neighbors
    is NOT in the polygon. Interior hexes have all neighbors inside.
    
    This is efficient: O(N × 6) where N = number of hexes in polygon.
    
    Args:
        polygon_hexes: Set of H3 hex IDs that fill the polygon
        
    Returns:
        Subset of polygon_hexes that are on the boundary
        
    Example:
        >>> park_hexes = {'8a2a1072b59ffff', '8a2a1072b5bffff', ...}
        >>> edges = find_edge_hexes(park_hexes)
        >>> len(edges) < len(park_hexes)  # Edges are subset
        True
        
    Note:
        For very small polygons (< 7 hexes), all hexes may be edges.
        For large polygons, edges are typically ~10-20% of total hexes.
    """
    if h3 is None:
        raise ImportError("h3 library required: pip install h3")
    
    if not polygon_hexes:
        return set()
    
    edges = set()
    
    for hex_id in polygon_hexes:
        try:
            # Get the 6 immediate neighbors
            neighbors = set(h3.grid_ring(hex_id, 1))
            
            # If any neighbor is outside the polygon, this is an edge
            if not neighbors.issubset(polygon_hexes):
                edges.add(hex_id)
                
        except Exception as e:
            log.debug(f"Error checking hex {hex_id}: {e}")
            # If we can't check, assume it's an edge to be safe
            edges.add(hex_id)
    
    return edges


def find_interior_hexes(polygon_hexes: Set[str]) -> Set[str]:
    """
    Find hexes that are completely inside a polygon (not on edge).
    
    Interior hexes have all 6 neighbors also inside the polygon.
    
    Args:
        polygon_hexes: Set of H3 hex IDs that fill the polygon
        
    Returns:
        Subset of polygon_hexes that are interior (not edges)
    """
    edges = find_edge_hexes(polygon_hexes)
    return polygon_hexes - edges


# =============================================================================
# EDGE PROPAGATION
# =============================================================================

def propagate_from_edges(
    edge_hexes: Set[str],
    polygon_hexes: Set[str],
    polygon_area_m2: float,
    resolution: int,
    feature_name: str,
    existing_matrix: Optional[Dict[str, Dict]] = None,
    max_rings: int = MAX_RINGS,
    size_tier_threshold: float = 20000,
) -> Dict[str, Dict]:
    """
    Propagate travel times from polygon edges using k-ring expansion.
    
    Unlike POI propagation, we start from the EDGES of the polygon,
    giving accurate travel times to the nearest part of the polygon.
    
    We also exclude hexes inside the polygon from the results (they're
    already at the feature, so travel time is 0).
    
    Args:
        edge_hexes: Set of H3 hex IDs on polygon boundary
        polygon_hexes: Set of all H3 hex IDs in polygon (for exclusion)
        polygon_area_m2: Area of the source polygon in m²
        resolution: H3 resolution level
        feature_name: Feature name (e.g., 'park', 'beach')
        existing_matrix: Optional existing results to update
        max_rings: Maximum ring distance to propagate
        size_tier_threshold: Minimum size for size-tiered columns (default: 20000 m²)
        
    Returns:
        Dictionary mapping hex_id → {feature_walk_min, feature_cycle_min, 
                                     feature_20k_walk_min (if area >= threshold)}
        
    Example:
        >>> edges = find_edge_hexes(park_hexes)
        >>> results = propagate_from_edges(
        ...     edges, park_hexes, 
        ...     polygon_area_m2=50000,  # 50k m² park
        ...     resolution=11, 
        ...     feature_name='park'
        ... )
        >>> results['nearby_hex']['park_walk_min']
        2.5  # 2.5 minutes walking to nearest park edge
    """
    if h3 is None:
        raise ImportError("h3 library required: pip install h3")
    
    results = existing_matrix if existing_matrix is not None else {}
    
    if not edge_hexes:
        return results
    
    edge_m = H3_EDGE_LENGTHS.get(resolution, 25)
    
    walk_col = f'{feature_name}_walk_min'
    cycle_col = f'{feature_name}_cycle_min'
    walk_20k_col = f'{feature_name}_20k_walk_min'
    cycle_20k_col = f'{feature_name}_20k_cycle_min'
    
    is_large_feature = polygon_area_m2 >= size_tier_threshold
    
    # k=0: edge hexes (at the polygon boundary)
    for edge_hex in edge_hexes:
        if edge_hex not in results:
            results[edge_hex] = {}
        results[edge_hex][walk_col] = 0.0
        results[edge_hex][cycle_col] = 0.0
        if is_large_feature:
            results[edge_hex][walk_20k_col] = 0.0
            results[edge_hex][cycle_20k_col] = 0.0
    
    # k=1 to max_rings: expanding from edges
    for k in range(1, max_rings + 1):
        distance_m = k * edge_m
        walk_min = distance_m / TRAVEL_SPEEDS['walk']
        cycle_min = distance_m / TRAVEL_SPEEDS['cycle']
        
        for edge_hex in edge_hexes:
            try:
                ring = h3.grid_ring(edge_hex, k)
                
                for neighbor in ring:
                    # Skip hexes inside the polygon
                    if neighbor in polygon_hexes:
                        continue
                    
                    if neighbor not in results:
                        results[neighbor] = {}
                    
                    # Keep minimum travel time
                    old_walk = results[neighbor].get(walk_col, 999.0)
                    results[neighbor][walk_col] = min(old_walk, walk_min)
                    
                    old_cycle = results[neighbor].get(cycle_col, 999.0)
                    results[neighbor][cycle_col] = min(old_cycle, cycle_min)
                    
                    # Size-tiered columns for "real" features
                    if is_large_feature:
                        old_walk_20k = results[neighbor].get(walk_20k_col, 999.0)
                        results[neighbor][walk_20k_col] = min(old_walk_20k, walk_min)
                        
                        old_cycle_20k = results[neighbor].get(cycle_20k_col, 999.0)
                        results[neighbor][cycle_20k_col] = min(old_cycle_20k, cycle_min)
                        
            except Exception as e:
                log.debug(f"Error propagating from {edge_hex} at k={k}: {e}")
                continue
    
    return results


def propagate_polygon_feature(
    polygon_hexes: Set[str],
    polygon_area_m2: float,
    resolution: int,
    feature_name: str,
    existing_matrix: Optional[Dict[str, Dict]] = None,
    max_rings: int = MAX_RINGS,
) -> Dict[str, Dict]:
    """
    Convenience function: find edges and propagate in one call.
    
    Args:
        polygon_hexes: Set of H3 hex IDs filling the polygon
        polygon_area_m2: Area of the polygon in m²
        resolution: H3 resolution level
        feature_name: Feature name (e.g., 'park', 'beach')
        existing_matrix: Optional existing results to update
        max_rings: Maximum ring distance
        
    Returns:
        Dictionary with travel times from this polygon
        
    Example:
        >>> results = propagate_polygon_feature(
        ...     park_hexes, 
        ...     polygon_area_m2=50000,
        ...     resolution=11,
        ...     feature_name='park'
        ... )
    """
    edges = find_edge_hexes(polygon_hexes)
    
    return propagate_from_edges(
        edge_hexes=edges,
        polygon_hexes=polygon_hexes,
        polygon_area_m2=polygon_area_m2,
        resolution=resolution,
        feature_name=feature_name,
        existing_matrix=existing_matrix,
        max_rings=max_rings,
    )

