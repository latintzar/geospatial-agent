'use client';

import { useMemo } from 'react';
import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { GeoJsonLayer, ScatterplotLayer, PathLayer, ArcLayer, PolygonLayer } from '@deck.gl/layers';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import { MaskExtension } from '@deck.gl/extensions';
import { cellToLatLng, cellsToMultiPolygon } from 'h3-js';
import type { AgentLayer, GeometryData, AreaCluster } from '@/lib/types';

// =============================================================================
// COLOR PALETTES
// =============================================================================

const COLOR_RANGES: Record<string, [number, number, number, number][]> = {
  magma: [
    [0, 0, 4, 25],
    [28, 16, 68, 60],
    [79, 18, 123, 110],
    [129, 37, 129, 160],
    [181, 54, 122, 195],
    [229, 80, 100, 220],
    [251, 135, 97, 240],
    [254, 194, 135, 255],
  ],
  inferno: [
    [0, 0, 4, 25],
    [31, 12, 72, 60],
    [85, 15, 109, 110],
    [136, 34, 106, 160],
    [186, 54, 85, 195],
    [227, 89, 51, 220],
    [249, 140, 10, 240],
    [252, 255, 164, 255],
  ],
  viridis: [
    [68, 1, 84, 25],
    [72, 36, 117, 60],
    [65, 68, 135, 110],
    [53, 95, 141, 160],
    [42, 120, 142, 195],
    [33, 145, 140, 220],
    [53, 183, 121, 240],
    [180, 222, 44, 255],
  ],
  plasma: [
    [13, 8, 135, 25],
    [75, 3, 161, 60],
    [126, 3, 168, 110],
    [168, 34, 150, 160],
    [203, 70, 121, 195],
    [229, 107, 93, 220],
    [248, 149, 64, 240],
    [240, 249, 33, 255],
  ],
};

// =============================================================================
// CONSTANTS
// =============================================================================

const VOID_COLOR_SPOTLIGHT: [number, number, number, number] = [0, 0, 0, 180]; // Darker for spotlight
const BOUNDARY_COLOR: [number, number, number, number] = [255, 255, 255, 255];
const NEON_CYAN: [number, number, number, number] = [0, 200, 255, 230];
const NEON_MAGENTA: [number, number, number, number] = [255, 100, 200, 230];

const WORLD_BOUNDS: number[][] = [
  [-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85],
];

// Cascade stage layer IDs - used to detect progressive visualization
const CASCADE_STAGES = ['cascade_res5', 'cascade_res8', 'cascade_final', 'cascade_res10_heatmap'];

// Singleton mask extension
const maskExtension = new MaskExtension();

// =============================================================================
// SPOTLIGHT GEOMETRY HELPER
// =============================================================================

/**
 * Creates a spotlight (void) polygon from H3 hexes.
 * Returns a polygon that covers the whole world EXCEPT the hex area.
 * This creates a "spotlight" effect where hexes are illuminated.
 */
function createSpotlightPolygon(hexes: string[]): number[][][] | null {
  if (!hexes || hexes.length === 0) {
    console.log('[createSpotlightPolygon] No hexes provided');
    return null;
  }
  
  try {
    console.log('[createSpotlightPolygon] Processing', hexes.length, 'hexes, sample:', hexes.slice(0, 3));
    // Get the multi-polygon boundary of all hexes
    const multiPolygon = cellsToMultiPolygon(hexes, true); // true = GeoJSON format [lng, lat]
    
    console.log('[createSpotlightPolygon] multiPolygon result:', multiPolygon?.length || 0, 'polygons');
    
    if (!multiPolygon || multiPolygon.length === 0) {
      console.log('[createSpotlightPolygon] No multiPolygon returned');
      return null;
    }
    
    // Use the first (outer) polygon as the spotlight hole
    // For a proper void effect, we need: [WORLD_BOUNDS, ...holes]
    const spotlightHoles = multiPolygon.map((polygon: number[][][]) => polygon[0]); // Outer ring of each polygon
    console.log('[createSpotlightPolygon] Created', spotlightHoles.length, 'holes for spotlight');
    
    return [WORLD_BOUNDS, ...spotlightHoles];
  } catch (e) {
    console.warn('[useLayerFactory] Failed to create spotlight polygon:', e);
    return null;
  }
}

// =============================================================================
// INTERNAL TYPES
// =============================================================================

interface H3Data {
  hex: string;
  value?: number;
  count?: number;
  weight?: number;
  lat?: number;
  lng?: number;
  [key: string]: unknown;
}

interface PointData {
  lat?: number;
  lng?: number;
  lon?: number;
  longitude?: number;
  latitude?: number;
  value?: number;
  weight?: number;
  count?: number;
  [key: string]: unknown;
}

// =============================================================================
// LAYER FACTORY FUNCTION
// =============================================================================

function createLayers(
  agentLayers: AgentLayer[],
  focusGeometry?: GeoJSON.Geometry | null,
  zoom: number = 12,
  hoveredCluster?: AreaCluster | null
): unknown[] {
  const deckLayers: unknown[] = [];
  const hasMask = !!focusGeometry;

  // ==========================================================================
  // CASCADE SPOTLIGHT DETECTION
  // ==========================================================================
  // Find cascade layers and determine the spotlight boundary
  // IMPORTANT: Spotlight is ALWAYS from Stage 1 (cascade_res5) - the city zone boundary
  // This defines what area is "in play" - everything outside goes dark
  const cascadeLayers = new Map<string, AgentLayer>();
  for (const layer of agentLayers) {
    if (CASCADE_STAGES.includes(layer.id)) {
      cascadeLayers.set(layer.id, layer);
    }
  }
  
  // Spotlight boundary is ALWAYS from Stage 1 (res5) - the city zone
  // This is what gets illuminated, everything else goes dark
  let spotlightHexes: string[] = [];
  const res5Layer = cascadeLayers.get('cascade_res5');
  if (res5Layer && res5Layer.visible && Array.isArray(res5Layer.data) && res5Layer.data.length > 0) {
    spotlightHexes = (res5Layer.data as H3Data[]).map(d => d.hex).filter(Boolean);
  }
  
  // Stage 2 (res8) hexes - for secondary spotlight effect
  let res8Hexes: string[] = [];
  const res8Layer = cascadeLayers.get('cascade_res8');
  if (res8Layer && res8Layer.visible && Array.isArray(res8Layer.data) && res8Layer.data.length > 0) {
    res8Hexes = (res8Layer.data as H3Data[]).map(d => d.hex).filter(Boolean);
  }
  
  // Track which stage is currently "active" for dimming previous stages
  let activeStageId: string | null = null;
  for (const stageId of ['cascade_final', 'cascade_res10_heatmap', 'cascade_res8', 'cascade_res5']) {
    const layer = cascadeLayers.get(stageId);
    if (layer && layer.visible && Array.isArray(layer.data) && layer.data.length > 0) {
      activeStageId = stageId;
      break;
    }
  }
  
  console.log('[useLayerFactory] Spotlight from res5:', spotlightHexes.length, 'hexes, res8:', res8Hexes.length, 'hexes, active stage:', activeStageId);

  // ==========================================================================
  // 1. AOI MASK LAYER (for MaskExtension - from explicit focusGeometry)
  // ==========================================================================
  if (focusGeometry && (focusGeometry.type === 'Polygon' || focusGeometry.type === 'MultiPolygon')) {
    deckLayers.push(
      new GeoJsonLayer({
        id: 'aoi-mask',
        data: { type: 'Feature', properties: {}, geometry: focusGeometry },
        operation: 'mask',
        pickable: false,
      })
    );
  }

  // ==========================================================================
  // 2. SPOTLIGHT VOID MASKS - CREATED BUT ADDED LAST (for proper z-ordering)
  // ==========================================================================
  // Stage 1 spotlight: Everything outside res5 goes dark
  // Stage 2 spotlight: Everything outside res8 (but inside res5) gets dimmed
  let spotlightVoidData: { polygon: number[][][] } | null = null;
  let res8SpotlightVoidData: { polygon: number[][][] } | null = null;
  
  if (spotlightHexes.length > 0) {
    // Create spotlight from the res5 hexes (outer boundary)
    console.log('[useLayerFactory] Creating res5 spotlight from', spotlightHexes.length, 'hexes');
    const spotlightPolygon = createSpotlightPolygon(spotlightHexes);
    console.log('[useLayerFactory] Spotlight polygon:', spotlightPolygon ? 'created' : 'NULL');
    if (spotlightPolygon) {
      console.log('[useLayerFactory] Spotlight has', spotlightPolygon.length, 'rings');
      spotlightVoidData = { polygon: spotlightPolygon };
    }
  }
  
  // Secondary spotlight for res8 (deeper spotlight within res5)
  if (res8Hexes.length > 0 && (activeStageId === 'cascade_res8' || activeStageId === 'cascade_final')) {
    console.log('[useLayerFactory] Creating res8 spotlight from', res8Hexes.length, 'hexes');
    const res8SpotlightPolygon = createSpotlightPolygon(res8Hexes);
    if (res8SpotlightPolygon) {
      console.log('[useLayerFactory] Res8 spotlight has', res8SpotlightPolygon.length, 'rings');
      res8SpotlightVoidData = { polygon: res8SpotlightPolygon };
    }
  } else if (focusGeometry && (focusGeometry.type === 'Polygon' || focusGeometry.type === 'MultiPolygon')) {
    // Fallback to focusGeometry void mask
    const holeCoords = focusGeometry.type === 'Polygon' 
      ? focusGeometry.coordinates[0] 
      : focusGeometry.coordinates[0][0];
    
    if (holeCoords && holeCoords.length > 0) {
      spotlightVoidData = { polygon: [WORLD_BOUNDS, holeCoords] };
    }
  }

  // ==========================================================================
  // 3. AGENT LAYERS (with cascade progressive dimming)
  // ==========================================================================
  for (const layer of agentLayers) {
    if (!layer.visible || !layer.data) continue;

    const colorScale = layer.vizConfig?.color_scale || 'magma';
    const colorRange = COLOR_RANGES[colorScale] || COLOR_RANGES.magma;
    const isFocus = layer.metadata?.is_focus === true;

    const extensions = isFocus && hasMask ? [maskExtension] : [];
    const extensionProps = isFocus && hasMask ? { maskId: 'aoi-mask' } : {};

    switch (layer.type) {
      // HEATMAP
      case 'heatmap':
      case 'weighted_points': {
        const pointData = Array.isArray(layer.data) ? layer.data as PointData[] : [];
        if (pointData.length === 0) continue;

        const points = pointData.map(d => ({
          position: [(d.lng ?? d.lon ?? d.longitude ?? 0) as number, (d.lat ?? d.latitude ?? 0) as number],
          weight: (d.value ?? d.weight ?? d.count ?? 1) as number,
        })).filter(p => p.position[0] !== 0 && p.position[1] !== 0);

        if (points.length === 0) continue;

        deckLayers.push(
          new HeatmapLayer({
            id: `heatmap-${layer.id}`,
            data: points,
            getPosition: (d: { position: number[] }) => d.position as [number, number],
            getWeight: (d: { weight: number }) => d.weight,
            radiusPixels: 50,
            intensity: 1.5,
            threshold: 0.03,
            colorRange,
            aggregation: 'SUM',
          })
        );
        break;
      }

      // H3 GRID - CASCADE LAYERS USE HEX FILLS, OTHERS USE HEATMAP
      case 'h3':
      case 'h3_grid':
      case 'population_h3': {
        let h3Data: H3Data[] = [];
        
        if (layer.type === 'population_h3') {
          const popData = layer.data as { population?: H3Data[] };
          h3Data = popData.population || [];
        } else {
          h3Data = Array.isArray(layer.data) ? layer.data as H3Data[] : [];
        }
        
        if (h3Data.length === 0) continue;

        const isCascadeLayer = CASCADE_STAGES.includes(layer.id);

        // =======================================================================
        // CASCADE_RES5: DO NOT RENDER - it's just the spotlight boundary
        // The void mask uses res5 to define what's illuminated
        // =======================================================================
        if (layer.id === 'cascade_res5') {
          console.log(`[useLayerFactory] Skipping ${layer.id} render - it's the spotlight boundary`);
          break;
        }

        // =======================================================================
        // CASCADE_RES8: Merged hex boundary (h3 multipolygon - no overlap)
        // Uses h3-js cellsToMultiPolygon which efficiently merges adjacent hexes
        // =======================================================================
        if (layer.id === 'cascade_res8') {
          console.log(`[useLayerFactory] Rendering ${layer.id} as merged polygon`);
          
          // Get hex IDs and create merged boundary using h3-js (efficient, native)
          const hexIds = h3Data.map(d => d.hex).filter(Boolean);
          
          if (hexIds.length > 0) {
            try {
              // cellsToMultiPolygon efficiently merges adjacent hexes into single shape
              const multiPolygon = cellsToMultiPolygon(hexIds, true); // geoJson=true
              
              deckLayers.push(
                new GeoJsonLayer({
                  id: `cascade-merged-${layer.id}`,
                  data: {
                    type: 'Feature',
                    properties: {},
                    geometry: { type: 'MultiPolygon', coordinates: multiPolygon }
                  },
                  getFillColor: [255, 255, 255, 50], // Subtle white
                  getLineColor: [255, 255, 255, 100],
                  lineWidthMinPixels: 1,
                  pickable: true,
                })
              );
            } catch (e) {
              console.warn('[useLayerFactory] Failed to merge res8 hexes:', e);
            }
          }
          break;
        }

        // =======================================================================
        // CASCADE_FINAL: H3 hexes with blur glow effect
        // Layer 1: HeatmapLayer for soft blur/glow (renders first = behind)
        // Layer 2: H3HexagonLayer for zoom-invariant value colors (on top)
        // =======================================================================
        if (isCascadeLayer) {
          // Calculate opacity based on active stage (progressive dimming)
          let layerOpacity = 0.85;
          
          if (activeStageId) {
            const layerStageIndex = CASCADE_STAGES.indexOf(layer.id);
            const activeIndex = CASCADE_STAGES.indexOf(activeStageId);
            
            if (layerStageIndex < activeIndex) {
              layerOpacity = 0.4;
              console.log(`[useLayerFactory] Dimming ${layer.id} to ${layerOpacity} (active: ${activeStageId})`);
            }
          }

          // LAYER 1: HeatmapLayer blur/glow effect (behind the hexes)
          const glowPoints = h3Data.map(d => {
            let lat = d.lat ?? 0;
            let lng = d.lng ?? 0;
            if ((lat === 0 || lng === 0) && d.hex) {
              try {
                [lat, lng] = cellToLatLng(d.hex);
              } catch { /* ignore */ }
            }
            return { 
              position: [lng, lat] as [number, number], 
              weight: d.value ?? d.count ?? d.weight ?? 1 
            };
          }).filter(p => p.position[0] !== 0 && p.position[1] !== 0);

          if (glowPoints.length > 0) {
            // Scale radiusPixels with zoom for consistent geographic size
            // At zoom 12 = 60px (50% larger), doubles for each zoom level
            const baseZoom = 10;
            const baseRadius = 60;
            const zoomScaledRadius = baseRadius * Math.pow(6, zoom - baseZoom);
            // Clamp to reasonable range
            const radiusPixels = Math.max(20, Math.min(zoomScaledRadius, 1000));
            
            // Scale intensity inversely - more spread = less intense
            const zoomScaledIntensity = (1.1 * layerOpacity) / Math.pow(1.2, zoom - baseZoom);

            // Pure HeatmapLayer - no hard hex edges, just smooth blur
            deckLayers.push(
              new HeatmapLayer({
                id: `cascade-heatmap-${layer.id}`,
                data: glowPoints,
                getPosition: (d: { position: [number, number]; weight: number }) => d.position,
                getWeight: (d: { position: [number, number]; weight: number }) => d.weight,
                radiusPixels: radiusPixels,
                intensity: Math.max(0.1, zoomScaledIntensity),
                threshold: 0.01,
                colorRange: colorRange,
                aggregation: 'SUM',
              })
            );
          }
          break;
        }

        // =======================================================================
        // NON-CASCADE LAYERS: Use HeatmapLayer (blurred for statistical data)
        // =======================================================================
        const layerOpacity = layer.vizConfig?.opacity ?? 0.8;

        const points = h3Data.map(d => {
          let lat = d.lat ?? 0;
          let lng = d.lng ?? 0;
          if ((lat === 0 || lng === 0) && d.hex) {
            try {
              [lat, lng] = cellToLatLng(d.hex);
            } catch { /* ignore */ }
          }
          return { position: [lng, lat], weight: d.value ?? d.count ?? d.weight ?? 1 };
        }).filter(p => p.position[0] !== 0 && p.position[1] !== 0);

        if (points.length === 0) continue;

        // Apply opacity to color range - scale alpha channel
        const opacityColorRange = colorRange.map(c => 
          [c[0], c[1], c[2], Math.floor(c[3] * layerOpacity)] as [number, number, number, number]
        );

        deckLayers.push(
          new HeatmapLayer({
            id: `heatmap-${layer.id}`,
            data: points,
            getPosition: (d: { position: number[] }) => d.position as [number, number],
            getWeight: (d: { weight: number }) => d.weight,
            radiusPixels: 60,
            intensity: 1.5,
            threshold: 0.03,
            colorRange: opacityColorRange,
            aggregation: 'SUM',
          })
        );
        break;
      }

      // H3 HEXAGON (crisp) - WITH CASCADE DIMMING
      case 'h3_hexagon': {
        const h3Data = Array.isArray(layer.data) ? layer.data as H3Data[] : [];
        if (h3Data.length === 0) continue;

        const values = h3Data.map(d => d.value ?? d.count ?? d.weight ?? 1);
        const maxValue = Math.max(...values, 1);

        // =======================================================================
        // CASCADE PROGRESSIVE DIMMING LOGIC
        // =======================================================================
        let layerOpacity = layer.vizConfig?.opacity ?? 0.8;
        const isCascadeLayer = CASCADE_STAGES.includes(layer.id);
        
        if (isCascadeLayer && activeStageId) {
          const layerStageIndex = CASCADE_STAGES.indexOf(layer.id);
          const activeIndex = CASCADE_STAGES.indexOf(activeStageId);
          
          if (layerStageIndex < activeIndex) {
            // Earlier stage - dim to 50%
            layerOpacity = Math.max((layer.vizConfig?.opacity ?? 0.5) * 0.5, 0.15);
          } else if (layer.id === activeStageId) {
            // Active stage - ensure high opacity
            layerOpacity = Math.max(layer.vizConfig?.opacity ?? 0.8, 0.6);
          }
        }

        deckLayers.push(
          new H3HexagonLayer({
            id: `h3-${layer.id}`,
            data: h3Data,
            getHexagon: (d: H3Data) => d.hex,
            getFillColor: (d: H3Data) => {
              const val = (d.value ?? d.count ?? d.weight ?? 0) / maxValue;
              const idx = Math.floor(val * (colorRange.length - 1));
              const baseColor = colorRange[Math.min(idx, colorRange.length - 1)];
              // Apply layer opacity to alpha
              return [baseColor[0], baseColor[1], baseColor[2], Math.floor(baseColor[3] * layerOpacity)] as [number, number, number, number];
            },
            extruded: false,
            pickable: true,
            extensions,
            ...extensionProps,
          })
        );
        break;
      }

      // EXTRUSION (3D)
      case 'extrusion': {
        const h3Data = Array.isArray(layer.data) ? layer.data as H3Data[] : [];
        if (h3Data.length === 0) continue;

        const values = h3Data.map(d => d.value ?? d.count ?? d.weight ?? 1);
        const maxValue = Math.max(...values, 1);

        deckLayers.push(
          new H3HexagonLayer({
            id: `extrusion-${layer.id}`,
            data: h3Data,
            getHexagon: (d: H3Data) => d.hex,
            getFillColor: (d: H3Data) => {
              const val = (d.value ?? d.count ?? d.weight ?? 0) / maxValue;
              const idx = Math.floor(val * (colorRange.length - 1));
              return colorRange[Math.min(idx, colorRange.length - 1)];
            },
            getElevation: (d: H3Data) => (d.value ?? d.count ?? d.weight ?? 0) * 10,
            elevationScale: 100,
            extruded: true,
            pickable: true,
            extensions,
            ...extensionProps,
          })
        );
        break;
      }

      // POINTS
      case 'points': {
        const pointData = Array.isArray(layer.data) ? layer.data as PointData[] : [];
        if (pointData.length === 0) continue;

        deckLayers.push(
          new ScatterplotLayer({
            id: `scatter-${layer.id}`,
            data: pointData,
            getPosition: (d: PointData) => [
              (d.lng ?? d.lon ?? d.longitude ?? 0) as number,
              (d.lat ?? d.latitude ?? 0) as number,
            ] as [number, number],
            getRadius: 100,
            getFillColor: [59, 130, 246, 200],
            pickable: true,
            extensions,
            ...extensionProps,
          })
        );
        break;
      }

      // ROUTE / PATH
      case 'route': {
        const geoData = layer.data as GeoJSON.FeatureCollection | GeoJSON.Feature;
        if (!geoData) continue;

        deckLayers.push(
          new PathLayer({
            id: `path-${layer.id}`,
            data: geoData.type === 'FeatureCollection' ? geoData.features : [geoData],
            getPath: (d: GeoJSON.Feature) => {
              if (d.geometry.type === 'LineString') return d.geometry.coordinates;
              if (d.geometry.type === 'MultiLineString') return d.geometry.coordinates.flat();
              return [];
            },
            getColor: NEON_CYAN,
            getWidth: 4,
            widthMinPixels: 2,
            pickable: true,
          })
        );
        break;
      }

      // GEOMETRY / BOUNDARY
      case 'geometry':
      case 'boundary': {
        const geoData = layer.data as GeometryData | GeoJSON.Feature | GeoJSON.FeatureCollection;
        let geojson: GeoJSON.FeatureCollection | null = null;
        
        if ('geometry' in geoData && geoData.geometry) {
          geojson = {
            type: 'FeatureCollection',
            features: [{ type: 'Feature', properties: {}, geometry: geoData.geometry }],
          };
        } else if ('type' in geoData) {
          if (geoData.type === 'FeatureCollection') {
            geojson = geoData as GeoJSON.FeatureCollection;
          } else if (geoData.type === 'Feature') {
            geojson = { type: 'FeatureCollection', features: [geoData as GeoJSON.Feature] };
          }
        }
        
        if (!geojson) continue;

        deckLayers.push(
          new GeoJsonLayer({
            id: `boundary-${layer.id}`,
            data: geojson,
            stroked: true,
            filled: false,
            getLineColor: BOUNDARY_COLOR,
            getLineWidth: 3,
            lineWidthMinPixels: 2,
            pickable: true,
          })
        );
        break;
      }

      // GEOJSON (generic)
      case 'geojson': {
        const geoData = layer.data as GeoJSON.FeatureCollection | GeoJSON.Feature;
        if (!geoData) continue;

        deckLayers.push(
          new GeoJsonLayer({
            id: `geojson-${layer.id}`,
            data: geoData,
            stroked: true,
            filled: true,
            getFillColor: [59, 130, 246, 100],
            getLineColor: [59, 130, 246, 255],
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            pickable: true,
            pointRadiusMinPixels: 5,
            extensions,
            ...extensionProps,
          })
        );
        break;
      }

      // ARC (trade flows)
      case 'arc': {
        const arcData = Array.isArray(layer.data) ? layer.data : [];
        if (arcData.length === 0) continue;

        deckLayers.push(
          new ArcLayer({
            id: `arc-${layer.id}`,
            data: arcData,
            getSourcePosition: (d: Record<string, unknown>) => [
              (d.source_lng ?? d.sourceLng ?? 0) as number,
              (d.source_lat ?? d.sourceLat ?? 0) as number,
            ] as [number, number],
            getTargetPosition: (d: Record<string, unknown>) => [
              (d.target_lng ?? d.targetLng ?? 0) as number,
              (d.target_lat ?? d.targetLat ?? 0) as number,
            ] as [number, number],
            getSourceColor: NEON_MAGENTA,
            getTargetColor: NEON_CYAN,
            getWidth: 2,
            pickable: true,
          })
        );
        break;
      }

      // POINTS - Simple pin markers (for DIEM selected location)
      case 'points': {
        const pointData = Array.isArray(layer.data) ? layer.data as Array<{lat: number; lng?: number; lon?: number; name?: string}> : [];
        if (pointData.length === 0) continue;

        const validPoints = pointData.filter(d => d.lat && (d.lng || d.lon));
        if (validPoints.length === 0) continue;

        // Use a vibrant color for the pin (default to violet if not specified)
        const pinColor = layer.color 
          ? (typeof layer.color === 'string' 
            ? layer.color.startsWith('#') 
              ? [parseInt(layer.color.slice(1, 3), 16), parseInt(layer.color.slice(3, 5), 16), parseInt(layer.color.slice(5, 7), 16), 255] as [number, number, number, number]
              : [168, 85, 247, 255] as [number, number, number, number]  // Violet fallback
            : [168, 85, 247, 255] as [number, number, number, number])
          : [168, 85, 247, 255] as [number, number, number, number];

        // Pin with outer ring
        deckLayers.push(
          new ScatterplotLayer({
            id: `pin-outer-${layer.id}`,
            data: validPoints,
            getPosition: (d: {lat: number; lng?: number; lon?: number}) => [(d.lng ?? d.lon) as number, d.lat] as [number, number],
            getFillColor: [255, 255, 255, 180] as [number, number, number, number],  // White ring
            getRadius: 12,
            radiusUnits: 'pixels',
            radiusMinPixels: 12,
            radiusMaxPixels: 16,
            pickable: false,
          })
        );
        
        // Inner pin dot
        deckLayers.push(
          new ScatterplotLayer({
            id: `pin-inner-${layer.id}`,
            data: validPoints,
            getPosition: (d: {lat: number; lng?: number; lon?: number}) => [(d.lng ?? d.lon) as number, d.lat] as [number, number],
            getFillColor: pinColor,
            getRadius: 8,
            radiusUnits: 'pixels',
            radiusMinPixels: 8,
            radiusMaxPixels: 12,
            pickable: true,
          })
        );
        break;
      }

      default:
        console.warn(`[useLayerFactory] Unknown layer type: ${layer.type}`);
    }
  }

  // ==========================================================================
  // FINAL: ADD SPOTLIGHT VOIDS ON TOP (renders last = appears on top)
  // ==========================================================================
  // Stage 1 void: Darkens everything OUTSIDE the res5 hex boundary
  if (spotlightVoidData) {
    console.log('[useLayerFactory] Adding res5 spotlight void - darkening outside res5');
    deckLayers.push(
      new PolygonLayer({
        id: 'cascade-spotlight-void-res5',
        data: [spotlightVoidData],
        getPolygon: (d: { polygon: number[][][] }) => d.polygon,
        getFillColor: VOID_COLOR_SPOTLIGHT,
        pickable: false,
      })
    );
  }
  
  // Stage 2 void: Dims the area INSIDE res5 but OUTSIDE res8 (deeper spotlight)
  if (res8SpotlightVoidData) {
    console.log('[useLayerFactory] Adding res8 spotlight void - dimming inside res5 but outside res8');
    deckLayers.push(
      new PolygonLayer({
        id: 'cascade-spotlight-void-res8',
        data: [res8SpotlightVoidData],
        getPolygon: (d: { polygon: number[][][] }) => d.polygon,
        getFillColor: [0, 0, 0, 120] as [number, number, number, number], // Lighter than res5 void for "spotlight within spotlight"
        pickable: false,
      })
    );
  }

  // ==========================================================================
  // HOVER HIGHLIGHT LAYER - Light up hovered cluster hexes
  // ==========================================================================
  if (hoveredCluster && hoveredCluster.hexes && hoveredCluster.hexes.length > 0) {
    console.log('[useLayerFactory] Adding hover highlight for cluster:', hoveredCluster.clusterId, 'with', hoveredCluster.hexes.length, 'hexes');
    
    // Create highlight layer with semi-transparent cyan fill + outline for "light up" effect
    deckLayers.push(
      new H3HexagonLayer({
        id: 'hover-cluster-highlight',
        data: hoveredCluster.hexes.map(hex => ({ hex })),
        getHexagon: (d: { hex: string }) => d.hex,
        getFillColor: [0, 200, 255, 60] as [number, number, number, number], // Soft cyan glow
        getLineColor: [0, 200, 255, 180] as [number, number, number, number], // Brighter cyan outline
        lineWidthMinPixels: 2,
        stroked: true,
        filled: true,
        extruded: false,
        pickable: false,
      })
    );
  }

  return deckLayers;
}

// =============================================================================
// HOOK
// =============================================================================

/**
 * Custom hook to create Deck.gl layers from AgentLayers.
 * Memoizes layer creation for performance.
 * 
 * @param agentLayers - Array of agent layers to render
 * @param focusGeometry - Optional geometry for focus mask
 * @param zoom - Current map zoom level
 * @param hoveredCluster - Optional hovered area cluster for outline highlighting
 */
export function useLayerFactory(
  agentLayers: AgentLayer[],
  focusGeometry?: GeoJSON.Geometry | null,
  zoom: number = 12,
  hoveredCluster?: AreaCluster | null
) {
  return useMemo(() => {
    console.log('[useLayerFactory] Creating layers for', agentLayers.length, 'agent layers, zoom:', zoom.toFixed(1));
    return createLayers(agentLayers, focusGeometry, zoom, hoveredCluster);
  }, [agentLayers, focusGeometry, zoom, hoveredCluster]);
}

export default useLayerFactory;
