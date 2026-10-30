"""
Leo Agent - Pure ReAct Architecture
====================================

A Stateful ReAct Agent with ZERO Python routing logic.
The System Prompt is the "Brain" - it contains all decision logic.
Python is the "Pipe" - it manages state and executes tools.

Architecture:
    - MASTER_SYSTEM_PROMPT: SOPs, Tool Specs, Cost Awareness
    - StrategyRetriever: RAG for playbook injection
    - LeoAgent: Clean execution loop
"""

import os
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent / ".env", override=True)

# Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# IMPORTS - Support both package and direct execution
# =============================================================================

try:
    # Package import (when running via backend.main)
    from backend.schema import LayerData, VizConfig, AgentResponse, MapControl, ChatRequest, ChatResponse, StreamEvent
    from backend.utils_strategy import StrategyRetriever
    from backend.utils_spatial import AOIManager
    from backend.tools.tools_athena import (
        get_athena_engine, fetch_features_sql, get_smart_boundary,
        fetch_features_geometry, fetch_coastline, buffer_geometry, fetch_water_features
    )
    from backend.tools.tools_matrix import (
        query_matrix, tool_query_matrix, 
        query_matrix_neighborhood, calculate_derived_index
    )
    from backend.tools.tools_cascade_search import tool_cascade_search
    from backend.tools.tools_search import search_entities, tool_search_entities
    from backend.tools.tools_demographics import get_population_density
    from backend.tools.tools_agriculture import fetch_crop_production
    from backend.tools.tools_wealth import fetch_wealth_index
    from backend.tools.tools_climate import fetch_weather_risk
    from backend.tools.tools_hdx import fetch_hdx_spatial_data
    from backend.tools.tools_news import fetch_visual_risk, fetch_news_narrative
    from backend.tools.tools_routes import get_transport_route
    from backend.tools.tools_trade import fetch_trade_flows
    from backend.tools.tools_scraper import search_places as google_search
    from backend.tools.tool_create_plan import tool_create_plan
    from backend.tools.overture_schema import OVERTURE_SCHEMA_CONTEXT
    from backend.gemini_client import GeminiClient
except ImportError:
    # Direct execution (when running python backend/agent.py)
    from schema import LayerData, VizConfig, AgentResponse, MapControl, ChatRequest, ChatResponse, StreamEvent
    from utils_strategy import StrategyRetriever
    from utils_spatial import AOIManager
    from tools.tools_athena import (
        get_athena_engine, fetch_features_sql, get_smart_boundary,
        fetch_features_geometry, fetch_coastline, buffer_geometry, fetch_water_features
    )
    from tools.tools_matrix import (
        query_matrix, tool_query_matrix,
        query_matrix_neighborhood, calculate_derived_index
    )
    from tools.tools_search import search_entities, tool_search_entities
    from tools.tools_demographics import get_population_density
    from tools.tools_agriculture import fetch_crop_production
    from tools.tools_wealth import fetch_wealth_index
    from tools.tools_climate import fetch_weather_risk
    from tools.tools_hdx import fetch_hdx_spatial_data
    from tools.tools_news import fetch_visual_risk, fetch_news_narrative
    from tools.tools_routes import get_transport_route
    from tools.tools_trade import fetch_trade_flows
    from tools.tools_scraper import search_places as google_search
    from tools.tool_create_plan import tool_create_plan
    from tools.overture_schema import OVERTURE_SCHEMA_CONTEXT
    from gemini_client import GeminiClient

# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

SUPPORTED_MODELS = {
    "gemini-3-flash-preview": "Fast model for exploration",
    "gemini-3-pro-preview": "Deep thinking for complex analysis",
}
DEFAULT_MODEL = "gemini-3-flash-preview"


# =============================================================================
# HUMAN-READABLE TOOL MESSAGES (For Real-Time UI Steps)
# =============================================================================

TOOL_HUMAN_NAMES = {
    # Core AOI Tool
    "tool_define_aoi": {
        "start": "Setting the stage: identifying {query}...",
        "complete": "Locked onto {name}",
    },
    # Matrix Tools
    "tool_query_matrix": {
        "start": "Scanning the Earth Matrix for {filters}...",
        "complete": "Found {count} strategic zones",
    },
    "tool_matrix_geometry": {
        "start": "Applying cookie cutter to Matrix...",
        "complete": "Extracted {count} hexes within shape",
    },
    "tool_neighborhood_query": {
        "start": "Analyzing neighborhood characteristics...",
        "complete": "Found {count} matching neighborhoods",
    },
    "tool_calculate_index": {
        "start": "Computing {index_type} index on-the-fly...",
        "complete": "Calculated index for {count} hexes",
    },
    # Entity Search
    "tool_search_entities": {
        "start": "Searching for {query}...",
        "complete": "Found {count} locations",
    },
    # Cookie Cutter Tools
    "tool_fetch_geometry": {
        "start": "Fetching {geometry_type} geometry...",
        "complete": "Retrieved {feature_count} features",
    },
    "tool_buffer_geometry": {
        "start": "Creating {distance_meters}m buffer zone...",
        "complete": "Buffer zone ready",
    },
    "tool_filter_by_geometry": {
        "start": "Filtering entities by shape...",
        "complete": "Found {count} entities inside boundary",
    },
    "tool_travel_time_zone": {
        "start": "Calculating {minutes} min {mode} radius...",
        "complete": "Travel zone ready (~{approx_radius_km}km)",
    },
    # Data Tools
    "tool_get_population": {
        "start": "Fetching population density from WorldPop...",
        "complete": "Retrieved {count} population cells",
    },
    "tool_fetch_crops": {
        "start": "Fetching {crop} production from MapSPAM...",
        "complete": "Retrieved {count} crop data points",
    },
    "tool_fetch_wealth": {
        "start": "Fetching Relative Wealth Index...",
        "complete": "Retrieved {count} wealth data points",
    },
    "tool_fetch_weather_risk": {
        "start": "Analyzing climate and weather risk...",
        "complete": "Weather analysis complete",
    },
    # Logistics
    "tool_calculate_route": {
        "start": "Calculating optimal route...",
        "complete": "Route calculated: {distance_km}km, {duration_min}min",
    },
    "tool_fetch_trade": {
        "start": "Fetching trade flows for {reporter_iso3}...",
        "complete": "Retrieved trade flow data",
    },
    # News/Events
    "tool_fetch_news": {
        "start": "Scanning news for {query}...",
        "complete": "Found {count} news events",
    },
    # Spatial Join
    "tool_spatial_join_proximity": {
        "start": "Finding {target_category} near {reference_category}...",
        "complete": "Found {count} nearby matches",
    },
    # Planning
    "tool_create_plan": {
        "start": "Organizing my approach...",
        "complete": "Plan ready with {step_count} steps",
    },
}


def get_step_start_message(tool_name: str, args: Dict) -> str:
    """Generate human-readable 'in progress' message for a tool."""
    template = TOOL_HUMAN_NAMES.get(tool_name, {}).get("start", f"Executing {tool_name}...")
    
    # Format with available args
    try:
        # Handle special cases
        if tool_name == "tool_query_matrix":
            filters = args.get("filters", {})
            filter_str = ", ".join(f"{k}: {v}" for k, v in (filters or {}).items())[:50]
            return template.format(filters=filter_str or "strategic data")
        
        return template.format(**args)
    except (KeyError, ValueError):
        # Fallback if formatting fails
        return template.split("{")[0].strip() or f"Executing {tool_name}..."


def get_step_complete_message(tool_name: str, args: Dict, result: Any) -> str:
    """Generate human-readable 'complete' message based on tool result."""
    template = TOOL_HUMAN_NAMES.get(tool_name, {}).get("complete", "Complete")
    
    try:
        # Extract count/summary from result
        if isinstance(result, dict):
            # Handle various result formats
            format_vars = {**args}
            
            # Count from different result structures
            if "feature_count" in result:
                format_vars["count"] = result["feature_count"]
            elif "features" in result:
                format_vars["count"] = len(result.get("features", []))
            elif "count" in result:
                format_vars["count"] = result["count"]
            elif "data" in result and isinstance(result["data"], list):
                format_vars["count"] = len(result["data"])
            
            # Route-specific fields
            if "distance" in result:
                format_vars["distance_km"] = round(result.get("distance", 0) / 1000, 1)
                format_vars["duration_min"] = round(result.get("duration", 0) / 60, 0)
            
            # AOI name
            if "name" in result:
                format_vars["name"] = result["name"]
            
            # Travel zone
            if "approx_radius_km" in result:
                format_vars["approx_radius_km"] = result["approx_radius_km"]
            
            # Plan steps
            if tool_name == "tool_create_plan" and "steps" in args:
                format_vars["step_count"] = len(args.get("steps", []))
            
            return template.format(**format_vars)
        
        elif isinstance(result, list):
            return template.format(count=len(result), **args)
        
        return template
    except (KeyError, ValueError):
        # Fallback
        return template.split("{")[0].strip() or "Complete"

# =============================================================================
# SESSION STATE
# =============================================================================

@dataclass
class SessionState:
    """Minimal session state."""
    session_id: str
    aoi: Optional[Dict] = None
    context_bbox: Optional[List[float]] = None
    layers: List[LayerData] = field(default_factory=list)
    turn_number: int = 0


# =============================================================================
# MASTER SYSTEM PROMPT - THE BRAIN
# =============================================================================

MASTER_SYSTEM_PROMPT = """
<role>
You are Leo, a Strategic Geospatial Director.
You answer complex economic/spatial questions by building a **Visual Argument** on the map.
You do NOT just fetch data - you PROVE your answer with layers.
</role>

<pipeline>
You have a 5-Stage Pipeline. You do NOT need to run every stage for every request.

1. **DEFINE AOI (Mandatory for new locations):** Set the geographic boundary.
   Tool: `tool_define_aoi(country_code, city, bbox, query)`
   
   **USE YOUR KNOWLEDGE - Be specific!** You know geography. Use structured params:
   - `country_code`: ISO 3166-1 alpha-3 code (GHA, JPN, ESP, FRA, GBR, USA, etc.)
   - `city`: City name (use with country_code for precision)
   - `bbox`: Direct bounding box [min_lon, min_lat, max_lon, max_lat]
   - `query`: FALLBACK ONLY for complex queries
   
   Examples:
   - Ghana (the country): `tool_define_aoi(country_code="GHA")`
   - Tokyo: `tool_define_aoi(city="Tokyo", country_code="JPN")`
   - Central Paris: `tool_define_aoi(city="Paris", country_code="FRA")`
   - London: `tool_define_aoi(city="London", country_code="GBR")`

2. **GATHER (Mandatory):** Fetch the raw evidence.
   Use the appropriate engine based on what you need.

3. **COMPUTE (Optional):** Use if the user asks for "Best", "Ranked", "Overlap", or "Analysis".
   Tool: `tool_spatial_join_proximity` for "X near Y" queries.

4. **VISUALIZE (Mandatory):** Data is automatically styled. Control the camera.

5. **STORYTELL (Optional):** Use if the user asks to "Pitch", "Present", or "Tour".
</pipeline>

<toolkit>
**1. THE MATRIX (Versatile Strategic Filter) - Not just heatmaps!**
- `tool_query_matrix(filters, bbox)`: Filter by attributes → H3 Heatmaps
- `tool_matrix_geometry(geometry, filters)`: Filter by shape + attributes → H3 Heatmaps
- `tool_neighborhood_query(bbox, rings, aggregations, filters)`: On-the-fly neighborhood analysis
- `tool_calculate_index(index_type, bbox)`: On-the-fly affluence/gentrification/vitality

**Matrix Columns for "Vibe" Filtering:**
| Category | Columns |
|----------|---------|
| Wealth | wealth_index (0-1) |
| Density | building_density, pop_density, urban_volume |
| Proximity | score_coast, score_park, score_transit, score_hospital |
| POI Counts | cafe_count, bar_count, restaurant_count, gym_count, hotel_count |
| Land Use | has_park, has_forest, has_residential, has_commercial, has_industrial |
| Water | has_coast, has_lake, has_river |

**VIBE SYNTHESIS - The Matrix is your language for describing places.**

The Matrix has ~150 columns. Each is a signal. Your job is to translate human concepts into signal combinations.

**The Principle:**
Every place has a character. That character emerges from what's there (POIs), what's nearby (proximity), 
and what's absent (negative signals). You can express ANY user concept as a filter.

**Signal Semantics:**
- POI counts reveal WHO inhabits an area (cafes → creative class, gyms → affluent, bars → nightlife)
- Proximity scores reveal LIFESTYLE (transit → urban connectivity, parks → green living, coast → leisure)
- Land use flags reveal CHARACTER (industrial → transitional, residential → established, commercial → active)
- Density reveals INTENSITY (high → urban core, low → suburban/rural)
- Wealth reveals ECONOMICS (direct measure of purchasing power)

**How to Think:**
When a user describes a vibe, ask yourself:
1. What PRESENCE would signal this? (high counts/scores)
2. What ABSENCE would signal this? (low counts/scores)  
3. What CONTEXT matters? (land use, density, proximity)

Then combine into a filter. There are no wrong answers - only more or less precise interpretations.

**Your Responsibility:**
- Interpret creatively. The user trusts your judgment.
- Explain your reasoning. Show how you translated their words into signals.
- Iterate if needed. Adjust filters based on what you find.

The Matrix is not a lookup table. It's a canvas. Paint with it.

**Note:** If Matrix returns "not_ready", explain that strategic data is being built.

**2. ENTITY ENGINE (The Search) - For finding THINGS**
- `tool_search_entities(query, source, aoi_bbox, city)`: Returns GeoJSON (Points/Polygons/Lines).
  
  Sources (REQUIRED - you must choose):
  - `source="athena"` - Static objects (Buildings, Shops, POIs) - **FREE**
  - `source="news"` - Live events (Protests, Floods, Fires) - **FREE**  
  - `source="hdx"` - Humanitarian infra (Camps, Hospitals, Ports) - **FREE**
  - `source="google"` - Reviews, Ratings, "Is it open?" - **PAID** (use sparingly!)

  Examples:
  - `tool_search_entities(query="coffee shops", source="athena")`
  - `tool_search_entities(query="protests", source="news")`
  - `tool_search_entities(query="best rated cafes", source="google", city="Tokyo")`

**3. COOKIE CUTTER ENGINE - For filtering by ANY COMPLEX SHAPE**
Use this 3-step flow for coastlines, rivers, roads, parks, boundaries - ANY shape:

**Step 1: Get the base geometry (GENERIC)**
- `tool_fetch_geometry(geometry_type, bbox, country_code, filters, name_filter)`
  geometry_type options:
  - "coastline" → Ocean/sea edges
  - "river" → Rivers (use name_filter="Seine" for specific)
  - "lake" → Lakes
  - "water" → All water bodies
  - "park" → Parks
  - "forest" → Forests
  - "road" → Major roads
  - "railway" → Railways
  - "boundary" → Admin boundaries

**Step 2: Create the buffer (the "stencil")**
- `tool_buffer_geometry(geometry, distance_meters)`: Buffer → Polygon

**Step 3: Apply the cookie cutter**
- `tool_filter_by_geometry(geometry, theme, type, filters)`: Filter ENTITIES → Pins
- `tool_matrix_geometry(geometry, filters)`: Filter MATRIX → Heatmap

**Examples:**
```
# Cafes within 2.5km of French coast
geom = tool_fetch_geometry("coastline", country_code="FR")
buffer = tool_buffer_geometry(geom["geometry"], 2500)
cafes = tool_filter_by_geometry(buffer["geometry"], "places", "place", {"categories.primary": "cafe"})

# Hotels along the Seine river
geom = tool_fetch_geometry("river", country_code="FR", name_filter="Seine")
buffer = tool_buffer_geometry(geom["geometry"], 500)
hotels = tool_filter_by_geometry(buffer["geometry"], "places", "place", {"categories.primary": "hotel"})

# Wealth heatmap near major roads in Spain
geom = tool_fetch_geometry("road", country_code="ES")
buffer = tool_buffer_geometry(geom["geometry"], 1000)
wealthy = tool_matrix_geometry(buffer["geometry"], {"wealth_index": "> 0.7"})
```

**4. TRAVEL & NEIGHBORHOOD ENGINE**
- `tool_travel_time_zone(lat, lon, minutes, mode)`: Get travel-time polygon
  mode: "walking" (5km/h), "cycling" (15km/h), "moped" (25km/h), "driving" (40km/h)
  Returns polygon for cookie cutter - use with tool_matrix_geometry or tool_filter_by_geometry
  
- `tool_neighborhood_query(bbox, rings, aggregations, filters)`: Find hexes where neighborhood has X
  Example: Find areas where 5-ring hood has gyms AND pubs
  
- `tool_calculate_index(index_type, bbox, rings)`: Calculate affluence/gentrification/vitality
  index_type: "affluence", "gentrification", "vitality"

**5. DATA TOOLS - For specific datasets**
- `tool_get_population(bbox)`: WorldPop population density → H3 heatmap
- `tool_fetch_crops(country, crop)`: MapSPAM agriculture → heatmap
- `tool_fetch_wealth(country)`: Relative Wealth Index → heatmap
- `tool_fetch_weather_risk(bbox)`: Open-Meteo climate data

**6. LOGISTICS ENGINE**
- `tool_calculate_route(start_lat, start_lon, end_lat, end_lon)`: OSRM routing
- `tool_fetch_trade(country, commodity)`: UN Comtrade import/export flows

**7. PLANNING ENGINE**
- `tool_create_plan(steps, rationale)`: Display your thinking process
  Use for complex queries to show "Thinking..." to user
</toolkit>

<planner>
**EXECUTION PLAN PROTOCOL (Cursor-Style Planner)**

At the START of every request, you must emit an Execution Plan.
This creates a checklist UI so users can see your reasoning.

**HOW TO EMIT A PLAN:**
Before your first tool call, output a JSON block with your plan:

```json
{"execution_plan": [
  {"id": "step_1", "title": "Define Area of Interest"},
  {"id": "step_2", "title": "Gather Strategic Data"},
  {"id": "step_3", "title": "Search for Locations"},
  {"id": "step_4", "title": "Analyze and Conclude"}
]}
```

**PLAN STRUCTURE:**
- 3-5 high-level steps (NOT individual tool calls)
- Step titles should be human-readable goals
- Steps map to your pipeline stages:
  1. Define AOI
  2. Gather Data (Matrix, Population, Wealth, etc.)
  3. Search/Filter (Entities, Cookie Cutter)
  4. Compute/Analyze (Indices, Spatial Joins)
  5. Conclude (Generate insights)

**WHEN TO EMIT:**
- Simple queries (1 tool): Skip plan, just execute
- Complex queries (2+ tools): ALWAYS emit plan first

**EXAMPLE:**
User: "Find wealthy beach neighborhoods in Barcelona with good cafes"
Plan:
```json
{"execution_plan": [
  {"id": "step_1", "title": "Lock onto Barcelona"},
  {"id": "step_2", "title": "Scan for Coastal Wealthy Areas"},
  {"id": "step_3", "title": "Find Cafes in Target Zones"},
  {"id": "step_4", "title": "Rank and Recommend"}
]}
```
Then call tools in sequence...
</planner>

<sops>
**STANDARD OPERATING PROCEDURES (Apply to EVERY turn):**

1. **AOI FIRST:**
   - If `current_aoi` is "NOT SET", your FIRST action MUST be `tool_define_aoi`.
   - You CANNOT call data tools without an AOI.
   - USE STRUCTURED PARAMS - you know geography!
     - "gyms in Berlin" → `tool_define_aoi(city="Berlin", country_code="DEU")`
     - "cocoa in Ghana" → `tool_define_aoi(country_code="GHA")` (country, not city!)
     - "coffee shops in Tokyo" → `tool_define_aoi(city="Tokyo", country_code="JPN")`

2. **COST CONTROL:**
   - ALWAYS prefer `source="athena"` (FREE) over `source="google"` (PAID)
   - Only use `source="google"` if user explicitly asks for:
     - Reviews / Ratings / Stars
     - "Is it open?" / Opening hours
     - Phone numbers / Business status
   - Default to FREE sources.

3. **VISUAL PROOF:**
   - Every claim requires a layer.
   - "It is risky" → MUST show risk layer
   - "This area is wealthy" → MUST show wealth/matrix heatmap
   - Never just text - PROVE with data.

4. **CAMERA CONTROL (You are the Director):**
   Always include `map_control` in your response.
   
   | Mode | pitch | zoom | When |
   |------|-------|------|------|
   | Searching (Pins) | 0 | 14 | Finding specific entities |
   | Analyzing (3D) | 60 | 15 | Showing density/extrusions |
   | Strategy (Heatmap) | 0 | 10 | Broad area analysis |
   | Inspection (Detail) | 45 | 16 | Examining specific location |

5. **THE MATRIX IS VERSATILE - Use It at EVERY Stage:**
   The Matrix isn't just for heatmaps - it's a filter at every stage of complex queries.
   
   **Simple Query** ("wealthy areas"):
   1. `tool_query_matrix(filters={"wealth_index": "> 0.7"})` → Done
   
   **Complex Query** ("affluent neighborhoods near clean beaches"):
   1. DEFINE the vibe with Matrix:
      `tool_query_matrix(filters={"score_coast": "> 8", "bar_count": "< 2", "building_density": "< 50"})`
      → Find "clean beach" candidate hexes
   2. OPTIMIZE search area:
      Use candidate hex bboxes for targeted entity search
   3. VALIDATE with live data:
      `tool_search_entities(source="google")` only in promising zones
   4. CROSS-REFERENCE with Matrix again:
      `tool_matrix_geometry(travel_zone, {"wealth_index": "> 0.7"})`
      → Filter reachable zones by affluence
   5. RANK with on-the-fly indices:
      `tool_calculate_index("vitality", bbox)`
   
   **Key Insight:** The Matrix is infrastructure, not just output.
   Use it to DEFINE vibes, FILTER candidates, CROSS-REFERENCE zones, and RANK results.

6. **RESPONSE STRUCTURE:**
   - Start with **INSIGHT** (The "So What?")
   - Follow with **EVIDENCE** (What layers prove it)
   - End with **RECOMMENDATION** (Next action)
</sops>

<cinematography>
**CINEMATOGRAPHY PROTOCOL - You are broadcasting LIVE**

You must direct the camera BEFORE you explain the data.
The user is watching the map update in real-time via Server-Sent Events.

**MOVE FIRST:**
- As soon as you decide to look at "Berlin", emit `tool_define_aoi(city="Berlin", country_code="DEU")` IMMEDIATELY.
- The camera will fly there while you gather data.
- Do NOT talk about Berlin while the camera is still on London.

**USE STRUCTURED PARAMS - You Know Geography!**
- You have world knowledge. Use country codes (ISO 3166-1 alpha-3).
- `tool_define_aoi(city="Tokyo", country_code="JPN")` - not ambiguous string "Tokyo"
- `tool_define_aoi(country_code="GHA")` - for Ghana the country (not Ghana, India!)
- `tool_define_aoi(city="Paris", country_code="FRA")` - not Paris, Texas
- Your knowledge is the disambiguation layer. Use it.

**LAYER STAGING (Visual Pacing):**
1. **Broad Context First** → Call Matrix/Population/Wealth tools (heatmaps appear)
2. **Then Zoom In** → Camera adjusts to show patterns
3. **Then Show Specifics** → Call Search/Points tools (markers pop in on top)

This pacing makes your reasoning easier to follow:
- User sees the "forest" (heatmap) before the "trees" (individual points)
- Each layer builds on the previous visual context

**EXAMPLE SEQUENCE:**
```
User: "Find coffee shops in wealthy areas of Tokyo"

1. tool_define_aoi(city="Tokyo", country_code="JPN") → Camera flies to Tokyo
2. tool_query_matrix(wealth_index > 0.7) → Heatmap shows wealthy areas
3. tool_search_entities("coffee shops")   → Points appear on heatmap
4. Generate text explanation              → User already sees the answer
```

**BAD EXAMPLE (Don't do this):**
```
User: "Find coffee shops in wealthy areas of Tokyo"

1. Generate text: "Let me analyze Tokyo..."  ❌ Camera still on London!
2. tool_search_entities("coffee shops")      ❌ Points with no context
3. tool_query_matrix(...)                    ❌ Heatmap appears after points
```
</cinematography>

<output>
Return JSON matching AgentResponse schema:
{
  "text": "Your narrative explaining the visual argument",
  "new_layers": [], // Automatically populated by tools
  "aoi": {...}, // Current AOI if set
  "map_control": {
    "fly_to": {"lat": 35.68, "lon": 139.76, "zoom": 12},
    "pitch": 45,
    "bearing": 0,
    "duration": 2000
  },
  "plan": "Optional: your reasoning process"
}

IMPORTANT: 
- Always include map_control to direct the camera
- The layers are created by tools - you orchestrate them
</output>

<overture_reference>
""" + OVERTURE_SCHEMA_CONTEXT + """
</overture_reference>
"""


# =============================================================================
# TOOL FUNCTIONS (For Gemini)
# =============================================================================

# AOI Tool - Smart structured inputs
def tool_define_aoi(
    country_code: Optional[str] = None,
    city: Optional[str] = None,
    bbox: Optional[List[float]] = None,
    query: Optional[str] = None,
) -> Dict:
    """
    Set the Area of Interest. MUST be called first for any location-based query.
    
    USE STRUCTURED PARAMS - you know geography! Don't pass ambiguous strings.
    
    Args:
        country_code: ISO 3166-1 alpha-3 code (e.g., "GHA" for Ghana, "JPN" for Japan, "ESP" for Spain).
                      Use this for countries - it's unambiguous!
        city: City name. Use with country_code for disambiguation (e.g., city="London", country_code="GBR").
        bbox: Direct bounding box [min_lon, min_lat, max_lon, max_lat]. Use when you know the exact area.
        query: Fallback for complex queries. Avoid if possible - use structured params instead.
    
    Examples:
        - Ghana (country): tool_define_aoi(country_code="GHA")
        - Tokyo, Japan: tool_define_aoi(city="Tokyo", country_code="JPN")
        - Central Paris: tool_define_aoi(city="Paris", country_code="FRA")
        - Custom area: tool_define_aoi(bbox=[2.2, 48.8, 2.5, 48.9])
    """
    import requests
    
    logger.info(f"🎯 tool_define_aoi: country_code={country_code}, city={city}, bbox={bbox}, query={query}")
    
    # Priority 1: Direct bbox - use as-is
    if bbox and len(bbox) == 4:
        logger.info(f"   Using direct bbox: {bbox}")
        return {
            "success": True,
            "aoi": None,
            "bbox": bbox,
            "name": f"Custom area [{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}]",
        }
    
    # Priority 2: Country code - unambiguous lookup
    if country_code:
        # Use Nominatim with country code for precise lookup
        search_query = country_code
        params = {"country": country_code.upper(), "format": "json", "limit": 1}
        
        if city:
            # City within country - very precise
            params["city"] = city
            search_name = f"{city}, {country_code}"
            logger.info(f"   Looking up city: {city} in {country_code}")
        else:
            # Just the country
            params["q"] = country_code
            search_name = country_code
            logger.info(f"   Looking up country: {country_code}")
        
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers={"User-Agent": "Leo/1.0"},
                timeout=10,
            )
            if resp.ok and resp.json():
                data = resp.json()[0]
                # Get bounding box from result
                if "boundingbox" in data:
                    bb = data["boundingbox"]  # [south, north, west, east]
                    result_bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
                else:
                    lat, lon = float(data["lat"]), float(data["lon"])
                    delta = 0.5 if not city else 0.1  # Larger for country, smaller for city
                    result_bbox = [lon - delta, lat - delta, lon + delta, lat + delta]
                
                logger.info(f"   ✅ Found: {data.get('display_name', search_name)}")
                logger.info(f"   📦 BBox: {result_bbox}")
                return {
                    "success": True,
                    "aoi": None,
                    "bbox": result_bbox,
                    "name": data.get("display_name", search_name),
                }
        except Exception as e:
            logger.warning(f"   Nominatim lookup failed: {e}")
    
    # Priority 3: Query string - legacy/fallback
    if query:
        logger.info(f"   Using query string fallback: {query}")
        try:
            aoi_manager = AOIManager()
            result = aoi_manager.get_aoi(query, prefer_type="city")
            return {
                "success": True,
                "aoi": result.get("focus_geometry"),
                "bbox": result.get("context_bbox"),
                "name": result.get("name", query),
            }
        except Exception as e:
            logger.warning(f"   AOIManager failed ({e}), trying Nominatim...")
            try:
                resp = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1},
                    headers={"User-Agent": "Leo/1.0"},
                    timeout=10,
                )
                if resp.ok and resp.json():
                    data = resp.json()[0]
                    if "boundingbox" in data:
                        bb = data["boundingbox"]
                        result_bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
                    else:
                        lat, lon = float(data["lat"]), float(data["lon"])
                        result_bbox = [lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1]
                    return {
                        "success": True,
                        "aoi": None,
                        "bbox": result_bbox,
                        "name": data.get("display_name", query),
                    }
            except Exception as geo_e:
                logger.error(f"   Geocoding also failed: {geo_e}")
            
            return {"success": False, "error": str(e), "name": query}
    
    # No valid input
    return {"success": False, "error": "Must provide country_code, city, bbox, or query", "name": "Unknown"}

# Population Tool
def tool_get_population(bbox: List[float], year: int = 2026) -> List[Dict]:
    """Get population density from WorldPop. Returns H3 hexagons."""
    result = get_population_density(bbox=bbox, year=year, aggregate_h3=True, h3_resolution=9)
    data = result.get("data", []) if result else []
    return [
        {"hex": d.get("hex"), "lat": d.get("lat"), "lng": d.get("lng"), "value": d.get("count", 0)}
        for d in data if d.get("hex")
    ]

# Crop Tool
def tool_fetch_crops(country: str, crop: str) -> List[Dict]:
    """Get crop production from MapSPAM."""
    data = fetch_crop_production(country, crop, "production")
    return [
        {"lat": d.get("lat"), "lng": d.get("lng") or d.get("lon"), "value": d.get("value", 0)}
        for d in (data or []) if d.get("lat")
    ]

# Wealth Tool
def tool_fetch_wealth(country_iso3: str) -> List[Dict]:
    """Get Relative Wealth Index."""
    data = fetch_wealth_index(country_iso3, None)
    return [
        {"lat": d.get("lat"), "lng": d.get("lng"), "value": d.get("rwi_score", 0)}
        for d in (data or []) if d.get("lat")
    ]

# Weather Tool
def tool_fetch_weather_risk(bbox: List[float]) -> Dict:
    """Get weather/climate risk data."""
    return fetch_weather_risk(bbox)

# Route Tool
def tool_calculate_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> Dict:
    """Calculate route between two points."""
    result = get_transport_route(start_lat, start_lon, end_lat, end_lon, "driving")
    return json.loads(result) if isinstance(result, str) else result

# Trade Tool
def tool_fetch_trade(reporter_iso3: str, commodity_code: str = "TOTAL") -> Dict:
    """Get trade flow data from UN Comtrade."""
    return fetch_trade_flows(reporter_iso3, commodity_code)

# News Tool
def tool_fetch_news(query: str) -> Dict:
    """Get news/events from GDELT."""
    return fetch_news_narrative(query, "point")

# =============================================================================
# COOKIE CUTTER TOOLS (Geometry Filtering) - GENERIC for ANY shape
# =============================================================================

def tool_fetch_geometry(
    geometry_type: str,
    bbox: Optional[List[float]] = None,
    country_code: Optional[str] = None,
    filters: Optional[Dict] = None,
    name_filter: Optional[str] = None,
) -> Dict:
    """
    Fetch ANY geometry from Overture to use as a Cookie Cutter stencil.
    
    This is STEP 1 of Cookie Cutter - get the base shape you want to buffer.
    
    Args:
        geometry_type: What to fetch:
            - "coastline" → Ocean/sea boundaries
            - "water" → Lakes, rivers, all water bodies  
            - "river" → Rivers specifically
            - "lake" → Lakes specifically
            - "park" → Parks (land_use)
            - "forest" → Forests (land_use)
            - "road" → Major roads (transportation)
            - "railway" → Railways (transportation)
            - "boundary" → Administrative boundaries
        bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
        country_code: ISO 2-letter code (FR, ES, GB, US) - for country-wide queries
        filters: Additional Overture filters
        name_filter: Filter by name (e.g., "Seine" for Seine river)
    
    Returns:
        GeoJSON geometry that can be passed to tool_buffer_geometry()
    
    Examples:
        # French coastline
        tool_fetch_geometry("coastline", country_code="FR")
        
        # Seine river
        tool_fetch_geometry("river", country_code="FR", name_filter="Seine")
        
        # Parks in a bbox
        tool_fetch_geometry("park", bbox=[2.3, 48.8, 2.4, 48.9])
        
        # Major roads in Spain
        tool_fetch_geometry("road", country_code="ES")
    """
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    from shapely import wkt
    
    try:
        engine = get_athena_engine()
        
        # Get bbox from country if not provided
        if not bbox and country_code:
            boundary = engine.get_smart_boundary(country_code, type_hint="country")
            bbox = boundary.focus_bbox
        
        if not bbox:
            return {"success": False, "error": "Must provide bbox or country_code"}
        
        # Map geometry_type to Overture theme/type/filters
        TYPE_MAPPING = {
            "coastline": ("base", "water", {"subtype": ["ocean", "sea", "bay"]}),
            "water": ("base", "water", None),
            "river": ("base", "water", {"subtype": ["river", "stream", "canal"]}),
            "lake": ("base", "water", {"subtype": ["lake", "pond", "reservoir"]}),
            "park": ("base", "land_use", {"class": "park"}),
            "forest": ("base", "land_use", {"class": "forest"}),
            "road": ("transportation", "segment", {"class": ["motorway", "trunk", "primary"]}),
            "railway": ("transportation", "segment", {"class": "rail"}),
            "boundary": ("divisions", "division_area", None),
        }
        
        if geometry_type not in TYPE_MAPPING:
            return {
                "success": False, 
                "error": f"Unknown geometry_type: {geometry_type}. Options: {list(TYPE_MAPPING.keys())}"
            }
        
        theme, feature_type, default_filters = TYPE_MAPPING[geometry_type]
        
        # Merge filters
        merged_filters = default_filters or {}
        if filters:
            merged_filters.update(filters)
        if name_filter:
            merged_filters["names.primary"] = name_filter
        
        # Fetch the geometry
        df = engine.fetch_features_sql(
            bbox=bbox,
            theme=theme,
            feature_type=feature_type,
            filters=merged_filters if merged_filters else None,
            limit=500,
        )
        
        if df.empty:
            return {"success": False, "error": f"No {geometry_type} found in area"}
        
        # Combine all geometries into one
        geometries = []
        for _, row in df.iterrows():
            if "geometry_wkt" in row and row["geometry_wkt"]:
                try:
                    geom = wkt.loads(row["geometry_wkt"])
                    geometries.append(geom)
                except:
                    pass
        
        if not geometries:
            return {"success": False, "error": "Could not parse geometries"}
        
        # Union all geometries
        combined = unary_union(geometries)
        
        # For water/coastline, extract boundary (the edge)
        if geometry_type in ("coastline", "water", "lake"):
            combined = combined.boundary
        
        return {
            "success": True,
            "geometry": mapping(combined),
            "type": combined.geom_type,
            "geometry_type": geometry_type,
            "feature_count": len(geometries),
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_buffer_geometry(geometry: Dict, distance_meters: float) -> Dict:
    """
    Create a buffer around a geometry. Use this as STEP 2 of Cookie Cutter.
    
    Takes a LineString (coastline, route) or Polygon and creates a buffer zone.
    
    Args:
        geometry: GeoJSON geometry dict (from tool_get_coastline or other sources)
        distance_meters: Buffer distance in meters
    
    Example:
        coast = tool_get_coastline("FR")
        buffer = tool_buffer_geometry(coast["geometry"], 2500)  # 2.5km buffer
    """
    try:
        result = buffer_geometry(geometry, distance_meters)
        return {
            "success": True,
            "geometry": result,
            "buffer_meters": distance_meters,
            "type": result.get("type", "Polygon"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_filter_by_geometry(
    geometry: Dict,
    theme: str,
    feature_type: str,
    filters: Optional[Dict] = None,
    limit: int = 5000,
) -> List[Dict]:
    """
    Filter Overture entities by ANY geometry shape (The Cookie Cutter for ENTITIES).
    
    Use this as STEP 3 of Cookie Cutter to get POI pins/polygons inside a complex shape.
    
    Args:
        geometry: GeoJSON Polygon (from tool_buffer_geometry)
        theme: Overture theme - "places", "base", "buildings", "transportation"
        feature_type: Feature type - "place", "land_use", "water", "building", "segment"
        filters: Attribute filters (e.g., {"categories.primary": "cafe"})
        limit: Max results
    
    Common theme/type combinations:
        - places/place: POIs (cafes, shops, hospitals)
        - base/land_use: Parks, forests, farmland
        - base/water: Lakes, rivers, coastline
        - buildings/building: Building footprints
        - transportation/segment: Roads
    
    Example:
        # Get cafes within 2.5km of French coast
        coast = tool_get_coastline("FR")
        buffer = tool_buffer_geometry(coast["geometry"], 2500)
        cafes = tool_filter_by_geometry(
            buffer["geometry"], "places", "place", 
            {"categories.primary": "cafe"}
        )
    """
    try:
        df = fetch_features_geometry(
            geometry=geometry,
            theme=theme,
            feature_type=feature_type,
            filters=filters,
            limit=limit,
        )
        
        # Convert DataFrame to list of dicts for GeoJSON
        results = []
        for _, row in df.iterrows():
            item = row.to_dict()
            # Extract coordinates if available
            if "lon" in item and "lat" in item:
                item["coordinates"] = [item["lon"], item["lat"]]
            results.append(item)
        
        return results
    except Exception as e:
        return [{"error": str(e)}]


def tool_matrix_geometry(
    geometry: Dict,
    filters: Optional[Dict[str, str]] = None,
    limit: int = 10000,
) -> List[Dict]:
    """
    Filter Matrix hexes by ANY geometry shape (The Cookie Cutter for MATRIX).
    
    Use this to get H3 heatmaps constrained to complex shapes.
    
    Args:
        geometry: GeoJSON Polygon (from tool_buffer_geometry)
        filters: Matrix column filters (e.g., {"wealth_index": "> 0.7"})
        limit: Max hexes
    
    Example:
        # Get wealthy coastal areas
        coast = tool_get_coastline("FR")
        buffer = tool_buffer_geometry(coast["geometry"], 2500)
        wealthy_coast = tool_matrix_geometry(
            buffer["geometry"],
            {"wealth_index": "> 0.7", "score_coast": "> 8"}
        )
    """
    try:
        result = query_matrix(
            aoi_geometry=geometry,
            filters=filters,
            limit=limit,
        )
        return result.data if hasattr(result, 'data') else []
    except Exception as e:
        return [{"error": str(e)}]


def tool_neighborhood_query(
    bbox: List[float],
    rings: int = 5,
    aggregations: Optional[Dict[str, str]] = None,
    filters: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """
    Find Matrix hexes where the surrounding NEIGHBORHOOD has specific features.
    
    This is for queries like "Find areas where the 5-ring neighborhood has gyms AND pubs".
    Aggregations happen on-the-fly at query time.
    
    Args:
        bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
        rings: H3 rings for neighborhood (5 = ~250m at resolution 11)
        aggregations: Columns to aggregate (e.g., {"gym_count": "SUM", "bar_count": "SUM"})
        filters: Filters on aggregated values (use "hood_" prefix! e.g., {"hood_gym_count": "> 0"})
    
    Example:
        # Find hexes where neighborhood has both gyms and pubs
        tool_neighborhood_query(
            bbox=[2.3, 48.8, 2.4, 48.9],
            aggregations={"gym_count": "SUM", "bar_count": "SUM"},
            filters={"hood_gym_count": "> 0", "hood_bar_count": "> 0"}
        )
    """
    try:
        result = query_matrix_neighborhood(
            bbox=bbox,
            rings=rings,
            aggregations=aggregations,
            filters=filters,
        )
        return result.data if hasattr(result, 'data') else []
    except Exception as e:
        return [{"error": str(e)}]


def tool_calculate_index(
    index_type: str,
    bbox: List[float],
    rings: int = 5,
) -> List[Dict]:
    """
    Calculate derived indices (affluence, gentrification, vitality) on-the-fly.
    
    These indices are NOT pre-computed - they use neighborhood aggregation.
    
    Args:
        index_type: "affluence", "gentrification", or "vitality"
        bbox: Bounding box to analyze
        rings: Neighborhood size for smoothing
    
    Index definitions:
        - affluence: Banks, hotels, gyms, malls vs convenience stores
        - gentrification: Cafes, gyms, bars, museums, building height
        - vitality: POI diversity, walkability, restaurant density
    
    Example:
        tool_calculate_index("affluence", [2.3, 48.8, 2.4, 48.9])
    """
    try:
        result = calculate_derived_index(
            index_type=index_type,
            bbox=bbox,
            rings=rings,
        )
        return result.data if hasattr(result, 'data') else []
    except Exception as e:
        return [{"error": str(e)}]


def tool_travel_time_zone(
    center_lat: float,
    center_lon: float,
    minutes: int,
    mode: str = "moped",
) -> Dict:
    """
    Get approximate travel-time zone as a polygon (for cookie cutter).
    
    Uses speed estimates to create a circular buffer approximating travel time.
    This is faster than real isochrones but less accurate for road networks.
    
    Args:
        center_lat: Center point latitude
        center_lon: Center point longitude
        minutes: Travel time in minutes
        mode: Transport mode affects speed estimate:
            - "walking": ~5 km/h
            - "cycling": ~15 km/h  
            - "moped": ~25 km/h
            - "driving": ~40 km/h (city average)
    
    Returns:
        GeoJSON Polygon that can be used with tool_matrix_geometry or tool_filter_by_geometry
    
    Example:
        # 20 min moped radius from a beach
        zone = tool_travel_time_zone(41.38, 2.19, 20, "moped")
        affluent = tool_matrix_geometry(zone["geometry"], {"wealth_index": "> 0.7"})
    """
    from shapely.geometry import Point, mapping
    
    SPEED_KMH = {
        "walking": 5,
        "cycling": 15,
        "moped": 25,
        "driving": 40,
    }
    
    speed = SPEED_KMH.get(mode, 25)
    distance_km = (speed * minutes) / 60
    
    # Convert km to degrees (approximate)
    # 1 degree ≈ 111 km at equator, less at higher latitudes
    import math
    km_per_degree = 111 * math.cos(math.radians(center_lat))
    distance_degrees = distance_km / km_per_degree
    
    # Create circular buffer
    center = Point(center_lon, center_lat)
    buffer = center.buffer(distance_degrees)
    
    return {
        "success": True,
        "geometry": mapping(buffer),
        "type": "Polygon",
        "mode": mode,
        "minutes": minutes,
        "approx_radius_km": round(distance_km, 1),
        "note": "Approximate circular zone. Real travel times depend on road network.",
    }


# Spatial Join Tool
def tool_spatial_join_proximity(
    bbox: List[float],
    target_category: str,
    reference_category: str,
    distance_meters: int = 500,
) -> Dict:
    """Find target entities near reference entities. For "X near Y" queries."""
    from tools.tools_athena import spatial_join_sql
    result = spatial_join_sql(
        bbox=bbox,
        target_theme="places",
        target_type="place", 
        target_filters={"categories.primary": target_category},
        reference_theme="places",
        reference_type="place", 
        reference_filters={"categories.primary": reference_category},
        distance_meters=distance_meters,
    )
    return {"type": "FeatureCollection", "features": result.to_dict("records") if hasattr(result, "to_dict") else []}


# Tool registry
TOOL_FUNCTIONS_FULL = [
    # Core tools
    tool_define_aoi,
    tool_query_matrix,
    tool_search_entities,

    # Cookie Cutter tools (Geometry Filtering) - GENERIC
    tool_fetch_geometry,      # Step 1: Get ANY geometry (coastline, river, road, park, etc.)
    tool_buffer_geometry,     # Step 2: Buffer it
    tool_filter_by_geometry,  # Step 3A: Apply to entities (pins)
    tool_matrix_geometry,     # Step 3B: Apply to matrix (heatmap)
    tool_travel_time_zone,    # Get approximate travel-time polygon
    tool_neighborhood_query,  # On-the-fly neighborhood aggregation
    tool_calculate_index,     # On-the-fly indices

    # Data tools
    tool_get_population,
    tool_fetch_crops,
    tool_fetch_wealth,
    tool_fetch_weather_risk,
    tool_calculate_route,
    tool_fetch_trade,
    tool_fetch_news,
    tool_spatial_join_proximity,
    tool_create_plan,
]

# Matrix-only mode - just AOI + Matrix tools for focused testing
TOOL_FUNCTIONS_MATRIX_ONLY = [
    tool_define_aoi,          # Essential: set location
    tool_query_matrix,        # Core: query the Matrix
    tool_matrix_geometry,     # Cookie cutter on Matrix
    tool_neighborhood_query,  # Neighborhood aggregation
    tool_calculate_index,     # On-the-fly indices (affluence, etc.)
    tool_travel_time_zone,    # Travel zones for cookie cutter
    tool_cascade_search,      # 🆕 Multi-resolution cascade filtering
]

# Toggle with environment variable: MATRIX_ONLY_MODE=true
import os
MATRIX_ONLY_MODE = os.environ.get("MATRIX_ONLY_MODE", "false").lower() == "true"
TOOL_FUNCTIONS = TOOL_FUNCTIONS_MATRIX_ONLY if MATRIX_ONLY_MODE else TOOL_FUNCTIONS_FULL

if MATRIX_ONLY_MODE:
    logger.info("🔒 MATRIX-ONLY MODE ENABLED - Limited to Matrix tools")

TOOL_MAP = {f.__name__: f for f in TOOL_FUNCTIONS}


# =============================================================================
# LEO AGENT
# =============================================================================

class LeoAgent:
    """Pure ReAct Agent - Python is the pipe, Prompt is the brain."""

    def __init__(self, model_id: str = DEFAULT_MODEL, session_id: Optional[str] = None):
        self.model_id = model_id
        self.client = GeminiClient()
        self.strategy_retriever = StrategyRetriever()
        self.session = SessionState(session_id=session_id or datetime.now().strftime("%Y%m%d_%H%M%S"))
        logger.info(f"🦁 Leo Agent initialized (model: {model_id}, session: {self.session.session_id})")
    
    def chat(self, message: str) -> AgentResponse:
        """Process user message through Pure ReAct loop."""
        self.session.turn_number += 1
        logger.info(f"💬 Turn {self.session.turn_number}: {message[:60]}...")
        
        # Build context
        context = self._build_context(message)
        
        # Tool executor
        def tool_executor(name: str, args: Dict) -> Any:
            if name not in TOOL_MAP:
                return {"error": f"Unknown tool: {name}"}
            
            logger.info(f"🔧 Calling: {name}")
            result = TOOL_MAP[name](**args)
            
            # Update session state if AOI was set
            if name == "tool_define_aoi" and result.get("success"):
                self.session.aoi = result.get("aoi")
                self.session.context_bbox = result.get("bbox")
            
            return result
        
        # Call LLM
        response = self.client.call(
            prompt=context,
            system_instruction=MASTER_SYSTEM_PROMPT,
            tools=TOOL_FUNCTIONS,
            tool_executor=tool_executor,
            model=self.model_id,
            max_tool_iterations=15,
            temperature=0.3,
        )
        
        if not response.success:
            return AgentResponse(
                text=f"Error: {response.error}",
                session_id=self.session.session_id,
                turn_number=self.session.turn_number,
            )
        
        # Parse response
        text, map_control = self._parse_response(response.text)
        
        return AgentResponse(
            text=text,
            new_layers=[],  # Tools populate this via capture
            aoi=self.session.aoi,
            map_control=map_control,
            session_id=self.session.session_id,
            turn_number=self.session.turn_number,
        )
    
    async def stream_chat(self, message: str, matrix_mode: bool = False) -> AsyncGenerator[StreamEvent, None]:
        """
        Process user message through Pure ReAct loop with real-time streaming.
        
        Args:
            message: User's message
            matrix_mode: When True, restricts agent to Matrix tools only (France H3 Store)
        
        Yields StreamEvents as the agent processes:
        1. plan_init - Execution plan checklist
        2. step_update - Plan step status changes
        3. log - Tool logs nested under current step
        4. thought - Status updates during processing
        5. map_control - Camera commands (fly_to IMMEDIATELY when AOI is set)
        6. layer_update - Layer data as tools return (data pops in live)
        7. text_chunk - LLM text response tokens as they stream
        8. done - Stream complete
        """
        self.session.turn_number += 1
        logger.info(f"💬 [STREAM] Turn {self.session.turn_number}: {message[:60]}..." + (" [MATRIX MODE]" if matrix_mode else ""))
        
        # =====================================================================
        # MATRIX MODE CONFIGURATION - Direct France H3 Access
        # =====================================================================
        FRANCE_BBOX = [-5.5, 41.0, 10.0, 51.5]
        
        if matrix_mode:
            # AUTO-SET France AOI - no tool call needed!
            self.session.aoi = None
            self.session.context_bbox = FRANCE_BBOX
            
            # Emit immediate camera move to France
            yield StreamEvent(type="thought", data="🔒 Matrix Mode: Direct France H3 Store...")
            yield StreamEvent(
                type="map_control",
                data={
                    "fly_to": {"lat": 46.6, "lon": 2.5, "zoom": 5},
                    "pitch": 0,
                    "duration": 1500
                }
            )
            
            # MATRIX MODE: Only Cascade Search
            active_tools = [
                tool_cascade_search,  # Multi-resolution cascade filtering (uses Hoxton parquets)
            ]
            active_tool_map = {f.__name__: f for f in active_tools}
            
            # Cascade-only system prompt - FORCE tool call, no questions
            matrix_mode_prompt = """IMMEDIATELY call tool_cascade_search. Do NOT ask clarifying questions. The search area is already set to Hoxton, London.

Extract features from the query and call the tool:
- summative_features: POIs to rank by (cafes, pubs, restaurants, etc.)
- driving_must_haves: Must be driveable (hospital, airport) - only if explicitly mentioned
- walking_transit: Must be walkable (tube/subway, train) - only if explicitly mentioned  
- walking_green: Must be walkable (park, forest) - only if explicitly mentioned

Examples:
"near pubs and cafes" → tool_cascade_search(summative_features=["pub", "cafe"])
"walkable to tube, near coffee shops" → tool_cascade_search(summative_features=["cafe"], walking_transit=["subway"])
"near restaurants, need hospital access" → tool_cascade_search(summative_features=["restaurant"], driving_must_haves=["hospital"])

ALWAYS call the tool. Never ask for location or clarification.
"""
        else:
            active_tools = TOOL_FUNCTIONS
            active_tool_map = TOOL_MAP
            matrix_mode_prompt = ""
            yield StreamEvent(type="thought", data="Analyzing request...")
        
        # Build context
        context = self._build_context(message)
        
        # Collected layers during tool execution
        collected_layers: List[Dict] = []
        aoi_result: Optional[Dict] = None
        
        # =====================================================================
        # PLAN TRACKING STATE (Cursor-Style Planner)
        # =====================================================================
        plan_steps: List[Dict] = []           # The execution plan
        current_plan_step_idx: int = 0         # Index of current step
        plan_emitted: bool = False             # Whether we've emitted the plan
        text_buffer: str = ""                  # Buffer for plan detection
        
        # Map tool names to plan step keywords for auto-advancing
        TOOL_TO_STEP_KEYWORDS = {
            "tool_define_aoi": ["aoi", "area", "location", "lock", "define"],
            "tool_query_matrix": ["gather", "scan", "matrix", "data", "strategic"],
            "tool_search_entities": ["search", "find", "entities", "cafes", "shops"],
            "tool_get_population": ["population", "density", "gather", "data"],
            "tool_fetch_crops": ["agriculture", "crops", "gather", "data"],
            "tool_fetch_wealth": ["wealth", "affluence", "gather", "data"],
            "tool_calculate_route": ["route", "logistics", "calculate"],
            "tool_calculate_index": ["analyze", "rank", "index", "compute"],
            "tool_spatial_join_proximity": ["analyze", "spatial", "compute"],
        }
        
        def find_matching_step_idx(tool_name: str) -> Optional[int]:
            """Find the plan step that best matches the current tool."""
            keywords = TOOL_TO_STEP_KEYWORDS.get(tool_name, [])
            for idx, step in enumerate(plan_steps):
                title_lower = step.get("title", "").lower()
                for keyword in keywords:
                    if keyword in title_lower:
                        return idx
            return None
        
        def advance_to_step(idx: int):
            """Mark previous steps as completed and set current step to running."""
            nonlocal current_plan_step_idx
            if idx >= len(plan_steps):
                return
            
            events_to_yield = []
            
            # Complete all previous steps
            for i in range(current_plan_step_idx, idx):
                if plan_steps[i]["status"] != "completed":
                    plan_steps[i]["status"] = "completed"
                    events_to_yield.append(StreamEvent(
                        type="step_update",
                        data={"id": plan_steps[i]["id"], "status": "completed"}
                    ))
            
            # Set current step to running
            if plan_steps[idx]["status"] != "running":
                plan_steps[idx]["status"] = "running"
                events_to_yield.append(StreamEvent(
                    type="step_update",
                    data={"id": plan_steps[idx]["id"], "status": "running"}
                ))
            
            current_plan_step_idx = idx
            return events_to_yield
        
        # Shared list for generator-yielded events (for streaming back)
        pending_stream_events = []
        
        # Tool executor with streaming events
        def tool_executor(name: str, args: Dict) -> Any:
            nonlocal aoi_result, collected_layers, pending_stream_events
            
            if name not in active_tool_map:
                if matrix_mode:
                    return {"error": f"Tool '{name}' not available in Matrix Mode. Use: tool_define_aoi, tool_query_matrix, tool_matrix_geometry, tool_neighborhood_query, tool_calculate_index, tool_travel_time_zone"}
                return {"error": f"Unknown tool: {name}"}
            
            # MATRIX MODE: Strip bbox to query ALL of France
            if matrix_mode and "bbox" in args:
                logger.info(f"🔒 [MATRIX] Stripping bbox - querying all of France")
                del args["bbox"]
            
            logger.info(f"🔧 [STREAM] Calling: {name}" + (" [MATRIX]" if matrix_mode else ""))
            result = active_tool_map[name](**args)
            
            # Handle GENERATOR results (for progressive streaming like cascade_search)
            # Generators yield events directly - we collect them for streaming
            import types
            if isinstance(result, types.GeneratorType):
                logger.info(f"🎬 Tool returned generator - consuming events...")
                final_result = None
                for event in result:
                    if isinstance(event, dict):
                        event_type = event.get("type")
                        if event_type == "layer_update":
                            # Store layer for streaming
                            layer_data = event.get("data", {})
                            collected_layers.append(layer_data)
                            pending_stream_events.append(("layer_update", layer_data))
                            logger.info(f"   📤 Queued layer: {layer_data.get('layer_id')}")
                        elif event_type == "thought":
                            pending_stream_events.append(("thought", event.get("data", "")))
                            logger.info(f"   💭 Queued thought: {event.get('data', '')[:50]}")
                        elif event_type == "cascade_complete":
                            final_result = event
                            logger.info(f"   ✅ Cascade complete")
                        else:
                            # Unknown event type - treat as result
                            final_result = event
                result = final_result or {"success": True, "message": "Generator completed"}
            
            # Update session state if AOI was set
            if name == "tool_define_aoi" and isinstance(result, dict) and result.get("success"):
                self.session.aoi = result.get("aoi")
                self.session.context_bbox = result.get("bbox")
                aoi_result = result
            
            return result
        
        # Build system prompt
        # Matrix Mode: Clean cascade-only prompt. Normal: Full Leo agent
        system_prompt = matrix_mode_prompt if matrix_mode else MASTER_SYSTEM_PROMPT
        
        # Use streaming call from GeminiClient
        # Matrix Mode: 3 iterations (should need 1). Normal: 15
        max_iterations = 3 if matrix_mode else 15
        
        for event in self.client.call_streaming(
            prompt=context,
            system_instruction=system_prompt,
            tools=active_tools,
            tool_executor=tool_executor,
            model=self.model_id,
            max_tool_iterations=max_iterations,
            temperature=0.3,
        ):
            event_type = event.get("type")
            
            if event_type == "thinking":
                # Convert client "thinking" to our "thought" type
                thinking_content = event.get("content", "Processing...")
                yield StreamEvent(type="thought", data=thinking_content)
                
                # Also emit as log if we have a plan
                if plan_emitted and plan_steps and current_plan_step_idx < len(plan_steps):
                    yield StreamEvent(
                        type="log",
                        data={
                            "message": thinking_content,
                            "plan_step_id": plan_steps[current_plan_step_idx]["id"],
                            "type": "thinking"
                        }
                    )
            
            elif event_type == "tool_call":
                tool_name = event.get("name", "")
                tool_args = event.get("args", {})
                
                # =========================================================
                # PLAN STEP ADVANCEMENT (Auto-advance based on tool)
                # =========================================================
                if plan_emitted and plan_steps:
                    matched_idx = find_matching_step_idx(tool_name)
                    if matched_idx is not None and matched_idx >= current_plan_step_idx:
                        step_events = advance_to_step(matched_idx)
                        if step_events:
                            for se in step_events:
                                yield se
                
                # Generate unique step ID for tracking
                step_id = str(uuid.uuid4())[:8]
                
                # Store step ID for later completion (associate with tool call)
                # We'll use the tool_name as key since tool_result comes right after
                if not hasattr(self, '_pending_steps'):
                    self._pending_steps = {}
                self._pending_steps[tool_name] = {"step_id": step_id, "args": tool_args}
                
                # Emit step_start event with human-readable message
                start_message = get_step_start_message(tool_name, tool_args)
                yield StreamEvent(
                    type="step_start",
                    data={
                        "step_id": step_id,
                        "message": start_message,
                        "tool_name": tool_name,
                        "status": "running"
                    }
                )
                
                # Emit as LOG (nested under current plan step)
                if plan_emitted and plan_steps and current_plan_step_idx < len(plan_steps):
                    yield StreamEvent(
                        type="log",
                        data={
                            "message": f"▶ {start_message}",
                            "plan_step_id": plan_steps[current_plan_step_idx]["id"],
                            "type": "tool_start"
                        }
                    )
                
                # Also emit legacy thought for backward compatibility
                yield StreamEvent(type="thought", data=start_message)
            
            elif event_type == "tool_result":
                tool_name = event.get("name", "")
                result = event.get("result")
                status = event.get("status", "success")
                
                # Retrieve pending step info for completion
                pending_step = getattr(self, '_pending_steps', {}).get(tool_name, {})
                step_id = pending_step.get("step_id", str(uuid.uuid4())[:8])
                step_args = pending_step.get("args", {})
                
                if status == "error":
                    # Emit step_complete with error status
                    yield StreamEvent(
                        type="step_complete",
                        data={
                            "step_id": step_id,
                            "message": f"Failed: {tool_name}",
                            "tool_name": tool_name,
                            "status": "error"
                        }
                    )
                    
                    # Emit as LOG (nested under current plan step)
                    if plan_emitted and plan_steps and current_plan_step_idx < len(plan_steps):
                        yield StreamEvent(
                            type="log",
                            data={
                                "message": f"✗ Failed: {tool_name}",
                                "plan_step_id": plan_steps[current_plan_step_idx]["id"],
                                "type": "error"
                            }
                        )
                    
                    yield StreamEvent(type="thought", data=f"Tool {tool_name} encountered an issue, continuing...")
                    continue
                
                # Emit step_complete event with result summary
                complete_message = get_step_complete_message(tool_name, step_args, result)
                yield StreamEvent(
                    type="step_complete",
                    data={
                        "step_id": step_id,
                        "message": complete_message,
                        "tool_name": tool_name,
                        "status": "done"
                    }
                )
                
                # Emit as LOG (nested under current plan step)
                if plan_emitted and plan_steps and current_plan_step_idx < len(plan_steps):
                    yield StreamEvent(
                        type="log",
                        data={
                            "message": f"✓ {complete_message}",
                            "plan_step_id": plan_steps[current_plan_step_idx]["id"],
                            "type": "success"
                        }
                    )
                
                # Step 1: Handle AOI result - IMMEDIATELY emit map_control to fly camera
                if tool_name == "tool_define_aoi" and isinstance(result, dict) and result.get("success"):
                    bbox = result.get("bbox")
                    aoi_name = result.get("name", "target area")
                    
                    if bbox and len(bbox) == 4:
                        # Calculate center of bbox for fly_to
                        center_lon = (bbox[0] + bbox[2]) / 2
                        center_lat = (bbox[1] + bbox[3]) / 2
                        
                        # Calculate appropriate zoom based on bbox size
                        bbox_width = abs(bbox[2] - bbox[0])
                        bbox_height = abs(bbox[3] - bbox[1])
                        bbox_size = max(bbox_width, bbox_height)
                        
                        # Larger areas get lower zoom, smaller areas get higher zoom
                        if bbox_size > 1:  # Country/region level
                            zoom = 6
                        elif bbox_size > 0.5:  # Large city
                            zoom = 8
                        elif bbox_size > 0.1:  # City
                            zoom = 11
                        else:  # Neighborhood
                            zoom = 13
                        
                        # Emit camera step_start
                        camera_step_id = str(uuid.uuid4())[:8]
                        yield StreamEvent(
                            type="step_start",
                            data={
                                "step_id": camera_step_id,
                                "message": f"Repositioning camera over {aoi_name}...",
                                "tool_name": "_camera_move",
                                "status": "running"
                            }
                        )
                        
                        # Emit map_control event IMMEDIATELY - camera starts moving while we fetch data
                        yield StreamEvent(
                            type="map_control",
                            data={
                                "fly_to": {
                                    "lat": center_lat,
                                    "lon": center_lon,
                                    "zoom": zoom
                                },
                                "pitch": 45,  # 3D view for analysis
                                "bearing": -15,  # Slight rotation for depth
                                "duration": 2500,
                                "bbox": bbox
                            }
                        )
                        
                        # Emit camera step_complete
                        yield StreamEvent(
                            type="step_complete",
                            data={
                                "step_id": camera_step_id,
                                "message": f"Camera moved to {aoi_name}",
                                "tool_name": "_camera_move",
                                "status": "done"
                            }
                        )
                        yield StreamEvent(type="thought", data=f"Focused on {aoi_name}")
                
                # Step 2 & 3: Handle data results - emit layer_update as soon as data is ready
                # Convert dataclass to dict if needed (LayerData from tools_matrix.py)
                from dataclasses import is_dataclass, asdict
                if is_dataclass(result) and not isinstance(result, type):
                    logger.info(f"📦 Converting LayerData dataclass to dict...")
                    result = asdict(result)
                    logger.info(f"📦 Converted! layer_id={result.get('layer_id')}, data_len={len(result.get('data', []))}")
                
                if isinstance(result, dict):
                    # Check if it's a layer-like result (GeoJSON FeatureCollection)
                    if "type" in result and "features" in result:
                        collected_layers.append(result)
                        feature_count = len(result.get("features", []))
                        yield StreamEvent(
                            type="layer_update",
                            data={
                                "layer_type": "geojson",
                                "feature_count": feature_count,
                                "geojson": result
                            }
                        )
                    elif result.get("type") == "cascade_result" and "stages" in result:
                        # PROGRESSIVE CASCADE: Emit stages with ASYNC delays for animation
                        # Using asyncio.sleep() so event loop can send events between stages
                        import asyncio
                        
                        logger.info(f"🎬 Emitting {len(result['stages'])} cascade stages with animation...")
                        
                        # Camera hug FIRST on stage 1 data
                        first_stage = result["stages"][0] if result["stages"] else None
                        if first_stage and matrix_mode:
                            first_layer = first_stage.get("layers", [{}])[0]
                            h3_data = first_layer.get("data", [])
                            if h3_data:
                                try:
                                    import h3
                                    lats, lons = [], []
                                    for item in h3_data[:500]:
                                        hex_id = item.get("hex")
                                        if hex_id:
                                            lat, lon = h3.cell_to_latlng(hex_id)
                                            lats.append(lat)
                                            lons.append(lon)
                                    if lats and lons:
                                        yield StreamEvent(type="map_control", data={
                                            "fit_bounds": [min(lons)-0.01, min(lats)-0.01, max(lons)+0.01, max(lats)+0.01],
                                            "padding": 30, "duration": 1000
                                        })
                                except Exception as e:
                                    logger.warning(f"Camera hug failed: {e}")
                        
                        for i, stage in enumerate(result["stages"]):
                            status = stage.get("status", f"Stage {i+1}...")
                            layers = stage.get("layers", [])
                            delay = stage.get("delay", 1.5)  # Delay BEFORE this stage
                            
                            # SLEEP BEFORE emitting this stage (except first)
                            # This gives animation time between stages
                            if i > 0 and delay > 0:
                                logger.info(f"   ⏱️ Sleeping {delay}s before stage {i+1}...")
                                await asyncio.sleep(delay)
                            
                            # Emit status thought
                            logger.info(f"🎬 {status}")
                            yield StreamEvent(type="thought", data=status)
                            
                            # Emit each layer in this stage
                            for layer in layers:
                                collected_layers.append(layer)
                                yield StreamEvent(type="layer_update", data=layer)
                                logger.info(f"   📤 Layer: {layer.get('layer_id')} ({layer.get('count')} hexes)")
                    
                    elif "layer_id" in result:
                        # LayerData-like result from matrix/search
                        collected_layers.append(result)
                        yield StreamEvent(type="layer_update", data=result)
                        
                        # =========================================================
                        # CAMERA HUG: Auto-fit bounds to H3 data in Matrix Mode
                        # =========================================================
                        if matrix_mode and result.get("type") == "h3_grid":
                            h3_data = result.get("data", [])
                            if h3_data and len(h3_data) > 0:
                                try:
                                    import h3
                                    # Extract bounding box from H3 hexagons
                                    lats, lons = [], []
                                    for item in h3_data[:5000]:  # Limit for performance
                                        hex_id = item.get("hex") or item.get("h3_index")
                                        if hex_id:
                                            try:
                                                lat, lon = h3.cell_to_latlng(hex_id)
                                                lats.append(lat)
                                                lons.append(lon)
                                            except:
                                                pass
                                    
                                    if lats and lons:
                                        # Calculate bounding box with padding
                                        min_lat, max_lat = min(lats), max(lats)
                                        min_lon, max_lon = min(lons), max(lons)
                                        
                                        # Emit camera hug command
                                        logger.info(f"📷 Camera hug: [{min_lon:.3f}, {min_lat:.3f}, {max_lon:.3f}, {max_lat:.3f}]")
                                        yield StreamEvent(
                                            type="map_control",
                                            data={
                                                "fit_bounds": [min_lon, min_lat, max_lon, max_lat],
                                                "padding": 50,
                                                "pitch": 0,  # Top-down for heatmaps
                                                "duration": 2000
                                            }
                                        )
                                except Exception as e:
                                    logger.warning(f"Camera hug calculation failed: {e}")
                
                elif isinstance(result, list) and len(result) > 0:
                    # List of data points (H3 hexagons for heatmaps, points for markers)
                    if isinstance(result[0], dict) and ("hex" in result[0] or "lat" in result[0]):
                        layer_type = "h3_grid" if "hex" in result[0] else "points"
                        layer_data = {
                            "layer_type": layer_type,
                            "count": len(result),
                            "data": result
                        }
                        collected_layers.append(layer_data)
                        yield StreamEvent(type="layer_update", data=layer_data)
                        
                        # Camera hug for raw H3 list data too
                        if matrix_mode and layer_type == "h3_grid":
                            try:
                                import h3
                                lats, lons = [], []
                                for item in result[:5000]:
                                    hex_id = item.get("hex") or item.get("h3_index")
                                    if hex_id:
                                        try:
                                            lat, lon = h3.cell_to_latlng(hex_id)
                                            lats.append(lat)
                                            lons.append(lon)
                                        except:
                                            pass
                                
                                if lats and lons:
                                    min_lat, max_lat = min(lats), max(lats)
                                    min_lon, max_lon = min(lons), max(lons)
                                    logger.info(f"📷 Camera hug (raw): [{min_lon:.3f}, {min_lat:.3f}, {max_lon:.3f}, {max_lat:.3f}]")
                                    yield StreamEvent(
                                        type="map_control",
                                        data={
                                            "fit_bounds": [min_lon, min_lat, max_lon, max_lat],
                                            "padding": 50,
                                            "pitch": 0,
                                            "duration": 2000
                                        }
                                    )
                            except Exception as e:
                                logger.warning(f"Camera hug (raw) calculation failed: {e}")
            
            elif event_type == "text":
                # Step 4: Stream text_chunk tokens as LLM generates explanation
                # The LLM may output JSON - extract just the "text" field if present
                content = event.get("content", "")
                
                # =========================================================
                # PLAN DETECTION: Check for execution_plan in JSON output
                # =========================================================
                text_buffer += content
                
                # Try to parse execution_plan from the buffer (before first tool call)
                if not plan_emitted and "execution_plan" in text_buffer:
                    try:
                        # Try to extract JSON with execution_plan
                        json_str = text_buffer
                        if "```json" in text_buffer:
                            start = text_buffer.find("```json") + 7
                            end = text_buffer.find("```", start)
                            if end > start:
                                json_str = text_buffer[start:end]
                        elif "{" in text_buffer:
                            # Find the JSON object
                            start = text_buffer.find("{")
                            # Find matching closing brace
                            brace_count = 0
                            end = start
                            for i, c in enumerate(text_buffer[start:], start):
                                if c == "{":
                                    brace_count += 1
                                elif c == "}":
                                    brace_count -= 1
                                    if brace_count == 0:
                                        end = i + 1
                                        break
                            json_str = text_buffer[start:end]
                        
                        parsed = json.loads(json_str.strip())
                        if isinstance(parsed, dict) and "execution_plan" in parsed:
                            raw_plan = parsed["execution_plan"]
                            if isinstance(raw_plan, list) and len(raw_plan) > 0:
                                # Initialize plan steps
                                plan_steps = [
                                    {
                                        "id": step.get("id", f"step_{i+1}"),
                                        "title": step.get("title", f"Step {i+1}"),
                                        "status": "running" if i == 0 else "pending"
                                    }
                                    for i, step in enumerate(raw_plan)
                                ]
                                
                                # Emit plan_init event
                                yield StreamEvent(type="plan_init", data=plan_steps)
                                plan_emitted = True
                                logger.info(f"📋 [PLAN] Emitted plan with {len(plan_steps)} steps")
                                
                                # Don't output the JSON as text
                                content = ""
                    except (json.JSONDecodeError, ValueError, KeyError) as e:
                        logger.debug(f"Plan parsing error (may be incomplete): {e}")
                
                # Try to parse if it looks like JSON with "text" field
                if content.strip().startswith("{") and "text" in content:
                    try:
                        # Handle both raw JSON and ```json blocks
                        json_str = content
                        if "```json" in content:
                            start = content.find("```json") + 7
                            end = content.find("```", start)
                            if end > start:
                                json_str = content[start:end]
                        
                        parsed = json.loads(json_str.strip())
                        if isinstance(parsed, dict) and "text" in parsed:
                            # Extract the clean text
                            content = parsed["text"]
                            
                            # Also check for map_control in the response
                            if "map_control" in parsed:
                                mc = parsed["map_control"]
                                if mc.get("fly_to"):
                                    yield StreamEvent(
                                        type="map_control",
                                        data={
                                            "fly_to": mc["fly_to"],
                                            "pitch": mc.get("pitch", 45),
                                            "bearing": mc.get("bearing", 0),
                                            "duration": mc.get("duration", 2000),
                                        }
                                    )
                    except json.JSONDecodeError:
                        # Not valid JSON, use content as-is
                        pass
                
                # Only emit text if not a plan JSON
                if content and "execution_plan" not in content:
                    yield StreamEvent(type="text_chunk", data=content)
            
            elif event_type == "error":
                yield StreamEvent(type="error", data=event.get("message", "Unknown error"))
            
            elif event_type == "done":
                # =========================================================
                # COMPLETE ALL REMAINING PLAN STEPS
                # =========================================================
                if plan_emitted and plan_steps:
                    for step in plan_steps:
                        if step["status"] != "completed":
                            step["status"] = "completed"
                            yield StreamEvent(
                                type="step_update",
                                data={"id": step["id"], "status": "completed"}
                            )
                
                # Emit final done event with metadata
                yield StreamEvent(
                    type="done",
                    data={
                        "session_id": self.session.session_id,
                        "turn_number": self.session.turn_number,
                        "layers_count": len(collected_layers),
                        "model": event.get("model"),
                        "usage": event.get("usage"),
                        "plan_completed": plan_emitted
                    }
                )
    
    def _build_context(self, message: str) -> str:
        """Build prompt context with state and strategies."""
        context = []
        
        # Current state
        context.append("## CURRENT STATE")
        if self.session.aoi:
            context.append(f"AOI: SET (bbox: {self.session.context_bbox})")
        else:
            context.append("AOI: NOT SET - You MUST call tool_define_aoi first!")
        context.append(f"Turn: {self.session.turn_number}")
        
        # Strategy injection (top 3)
        strategies = self.strategy_retriever.find_relevant_strategies(message, top_k=3)
        if strategies:
            context.append("")
            context.append("## RELEVANT PLAYBOOKS (Use as inspiration)")
            for i, s in enumerate(strategies, 1):
                context.append(f"### Playbook {i}: {s.get('title', 'Unknown')}")
                if s.get('description'):
                    context.append(f"   {s['description'][:200]}...")
                if s.get('reasoning_chain'):
                    context.append(f"   Steps: {s['reasoning_chain'][:300]}...")
        
        # User message
        context.append("")
        context.append("## USER REQUEST")
        context.append(message)
        
        return "\n".join(context)
    
    def _parse_response(self, text: str) -> tuple:
        """Extract text and map_control from response."""
        if not text:
            return "Analysis complete.", None
        
        # Try to parse JSON from response
        map_control = None
        clean_text = text
        
        # Check for JSON block
        if "```json" in text:
            try:
                start = text.find("```json") + 7
                end = text.find("```", start)
                if end > start:
                    json_str = text[start:end].strip()
                    parsed = json.loads(json_str)
                    if isinstance(parsed, dict):
                        if "text" in parsed:
                            clean_text = parsed["text"]
                        if "map_control" in parsed:
                            mc = parsed["map_control"]
                            map_control = MapControl(
                                fly_to=mc.get("fly_to"),
                                pitch=mc.get("pitch"),
                                bearing=mc.get("bearing"),
                                duration=mc.get("duration", 2000),
                            )
            except json.JSONDecodeError:
                pass
        
        return clean_text, map_control


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="Leo Agent", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instance
agent: Optional[LeoAgent] = None

def get_agent() -> LeoAgent:
    global agent
    if agent is None:
        agent = LeoAgent()
    return agent


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint."""
    leo = get_agent()
    
    # Switch model if requested
    if request.model != leo.model_id and request.model in SUPPORTED_MODELS:
        leo.model_id = request.model
    
    response = leo.chat(request.message)
    
    return ChatResponse(
        text=response.text,
        layers=[l.dict() for l in response.new_layers] if response.new_layers else [],
        aoi=response.aoi,
        map_control=response.map_control.dict() if response.map_control else None,
    )


@app.post("/stream-chat")
async def stream_chat(request: ChatRequest):
    """
    Server-Sent Events streaming chat endpoint.
    
    Streams events in real-time as the agent processes:
    - step_start: Tool execution started (spinner)
    - step_complete: Tool execution completed (checkmark)
    - thought: Status update
    - map_control: Camera command
    - layer_update: Layer data
    - text_chunk: LLM text response
    - error: Error message
    - done: Stream complete
    
    Matrix Mode:
    - When request.matrix_mode is True, agent is restricted to Matrix tools only
    - Camera auto-fits to returned H3 hexagon data
    """
    from fastapi.responses import StreamingResponse
    
    leo = get_agent()
    
    # Switch model if requested
    if request.model != leo.model_id and request.model in SUPPORTED_MODELS:
        leo.model_id = request.model
    
    # Log Matrix Mode status
    if request.matrix_mode:
        logger.info("🔒 [MATRIX MODE] Request received - restricting to H3 Feature Store")
    
    async def event_generator():
        """Generate SSE events from stream_chat."""
        try:
            async for event in leo.stream_chat(request.message, matrix_mode=request.matrix_mode):
                # Format as SSE: data: {json}\n\n
                event_data = {
                    "type": event.type,
                    "data": event.data
                }
                yield f"data: {json.dumps(event_data)}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            error_event = {
                "type": "error",
                "data": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": DEFAULT_MODEL}


@app.get("/models")
async def list_models():
    return {"models": SUPPORTED_MODELS, "default": DEFAULT_MODEL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
