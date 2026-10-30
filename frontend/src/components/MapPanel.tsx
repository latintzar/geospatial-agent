'use client';

import { useCallback, useState, useEffect, useRef, useMemo } from 'react';
import dynamic from 'next/dynamic';
import type { AgentLayer, ViewState, MapControl, TooltipInfo, AreaCluster } from '@/lib/types';
import { Eye, EyeOff, Layers, Box, Map as MapIcon } from 'lucide-react';
import { AreaInsightCard } from './AreaInsightCard';
import { useVoronoiHover } from '@/hooks/useVoronoiHover';

// =============================================================================
// CONSTANTS
// =============================================================================

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || ' '.trim();
const MAP_STYLE = { version: 8 as const, sources: { osm: { type: 'raster' as const, tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } }, layers: [{ id: 'osm', type: 'raster' as const, source: 'osm' }] };
const DEFAULT_PITCH = 45;
const DEFAULT_BEARING = -10;
const FLIGHT_DURATION = 2000;
const STREET_ZOOM_THRESHOLD = 14;
const CITY_ZOOM_THRESHOLD = 10;

/** Calculate context-aware pitch based on zoom level */
const getContextAwarePitch = (zoom: number): number => {
  if (zoom > STREET_ZOOM_THRESHOLD) return 45;
  if (zoom < CITY_ZOOM_THRESHOLD) return 0;
  const t = (zoom - CITY_ZOOM_THRESHOLD) / (STREET_ZOOM_THRESHOLD - CITY_ZOOM_THRESHOLD);
  return Math.round(t * 45);
};

// =============================================================================
// TYPES
// =============================================================================

interface MapPanelProps {
  layers: AgentLayer[];
  viewState: ViewState;
  onViewStateChange: (vs: ViewState) => void;
  onToggleLayer?: (layerId: string) => void;
  targetViewState?: ViewState;
  mapControl?: MapControl | null;
  focusGeometry?: GeoJSON.Geometry | null;
  areaClusters?: AreaCluster[];
  onMapClick?: (lat: number, lng: number) => void;
  clickMode?: boolean;
}

// Internal view state with required pitch/bearing (not optional like ViewState)
interface InternalViewState extends Omit<ViewState, 'pitch' | 'bearing'> {
  pitch: number;
  bearing: number;
}

// =============================================================================
// DYNAMIC IMPORTS - Prevents SSR WebGL errors
// =============================================================================

const DeckGLMap = dynamic(
  () => import('./DeckGLMap'),
  { ssr: false }
);

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function MapPanel({
  layers,
  viewState,
  onViewStateChange,
  onToggleLayer,
  targetViewState,
  mapControl,
  focusGeometry,
  areaClusters = [],
  onMapClick,
  clickMode = false,
}: MapPanelProps) {
  const [, setTooltipInfo] = useState<TooltipInfo | null>(null);
  const [is3DMode, setIs3DMode] = useState(true);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  
  // Area insights hover state
  const [hoveredCluster, setHoveredCluster] = useState<AreaCluster | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  
  // Track if we're currently executing an agent-controlled animation
  // This prevents auto-zoom from overriding director commands
  const [isAgentControlled, setIsAgentControlled] = useState(false);
  
  // Track previous mapControl to detect actual changes
  const prevMapControlRef = useRef<MapControl | null | undefined>(undefined);
  
  // ==========================================================================
  // Container size tracking for Voronoi calculation
  // ==========================================================================
  useEffect(() => {
    if (!containerRef.current) return;
    
    const updateSize = () => {
      if (containerRef.current) {
        setContainerSize({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };
    
    updateSize();
    
    const resizeObserver = new ResizeObserver(updateSize);
    resizeObserver.observe(containerRef.current);
    
    return () => resizeObserver.disconnect();
  }, []);
  
  // ==========================================================================
  // Projection function for Voronoi (lng,lat -> screen x,y)
  // Uses current viewState to project cluster centroids
  // ==========================================================================
  const projectToScreen = useCallback((lngLat: [number, number]): [number, number] => {
    const [lng, lat] = lngLat;
    const { width, height } = containerSize;
    
    if (width === 0 || height === 0) return [0, 0];
    
    // Simple Web Mercator projection relative to current view
    const scale = Math.pow(2, viewState.zoom) * 256;
    const worldX = (lng + 180) / 360 * scale;
    const worldY = (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * scale;
    
    const centerWorldX = (viewState.longitude + 180) / 360 * scale;
    const centerWorldY = (1 - Math.log(Math.tan(viewState.latitude * Math.PI / 180) + 1 / Math.cos(viewState.latitude * Math.PI / 180)) / Math.PI) / 2 * scale;
    
    const screenX = width / 2 + (worldX - centerWorldX);
    const screenY = height / 2 + (worldY - centerWorldY);
    
    return [screenX, screenY];
  }, [viewState.longitude, viewState.latitude, viewState.zoom, containerSize]);
  
  // ==========================================================================
  // Voronoi hover detection for area clusters
  // ==========================================================================
  const { findClusterAtPoint } = useVoronoiHover(areaClusters, {
    width: containerSize.width,
    height: containerSize.height,
    project: projectToScreen,
  });

  const [internalViewState, setInternalViewState] = useState<InternalViewState>({
    longitude: viewState.longitude,
    latitude: viewState.latitude,
    zoom: viewState.zoom,
    pitch: viewState.pitch || DEFAULT_PITCH,
    bearing: viewState.bearing || DEFAULT_BEARING,
  });

  // ==========================================================================
  // Extract focusGeometry from layers if not provided directly
  // ==========================================================================
  const derivedFocusGeometry = useMemo(() => {
    if (focusGeometry) return focusGeometry;
    
    // Look for AOI/boundary layer to extract focus geometry
    for (const layer of layers) {
      if (layer.visible && (
        layer.type === 'boundary' ||
        layer.id.includes('aoi') ||
        layer.id.includes('boundary') ||
        layer.type === 'geometry'
      )) {
        const data = layer.data as { geometry?: GeoJSON.Geometry } | GeoJSON.Feature | GeoJSON.FeatureCollection;
        
        if ('geometry' in data && data.geometry) {
          return data.geometry;
        }
        if ('features' in data && data.features?.[0]?.geometry) {
          return data.features[0].geometry;
        }
      }
    }
    
    return null;
  }, [focusGeometry, layers]);

  // ==========================================================================
  // 🎬 THE DIRECTOR - Agent-driven camera control (HIGHEST PRIORITY)
  // ==========================================================================
  useEffect(() => {
    if (!mapControl) {
      prevMapControlRef.current = mapControl;
      return;
    }
    
    // Always process map_control commands - timestamp ensures uniqueness
    // Update ref for tracking
    prevMapControlRef.current = mapControl;
    
    console.log('🎬 Director Command Received:', mapControl);
    
    // Mark that agent is controlling the camera
    setIsAgentControlled(true);
    
    // Use agent-specified duration or default to 2000ms for cinematic feel
    const duration = mapControl.duration ?? FLIGHT_DURATION;
    
    // Build the new view state based on mapControl commands
    setInternalViewState(prev => {
      const newState: InternalViewState = { ...prev, transitionDuration: duration };
      
      // fly_to - Navigate to a specific location with smooth transition
      if (mapControl.fly_to) {
        newState.longitude = mapControl.fly_to.lon;
        newState.latitude = mapControl.fly_to.lat;
        if (mapControl.fly_to.zoom !== undefined) {
          newState.zoom = mapControl.fly_to.zoom;
        }
      }
      
      // pitch - Camera tilt (0 = 2D flat/overview, 45+ = 3D analysis view)
      if (mapControl.pitch !== undefined) {
        newState.pitch = mapControl.pitch;
        // Update 3D mode indicator based on pitch
        setIs3DMode(mapControl.pitch > 20);
      }
      
      // bearing - Camera rotation for dramatic reveals
      if (mapControl.bearing !== undefined) {
        newState.bearing = mapControl.bearing;
      }
      
      // If fly_to has zoom but no explicit pitch, apply context-aware pitch
      // Rule: 45° for analysis (street level), 0° for overview (city level)
      if (mapControl.fly_to?.zoom !== undefined && mapControl.pitch === undefined) {
        newState.pitch = getContextAwarePitch(mapControl.fly_to.zoom);
        setIs3DMode(newState.pitch > 20);
      }
      
      return newState;
    });
    
    // Sync with parent view state
    if (mapControl.fly_to || mapControl.pitch !== undefined || mapControl.bearing !== undefined) {
      const syncState: ViewState = {
        longitude: mapControl.fly_to?.lon ?? viewState.longitude,
        latitude: mapControl.fly_to?.lat ?? viewState.latitude,
        zoom: mapControl.fly_to?.zoom ?? viewState.zoom,
        pitch: mapControl.pitch ?? viewState.pitch,
        bearing: mapControl.bearing ?? viewState.bearing,
      };
      onViewStateChange(syncState);
    }
    
    // Release agent control after animation completes
    const releaseTimer = setTimeout(() => {
      setIsAgentControlled(false);
    }, duration + 100);
    
    return () => clearTimeout(releaseTimer);
  }, [mapControl, viewState, onViewStateChange]);

  // ==========================================================================
  // Auto-zoom to targetViewState (DATA-DRIVEN) - Lower priority than Director
  // ==========================================================================
  useEffect(() => {
    // Skip if agent is currently controlling the camera
    if (isAgentControlled) return;
    
    if (targetViewState) {
      // Calculate context-aware pitch based on target zoom level
      const targetZoom = targetViewState.zoom;
      const contextPitch = targetViewState.pitch ?? getContextAwarePitch(targetZoom);
      
      setInternalViewState(prev => ({
        ...prev,
        longitude: targetViewState.longitude,
        latitude: targetViewState.latitude,
        zoom: targetZoom,
        pitch: contextPitch,
        bearing: targetViewState.bearing ?? DEFAULT_BEARING,
        transitionDuration: FLIGHT_DURATION, // Smooth cinematic flight
      }));
    }
  }, [targetViewState, isAgentControlled]);

  // ==========================================================================
  // External viewState sync - Handles BOTH user updates and SSE fly-to commands
  // SSE sends viewState with transitionDuration → triggers animated fly-to
  // ==========================================================================
  const prevExternalRef = useRef({ lat: 0, lng: 0, zoom: 0 });
  
  useEffect(() => {
    // Guard against undefined viewState coordinates
    if (viewState.latitude === undefined || viewState.longitude === undefined) {
      return;
    }
    
    // Check if this is a PROGRAMMATIC fly-to (has transitionDuration)
    const isProgrammaticFlyTo = viewState.transitionDuration && viewState.transitionDuration > 0;
    
    // Check if destination OR zoom actually changed
    const latDiff = Math.abs(prevExternalRef.current.lat - viewState.latitude);
    const lngDiff = Math.abs(prevExternalRef.current.lng - viewState.longitude);
    const zoomDiff = Math.abs((prevExternalRef.current.zoom ?? 0) - viewState.zoom);
    // Lower threshold to detect stage transitions (was 0.5, now 0.1)
    const isNewDestination = latDiff > 0.1 || lngDiff > 0.1 || zoomDiff > 0.5;
    
    if (isProgrammaticFlyTo && isNewDestination) {
      // SSE fly-to command - animate to new location
      console.log('🎬 SSE FlyTo:', viewState.latitude.toFixed(2), viewState.longitude.toFixed(2), 'zoom:', viewState.zoom?.toFixed(1), 'pitch:', viewState.pitch);
      
      setIsAgentControlled(true);
      prevExternalRef.current = { lat: viewState.latitude, lng: viewState.longitude, zoom: viewState.zoom };
      
      const newPitch = viewState.pitch ?? getContextAwarePitch(viewState.zoom);
      setInternalViewState({
        longitude: viewState.longitude,
        latitude: viewState.latitude,
        zoom: viewState.zoom,
        pitch: newPitch,
        bearing: viewState.bearing ?? DEFAULT_BEARING,
        transitionDuration: viewState.transitionDuration,
      });
      setIs3DMode(newPitch > 20);
      
      // Release control after animation
      setTimeout(() => {
        setIsAgentControlled(false);
      }, (viewState.transitionDuration || FLIGHT_DURATION) + 100);
      
      return;
    }
    
    // Normal sync (user typing coordinates, etc.) - no animation
    if (!isAgentControlled) {
      const newPitch = viewState.pitch ?? getContextAwarePitch(viewState.zoom);
      setInternalViewState(prev => ({
        ...prev,
        longitude: viewState.longitude,
        latitude: viewState.latitude,
        zoom: viewState.zoom,
        pitch: newPitch,
        bearing: viewState.bearing ?? prev.bearing,
      }));
    }
  }, [viewState.longitude, viewState.latitude, viewState.zoom, viewState.pitch, viewState.bearing, viewState.transitionDuration, isAgentControlled]);

  const handleViewStateChange = useCallback((vs: InternalViewState) => {
    setInternalViewState(vs);
    onViewStateChange({
      longitude: vs.longitude,
      latitude: vs.latitude,
      zoom: vs.zoom,
      pitch: vs.pitch,
      bearing: vs.bearing,
    });
  }, [onViewStateChange]);

  const handleHover = useCallback((info: { x: number; y: number; object?: Record<string, unknown>; layerId?: string }) => {
    if (info.object) {
      const agentLayer = layers.find(l => info.layerId?.includes(l.id));
      setTooltipInfo({
        x: info.x,
        y: info.y,
        object: info.object,
        layerName: agentLayer?.name || 'Data',
      });
    } else {
      setTooltipInfo(null);
    }
  }, [layers]);
  
  // ==========================================================================
  // Mouse move handler for Voronoi cluster hover
  // ==========================================================================
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (areaClusters.length === 0) {
      if (hoveredCluster) setHoveredCluster(null);
      return;
    }
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    const cluster = findClusterAtPoint(x, y);
    
    if (cluster?.clusterId !== hoveredCluster?.clusterId) {
      setHoveredCluster(cluster);
    }
  }, [areaClusters, findClusterAtPoint, hoveredCluster]);
  
  const handleMouseLeave = useCallback(() => {
    setHoveredCluster(null);
  }, []);

  const toggle3D = useCallback(() => {
    setIs3DMode((prev: boolean) => {
      const newPitch = prev ? 0 : DEFAULT_PITCH;
      const newBearing = prev ? 0 : DEFAULT_BEARING;
      setInternalViewState((vs: InternalViewState) => ({
        ...vs,
        pitch: newPitch,
        bearing: newBearing,
        transitionDuration: 800, // Smooth transition
      }));
      return !prev;
    });
  }, []);

  const visibleCount = layers.filter(l => l.visible).length;

  return (
    <div 
      ref={containerRef}
      className="relative w-full h-full bg-background"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* Deck.gl Map - Dynamically loaded */}
      <DeckGLMap
        layers={layers}
        viewState={internalViewState}
        onViewStateChange={handleViewStateChange}
        onHover={handleHover}
        mapStyle={MAP_STYLE}
        mapboxToken={MAPBOX_TOKEN}
        focusGeometry={derivedFocusGeometry}
        hoveredCluster={hoveredCluster}
        onMapClick={onMapClick}
        clickMode={clickMode}
      />
      
      {/* Area Insight Card - Shows on cluster hover */}
      <AreaInsightCard 
        cluster={hoveredCluster!}
        isVisible={!!hoveredCluster}
      />

      {/* 3D Toggle - near nav controls */}
      <button
        onClick={toggle3D}
        className={`absolute top-[120px] right-[10px] w-[29px] h-[29px] flex items-center justify-center interactive-panel ${
          is3DMode ? 'interactive-panel-active' : ''
        }`}
        title={is3DMode ? '3D View (Analysis)' : '2D View (Overview)'}
        aria-label={is3DMode ? 'Switch to 2D overview' : 'Switch to 3D analysis'}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggle3D(); }}
      >
        {is3DMode ? <Box className="w-3.5 h-3.5" /> : <MapIcon className="w-3.5 h-3.5" />}
      </button>

      {/* Mouse-following tooltip - DISABLED for cleaner UX
      {tooltipInfo && (
        <div
          className="absolute z-10 pointer-events-none glass-panel p-3 max-w-xs"
          style={{ left: tooltipInfo.x + 15, top: tooltipInfo.y + 15 }}
        >
          <h3 className="font-medium text-sm mb-2 text-white border-b border-stone-800 pb-2">
            {tooltipInfo.layerName}
          </h3>
          <div className="space-y-1.5 text-xs">
            {Object.entries(tooltipInfo.object)
              .filter(([k]) => !['color', 'position', 'path', 'sourcePosition', 'targetPosition', 'geometry', 'polygon'].includes(k))
              .slice(0, 8)
              .map(([key, value]) => (
                <div key={key} className="flex justify-between gap-4">
                  <span className="text-stone-500 capitalize">{key.replace(/_/g, ' ')}</span>
                  <span className="text-white font-medium tabular-nums">
                    {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value).slice(0, 50)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
      */}

      {/* Layer Toggle */}
      <button
        onClick={() => setIsPanelOpen(!isPanelOpen)}
        className={`absolute top-4 left-4 w-9 h-9 flex items-center justify-center interactive-panel ${
          isPanelOpen ? 'interactive-panel-active' : ''
        }`}
        title="Toggle layers"
        aria-label="Toggle layer panel"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setIsPanelOpen(!isPanelOpen); }}
      >
        <Layers className="w-4 h-4" />
        {layers.length > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-white text-background text-[9px] font-bold rounded-full flex items-center justify-center">
            {visibleCount}
          </span>
        )}
      </button>

      {/* Layer Panel */}
      {isPanelOpen && (
        <div className="absolute top-16 left-4 glass-panel p-3 w-56">
          <div className="flex items-center justify-between mb-3 pb-2 border-b border-stone-800">
            <span className="text-sm font-medium text-white">Layers</span>
            <span className="text-xs text-stone-500">{visibleCount}/{layers.length}</span>
          </div>
          {layers.length === 0 ? (
            <div className="text-xs text-stone-500 text-center py-4">No layers yet</div>
          ) : (
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {layers.map((layer) => (
                <button
                  key={layer.id}
                  onClick={() => onToggleLayer?.(layer.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onToggleLayer?.(layer.id); }}
                  tabIndex={0}
                  aria-label={`${layer.visible ? 'Hide' : 'Show'} ${layer.name}`}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-all ${
                    layer.visible ? 'bg-white/5 text-white' : 'text-stone-500 hover:bg-white/5'
                  }`}
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ 
                      backgroundColor: layer.visible ? layer.color : '#444',
                      boxShadow: layer.visible ? `0 0 6px ${layer.color}50` : 'none'
                    }}
                  />
                  <span className="flex-1 text-left truncate">{layer.name}</span>
                  {layer.visible ? <Eye className="w-3 h-3 text-stone-400" /> : <EyeOff className="w-3 h-3" />}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Agent Control Indicator */}
      {isAgentControlled && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 px-3 py-1.5 glass-panel-subtle text-xs text-white/70 flex items-center gap-2">
          <span className="w-2 h-2 bg-cyan-400 rounded-full animate-pulse" />
          Camera controlled by Leo
        </div>
      )}
    </div>
  );
}
