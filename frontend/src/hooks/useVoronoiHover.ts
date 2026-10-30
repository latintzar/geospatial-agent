'use client';

import { useMemo, useCallback } from 'react';
import { Delaunay } from 'd3-delaunay';
import type { AreaCluster } from '@/lib/types';

// =============================================================================
// TYPES
// =============================================================================

interface VoronoiCell {
  clusterId: string;
  polygon: [number, number][];  // Polygon vertices in screen coords
}

interface UseVoronoiHoverOptions {
  /** Map container width in pixels */
  width: number;
  /** Map container height in pixels */
  height: number;
  /** Function to project [lng, lat] to [x, y] screen coords */
  project: (lngLat: [number, number]) => [number, number];
}

interface UseVoronoiHoverReturn {
  /** Find which cluster (if any) contains the given screen point */
  findClusterAtPoint: (x: number, y: number) => AreaCluster | null;
  /** All Voronoi cells (for debugging visualization) */
  cells: VoronoiCell[];
}

// =============================================================================
// HOOK
// =============================================================================

/**
 * Hook for Voronoi-based hover detection over area clusters.
 * 
 * Creates a Voronoi tessellation from cluster centroids, so hover zones
 * naturally "meet in the middle" between adjacent clusters with no overlap.
 * 
 * @param clusters - Array of area clusters with centroids
 * @param options - Configuration options
 * @returns Functions for hover detection
 * 
 * @example
 * ```tsx
 * const { findClusterAtPoint } = useVoronoiHover(clusters, {
 *   width: mapWidth,
 *   height: mapHeight,
 *   project: (lngLat) => map.project(lngLat),
 * });
 * 
 * const handleMouseMove = (e: MouseEvent) => {
 *   const cluster = findClusterAtPoint(e.clientX, e.clientY);
 *   setHoveredCluster(cluster);
 * };
 * ```
 */
export function useVoronoiHover(
  clusters: AreaCluster[],
  options: UseVoronoiHoverOptions
): UseVoronoiHoverReturn {
  const { width, height, project } = options;
  
  // Build Voronoi diagram from cluster centroids
  const { delaunay, clusterMap, projectedPoints } = useMemo(() => {
    if (!clusters || clusters.length === 0 || width === 0 || height === 0) {
      return { delaunay: null, clusterMap: new Map<number, AreaCluster>(), projectedPoints: [] };
    }
    
    // Project all centroids to screen coordinates
    const points: [number, number][] = [];
    const map = new Map<number, AreaCluster>();
    
    clusters.forEach((cluster) => {
      try {
        // cluster.centroid is [lng, lat]
        const [x, y] = project(cluster.centroid);
        
        // Only include points that are on screen (with buffer)
        const buffer = 100;
        if (x >= -buffer && x <= width + buffer && y >= -buffer && y <= height + buffer) {
          points.push([x, y]);
          map.set(points.length - 1, cluster);
        }
      } catch {
        // Skip clusters that can't be projected
      }
    });
    
    if (points.length === 0) {
      return { delaunay: null, clusterMap: map, projectedPoints: points };
    }
    
    // Create Delaunay triangulation (basis for Voronoi)
    const d = Delaunay.from(points);
    
    return { delaunay: d, clusterMap: map, projectedPoints: points };
  }, [clusters, width, height, project]);
  
  // Generate Voronoi cells for visualization/debugging
  const cells = useMemo((): VoronoiCell[] => {
    if (!delaunay || projectedPoints.length === 0) {
      return [];
    }
    
    // Create bounded Voronoi diagram
    const voronoi = delaunay.voronoi([0, 0, width, height]);
    
    const result: VoronoiCell[] = [];
    
    for (let i = 0; i < projectedPoints.length; i++) {
      const cluster = clusterMap.get(i);
      if (!cluster) continue;
      
      const cellPolygon = voronoi.cellPolygon(i);
      if (cellPolygon) {
        result.push({
          clusterId: cluster.clusterId,
          polygon: cellPolygon as [number, number][],
        });
      }
    }
    
    return result;
  }, [delaunay, clusterMap, projectedPoints, width, height]);
  
  // Find cluster at screen point
  const findClusterAtPoint = useCallback((x: number, y: number): AreaCluster | null => {
    if (!delaunay || projectedPoints.length === 0) {
      return null;
    }
    
    // Find nearest point using Delaunay
    const index = delaunay.find(x, y);
    
    if (index === -1) {
      return null;
    }
    
    // Get the cluster for this index
    const cluster = clusterMap.get(index);
    
    if (!cluster) {
      return null;
    }
    
    // Optional: Add a max distance check to avoid selecting very far clusters
    const [px, py] = projectedPoints[index];
    const distance = Math.sqrt((x - px) ** 2 + (y - py) ** 2);
    
    // Max hover distance in pixels (prevents selecting clusters off-screen)
    const maxDistance = Math.max(width, height) * 0.5;
    if (distance > maxDistance) {
      return null;
    }
    
    return cluster;
  }, [delaunay, clusterMap, projectedPoints, width, height]);
  
  return {
    findClusterAtPoint,
    cells,
  };
}

export default useVoronoiHover;

