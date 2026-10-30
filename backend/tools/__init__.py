"""
Leo Backend Tools - Package Entry Point
========================================

This module exports:
1. ALL Data Tools for the ReAct agent
2. Core Architecture classes for the 5-Step Pipeline

5-STEP PIPELINE ARCHITECTURE (Cloud-Native Edition)
---------------------------------------------------
    Step 1: Define AOI     → AOIManager (Athena-based, from utils_spatial)
    Step 2: Gather Data    → Athena (infrastructure) + Tool functions
    Step 3: Format Output  → LayerData, format_layer_output, format_tool_response
    Step 4: Visualization  → VizConfig (from schema)
    Step 5: Response       → AgentResponse (from schema)

CLOUD-NATIVE ARCHITECTURE:
--------------------------
The backend uses AWS Athena to query Overture Maps data directly.
This replaces fragile local lookups with robust global querying.

Key Components:
- tools_athena: AWS Athena for boundaries & infrastructure (THE HEAVY LIFTER)
- tools_semantic: Embedding-based "Vibe Check" for qualitative queries
- tools_search: Unified entity search across sources
- tools_matrix: H3 Feature Store queries
- utils_spatial: AOIManager now uses Athena backend

TOOL MODULES
------------
| Module              | Purpose                          | Cost      |
|---------------------|----------------------------------|-----------|
| tools_athena        | Overture via AWS Athena          | AWS       |
| tools_search        | Unified entity search            | AWS       |
| tools_matrix        | H3 Feature Store                 | FREE      |
| tools_semantic      | Vibe Check / Embeddings          | FREE*     |
| tools_demographics  | Population (WorldPop R2025A)     | FREE      |
| tools_agriculture   | Crop production (MapSPAM)        | FREE      |
| tools_wealth        | Relative Wealth Index            | FREE      |
| tools_climate       | Weather risk, elevation          | FREE      |
| tools_hdx           | Humanitarian data                | FREE      |
| tools_news          | GDELT news/risk                  | FREE      |
| tools_routes        | OSRM routing                     | FREE      |
| tools_trade         | UN Comtrade trade flows          | RATE-LTD  |
| tools_scraper       | Google Maps via ScrapingDog      | PAID      |
| tools_corporate     | OpenCorporates                   | PARKED    |

* tools_semantic uses Gemini embeddings (free tier available)
"""

import logging

logger = logging.getLogger(__name__)

# =============================================================================
# CORE SCHEMA (Imported first - used by all tools)
# =============================================================================

try:
    from ..schema import (
        LayerData, VizConfig, AgentResponse, MapControl,
        StoryChapter, create_h3_layer, create_geojson_layer,
        format_tool_response,  # NEW: Standardized tool output wrapper
    )
except ImportError:
    try:
        from schema import (
            LayerData, VizConfig, AgentResponse, MapControl,
            StoryChapter, create_h3_layer, create_geojson_layer,
            format_tool_response,
        )
    except ImportError as e:
        logger.warning(f"Could not import schema: {e}")
        LayerData = None
        VizConfig = None
        AgentResponse = None
        MapControl = None
        StoryChapter = None
        create_h3_layer = None
        create_geojson_layer = None
        format_tool_response = None

# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

try:
    from ..utils_formatting import (
        format_layer, format_h3_layer, format_geojson_layer, format_error,
        h3_to_geojson, points_to_geojson, dataframe_to_geojson,
    )
    format_layer_output = format_layer  # Alias
except ImportError:
    try:
        from utils_formatting import (
            format_layer, format_h3_layer, format_geojson_layer, format_error,
            h3_to_geojson, points_to_geojson, dataframe_to_geojson,
        )
        format_layer_output = format_layer
    except ImportError as e:
        logger.warning(f"Could not import utils_formatting: {e}")
        format_layer = None
        format_layer_output = None
        format_h3_layer = None
        format_geojson_layer = None
        format_error = None
        h3_to_geojson = None
        points_to_geojson = None
        dataframe_to_geojson = None

# =============================================================================
# AOI MANAGEMENT (Step 1)
# =============================================================================

try:
    from ..utils_spatial import AOIManager, get_aoi, create_corridor, mask_layer_by_aoi
except ImportError:
    try:
        from utils_spatial import AOIManager, get_aoi, create_corridor, mask_layer_by_aoi
    except ImportError as e:
        logger.warning(f"Could not import utils_spatial: {e}")
        AOIManager = None
        get_aoi = None
        create_corridor = None
        mask_layer_by_aoi = None

# =============================================================================
# CLOUD-NATIVE ENGINES
# =============================================================================

# Athena Engine (Boundaries & Infrastructure + Cookie Cutter)
try:
    from .tools_athena import (
        AthenaEngine, get_athena_engine, get_smart_boundary, fetch_infrastructure_sql,
        # Cookie Cutter (Geometry Filtering)
        fetch_features_geometry, fetch_coastline, buffer_geometry, fetch_water_features,
    )
except ImportError:
    try:
        from tools_athena import (
            AthenaEngine, get_athena_engine, get_smart_boundary, fetch_infrastructure_sql,
            fetch_features_geometry, fetch_coastline, buffer_geometry, fetch_water_features,
        )
    except ImportError as e:
        logger.warning(f"Could not import tools_athena: {e}")
        AthenaEngine = None
        get_athena_engine = None
        get_smart_boundary = None
        fetch_infrastructure_sql = None
        fetch_features_geometry = None
        fetch_coastline = None
        buffer_geometry = None
        fetch_water_features = None

# Semantic Engine (Vibe Check)
try:
    from .tools_semantic import SemanticEngine, semantic_rerank, filter_by_vibe, cluster_by_vibe
except ImportError:
    try:
        from tools_semantic import SemanticEngine, semantic_rerank, filter_by_vibe, cluster_by_vibe
    except ImportError as e:
        logger.warning(f"Could not import tools_semantic: {e}")
        SemanticEngine = None
        semantic_rerank = None
        filter_by_vibe = None
        cluster_by_vibe = None

# =============================================================================
# AGENT-CALLABLE TOOLS (tool_* wrappers for Gemini function calling)
# =============================================================================

# Entity Search (Unified discrete object search)
from .tools_search import search_entities, tool_search_entities

# Cascade Search (H3 Multi-Resolution Search)
from .tools_cascade_search import tool_cascade_search

# Planning Tool
from .tool_create_plan import create_execution_plan, tool_create_plan

# Legacy Matrix tools moved to _archive/
query_matrix = None
tool_query_matrix = None
get_matrix_stats = None
query_matrix_neighborhood = None
calculate_derived_index = None
tool_query_neighborhood = None
tool_calculate_index = None

# =============================================================================
# DATA TOOLS
# =============================================================================

# Demographics/Population (WorldPop R2025A)
from .tools_demographics import (
    get_population_density,
    get_population_for_location,
    fetch_worldpop_population,
    list_available_years,
    list_downloaded_data,
    clear_downloaded_data,
    download_population_data,
    download_agesex_data,
    DEFAULT_YEAR,
)

# Agriculture (MapSPAM crop production)
from .tools_agriculture import (
    fetch_crop_production,
    fetch_crop_production_grid,
    list_available_crops,
    get_crop_info,
)

# Wealth Index (HDX RWI)
from .tools_wealth import (
    fetch_wealth_index,
    get_wealth_summary,
    list_available_countries as list_rwi_countries,
)

# Climate Risk (Open-Meteo)
from .tools_climate import (
    fetch_weather_risk,
    fetch_elevation,
    fetch_complete_climate_profile,
)

# Humanitarian Data (HDX)
from .tools_hdx import fetch_hdx_spatial_data

# News Intelligence (GDELT)
from .tools_news import (
    fetch_visual_risk,
    fetch_news_narrative,
    fetch_sentiment_trends,
    fetch_development_signals,
)

# Transport Routing (OSRM)
from .tools_routes import (
    get_transport_route,
    get_multi_stop_route,
    get_supply_chain_route,
)

# Trade Flows (UN Comtrade)
from .tools_trade import (
    fetch_trade_flows,
    list_commodity_codes,
)

# =============================================================================
# PAID/PARKED TOOLS (Conditionally Imported)
# =============================================================================

# Scraper (PAID - ScrapingDog Google Maps API)
try:
    from .tools_scraper import (
        search_places,
        get_place_details,
        get_brand_high_performers,
        analyze_competitor_weaknesses,
        fetch_qualitative_data,
    )
except ImportError:
    logger.debug("tools_scraper not available (paid API)")
    search_places = None
    get_place_details = None
    get_brand_high_performers = None
    analyze_competitor_weaknesses = None
    fetch_qualitative_data = None

# Corporate Search (PARKED - OpenCorporates API)
try:
    from .tools_corporate import (
        search_companies,
        get_company_details,
    )
except ImportError:
    logger.debug("tools_corporate not available (parked)")
    search_companies = None
    get_company_details = None

# =============================================================================
# __all__ - Public API
# =============================================================================

__all__ = [
    # =========================================================================
    # CORE SCHEMA
    # =========================================================================
    'LayerData',
    'VizConfig',
    'AgentResponse',
    'MapControl',
    'StoryChapter',
    'create_h3_layer',
    'create_geojson_layer',
    'format_tool_response',
    
    # =========================================================================
    # OUTPUT FORMATTING
    # =========================================================================
    'format_layer',
    'format_layer_output',
    'format_h3_layer',
    'format_geojson_layer',
    'format_error',
    'h3_to_geojson',
    'points_to_geojson',
    'dataframe_to_geojson',
    
    # =========================================================================
    # AOI MANAGEMENT
    # =========================================================================
    'AOIManager',
    'get_aoi',
    'create_corridor',
    'mask_layer_by_aoi',
    
    # =========================================================================
    # CLOUD-NATIVE ENGINES
    # =========================================================================
    
    # Athena Engine
    'AthenaEngine',
    'get_athena_engine',
    'get_smart_boundary',
    'fetch_infrastructure_sql',
    # Cookie Cutter (Geometry Filtering)
    'fetch_features_geometry',
    'fetch_coastline',
    'buffer_geometry',
    'fetch_water_features',
    
    # Semantic Engine
    'SemanticEngine',
    'semantic_rerank',
    'filter_by_vibe',
    'cluster_by_vibe',
    
    # =========================================================================
    # AGENT-CALLABLE TOOLS (tool_* wrappers)
    # =========================================================================
    'search_entities',
    'tool_search_entities',
    # Cascade Search (THE MAIN TOOL)
    'tool_cascade_search',
    # Planning
    'create_execution_plan',
    'tool_create_plan',
    
    # =========================================================================
    # DATA TOOLS
    # =========================================================================
    
    # Demographics/Population
    'get_population_density',
    'get_population_for_location',
    'fetch_worldpop_population',
    'list_available_years',
    'list_downloaded_data',
    'clear_downloaded_data',
    'download_population_data',
    'download_agesex_data',
    'DEFAULT_YEAR',
    
    # Agriculture
    'fetch_crop_production',
    'fetch_crop_production_grid',
    'list_available_crops',
    'get_crop_info',
    
    # Wealth
    'fetch_wealth_index',
    'get_wealth_summary',
    'list_rwi_countries',
    
    # Climate
    'fetch_weather_risk',
    'fetch_elevation',
    'fetch_complete_climate_profile',
    
    # HDX
    'fetch_hdx_spatial_data',
    
    # News/GDELT
    'fetch_visual_risk',
    'fetch_news_narrative',
    'fetch_sentiment_trends',
    'fetch_development_signals',
    
    # Routes
    'get_transport_route',
    'get_multi_stop_route',
    'get_supply_chain_route',
    
    # Trade
    'fetch_trade_flows',
    'list_commodity_codes',
    
    # =========================================================================
    # PAID/PARKED TOOLS
    # =========================================================================
    
    # Scraper (PAID)
    'search_places',
    'get_place_details',
    'get_brand_high_performers',
    'analyze_competitor_weaknesses',
    'fetch_qualitative_data',
    
    # Corporate (PARKED)
    'search_companies',
    'get_company_details',
]
