'use client';

import { useState, useCallback, useRef } from 'react';
import type { AgentLayer, ViewState, VizConfig } from '@/lib/types';
import { getLayerColor } from '@/lib/types';

// =============================================================================
// TYPES
// =============================================================================

export interface DiemReference {
  hex: string;
  lat: number;
  lng: number;
  description?: string;  // AI-generated vibe description
  starter_pack?: string;  // AI-generated meme description  
  top_scores?: Array<{ column: string; value: number }>;
}

export interface DiemStats {
  total_hexes: number;
  feature_dimensions: number;
  top_k: number;
  mean_similarity: number;
  max_similarity: number;
  min_similarity: number;
}

export interface DiemResult {
  reference: DiemReference;
  stats: DiemStats;
}

export interface UseDiemSearchReturn {
  // State
  isSearching: boolean;
  result: DiemResult | null;
  error: string | null;
  layers: AgentLayer[];
  viewState: ViewState;
  statusMessage: string;
  
  // Actions
  search: (lat: number, lng: number, topK?: number) => Promise<void>;
  clearResults: () => void;
  setViewState: (vs: ViewState | ((prev: ViewState) => ViewState)) => void;
  setSelectedLocation: (lat: number, lng: number) => void;  // Show pin on map
}

// =============================================================================
// BACKEND API URL
// =============================================================================

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// =============================================================================
// HOOK: useDiemSearch
// =============================================================================

export function useDiemSearch(): UseDiemSearchReturn {
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<DiemResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<AgentLayer[]>([]);
  const [statusMessage, setStatusMessage] = useState('');
  const [viewState, setViewState] = useState<ViewState>({
    longitude: 0,
    latitude: 30,
    zoom: 2,
    pitch: 0,
    bearing: 0,
  });
  
  const abortControllerRef = useRef<AbortController | null>(null);

  // Clear all results
  const clearResults = useCallback(() => {
    setResult(null);
    setError(null);
    setLayers([]);
    setStatusMessage('');
  }, []);

  // Show pin on map when location is selected (before search)
  const setSelectedLocation = useCallback((lat: number, lng: number) => {
    // Create marker layer for the clicked location
    const pinLayer: AgentLayer = {
      id: 'diem_selected_pin',
      name: '📍 Selected Location',
      type: 'points',
      data: [{ lat, lng, name: 'Selected Point' }],
      color: '#A855F7',  // Violet
      visible: true,
      metadata: { source: 'diem_selection' },
    };
    
    // Only add the pin layer, preserve any existing result layers
    setLayers(prev => {
      const filtered = prev.filter(l => l.id !== 'diem_selected_pin' && l.id !== 'diem_click_marker');
      return [pinLayer, ...filtered];
    });
  }, []);

  // Run DIEM search
  const search = useCallback(async (lat: number, lng: number, topK: number = 1000) => {
    // Cancel any existing search
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    // Reset state
    setIsSearching(true);
    setError(null);
    setResult(null);
    setStatusMessage('🎯 Starting DIEM search...');
    
    // Add immediate marker layer showing clicked location
    const clickMarker: AgentLayer = {
      id: 'diem_click_marker',
      name: '📍 Selected Location',
      type: 'points',
      data: [{ lat, lng: lng, name: 'Reference Point' }],
      color: '#A855F7',  // Violet
      visible: true,
      metadata: { source: 'diem_click' },
    };
    setLayers([clickMarker]);

    try {
      // Make SSE request
      const response = await fetch(`${API_URL}/stream-diem`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lng, top_k: topK, method: 'diem' }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('No response body');
      }

      // Stream reader
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let layerCount = 0;

      // Process stream
      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          console.log('[DIEM] Stream complete');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event = JSON.parse(jsonStr);
            console.log('[DIEM Event]', event.type, event.data);

            switch (event.type) {
              case 'thought': {
                setStatusMessage(event.data as string);
                break;
              }

              case 'layer_update': {
                const layerData = event.data;
                const newLayer: AgentLayer = {
                  id: layerData.layer_id,
                  name: (layerData.viz_config as VizConfig)?.label || layerData.layer_id,
                  type: layerData.type === 'h3_grid' ? 'h3' : 'geojson',
                  data: layerData.data,
                  color: getLayerColor(layerCount++),
                  visible: true,
                  vizConfig: layerData.viz_config,
                  metadata: { source: 'diem' },
                };
                setLayers(prev => {
                  const existingIdx = prev.findIndex(l => l.id === newLayer.id);
                  if (existingIdx >= 0) {
                    const updated = [...prev];
                    updated[existingIdx] = newLayer;
                    return updated;
                  }
                  return [...prev, newLayer];
                });
                break;
              }

              case 'map_control': {
                const control = event.data;
                
                if (control.fit_bounds) {
                  // FIT BOUNDS: Calculate optimal zoom to show all results
                  const [minLon, minLat, maxLon, maxLat] = control.fit_bounds;
                  const centerLat = (minLat + maxLat) / 2;
                  const centerLon = (minLon + maxLon) / 2;
                  
                  // Calculate zoom based on bounds size
                  const latDiff = maxLat - minLat;
                  const lonDiff = maxLon - minLon;
                  const maxDiff = Math.max(latDiff, lonDiff);
                  
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
                    pitch: control.pitch ?? 0,
                    bearing: control.bearing ?? 0,
                    transitionDuration: control.duration || 2000,
                  }));
                } else if (control.fly_to) {
                  setViewState(prev => ({
                    ...prev,
                    latitude: control.fly_to.lat,
                    longitude: control.fly_to.lon,
                    zoom: control.fly_to.zoom ?? prev.zoom,
                    pitch: control.pitch ?? prev.pitch,
                    bearing: control.bearing ?? prev.bearing,
                    transitionDuration: control.duration || 2000,
                  }));
                } else {
                  // Partial update (pitch/bearing only)
                  setViewState(prev => ({
                    ...prev,
                    ...(control.pitch !== undefined && { pitch: control.pitch }),
                    ...(control.bearing !== undefined && { bearing: control.bearing }),
                    transitionDuration: control.duration || 1000,
                  }));
                }
                break;
              }

              case 'diem_complete': {
                const data = event.data;
                console.log('[DIEM Complete]', {
                  success: data.success,
                  hasVibe: !!data.reference?.description,
                  vibePreview: data.reference?.description?.slice(0, 50),
                  hasStarterPack: !!data.reference?.starter_pack,
                  starterPackPreview: data.reference?.starter_pack?.slice(0, 50),
                });
                if (data.success) {
                  setResult({
                    reference: data.reference,
                    stats: data.stats,
                  });
                  setStatusMessage(data.message || 'Search complete');
                }
                break;
              }

              case 'error': {
                setError(event.data as string);
                setStatusMessage(`Error: ${event.data}`);
                break;
              }

              case 'done': {
                setStatusMessage('Complete');
                break;
              }
            }
          } catch (parseError) {
            console.error('[DIEM Parse Error]', parseError, jsonStr);
          }
        }
      }

    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        console.log('[DIEM] Search aborted');
        return;
      }
      
      console.error('[DIEM Error]', err);
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMsg);
      setStatusMessage(`Error: ${errorMsg}`);
    } finally {
      setIsSearching(false);
    }
  }, []);

  return {
    isSearching,
    result,
    error,
    layers,
    viewState,
    statusMessage,
    search,
    clearResults,
    setViewState,
    setSelectedLocation,
  };
}

export default useDiemSearch;

