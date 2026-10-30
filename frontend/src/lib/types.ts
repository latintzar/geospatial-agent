// Leo Frontend Types
// =============================================================================
// BACKEND SCHEMA TYPES - Match Leo/backend/schema.py exactly
// =============================================================================

/**
 * Visualization configuration from backend - Unified Visual Design System
 * Matches VizConfig in schema.py
 * 
 * Each data category has a distinct visual signature:
 * - demographics: 3D Magma towers
 * - agriculture: Flat green terrain
 * - wealth: Flat viridis colors
 * - retail: 3D Inferno towers
 * - risk: Red/green symbols
 * - routes: Neon blue paths
 * - trade: Magenta sky arcs
 */
export type VizStyle = 'heatmap' | 'heatmap_blur' | 'contour' | 'choropleth' | 'symbol' | 'line' | 'extrusion' | 'fill' | 'circle' | 'arc' | 'icon';

export type ColorScale = 
  | 'magma'             // Demographics - Dark purple -> Bright yellow
  | 'viridis'           // Wealth - Blue -> Green -> Yellow
  | 'inferno'           // Retail Gravity - Black -> Red -> Yellow
  | 'plasma'            // POIs - Purple -> Orange -> Yellow
  | 'ylgn'              // Agriculture - Yellow -> Green
  | 'rdbu'              // Climate - Red -> Blue (diverging)
  | 'rdylgn'            // Risk sentiment - Red -> Yellow -> Green
  | 'neon_blue'         // Routes - Cyan glowing paths
  | 'neon_magenta'      // Trade - Magenta sky arcs
  | 'categorical_risk'  // Risk - Red (negative) / Green (positive)
  | 'categorical_poi';  // POIs - Blue (shop) / Red (competitor)

export interface VizConfig {
  // Core rendering strategy
  style: VizStyle;
  
  // Color theme (frontend maps to D3 interpolators)
  color_scale?: string;  // Uses ColorScale type values
  
  // Display label for legend
  label: string;
  
  // Key properties
  value_key?: string;           // Property key for values (default: 'value')
  property_key?: string;        // Legacy alias for value_key
  
  // 3D extrusion settings
  elevation_scale?: number;     // Height multiplier for 3D (default: 10.0)
  
  // Opacity (0-1)
  opacity?: number;             // Layer opacity (default: 0.8)
  
  // Coverage for H3 hexes (0.9 = gaps, 1.0 = solid)
  coverage?: number;            // Hex coverage (default: 0.9)
  
  // Symbol/circle settings
  radius?: number;              // Radius for symbols (pixels)
  stroke_width?: number;        // Line width
  stroke_color?: string;        // Line color (hex)
  
  // Arc settings (for trade flows)
  arc_width?: number;           // Arc line width (default: 3)
  
  // Heatmap blur settings (for honest cartography - statistical data)
  radius_pixels?: number;       // Blur radius in pixels (default: 30)
  intensity?: number;           // Heatmap intensity multiplier (default: 1.0)
  threshold?: number;           // Min value to render 0-1 (default: 0.05)
  
  // Contour settings (alternative to heatmap_blur)
  contour_bands?: number;       // Number of contour bands (default: 5)
  
  // Zoom range
  min_zoom?: number;
  max_zoom?: number;
}

/**
 * Layer data from backend tools
 * Matches LayerData in schema.py
 */
export interface LayerData {
  layer_id: string;
  type: 'h3_grid' | 'geojson_point' | 'geojson_line' | 'geojson_poly' | 'geojson_collection' | 'weighted_points';
  data: unknown;
  viz_config: VizConfig;
  summary?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Agent response from backend /chat endpoint
 * Matches AgentResponse in schema.py
 */
export interface AgentResponse {
  text: string;
  new_layers: LayerData[];
  aoi?: GeoJSON.Geometry | null;
  storyboard?: StoryChapter[] | null;
  map_control?: MapControl | null;  // Agent-driven camera commands
  suggested_actions?: string[];
  session_id: string;
  turn_number: number;
  tools_used: string[];
  model: string;
}

/**
 * Story chapter for narrative presentations
 * Matches StoryChapter in schema.py
 */
export interface StoryChapter {
  chapter_id: number;
  title: string;
  narrative: string;
  view_state: {
    lat: number;
    lon: number;
    zoom: number;
    pitch?: number;
    bearing?: number;
  };
  active_layers: string[];
  hidden_layers: string[];
}

/**
 * Map Control - Agent-driven camera commands (The Director Module)
 * Matches MapControl in schema.py
 * 
 * Allows the AI agent to control the map camera for cinematic experiences:
 * - fly_to: Navigate to a specific location
 * - pitch: Camera tilt (0 = 2D flat, 60 = 3D tilted)
 * - bearing: Camera rotation
 * - duration: Animation duration
 * - active_layers: Layers to make visible
 * - highlight_layer: Layer to emphasize
 */
export interface MapControl {
  fly_to?: { lat: number; lon: number; zoom?: number };
  pitch?: number;
  bearing?: number;
  duration?: number;
  active_layers?: string[];
  highlight_layer?: string;
}

// =============================================================================
// FRONTEND-SPECIFIC TYPES
// =============================================================================

/**
 * Agent Layer - Frontend representation of a layer for rendering
 * Enriched version of LayerData with frontend-specific properties
 * 
 * Layer Types (Unified Visual Design System):
 * - focus_mask: World minus AOI (void effect) - black 80% opacity
 * - boundary: AOI/region outlines - thick white line with glow
 * - buildings_3d: Extruded 3D buildings - grey/metallic
 * - overture_buildings: Overture Maps buildings - extruded grey
 * - h3: H3 hexagon grid - choropleth or extrusion
 * - trade: Trade flows - animated 3D arcs (magenta->blue)
 * - arc: Generic arc layer
 * - route: Path/route lines - neon blue glow
 * - points: Scatter plot symbols
 */
export type AgentLayerType = 
  | 'h3' 
  | 'h3_grid'
  | 'h3_hexagon'       // Crisp hexagon style (discrete data)
  | 'heatmap'          // Blurred heatmap (continuous data)
  | 'geojson' 
  | 'points' 
  | 'route' 
  | 'geometry' 
  | 'info' 
  | 'population_h3' 
  | 'extrusion' 
  | 'building_density' 
  | 'buildings' 
  | 'weighted_points'
  | 'focus_mask'       // Void effect - world minus AOI
  | 'boundary'         // AOI boundary with thick white line
  | 'buildings_3d'     // Extruded 3D buildings
  | 'overture_buildings'
  | 'trade'            // Trade flow arcs
  | 'arc';             // Generic arc layer

export interface AgentLayer {
  id: string;
  name: string;
  type: AgentLayerType;
  data: H3Data[] | GeoJSON.FeatureCollection | GeoJSON.Feature | PointData[] | GeometryData | PopulationData | WeightedPointData[] | BuildingData[] | TradeFlowData[] | Record<string, unknown>;
  color: string;
  visible: boolean;
  vizConfig?: VizConfig;  // Original viz config from backend
  metadata?: {
    source?: string;
    timestamp?: string;
    unit?: string;
    source_resolution_m?: number;  // For honest cartography metadata
    [key: string]: unknown;
  };
}

/**
 * Geometry data from boundary lookups
 */
export interface GeometryData {
  geometry: GeoJSON.Geometry;
  bbox?: [number, number, number, number];
  display_name?: string;
  address?: Record<string, string>;
  [key: string]: unknown;
}

/**
 * H3 hexagon data from backend
 */
export interface H3Data {
  hex: string;
  value?: number;
  count?: number;
  waste_mt?: number;
  rwi_score?: number;
  [key: string]: unknown;
}

/**
 * Point data (news, POIs, etc.)
 */
export interface PointData {
  lat: number;
  lng: number;
  name?: string;
  properties?: Record<string, unknown>;
}

/**
 * Weighted point data for heatmap blur visualization (Honest Cartography)
 * Used for statistical/aggregated data that shouldn't imply false precision
 */
export interface WeightedPointData {
  lat: number;
  lng?: number;
  lon?: number;
  weight: number;
  [key: string]: unknown;
}

/**
 * Building data for 3D extruded buildings (Overture/OSM)
 */
export interface BuildingData {
  polygon: number[][];  // Polygon coordinates
  height?: number;      // Building height in meters
  num_floors?: number;  // Alternative to height
  name?: string;
  building_type?: string;
  [key: string]: unknown;
}

/**
 * Trade flow data for arc visualization
 */
export interface TradeFlowData {
  source_lat: number;
  source_lon: number;
  target_lat: number;
  target_lon: number;
  value?: number;       // Trade volume
  commodity?: string;   // What's being traded
  [key: string]: unknown;
}

/**
 * Population data from demographics tools
 */
export interface PopulationData {
  boundary?: GeometryData;
  population?: H3Data[];
  country_iso3?: string;
  metadata?: {
    bbox?: [number, number, number, number];
    resolution?: number;
    hex_count?: number;
    total_population?: number;
    data_source?: string;
    [key: string]: unknown;
  };
}

/**
 * Chat message
 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  layers?: string[];  // IDs of layers this message generated
  rawResponse?: Record<string, unknown>;  // Raw JSON response for debugging
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>;  // Tool calls made
}

/**
 * Backend layer data (individual layer info)
 */
export interface BackendLayerData {
  name: string;
  type: string;
  data: unknown;
  count?: number;
  timestamp?: string;
  error?: string;
}

/**
 * Backend layer info (as stored in the dict)
 */
export interface BackendLayerInfo {
  data: unknown;
  type: string;
  timestamp?: string;
  args?: Record<string, unknown>;
  error?: string;
  count?: number;  // Optional count of features
}

/**
 * New LayerData format (v3)
 */
export interface BackendLayerDataV3 {
  layer_id: string;
  type: string;
  data: unknown;
  viz_config: VizConfig;
  summary: string;
  metadata?: Record<string, unknown>;
}

/**
 * Backend chat response (supports both v2 legacy and v3 new format)
 * v3: uses new_layers array
 * v2: uses layers dict (legacy streaming)
 */
export interface BackendChatResponse {
  text: string;
  // v3 format - new /chat endpoint
  new_layers?: BackendLayerDataV3[];
  // v2 format - legacy streaming endpoint
  layers?: Record<string, BackendLayerInfo>;
  // Common fields
  aoi?: GeoJSON.Geometry | null;
  storyboard?: Record<string, unknown> | null;
  map_control?: MapControl | null;  // Agent-driven camera commands
  suggested_actions?: string[];
  session_id?: string;
  turn_number?: number;
  tools_used: string[];
  model: string;
  debug?: {
    raw_response?: string;
    tokens_used?: number;
    iterations?: number;
    errors?: string[];
    warnings?: string[];
  };
}

/**
 * Map view state
 */
export interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch?: number;
  bearing?: number;
  transitionDuration?: number;
}

/**
 * Tooltip info for map hover
 */
export interface TooltipInfo {
  x: number;
  y: number;
  object: Record<string, unknown>;
  layerName: string;
}

/**
 * Tool call info for chat display
 */
export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  duration?: number;
  status?: 'running' | 'success' | 'error';
  startTime?: number;
}

/**
 * Streaming event types from the backend (Legacy format)
 */
export type StreamEventType = 'thinking' | 'tool_call' | 'tool_result' | 'text' | 'layers' | 'layer_added' | 'done' | 'error' | 'strategy';

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  message?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: string;
  status?: 'running' | 'success' | 'error';
  model?: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  data?: Record<string, BackendLayerInfo>;
  tools_used?: string[];
  // For 'done' event - final response with layers
  text?: string;
  layers?: BackendLayerDataV3[];  // v3 format: layer_id, type, data, viz_config, summary
  iterations?: number;
  map_control?: MapControl;  // Agent camera commands
  // For 'layer_added' event - summary notification
  layer_type?: string;
  count?: number;
  // For 'strategy' event - matched playbook
  title?: string;
  score?: number;
}

/**
 * SSE Event Types (New streaming format - matches backend/schema.py StreamEvent)
 * Used by useLeoClient hook for real-time streaming
 * 
 * The agent drives the UI incrementally:
 * - plan_init: Initialize execution plan checklist
 * - plan_update: Update/replace plan steps (dynamic re-planning)
 * - step_update: Update a specific step's status
 * - log: Log message nested under current step
 * - thought: Status updates ("Analyzing...", "Fetching MapSPAM...")
 * - map_control: Camera fly_to IMMEDIATELY when AOI is set
 * - layer_update: Heatmaps/points pop in as tools return
 * - text_chunk: LLM explanation tokens stream in
 */
export type SSEEventType = 
  | 'plan_init'      // Initialize execution plan
  | 'plan_update'    // Update/replace plan steps
  | 'step_update'    // Update step status
  | 'log'            // Log nested under current step
  | 'step_start'     // Tool execution started
  | 'step_complete'  // Tool execution completed
  | 'thought' 
  | 'map_control' 
  | 'layer_update' 
  | 'text_chunk' 
  | 'error' 
  | 'done';

export interface SSEEvent {
  type: SSEEventType;
  data: unknown;  // String for text/thought, Dict for control/layer
}

/**
 * map_control event - Camera commands (fly_to IMMEDIATELY)
 */
export interface SSEMapControlEvent {
  fly_to?: { lat: number; lon: number; zoom?: number };
  pitch?: number;
  bearing?: number;
  duration?: number;
  bbox?: [number, number, number, number];
}

/**
 * layer_update event - Layer data as tools return
 */
export interface SSELayerUpdateEvent {
  layer_type?: string;
  feature_count?: number;
  count?: number;
  data?: unknown;
  geojson?: unknown;
  layer_id?: string;
}

/**
 * done event metadata
 */
export interface SSEDoneEvent {
  session_id?: string;
  turn_number?: number;
  layers_count?: number;
  model?: string;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/**
 * Thought log entry for tracking agent thinking process
 */
export interface ThoughtLogEntry {
  id: string;
  timestamp: Date;
  message: string;
  type: 'thought' | 'tool' | 'error';
}

// =============================================================================
// EXECUTION PLAN TYPES (Cursor-Style Planner)
// =============================================================================

/**
 * Status of a plan step
 */
export type PlanStepStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * A log entry nested under a plan step
 */
export interface PlanStepLog {
  id: string;
  message: string;
  type: 'tool_start' | 'success' | 'error' | 'thinking';
  timestamp: Date;
}

/**
 * A single step in the agent's execution plan.
 * 
 * Displayed as a checklist item with nested logs underneath.
 * This creates the "Cursor-style" planner effect where you see
 * the checklist and can expand each step to see detailed logs.
 */
export interface PlanStep {
  id: string;                      // Unique step ID (e.g., "step_1")
  title: string;                   // High-level goal (e.g., "Define Area of Interest")
  status: PlanStepStatus;          // Current status
  logs: PlanStepLog[];             // CRITICAL: Logs live inside the step
  startTime?: number;              // When this step started (timestamp)
  endTime?: number;                // When this step completed (timestamp)
}

/**
 * The complete planner state
 */
export interface PlannerState {
  plan: PlanStep[];                // The execution plan steps
  isActive: boolean;               // Whether a plan is currently running
  currentStepId: string | null;    // ID of the currently active step
}

/**
 * Live streaming state for real-time UI updates
 */
export interface StreamingState {
  isStreaming: boolean;
  thinkingMessage: string;
  activeToolCalls: Array<{
    name: string;
    args: Record<string, unknown>;
    status: 'running' | 'success' | 'error';
    result?: string;
    startTime: number;
  }>;
  streamedText: string;
}

/**
 * Available Gemini models - MUST match backend/agent.py SUPPORTED_MODELS
 */
export const AVAILABLE_MODELS = [
  { id: 'gemini-3-flash-preview', name: 'Gemini 3 Flash', description: 'Fast & capable (default)' },
  { id: 'gemini-3-pro-preview', name: 'Gemini 3 Pro', description: 'Deep thinking' },
] as const;

export type ModelId = typeof AVAILABLE_MODELS[number]['id'];

/**
 * Modern iridescent/fluorescent color palette for map layers
 * Premium, vibrant colors that pop on dark backgrounds
 */
export const LAYER_COLORS = [
  '#00D4FF',  // Electric Cyan
  '#FF6B9D',  // Hot Magenta
  '#A855F7',  // Vivid Purple
  '#22D3EE',  // Neon Aqua
  '#F472B6',  // Pink Glow
  '#818CF8',  // Indigo Pulse
  '#34D399',  // Emerald Fluorescent
  '#FBBF24',  // Golden Amber
  '#F87171',  // Coral Flame
  '#C084FC',  // Lavender Electric
  '#2DD4BF',  // Teal Iridescent
  '#FB923C',  // Tangerine Glow
];

/**
 * Get a color for a layer based on index
 */
export const getLayerColor = (index: number): string => {
  return LAYER_COLORS[index % LAYER_COLORS.length];
};

// =============================================================================
// AREA INSIGHTS TYPES
// =============================================================================

/**
 * Column score info for an area cluster
 */
export interface ColumnScore {
  name: string;
  value: number;
  is_user: boolean;  // Whether user specifically requested this column
}

/**
 * Area Cluster - A group of adjacent H3 res8 hexagons with AI-generated description
 * 
 * Generated by the backend Area Insights Engine after cascade search.
 * Used for hover info cards on the map.
 */
export interface AreaCluster {
  clusterId: string;
  hexes: string[];  // H3 res8 hex IDs
  centroid: [number, number];  // [lng, lat]
  totalScore: number;
  description: string | null;  // AI-generated one-liner
  topColumns: ColumnScore[];  // User columns + top 10 bonus columns
}

/**
 * Area Insights event data from backend
 */
export interface AreaInsightsData {
  clusters: AreaCluster[];
  count: number;
  user_query: string;
}

/**
 * Hovered cluster state for info card display
 */
export interface HoveredClusterState {
  cluster: AreaCluster | null;
  position: { x: number; y: number } | null;
}

// =============================================================================
// DECK.GL SPECIFIC TYPES
// =============================================================================

/**
 * H3 hexagon with building/density data
 */
export interface H3BuildingData extends H3Data {
  count?: number;       // Number of buildings
  avg_height?: number;  // Average building height in meters
  volume?: number;      // Urban mass proxy (count × avg_height)
}

/**
 * Deck.gl layer configuration
 */
export interface DeckLayerConfig {
  id: string;
  type: 'H3HexagonLayer' | 'GeoJsonLayer' | 'ScatterplotLayer' | 'PathLayer' | 'ColumnLayer';
  data: unknown;
  visible: boolean;
  pickable: boolean;
  extruded?: boolean;       // For 3D extrusions
  getElevation?: (d: unknown) => number;
  getFillColor?: (d: unknown) => [number, number, number, number];
  getLineColor?: (d: unknown) => [number, number, number, number];
  opacity?: number;
  colorScale?: string;      // d3 color scale name
}

/**
 * Color scale presets for deck.gl visualization
 * Maps backend color_scale names to d3-scale-chromatic interpolators
 * 
 * Unified Visual Design System colors:
 * - magma: Demographics (3D towers)
 * - ylgn: Agriculture (flat green terrain)
 * - viridis: Wealth (flat diverging)
 * - inferno: Retail Gravity (3D towers)
 * - neon_blue: Routes (glowing paths)
 * - neon_magenta: Trade (sky arcs)
 * - categorical_risk: Risk events (red/green)
 */
export const COLOR_SCALE_MAP: Record<string, string> = {
  // Unified Visual Design System - Primary scales
  'magma': 'interpolateMagma',        // Demographics
  'viridis': 'interpolateViridis',    // Wealth
  'inferno': 'interpolateInferno',    // Retail
  'plasma': 'interpolatePlasma',      // POIs
  'ylgn': 'interpolateYlGn',          // Agriculture
  'rdbu': 'interpolateRdBu',          // Climate
  'rdylgn': 'interpolateRdYlGn',      // Risk sentiment
  
  // Custom neon scales (implemented in DeckGLMap)
  'neon_blue': 'custom_neon_blue',      // Routes
  'neon_magenta': 'custom_neon_magenta', // Trade
  
  // Categorical scales (implemented in DeckGLMap)
  'categorical_risk': 'custom_categorical_risk',  // Risk
  'categorical_poi': 'custom_categorical_poi',    // POI competitor
  
  // Legacy support
  'YlOrRd': 'interpolateYlOrRd',
  'YlGn': 'interpolateYlGn',
  'YlGnBu': 'interpolateYlGnBu',
  'oranges': 'interpolateOranges',
  'reds': 'interpolateReds',
  'blues': 'interpolateBlues',
  'greens': 'interpolateGreens',
  'purples': 'interpolatePurples',
  'RdYlGn': 'interpolateRdYlGn',
  'RdYlBu': 'interpolateRdYlBu',
  'RdBu': 'interpolateRdBu',
  'spectral': 'interpolateSpectral',
};

/**
 * Default viz style for data categories - Unified Visual Design System
 * 
 * HONEST CARTOGRAPHY PRINCIPLE:
 * - SHARP = Actual geometry (buildings, POIs, routes, boundaries)
 * - BLUR = Statistical estimates (population, wealth, agriculture, retail)
 * 
 * | Category     | Style        | Color Scale | Visual Signature          |
 * |--------------|--------------|-------------|---------------------------|
 * | demographics | heatmap_blur | magma       | Blurred population clouds |
 * | agriculture  | heatmap_blur | ylgn        | Blurred crop intensity    |
 * | wealth       | heatmap_blur | viridis     | Blurred wealth gradient   |
 * | retail       | heatmap_blur | inferno     | Blurred commercial heat   |
 * | places       | symbol       | plasma      | SHARP dots (actual POIs)  |
 * | risk         | symbol       | categorical | SHARP symbols (events)    |
 * | routes       | line         | neon_blue   | SHARP paths (actual roads)|
 * | trade        | arc          | neon_magenta| Stylized arcs             |
 * | buildings    | fill         | magma       | SHARP polygons (actual)   |
 * | boundaries   | line         | neon_blue   | SHARP outlines (actual)   |
 */
export const DEFAULT_VIZ_STYLES: Record<string, Partial<VizConfig>> = {
  // BLURRED: Statistical/aggregated data (Honest Cartography)
  demographics: { style: 'heatmap_blur', color_scale: 'magma', opacity: 0.8, radius_pixels: 30, intensity: 1.0 },
  agriculture: { style: 'heatmap_blur', color_scale: 'ylgn', opacity: 0.75, radius_pixels: 40, intensity: 1.0 },
  wealth: { style: 'heatmap_blur', color_scale: 'viridis', opacity: 0.7, radius_pixels: 35, intensity: 1.0 },
  retail: { style: 'heatmap_blur', color_scale: 'inferno', opacity: 0.8, radius_pixels: 25, intensity: 1.2 },
  climate: { style: 'heatmap_blur', color_scale: 'rdbu', opacity: 0.6, radius_pixels: 50, intensity: 0.8 },
  building_density: { style: 'heatmap_blur', color_scale: 'magma', opacity: 0.75, radius_pixels: 25, intensity: 1.0 },
  affluence: { style: 'heatmap_blur', color_scale: 'viridis', opacity: 0.75, radius_pixels: 30, intensity: 1.0 },
  
  // SHARP: Actual geometry (precise locations/shapes)
  places: { style: 'symbol', color_scale: 'plasma', opacity: 0.9, radius: 6 },
  risk: { style: 'symbol', color_scale: 'categorical_risk', opacity: 0.95, radius: 8 },
  development: { style: 'symbol', color_scale: 'ylgn', opacity: 0.9, radius: 7 },
  routes: { style: 'line', color_scale: 'neon_blue', opacity: 0.9, stroke_width: 4 },
  trade: { style: 'arc', color_scale: 'neon_magenta', opacity: 0.85, arc_width: 3 },
  boundaries: { style: 'line', color_scale: 'neon_blue', opacity: 1.0, stroke_width: 3 },
  buildings: { style: 'fill', color_scale: 'magma', opacity: 0.8, stroke_width: 1 },
  hdx: { style: 'symbol', color_scale: 'plasma', opacity: 0.9, radius: 5 },
  
  // Layer types
  weighted_points: { style: 'heatmap_blur', color_scale: 'magma', opacity: 0.8, radius_pixels: 30 },
  h3_grid: { style: 'heatmap_blur', color_scale: 'viridis' },  // Changed to blur
  geojson_point: { style: 'symbol', color_scale: 'plasma' },
  geojson_line: { style: 'line', color_scale: 'neon_blue' },
  geojson_poly: { style: 'fill', color_scale: 'viridis' },
};

