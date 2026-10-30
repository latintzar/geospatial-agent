"""
Leo Schema - Core Data Contracts
================================

Strict Pydantic models for Frontend/Backend communication.
This is the "Contract" - every tool outputs LayerData, agent returns AgentResponse.

Models:
    - VizConfig: How to render a layer
    - LayerData: The data payload
    - MapControl: Camera commands
    - StoryChapter: Narrative segments
    - AgentResponse: Complete API response
"""

from typing import List, Dict, Optional, Any, Literal, Union
from pydantic import BaseModel, Field


# =============================================================================
# VISUALIZATION CONFIG
# =============================================================================

class VizConfig(BaseModel):
    """How to render a layer on the map."""
    style: Literal["heatmap", "choropleth", "symbol", "line", "extrusion", "arc", "icon", "fill"]
    color_scale: Literal[
        "magma", "viridis", "inferno", "plasma", "ylgn", "rdbu", "rdylgn",
        "categorical_risk", "neon_blue", "neon_magenta"
    ] = "viridis"
    property_key: Optional[str] = "value"
    label: str = "Layer"
    opacity: float = 0.8
    elevation_scale: float = 10.0


# =============================================================================
# DATA LAYER
# =============================================================================

class LayerData(BaseModel):
    """A single data layer returned by tools."""
    layer_id: str
    type: Literal["h3_grid", "geojson_point", "geojson_line", "geojson_poly", "weighted_points"]
    data: Union[List[Dict], Dict]  # H3 list or GeoJSON FeatureCollection
    viz_config: VizConfig
    summary: str
    metadata: Optional[Dict] = {}


# =============================================================================
# CAMERA CONTROL
# =============================================================================

class MapControl(BaseModel):
    """Camera commands for map animation."""
    fly_to: Optional[Dict[str, float]] = None  # {lat, lon, zoom}
    fit_bounds: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat] - "hug" the data
    padding: Optional[int] = 50  # Padding around fit_bounds in pixels
    pitch: Optional[float] = None  # 0 = top-down, 60 = 3D
    bearing: Optional[float] = None  # rotation
    duration: int = 2000  # animation ms
    active_layers: Optional[List[str]] = None


# =============================================================================
# STORYTELLING
# =============================================================================

class StoryChapter(BaseModel):
    """A segment of a scrollytelling narrative."""
    chapter_id: int
    title: str
    narrative: str
    map_control: MapControl


# =============================================================================
# API RESPONSE
# =============================================================================

class AgentResponse(BaseModel):
    """Complete response from Leo agent."""
    text: str
    new_layers: List[LayerData] = []
    aoi: Optional[Dict] = None
    map_control: Optional[MapControl] = None
    storyboard: Optional[List[StoryChapter]] = None
    plan: Optional[str] = None  # Display reasoning
    session_id: Optional[str] = None
    turn_number: Optional[int] = None


# =============================================================================
# API REQUEST/RESPONSE MODELS
# =============================================================================

class ChatRequest(BaseModel):
    """Incoming chat request from frontend."""
    message: str
    model: str = "gemini-3-flash-preview"
    matrix_mode: bool = False  # When True, restrict agent to Matrix tools only


class ChatResponse(BaseModel):
    """Outgoing chat response to frontend."""
    text: str
    layers: List[Dict] = []
    aoi: Optional[Dict] = None
    map_control: Optional[Dict] = None


# =============================================================================
# EXECUTION PLAN (Cursor-Style Planner)
# =============================================================================

class PlanStep(BaseModel):
    """
    A single step in the agent's execution plan.
    
    Displayed as a checklist item with nested logs underneath.
    """
    id: str                                                          # Unique step ID (e.g., "step_1")
    title: str                                                       # High-level goal (e.g., "Define Area of Interest")
    status: Literal['pending', 'running', 'completed', 'failed'] = 'pending'


# =============================================================================
# STREAMING EVENTS (SSE)
# =============================================================================

class StreamEvent(BaseModel):
    """
    Server-Sent Event for real-time streaming.
    
    Event Types:
        PLAN EVENTS (Cursor-Style Planner):
        - plan_init: Initialize the execution plan checklist
            data: List[PlanStep] - The full plan steps
        - plan_update: Update/replace future steps (dynamic re-planning)
            data: List[PlanStep] - Updated steps to merge
        - step_update: Update a specific step's status
            data: { id, status, title? } - Step ID and new status
        
        LOG EVENTS (Nested under active step):
        - log: A log message to nest under the current step
            data: { message, type? } - Log text and optional type
        - step_start: Tool execution started (spinner in UI)
            data: { step_id, message, tool_name, status: "running" }
        - step_complete: Tool execution completed (checkmark in UI)
            data: { step_id, message, tool_name, status: "done" | "error" }
        
        DATA EVENTS:
        - thought: Agent reasoning/status updates ("Analyzing request...", "Targeting Berlin...")
        - map_control: Camera/map commands (fly_to, pitch, bearing) - IMMEDIATE camera swoop
        - layer_update: Layer data as tools return results - data pops in live
        - area_insights: AI-generated descriptions for top area clusters
            data: { clusters: [], count: int, user_query: str }
        - cascade_complete: Cascade search finished with summary stats
            data: { res5_input, res5_output, res8_output, res10_output }
        - text_chunk: LLM text response tokens as they stream
        - error: Error messages
        - done: Stream complete signal
    """
    type: Literal[
        # Plan events
        "plan_init", "plan_update", "step_update",
        # Log events
        "log", "step_start", "step_complete",
        # Data events
        "thought", "map_control", "layer_update", "area_insights", "cascade_complete",
        "text_chunk", "error", "done"
    ]
    data: Any  # String for text/thought, Dict for control/layer/step, List for plan


# =============================================================================
# TOOL RESPONSE HELPER
# =============================================================================

def format_tool_response(layer: LayerData, success: bool = True) -> Dict[str, Any]:
    """
    Standardize tool responses for Gemini function calling.
    Use this in all tool_* wrapper functions.
    """
    return {
        "success": success,
        "layer_id": layer.layer_id,
        "type": layer.type,
        "count": len(layer.data) if isinstance(layer.data, list) else len(layer.data.get("features", [])),
        "data": layer.data,
        "viz_config": {
            "style": layer.viz_config.style,
            "color_scale": layer.viz_config.color_scale,
            "label": layer.viz_config.label,
        },
        "summary": layer.summary,
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_layer(
    layer_id: str,
    layer_type: str,
    data: Union[List, Dict],
    label: str,
    style: str = "symbol",
    color_scale: str = "viridis",
    summary: str = "",
) -> LayerData:
    """Quick helper to create a LayerData object."""
    return LayerData(
        layer_id=layer_id,
        type=layer_type,
        data=data,
        viz_config=VizConfig(style=style, color_scale=color_scale, label=label),
        summary=summary or f"{label} layer",
    )


def create_h3_layer(
    layer_id: str,
    data: List[Dict],
    label: str,
    color_scale: str = "magma",
    summary: str = "",
) -> LayerData:
    """Helper for H3 hexagon layers."""
    return LayerData(
        layer_id=layer_id,
        type="h3_grid",
        data=data,
        viz_config=VizConfig(style="extrusion", color_scale=color_scale, label=label),
        summary=summary or f"{label} H3 grid",
    )


def create_geojson_layer(
    layer_id: str,
    geojson: Dict,
    label: str,
    style: str = "symbol",
    color_scale: str = "plasma",
    summary: str = "",
) -> LayerData:
    """Helper for GeoJSON layers."""
    # Detect type from geometry
    features = geojson.get("features", [])
    if features:
        geom_type = features[0].get("geometry", {}).get("type", "Point")
        layer_type = {
            "Point": "geojson_point",
            "Polygon": "geojson_poly",
            "MultiPolygon": "geojson_poly",
            "LineString": "geojson_line",
        }.get(geom_type, "geojson_point")
    else:
        layer_type = "geojson_point"
    
    return LayerData(
        layer_id=layer_id,
        type=layer_type,
        data=geojson,
        viz_config=VizConfig(style=style, color_scale=color_scale, label=label),
        summary=summary or f"{label} layer",
    )
