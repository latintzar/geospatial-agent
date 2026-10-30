"""
Propagation Module for Earth Matrix ETL
========================================

This module contains the core algorithms for propagating travel times
and scores across H3 hexes.

Key Algorithms:
    - K-Ring Propagation: POI hexes → travel times to nearby hexes
    - Edge Detection: Find boundary hexes of polygon fills
    - Edge Propagation: Polygon edges → travel times to nearby hexes

Usage:
    from propagation import (
        propagate_from_pois,
        find_edge_hexes,
        propagate_from_edges,
        get_decay_score,
    )
    
    # Propagate from cafe POIs
    cafe_times = propagate_from_pois(cafe_hexes, resolution=11)
    
    # Find park edges and propagate
    edges = find_edge_hexes(park_hexes)
    park_times = propagate_from_edges(edges, park_hexes, park_area, resolution=11)
"""

from .kring import (
    propagate_from_pois,
    get_decay_score,
    H3_EDGE_LENGTHS,
    TRAVEL_SPEEDS,
)

from .edge import (
    find_edge_hexes,
    propagate_from_edges,
)

from .aggregation import (
    aggregate_to_parent_resolution,
)

__all__ = [
    'propagate_from_pois',
    'get_decay_score',
    'find_edge_hexes',
    'propagate_from_edges',
    'aggregate_to_parent_resolution',
    'H3_EDGE_LENGTHS',
    'TRAVEL_SPEEDS',
]

