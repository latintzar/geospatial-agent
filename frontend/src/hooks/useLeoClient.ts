'use client';
import exampleResults from '@/lib/example-results.json';

import { useState, useCallback, useRef } from 'react';
import type { 
  ChatMessage, 
  AgentLayer, 
  ViewState, 
  ModelId,
  VizConfig,
  BackendLayerDataV3,
  PlanStepLog,
  PlanStepStatus,
  AreaCluster,
  AreaInsightsData,
} from '@/lib/types';
import { getLayerColor } from '@/lib/types';

// =============================================================================
// SSE EVENT TYPES (Match backend/schema.py StreamEvent)
// =============================================================================

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
  | 'area_insights'  // Area insights with cluster descriptions
  | 'text_chunk' 
  | 'error' 
  | 'done';

export interface SSEEvent {
  type: SSEEventType;
  data: unknown;  // String for text/thought, Dict for control/layer
}

// =============================================================================
// PLAN TYPES (Cursor-Style Planner with Nested Logs)
// =============================================================================

export interface PlanStep {
  id: string;
  title: string;
  status: PlanStepStatus;
  logs: PlanStepLog[];
  startTime?: number;
  endTime?: number;
}

export interface PlanInitEvent {
  id: string;
  title: string;
  status: PlanStepStatus;
}

export interface StepUpdateEvent {
  id: string;
  status: PlanStepStatus;
  title?: string;
}

export interface LogEvent {
  message: string;
  plan_step_id: string;
  type?: 'tool_start' | 'success' | 'error' | 'thinking';
}

// =============================================================================
// PROCESS STEP TYPES (Real-Time Agent Actions Display - Legacy)
// =============================================================================

export type ProcessStepStatus = 'pending' | 'running' | 'done' | 'error';

export interface ProcessStep {
  id: string;
  message: string;
  status: ProcessStepStatus;
  toolName?: string;
  timestamp: Date;
}

export interface StepStartEvent {
  step_id: string;
  message: string;
  tool_name?: string;
  status: 'running';
}

export interface StepCompleteEvent {
  step_id: string;
  message: string;
  tool_name?: string;
  status: 'done' | 'error';
}

export interface ThoughtLogEntry {
  id: string;
  timestamp: Date;
  message: string;
  type: 'thought' | 'tool' | 'error';
}

export interface MapControlEvent {
  fly_to?: { lat: number; lon: number; zoom?: number };
  fit_bounds?: [number, number, number, number];  // [min_lon, min_lat, max_lon, max_lat]
  padding?: number;
  pitch?: number;
  bearing?: number;
  duration?: number;
  bbox?: [number, number, number, number];
}

export interface LayerUpdateEvent {
  layer_type?: string;
  feature_count?: number;
  count?: number;
  data?: unknown;
  geojson?: unknown;
  layer_id?: string;
}

// =============================================================================
// BACKEND API URL
// =============================================================================

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// =============================================================================
// LAYER PARSING UTILITIES
// =============================================================================

/**
 * Parse streaming layer_update event into AgentLayer format
 */
function parseStreamingLayer(
  layerUpdate: LayerUpdateEvent,
  existingLayerCount: number
): AgentLayer | null {
  const colorIndex = existingLayerCount;
  const timestamp = Date.now();
  
  // Handle GeoJSON FeatureCollection (from layer_update with geojson field)
  const geojsonData = layerUpdate.geojson || layerUpdate.data;
  if (geojsonData && typeof geojsonData === 'object' && 'features' in (geojsonData as Record<string, unknown>)) {
    const geojson = geojsonData as { features: unknown[]; type?: string };
    return {
      id: `stream-geojson-${timestamp}`,
      name: `Features (${layerUpdate.feature_count || geojson.features?.length || 0})`,
      type: 'geojson',
      data: geojson,
      color: getLayerColor(colorIndex),
      visible: true,
      metadata: { source: 'stream', timestamp: new Date().toISOString() },
    };
  }
  
  // Handle H3 grid data (heatmaps)
  if (layerUpdate.layer_type === 'h3_grid' && Array.isArray(layerUpdate.data)) {
    return {
      id: `stream-h3-${timestamp}`,
      name: `H3 Grid (${layerUpdate.count || (layerUpdate.data as unknown[]).length})`,
      type: 'h3',
      data: layerUpdate.data,
      color: getLayerColor(colorIndex),
      visible: true,
      metadata: { source: 'stream', timestamp: new Date().toISOString() },
    };
  }
  
  // Handle points data (markers)
  if (layerUpdate.layer_type === 'points' && Array.isArray(layerUpdate.data)) {
    return {
      id: `stream-points-${timestamp}`,
      name: `Points (${layerUpdate.count || (layerUpdate.data as unknown[]).length})`,
      type: 'points',
      data: layerUpdate.data,
      color: getLayerColor(colorIndex),
      visible: true,
      metadata: { source: 'stream', timestamp: new Date().toISOString() },
    };
  }
  
  // Handle v3 LayerData format (layer_id present - from matrix/search tools)
  if (layerUpdate.layer_id) {
    const layerData = layerUpdate as unknown as BackendLayerDataV3;
    return {
      id: layerData.layer_id,
      name: (layerData.viz_config as VizConfig)?.label || layerData.layer_id,
      type: layerData.type === 'h3_grid' ? 'h3' : 
            layerData.type === 'geojson_point' ? 'points' :
            layerData.type === 'geojson_line' ? 'route' :
            layerData.type === 'geojson_poly' ? 'geometry' : 'geojson',
      data: layerData.data as AgentLayer['data'],
      color: getLayerColor(colorIndex),
      visible: true,
      vizConfig: layerData.viz_config as VizConfig,
      metadata: { 
        source: layerData.layer_id, 
        summary: layerData.summary,
        ...((layerData.metadata || {}) as Record<string, unknown>)
      },
    };
  }
  
  return null;
}

// =============================================================================
// CUSTOM HOOK: useLeoClient
// =============================================================================

export interface UseLeoClientReturn {
  // State
  messages: ChatMessage[];
  mapLayers: AgentLayer[];
  viewState: ViewState;
  thinkingLog: ThoughtLogEntry[];
  isThinking: boolean;
  currentMessage: string;
  statusMessage: string;  // Current "Processing..." status for status bar
  selectedModel: ModelId;
  processSteps: ProcessStep[];  // Real-time agent action steps (legacy)
  isRequestComplete: boolean;   // Track if request finished (for auto-collapse)
  
  // NEW: Cursor-Style Planner State
  planSteps: PlanStep[];         // The execution plan with nested logs
  currentPlanStepId: string | null;  // ID of currently active step
  isPlanActive: boolean;         // Whether a plan is currently running
  
  // NEW: Area Insights
  areaClusters: AreaCluster[];   // Area clusters with AI descriptions
  
  // Actions
  sendMessage: (text: string) => Promise<void>;
  setSelectedModel: (model: ModelId) => void;
  clearLayers: () => void;
  toggleLayer: (layerId: string) => void;
  setViewState: (viewState: ViewState | ((prev: ViewState) => ViewState)) => void;
  clearThinkingLog: () => void;
  clearProcessSteps: () => void;
  clearPlan: () => void;  // NEW: Clear plan
}

export const useLeoClient = (): UseLeoClientReturn => {
  // Core state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mapLayers, setMapLayers] = useState<AgentLayer[]>([]);
  const [viewState, setViewState] = useState<ViewState>({
    longitude: 0,
    latitude: 20,
    zoom: 2,
    pitch: 45,
    bearing: 0,
  });
  
  // Streaming state
  const [thinkingLog, setThinkingLog] = useState<ThoughtLogEntry[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [currentMessage, setCurrentMessage] = useState('');
  const [statusMessage, setStatusMessage] = useState('');  // "Processing...", "Fetching MapSPAM..."
  const [selectedModel, setSelectedModel] = useState<ModelId>('gemini-3-flash-preview');
  
  // Real-time process steps state (legacy)
  const [processSteps, setProcessSteps] = useState<ProcessStep[]>([]);
  const [isRequestComplete, setIsRequestComplete] = useState(false);
  
  // NEW: Cursor-Style Planner State
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [currentPlanStepId, setCurrentPlanStepId] = useState<string | null>(null);
  const [isPlanActive, setIsPlanActive] = useState(false);
  
  // NEW: Area Insights State
  const [areaClusters, setAreaClusters] = useState<AreaCluster[]>([]);
  
  // Refs for streaming - use refs to avoid stale closure issues
  const abortControllerRef = useRef<AbortController | null>(null);
  const layerCountRef = useRef(0);
  const mapLayersRef = useRef<AgentLayer[]>([]);
  
  // Keep ref in sync with state
  mapLayersRef.current = mapLayers;

  // ==========================================================================
  // ADD THOUGHT TO LOG
  // ==========================================================================
  const addThought = useCallback((message: string, type: ThoughtLogEntry['type'] = 'thought') => {
    const entry: ThoughtLogEntry = {
      id: `thought-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: new Date(),
      message,
      type,
    };
    setThinkingLog(prev => [...prev, entry]);
  }, []);

  // ==========================================================================
  // CLEAR THINKING LOG
  // ==========================================================================
  const clearThinkingLog = useCallback(() => {
    setThinkingLog([]);
  }, []);

  // ==========================================================================
  // CLEAR PROCESS STEPS
  // ==========================================================================
  const clearProcessSteps = useCallback(() => {
    setProcessSteps([]);
    setIsRequestComplete(false);
  }, []);

  // ==========================================================================
  // CLEAR PLAN (Cursor-Style Planner)
  // ==========================================================================
  const clearPlan = useCallback(() => {
    setPlanSteps([]);
    setCurrentPlanStepId(null);
    setIsPlanActive(false);
  }, []);


  // ==========================================================================
  // SEND MESSAGE - SSE Streaming with ReadableStream
  // ==========================================================================
  /**
   * Sends a message and consumes the SSE stream to update the map LIVE.
   * 
   * Key behaviors:
   * - map_control: IMMEDIATELY calls setViewState (flyTo). Does NOT wait.
   * - layer_update: APPENDS new layer to existing mapLayers (doesn't replace).
   * - text_chunk: Appends to chat text (typewriter effect).
   * - thought: Updates the status bar message.
   * 
   * This ensures that if Matrix takes 1s and Points takes 5s, the user
   * sees Matrix first while waiting for Points.
   */
  const sendMessage = useCallback(async (text: string) => {
    // Cancel any existing stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    // Add user message
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    
    // Public example: a retained result from the actual scorer on generated features.
    if (process.env.NEXT_PUBLIC_EXAMPLE_MODE === 'true') {
      const supported = ['find locations similar to covent garden', 'show synthetic retail location matches', 'explain the synthetic location example'].includes(text.trim().toLowerCase());
      if (supported) {
        setMapLayers([{ id: 'synthetic-retail', name: 'Synthetic similarity results', type: 'h3', data: exampleResults.similar_hexes, color: '#34d399', visible: true, metadata: { source: 'Generated example features; Leo scorer' } }]);
        setViewState({ longitude: -0.105, latitude: 51.515, zoom: 12, pitch: 0, bearing: 0, transitionDuration: 1800 });
      }
      setMessages(prev => [...prev, { id: `example-${Date.now()}`, role: 'assistant', content: supported ? '30 locations match the Covent Garden reference. Select a cell to inspect its score.' : 'Choose an example or connect your model in the source.', timestamp: new Date() }]);
      return;
    }

    // Reset streaming state
    setIsThinking(true);
    setCurrentMessage('');
    setStatusMessage('🔬 Cascade Search: Analyzing...');
    clearThinkingLog();
    clearProcessSteps();
    clearPlan();
    setIsRequestComplete(false);
    
    // Track layer count via ref (avoids stale closure)
    layerCountRef.current = mapLayersRef.current.length;
    
    // Collected layers and text during streaming
    const streamedLayers: AgentLayer[] = [];
    let streamedText = '';
    
    try {
      // ================================================================
      // INITIATE SSE FETCH with ReadableStream reader
      // ================================================================
      const response = await fetch(`${API_URL}/stream-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          model: selectedModel,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      // Get ReadableStream reader for streaming
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // ================================================================
      // THE STREAMING LOOP - Process events as they arrive
      // ================================================================
      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          console.log('[SSE] Stream complete');
          break;
        }

        // Decode chunk and add to buffer
        buffer += decoder.decode(value, { stream: true });
        
        // Process complete SSE lines (format: "data: {json}\n\n")
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;
          
          try {
            const event = JSON.parse(jsonStr) as SSEEvent;
            console.log('[SSE Event]', event.type, event.data);
            
            // ============================================================
            // EVENT HANDLERS - Each updates UI IMMEDIATELY
            // ============================================================
            switch (event.type) {
              
              // ----------------------------------------------------------
              // PLAN_INIT: Initialize the execution plan checklist
              // ----------------------------------------------------------
              case 'plan_init': {
                const planData = event.data as PlanInitEvent[];
                const initializedSteps: PlanStep[] = planData.map((step, idx) => ({
                  id: step.id,
                  title: step.title,
                  status: idx === 0 ? 'running' : 'pending',
                  logs: [],
                  startTime: idx === 0 ? Date.now() : undefined,
                }));
                setPlanSteps(initializedSteps);
                setCurrentPlanStepId(initializedSteps[0]?.id || null);
                setIsPlanActive(true);
                setStatusMessage(`Plan: ${initializedSteps.length} steps`);
                console.log('[SSE Plan Init]', initializedSteps);
                break;
              }
              
              // ----------------------------------------------------------
              // STEP_UPDATE: Update a plan step's status
              // ----------------------------------------------------------
              case 'step_update': {
                const updateData = event.data as StepUpdateEvent;
                setPlanSteps(prev => {
                  const updated = prev.map(step => {
                    if (step.id === updateData.id) {
                      return {
                        ...step,
                        status: updateData.status,
                        title: updateData.title || step.title,
                        endTime: updateData.status === 'completed' ? Date.now() : step.endTime,
                        startTime: updateData.status === 'running' ? Date.now() : step.startTime,
                      };
                    }
                    return step;
                  });
                  
                  // Update current step ID if this step is now running
                  if (updateData.status === 'running') {
                    setCurrentPlanStepId(updateData.id);
                  }
                  
                  return updated;
                });
                break;
              }
              
              // ----------------------------------------------------------
              // LOG: Add a log entry nested under the current plan step
              // ----------------------------------------------------------
              case 'log': {
                const logData = event.data as LogEvent;
                const newLog: PlanStepLog = {
                  id: `log-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
                  message: logData.message,
                  type: logData.type || 'thinking',
                  timestamp: new Date(),
                };
                
                // Add to the specified step or current step
                const targetStepId = logData.plan_step_id || currentPlanStepId;
                if (targetStepId) {
                  setPlanSteps(prev =>
                    prev.map(step =>
                      step.id === targetStepId
                        ? { ...step, logs: [...step.logs, newLog] }
                        : step
                    )
                  );
                }
                break;
              }
              
              // ----------------------------------------------------------
              // STEP_START: Add new step with 'running' status (spinner)
              // (Also adds as log to current plan step)
              // ----------------------------------------------------------
              case 'step_start': {
                const stepData = event.data as StepStartEvent;
                const newStep: ProcessStep = {
                  id: stepData.step_id,
                  message: stepData.message,
                  status: 'running',
                  toolName: stepData.tool_name,
                  timestamp: new Date(),
                };
                setProcessSteps(prev => [...prev, newStep]);
                setStatusMessage(stepData.message);  // Also update status bar
                break;
              }
              
              // ----------------------------------------------------------
              // STEP_COMPLETE: Update step status to 'done' (checkmark)
              // ----------------------------------------------------------
              case 'step_complete': {
                const stepData = event.data as StepCompleteEvent;
                setProcessSteps(prev =>
                  prev.map(step =>
                    step.id === stepData.step_id
                      ? { ...step, message: stepData.message, status: stepData.status }
                      : step
                  )
                );
                setStatusMessage(stepData.message);  // Update status bar
                break;
              }
              
              // ----------------------------------------------------------
              // THOUGHT: Update the status bar (e.g., "Fetching MapSPAM...")
              // ----------------------------------------------------------
              case 'thought': {
                const thoughtContent = event.data as string;
                setStatusMessage(thoughtContent);  // Update status bar
                addThought(thoughtContent, 'thought');  // Add to log
                break;
              }
              
              // ----------------------------------------------------------
              // MAP_CONTROL: IMMEDIATELY call setViewState - DO NOT WAIT
              // Camera starts moving while data is still being fetched
              // ----------------------------------------------------------
              case 'map_control': {
                const control = event.data as MapControlEvent;
                
                if (control.fit_bounds) {
                  // FIT BOUNDS: Camera "hugs" the data - calculates optimal zoom
                  const [minLon, minLat, maxLon, maxLat] = control.fit_bounds;
                  const centerLat = (minLat + maxLat) / 2;
                  const centerLon = (minLon + maxLon) / 2;
                  
                  // Calculate appropriate zoom level based on bounds size
                  const latDiff = maxLat - minLat;
                  const lonDiff = maxLon - minLon;
                  const maxDiff = Math.max(latDiff, lonDiff);
                  
                  // Rough zoom calculation (higher maxDiff = lower zoom)
                  let zoom = 10;
                  if (maxDiff > 5) zoom = 5;
                  else if (maxDiff > 2) zoom = 7;
                  else if (maxDiff > 1) zoom = 8;
                  else if (maxDiff > 0.5) zoom = 9;
                  else if (maxDiff > 0.2) zoom = 10;
                  else if (maxDiff > 0.1) zoom = 11;
                  else zoom = 12;
                  
                  setViewState(prev => ({
                    ...prev,
                    latitude: centerLat,
                    longitude: centerLon,
                    zoom: zoom,
                    pitch: control.pitch ?? 0,  // Top-down for heatmaps
                    bearing: control.bearing ?? 0,
                    transitionDuration: control.duration || 2000,
                  }));
                  addThought(`📷 Camera hug: fitting to ${(maxDiff * 111).toFixed(0)}km area`, 'tool');
                } else if (control.fly_to) {
                  // IMMEDIATE update - camera swoops to AOI now
                  console.log('[useLeoClient] fly_to received:', control.fly_to, 'zoom:', control.fly_to.zoom);
                  setViewState(prev => ({
                    ...prev,
                    latitude: control.fly_to!.lat,
                    longitude: control.fly_to!.lon,
                    zoom: control.fly_to!.zoom ?? prev.zoom,  // Use ?? instead of || to allow zoom=0
                    pitch: control.pitch ?? prev.pitch,
                    bearing: control.bearing ?? prev.bearing,
                    transitionDuration: control.duration || 2000,
                  }));
                  addThought(`📍 Flying to ${control.fly_to.lat.toFixed(2)}, ${control.fly_to.lon.toFixed(2)}`, 'tool');
                }
                break;
              }
              
              // ----------------------------------------------------------
              // LAYER_UPDATE: APPEND to mapLayers - don't replace whole list
              // Matrix arrives in 1s → shows immediately
              // Points arrive in 5s → pops in on top of Matrix
              // ----------------------------------------------------------
              case 'layer_update': {
                const layerEvent = event.data as LayerUpdateEvent;
                const layer = parseStreamingLayer(
                  layerEvent, 
                  layerCountRef.current + streamedLayers.length
                );
                if (layer) {
                  // UPDATE OR APPEND - replace if layer ID exists, else append
                  setMapLayers(prev => {
                    const existingIdx = prev.findIndex(l => l.id === layer.id);
                    if (existingIdx >= 0) {
                      // Replace existing layer (for progressive dimming)
                      const updated = [...prev];
                      updated[existingIdx] = layer;
                      addThought(`🔄 Updated layer: ${layer.name}`, 'tool');
                      return updated;
                    }
                    // Append new layer
                    streamedLayers.push(layer);
                    addThought(`📊 Added layer: ${layer.name}`, 'tool');
                    return [...prev, layer];
                  });
                  setStatusMessage(`${layer.name}`);
                }
                break;
              }
              
              // ----------------------------------------------------------
              // AREA_INSIGHTS: Store cluster descriptions for hover cards
              // ----------------------------------------------------------
              case 'area_insights': {
                const insightsData = event.data as AreaInsightsData;
                if (insightsData.clusters && insightsData.clusters.length > 0) {
                  setAreaClusters(insightsData.clusters);
                  addThought(`🧠 Generated insights for ${insightsData.count} areas`, 'tool');
                  setStatusMessage(`${insightsData.count} area insights ready`);
                }
                break;
              }
              
              // ----------------------------------------------------------
              // TEXT_CHUNK: Append to chat text (typewriter effect)
              // ----------------------------------------------------------
              case 'text_chunk': {
                const textContent = event.data as string;
                streamedText += textContent;
                setCurrentMessage(streamedText);
                break;
              }
              
              // ----------------------------------------------------------
              // ERROR: Log and show in status
              // ----------------------------------------------------------
              case 'error': {
                const errorContent = event.data as string;
                setStatusMessage(`Error: ${errorContent}`);
                addThought(`❌ Error: ${errorContent}`, 'error');
                console.error('[SSE Error]', errorContent);
                break;
              }
              
              // ----------------------------------------------------------
              // DONE: Stream complete - finalize
              // ----------------------------------------------------------
              case 'done': {
                const doneContent = event.data as Record<string, unknown>;
                console.log('[SSE Done]', doneContent);
                setStatusMessage('Complete');
                setIsRequestComplete(true);  // Trigger auto-collapse timer
                setIsPlanActive(false);      // Mark plan as inactive
                
                // Mark all plan steps as completed
                setPlanSteps(prev =>
                  prev.map(step => ({
                    ...step,
                    status: step.status === 'running' ? 'completed' : step.status,
                    endTime: step.status === 'running' ? Date.now() : step.endTime,
                  }))
                );
                
                addThought('✅ Complete', 'thought');
                break;
              }
            }
          } catch (parseError) {
            console.error('[SSE Parse Error]', parseError, jsonStr);
          }
        }
      }

      // Add assistant message with final text
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: streamedText || 'I processed your request.',
        timestamp: new Date(),
        layers: streamedLayers.map(l => l.id),
      };
      setMessages(prev => [...prev, assistantMessage]);

    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        console.log('[SSE] Stream aborted');
        return;
      }
      
      console.error('[SSE Error]', error);
      const errorMsg = error instanceof Error ? error.message : 'Unknown error';
      setStatusMessage(`Error: ${errorMsg}`);
      addThought(`❌ ${errorMsg}`, 'error');
      
      // Add error message to chat
      const errorMessage: ChatMessage = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Sorry, I encountered an error: ${errorMsg}. Make sure the backend is running at ${API_URL}.`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsThinking(false);
      setCurrentMessage('');
      setStatusMessage('');
    }
  }, [selectedModel, addThought, clearThinkingLog, clearProcessSteps, clearPlan, currentPlanStepId]);

  // ==========================================================================
  // LAYER CONTROLS
  // ==========================================================================
  const clearLayers = useCallback(() => {
    setMapLayers([]);
  }, []);

  const toggleLayer = useCallback((layerId: string) => {
    setMapLayers(prev =>
      prev.map(l => (l.id === layerId ? { ...l, visible: !l.visible } : l))
    );
  }, []);

  // ==========================================================================
  // RETURN
  // ==========================================================================
  return {
    // State
    messages,
    mapLayers,
    viewState,
    thinkingLog,
    isThinking,
    currentMessage,
    statusMessage,  // "Processing...", "Fetching MapSPAM...", etc.
    selectedModel,
    processSteps,      // Real-time agent action steps (legacy)
    isRequestComplete, // For auto-collapse
    
    // Cursor-Style Planner State
    planSteps,           // The execution plan with nested logs
    currentPlanStepId,   // ID of currently active step
    isPlanActive,        // Whether a plan is currently running
    
    // Area Insights
    areaClusters,        // Area clusters with AI descriptions
    
    // Actions
    sendMessage,
    setSelectedModel,
    clearLayers,
    toggleLayer,
    setViewState,
    clearThinkingLog,
    clearProcessSteps,
    clearPlan,           // Clear plan
  };
};

export default useLeoClient;
