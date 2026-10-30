"""
Leo Agent - CASCADE + DIEM SEARCH
==================================

Multi-mode search agent supporting:
- CASCADE: Multi-resolution H3 search using local London parquets
- DIEM: Dimension Insensitive Euclidean Metric similarity search

ARCHITECTURE:
1. Extract features from query (simple Gemini call)
2. Run cascade/DIEM search IMMEDIATELY with progressive streaming
3. Summarize results with Gemini AFTER search completes
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from pydantic import BaseModel

# Load env
load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent / ".env", override=True)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =============================================================================
# IMPORTS
# =============================================================================

from backend.schema import StreamEvent
from backend.gemini_client import GeminiClient
from backend.tools.tools_cascade_search import tool_cascade_search
from backend.tools.tools_diem_search import tool_diem_search

# =============================================================================
# FEATURE EXTRACTION PROMPT
# =============================================================================

EXTRACT_PROMPT = """Extract location search features from this query. Return JSON only.

Query: "{query}"

Return ONLY valid JSON like:
{{"summative_features": ["cafe", "pub"], "walking_green": ["park"], "walking_transit": [], "driving_must_haves": []}}

Rules:
- summative_features: POIs to count (cafe, pub, restaurant, shop, etc.)
- walking_green: Green spaces within walking distance (park, garden)  
- walking_transit: Transit within walking distance (subway, train, bus)
- driving_must_haves: Critical amenities within driving distance (hospital, university)
"""


class CascadeAgent:
    """Progressive cascade search agent - streams layers LIVE as they're computed."""
    
    def __init__(self):
        self.client = GeminiClient(model="gemini-3-flash-preview")
        logger.info(f"🦁 Cascade Agent initialized with model: {self.client.model}")
    
    def _extract_features(self, query: str) -> Dict[str, Any]:
        """Quick Gemini call to extract features from natural language."""
        try:
            response = self.client.call(
                prompt=EXTRACT_PROMPT.format(query=query),
                temperature=0.1,
            )
            if response.success and response.text:
                # Parse JSON from response
                text = response.text.strip()
                # Handle markdown code blocks
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                
                features = json.loads(text)
                logger.info(f"📝 Extracted features: {features}")
                return features
        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}, using defaults")
        
        # Default fallback - just use the query words
        words = query.lower().split()
        return {"summative_features": words[:3], "walking_green": [], "walking_transit": [], "driving_must_haves": []}
    
    async def stream_search(self, query: str) -> AsyncGenerator[StreamEvent, None]:
        """Stream cascade search with LIVE progressive layers."""
        
        yield StreamEvent(type="thought", data="🔬 Starting cascade search...")
        
        # Step 1: Extract features (fast)
        yield StreamEvent(type="thought", data="📝 Extracting features from query...")
        features = self._extract_features(query)
        
        yield StreamEvent(type="thought", data=f"Found features: {list(features.get('summative_features', []))}")
        
        # Step 2: Run cascade and stream layers LIVE
        yield StreamEvent(type="thought", data="🎯 Running cascade search...")
        
        collected_layers = []
        stage_count = 0
        
        # Call cascade - it's a generator!
        cascade_gen = tool_cascade_search(
            summative_features=features.get("summative_features", []),
            driving_must_haves=features.get("driving_must_haves"),
            walking_transit=features.get("walking_transit"),
            walking_green=features.get("walking_green"),
        )
        
        # Stream events LIVE as they come from the generator
        import types as pytypes
        if isinstance(cascade_gen, pytypes.GeneratorType):
            for event in cascade_gen:
                if isinstance(event, dict):
                    event_type = event.get("type")
                    logger.info(f"🎬 Agent received event: {event_type}")
            
                    if event_type == "layer_update":
                        layer_data = event.get("data", event)
                        collected_layers.append(layer_data)
                        stage_count += 1
                        
                        logger.info(f"🎬 LIVE: Emitting layer {stage_count}: {layer_data.get('layer_id')}")
                        yield StreamEvent(type="layer_update", data=layer_data)
                        
                        layer_id = layer_data.get("layer_id", "")
                        hex_data = layer_data.get("data", [])
                        
                        # =================================================================
                        # STAGE 1 (res5): 2D view, fit to res5 boundary
                        # =================================================================
                        if "res5" in layer_id and hex_data:
                            import h3
                            import math
                            all_boundary_lats = []
                            all_boundary_lons = []
                            
                            for item in hex_data:
                                hex_id = item.get("hex")
                                if hex_id:
                                    try:
                                        boundary = h3.cell_to_boundary(hex_id)
                                        for lat, lon in boundary:
                                            all_boundary_lats.append(lat)
                                            all_boundary_lons.append(lon)
                                    except:
                                        pass
                            
                            if all_boundary_lats and all_boundary_lons:
                                min_lat, max_lat = min(all_boundary_lats), max(all_boundary_lats)
                                min_lon, max_lon = min(all_boundary_lons), max(all_boundary_lons)
                                center_lat = (min_lat + max_lat) / 2
                                center_lon = (min_lon + max_lon) / 2
                                
                                lat_span = (max_lat - min_lat) * 1.25  # 25% buffer for stage 1
                                lon_span = (max_lon - min_lon) * 1.25
                                max_span = max(lat_span, lon_span * 0.6)
                                zoom = math.log2(360 / max_span) if max_span > 0 else 12
                                zoom = max(3, min(round(zoom, 1), 15))
                                
                                # 2D view for stage 1
                                import time
                                yield StreamEvent(type="map_control", data={
                                    "fly_to": {"lat": center_lat, "lon": center_lon, "zoom": zoom},
                                    "pitch": 0,  # 2D flat view
                                    "duration": 1500,
                                    "_ts": time.time()  # Unique timestamp for change detection
                                })
                        
                        # =================================================================
                        # STAGE 2 (res8): 2D view, fit to res8 results
                        # =================================================================
                        elif "res8" in layer_id and hex_data:
                            import h3
                            import math
                            all_boundary_lats = []
                            all_boundary_lons = []
                            
                            for item in hex_data:
                                hex_id = item.get("hex")
                                if hex_id:
                                    try:
                                        boundary = h3.cell_to_boundary(hex_id)
                                        for lat, lon in boundary:
                                            all_boundary_lats.append(lat)
                                            all_boundary_lons.append(lon)
                                    except:
                                        pass
                            
                            if all_boundary_lats and all_boundary_lons:
                                min_lat, max_lat = min(all_boundary_lats), max(all_boundary_lats)
                                min_lon, max_lon = min(all_boundary_lons), max(all_boundary_lons)
                                center_lat = (min_lat + max_lat) / 2
                                center_lon = (min_lon + max_lon) / 2
                                
                                lat_span = (max_lat - min_lat) * 1.3  # 30% padding for stage 2
                                lon_span = (max_lon - min_lon) * 1.3
                                max_span = max(lat_span, lon_span * 0.6)
                                zoom = math.log2(360 / max_span) if max_span > 0 else 12
                                zoom = max(3, min(round(zoom, 1), 15))
                                
                                # 2D view for stage 2 - zoom to fit res8 results
                                import time
                                yield StreamEvent(type="map_control", data={
                                    "fly_to": {"lat": center_lat, "lon": center_lon, "zoom": zoom},
                                    "pitch": 0,  # 2D flat view
                                    "duration": 1500,
                                    "_ts": time.time()  # Unique timestamp for change detection
                                })
                        
                        # =================================================================
                        # STAGE 4 (final): Switch to 3D, NO camera movement
                        # =================================================================
                        elif "final" in layer_id:
                            # Just tilt to 3D, keep current position
                            import time
                            yield StreamEvent(type="map_control", data={
                                "pitch": 50,  # 3D tilt
                                "duration": 800,
                                "_ts": time.time()  # Unique timestamp for change detection
                            })
                        
                        # LIVE delay - user sees each stage appear
                        await asyncio.sleep(2.0)
                        
                    elif event_type == "thought":
                        yield StreamEvent(type="thought", data=event.get("data", ""))
                    
                    elif event_type == "area_insights":
                        # Forward area insights to frontend for display
                        insights_data = event.get("data", {})
                        logger.info(f"🧠 Area insights: {insights_data.get('count', 0)} clusters")
                        yield StreamEvent(type="area_insights", data=insights_data)
                    
                    elif event_type == "cascade_complete":
                        # Forward completion event
                        summary = event.get("summary", {})
                        logger.info(f"✅ Cascade complete: {summary}")
                        yield StreamEvent(type="cascade_complete", data=summary)
        
        # Step 3: Summary text
        total_hexes = sum(len(l.get("data", [])) for l in collected_layers)
        yield StreamEvent(type="text_chunk", data=f"Found {total_hexes} candidate locations matching your criteria.")
        
        yield StreamEvent(type="done", data={"status": "complete"})


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(title="Leo Cascade Agent", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton agent
_agent = None

def get_agent():
    global _agent
    if _agent is None:
        _agent = CascadeAgent()
    return _agent


class SearchRequest(BaseModel):
    message: str
    model: str = "gemini-3-flash-preview"


class DiemRequest(BaseModel):
    lat: float
    lng: float
    top_k: int = 1000


@app.post("/stream-chat")
async def stream_chat(request: SearchRequest):
    """Stream cascade search results via SSE."""
    
    agent = get_agent()
    logger.info(f"🔬 Cascade search: {request.message[:60]}...")
    
    async def event_generator():
        try:
            async for event in agent.stream_search(request.message):
                event_data = {
                    "type": event.type,
                    "data": event.data
                }
                yield f"data: {json.dumps(event_data)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/stream-diem")
async def stream_diem(request: DiemRequest):
    """
    Stream DIEM similarity search results via SSE.
    
    DIEM (Dimension Insensitive Euclidean Metric) finds hexes
    globally that are most similar to the reference location
    across ALL feature dimensions (~1,956 columns).
    """
    logger.info(f"🎯 DIEM search: lat={request.lat}, lng={request.lng}, top_k={request.top_k}")
    
    async def event_generator():
        try:
            # DIEM tool is a generator
            import types as pytypes
            diem_gen = tool_diem_search(
                lat=request.lat,
                lng=request.lng,
                top_k=request.top_k
            )
            
            if isinstance(diem_gen, pytypes.GeneratorType):
                for event in diem_gen:
                    if isinstance(event, dict):
                        yield f"data: {json.dumps(event)}\n\n"
                        # Small delay for smooth streaming
                        await asyncio.sleep(0.1)
            
            # Send done event
            yield f"data: {json.dumps({'type': 'done', 'data': {'status': 'complete'}})}\n\n"
            
        except Exception as e:
            logger.error(f"DIEM stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "cascade+diem"}
