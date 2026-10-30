'use client';

import React, { useCallback, useRef, memo, useState } from 'react';
import DeckGL from '@deck.gl/react';
import { Map, NavigationControl, ScaleControl } from 'react-map-gl/mapbox';
import type { AgentLayer, AreaCluster } from '@/lib/types';
import type { MapViewState } from '@deck.gl/core';
import { useLayerFactory } from '@/hooks/useLayerFactory';
import { useCameraControl } from '@/hooks/useCameraControl';
import 'mapbox-gl/dist/mapbox-gl.css';

// =============================================================================
// CONFIGURATION
// =============================================================================

const FOG_CONFIG = {
  range: [0.5, 10] as [number, number],
  color: '#242B4B',
  'high-color': '#161B33',
  'horizon-blend': 0.2,
};

const TERRAIN_CONFIG = {
  source: 'mapbox-dem',
  exaggeration: 1.5,
};

// =============================================================================
// TYPES
// =============================================================================

interface DeckGLMapProps {
  layers: AgentLayer[];
  viewState: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch?: number;
    bearing?: number;
    transitionDuration?: number;
  };
  onViewStateChange: (vs: { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number }) => void;
  onHover: (info: { x: number; y: number; object?: Record<string, unknown>; layerId?: string }) => void;
  mapStyle: string;
  mapboxToken: string;
  focusGeometry?: GeoJSON.Geometry | null;
  hoveredCluster?: AreaCluster | null;
  onMapClick?: (lat: number, lng: number) => void;
  clickMode?: boolean;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function DeckGLMapInner({
  layers,
  viewState,
  onViewStateChange,
  onHover,
  mapStyle,
  mapboxToken,
  focusGeometry,
  onMapClick,
  clickMode = false,
}: DeckGLMapProps) {
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);

  // ==========================================================================
  // CUSTOM HOOKS
  // ==========================================================================
  
  // Layer factory hook - creates Deck.gl layers from AgentLayers
  const deckLayers = useLayerFactory(layers, focusGeometry);

  // Camera control hook - manages view state with transitions
  // Only use transitions when map is ready to avoid race conditions
  const camera = useCameraControl(
    mapReady ? viewState : { ...viewState, transitionDuration: undefined },
    {
      defaultPitch: 45,
      defaultBearing: 0,
      defaultTransition: 2000,
    }
  );

  // ==========================================================================
  // HANDLERS
  // ==========================================================================
  
  const handleViewStateChange = useCallback(({ viewState: vs }: { viewState: MapViewState }) => {
    camera.handleViewStateChange(
      {
        longitude: vs.longitude,
        latitude: vs.latitude,
        zoom: vs.zoom,
        pitch: vs.pitch ?? 45,
        bearing: vs.bearing ?? 0,
      },
      onViewStateChange
    );
  }, [camera, onViewStateChange]);

  const handleHover = useCallback((info: { x: number; y: number; object?: unknown; layer?: { id: string } }) => {
    onHover({
      x: info.x,
      y: info.y,
      object: info.object as Record<string, unknown> | undefined,
      layerId: info.layer?.id,
    });
  }, [onHover]);

  // Click handler for DIEM location selection
  const handleClick = useCallback((info: { coordinate?: [number, number] }) => {
    if (clickMode && onMapClick && info.coordinate) {
      const [lng, lat] = info.coordinate;
      onMapClick(lat, lng);
    }
  }, [clickMode, onMapClick]);

  const handleMapLoad = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    console.log('[DeckGLMap] Map loaded - ready for camera commands');

    if (!map.getSource('mapbox-dem')) {
      map.addSource('mapbox-dem', {
        type: 'raster-dem',
        url: 'mapbox://mapbox.mapbox-terrain-dem-v1',
        tileSize: 512,
        maxzoom: 14,
      });
    }
    map.setTerrain(TERRAIN_CONFIG);
    map.setFog(FOG_CONFIG);
    
    // Mark map as ready for camera transitions
    setMapReady(true);
  }, []);

  // ==========================================================================
  // RENDER
  // ==========================================================================
  return (
    <DeckGL
      viewState={camera.viewState}
      onViewStateChange={handleViewStateChange}
      controller={true}
      layers={deckLayers}
      onHover={handleHover}
      onClick={handleClick}
      getCursor={() => clickMode ? 'crosshair' : 'grab'}
      style={{ position: 'absolute', width: '100%', height: '100%' }}
    >
      <Map
        ref={(ref) => { mapRef.current = ref?.getMap() || null; }}
        mapStyle={mapStyle}
        mapboxAccessToken={mapboxToken}
        attributionControl={true}
        onLoad={handleMapLoad}
        projection={{ name: 'globe' }}
      >
        <NavigationControl position="top-right" />
        <ScaleControl position="bottom-right" />
      </Map>
    </DeckGL>
  );
}

// Memoized component for performance
export const DeckGLMap = memo(DeckGLMapInner);
export default DeckGLMap;