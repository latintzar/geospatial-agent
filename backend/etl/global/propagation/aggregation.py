"""
Resolution Aggregation for Earth Matrix
========================================

This module handles aggregating Earth Matrix data from finer resolutions
to coarser resolutions (e.g., res 11 → res 8 → res 5).

Important Constraints:
    - Counts and areas CAN aggregate (SUM)
    - Average values CAN aggregate (weighted mean)
    - Travel times CANNOT aggregate (position-dependent)
    - Scores CANNOT aggregate (position-dependent)

Why Travel Times Don't Aggregate:
    If hex A has park_walk_min=2 and hex B has park_walk_min=8,
    their parent hex covers both locations. The actual travel time
    from the parent's centroid is neither 2 nor 8 nor their average -
    it depends on where the parent's centroid is relative to the park.

Example:
    >>> from propagation.aggregation import aggregate_to_parent_resolution
    >>> df_res11 = pd.read_parquet('matrix_res11.parquet')
    >>> df_res8 = aggregate_to_parent_resolution(df_res11, target_res=8)
"""

from typing import Dict, List, Optional
import logging

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import h3
except ImportError:
    h3 = None

log = logging.getLogger(__name__)


# Column patterns that CAN aggregate
AGGREGATABLE_PATTERNS = [
    '_count',       # Counts: SUM
    '_in_hex_m2',   # Areas: SUM
    '_density',     # Densities: SUM (or could be mean)
]

# Column patterns that aggregate as averages
AVERAGE_PATTERNS = [
    '_avg_',        # Average values: MEAN
    'avg_',         # Average values: MEAN
]

# Column patterns that CANNOT aggregate
NON_AGGREGATABLE_PATTERNS = [
    '_walk_min',    # Travel times: position-dependent
    '_cycle_min',   # Travel times: position-dependent
    '_drive_min',   # Travel times: position-dependent
    '_score',       # Scores: position-dependent
]


def get_aggregation_function(column_name: str) -> Optional[str]:
    """
    Determine the aggregation function for a column.
    
    Args:
        column_name: Name of the column
        
    Returns:
        'sum', 'mean', or None (if not aggregatable)
        
    Example:
        >>> get_aggregation_function('cafe_count')
        'sum'
        >>> get_aggregation_function('cafe_walk_min')
        None
        >>> get_aggregation_function('park_avg_area_m2')
        'mean'
    """
    # Check non-aggregatable patterns first
    for pattern in NON_AGGREGATABLE_PATTERNS:
        if pattern in column_name:
            return None
    
    # Check sum patterns
    for pattern in AGGREGATABLE_PATTERNS:
        if pattern in column_name:
            return 'sum'
    
    # Check average patterns
    for pattern in AVERAGE_PATTERNS:
        if pattern in column_name:
            return 'mean'
    
    # Default: don't aggregate unknown columns
    return None


def aggregate_to_parent_resolution(
    df: 'pd.DataFrame',
    target_res: int,
    h3_column: str = 'h3_index',
) -> 'pd.DataFrame':
    """
    Aggregate a DataFrame from current resolution to a coarser resolution.
    
    Only aggregatable columns (counts, areas) are included in output.
    Travel times and scores are dropped as they don't aggregate correctly.
    
    Args:
        df: DataFrame with H3 index column
        target_res: Target (coarser) resolution
        h3_column: Name of H3 index column
        
    Returns:
        New DataFrame at target resolution with aggregated columns
        
    Example:
        >>> df_res11 = pd.read_parquet('matrix_res11.parquet')
        >>> df_res8 = aggregate_to_parent_resolution(df_res11, target_res=8)
        >>> len(df_res8) < len(df_res11)  # Fewer rows at coarser resolution
        True
    """
    if pd is None:
        raise ImportError("pandas required: pip install pandas")
    if h3 is None:
        raise ImportError("h3 required: pip install h3")
    
    # Create parent column
    df = df.copy()
    df['_parent'] = df[h3_column].apply(
        lambda x: h3.cell_to_parent(x, target_res) if x else None
    )
    
    # Build aggregation functions for each column
    agg_funcs = {}
    skipped_columns = []
    
    for col in df.columns:
        if col in [h3_column, '_parent']:
            continue
        
        agg_func = get_aggregation_function(col)
        if agg_func:
            agg_funcs[col] = agg_func
        else:
            skipped_columns.append(col)
    
    if skipped_columns:
        log.info(f"Skipping {len(skipped_columns)} non-aggregatable columns: "
                 f"{skipped_columns[:5]}{'...' if len(skipped_columns) > 5 else ''}")
    
    if not agg_funcs:
        log.warning("No aggregatable columns found")
        return pd.DataFrame()
    
    # Perform aggregation
    result = df.groupby('_parent').agg(agg_funcs).reset_index()
    result = result.rename(columns={'_parent': h3_column})
    
    log.info(f"Aggregated {len(df)} rows → {len(result)} rows "
             f"({len(agg_funcs)} columns)")
    
    return result


def get_aggregatable_columns(df: 'pd.DataFrame') -> List[str]:
    """
    Get list of columns that can be aggregated.
    
    Args:
        df: DataFrame to analyze
        
    Returns:
        List of column names that can aggregate
    """
    return [col for col in df.columns 
            if get_aggregation_function(col) is not None]


def get_non_aggregatable_columns(df: 'pd.DataFrame') -> List[str]:
    """
    Get list of columns that cannot be aggregated.
    
    Args:
        df: DataFrame to analyze
        
    Returns:
        List of column names that cannot aggregate (travel times, scores)
    """
    return [col for col in df.columns 
            if get_aggregation_function(col) is None 
            and col not in ['h3_index', 'h3_res5', '_parent']]


def create_multi_resolution_matrix(
    df_finest: 'pd.DataFrame',
    resolutions: List[int],
    h3_column: str = 'h3_index',
) -> Dict[int, 'pd.DataFrame']:
    """
    Create matrices at multiple resolutions from the finest resolution.
    
    Note: This only aggregates counts/areas. Travel times must be
    recomputed at each resolution for accuracy.
    
    Args:
        df_finest: DataFrame at finest resolution
        resolutions: List of target resolutions (coarser than current)
        h3_column: Name of H3 index column
        
    Returns:
        Dictionary mapping resolution → DataFrame
        
    Example:
        >>> df_res11 = pd.read_parquet('matrix_res11.parquet')
        >>> multi = create_multi_resolution_matrix(df_res11, [8, 5])
        >>> multi[8]  # Resolution 8 matrix
        >>> multi[5]  # Resolution 5 matrix
    """
    results = {}
    
    for res in sorted(resolutions, reverse=True):
        log.info(f"Aggregating to resolution {res}")
        results[res] = aggregate_to_parent_resolution(
            df_finest, 
            target_res=res,
            h3_column=h3_column,
        )
    
    return results

