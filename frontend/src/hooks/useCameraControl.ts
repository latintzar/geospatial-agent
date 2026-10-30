'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { ViewState } from '@/lib/types';

// =============================================================================
// TYPES
// =============================================================================

export interface InternalViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
  transitionDuration?: number;
}

export interface CameraControlOptions {
  /** Default pitch when not specified */
  defaultPitch?: number;
  /** Default bearing when not specified */
  defaultBearing?: number;
  /** Default transition duration in ms */
  defaultTransition?: number;
  /** Threshold for significant position change detection (larger = less sensitive) */
  positionThreshold?: number;
  /** Threshold for significant zoom change detection */
  zoomThreshold?: number;
}

// =============================================================================
// HOOK
// =============================================================================

/**
 * Custom hook for managing Deck.gl camera state.
 * 
 * KEY BEHAVIOR:
 * - User can ALWAYS pan/zoom freely (no blocking)
 * - Only responds to PROGRAMMATIC fly-to commands (transitionDuration present)
 * - Does NOT react to its own user-initiated state changes
 * 
 * @param viewState - External view state from parent
 * @param options - Configuration options
 * @returns Camera control state and handlers
 */
export function useCameraControl(
  viewState: ViewState,
  options: CameraControlOptions = {}
) {
  const {
    defaultPitch = 45,
    defaultBearing = 0,
    defaultTransition = 2000,
    positionThreshold = 0.5,  // Larger threshold - only fly-to commands trigger
    // zoomThreshold not used - position-only detection for fly-to
  } = options;

  // Internal state that DeckGL controls
  const [internalViewState, setInternalViewState] = useState<InternalViewState>({
    longitude: viewState.longitude,
    latitude: viewState.latitude,
    zoom: viewState.zoom,
    pitch: viewState.pitch ?? defaultPitch,
    bearing: viewState.bearing ?? defaultBearing,
  });

  // Track if a programmatic animation is in progress
  const isAnimatingRef = useRef(false);
  
  // Track the last programmatic target to detect new fly-to commands
  const lastFlyToRef = useRef({ lat: 0, lng: 0, zoom: 0 });

  // ==========================================================================
  // Respond ONLY to programmatic fly-to commands (with transitionDuration)
  // User pan/zoom is handled by DeckGL directly, we don't interfere
  // ==========================================================================
  useEffect(() => {
    // Only respond if this looks like a programmatic fly-to (has transitionDuration)
    if (!viewState.transitionDuration) return;
    
    // Check if this is a NEW destination (not just echoing back user interaction)
    const latDiff = Math.abs(lastFlyToRef.current.lat - viewState.latitude);
    const lngDiff = Math.abs(lastFlyToRef.current.lng - viewState.longitude);
    const zoomDiff = Math.abs(lastFlyToRef.current.zoom - viewState.zoom);
    
    // Lower threshold (0.1) and add zoom detection for cascade stage transitions
    const isNewDestination = latDiff > 0.1 || lngDiff > 0.1 || zoomDiff > 0.5;
    
    if (isNewDestination) {
      console.log('[useCameraControl] FlyTo command:', { 
        lat: viewState.latitude.toFixed(4), 
        lng: viewState.longitude.toFixed(4), 
        zoom: viewState.zoom.toFixed(1),
        duration: viewState.transitionDuration,
      });
      
      // Mark as animating
      isAnimatingRef.current = true;
      
      // Update last flyTo target
      lastFlyToRef.current = { lat: viewState.latitude, lng: viewState.longitude, zoom: viewState.zoom };
      
      // Perform the fly-to with transition
      setInternalViewState({
        longitude: viewState.longitude,
        latitude: viewState.latitude,
        zoom: viewState.zoom,
        pitch: viewState.pitch ?? defaultPitch,
        bearing: viewState.bearing ?? defaultBearing,
        transitionDuration: viewState.transitionDuration,
      });
      
      // Clear animating flag after transition completes
      setTimeout(() => {
        isAnimatingRef.current = false;
      }, viewState.transitionDuration + 100);
    }
  }, [viewState.latitude, viewState.longitude, viewState.zoom, viewState.transitionDuration, viewState.pitch, viewState.bearing, defaultPitch, defaultBearing, positionThreshold]);

  // ==========================================================================
  // Handler for DeckGL onViewStateChange (USER interactions)
  // This is called every frame during pan/zoom - we MUST update internal state
  // but we DON'T notify parent to avoid feedback loops
  // ==========================================================================
  const handleViewStateChange = useCallback((
    newState: InternalViewState,
    onExternalChange?: (vs: { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number }) => void
  ) => {
    // Always update internal state (allows smooth user interaction)
    setInternalViewState({
      ...newState,
      transitionDuration: undefined, // Clear transition for user interactions
    });
    
    // Only notify parent if NOT currently animating (avoids feedback loop)
    // Also skip during rapid user interactions
    if (!isAnimatingRef.current && onExternalChange) {
      // Debounce parent updates to avoid excessive re-renders
      onExternalChange({
        longitude: newState.longitude,
        latitude: newState.latitude,
        zoom: newState.zoom,
        pitch: newState.pitch,
        bearing: newState.bearing,
      });
    }
  }, []);

  // ==========================================================================
  // Programmatic camera control
  // ==========================================================================
  const flyTo = useCallback((
    target: { lat: number; lng: number; zoom?: number },
    duration?: number
  ) => {
    isAnimatingRef.current = true;
    lastFlyToRef.current = { lat: target.lat, lng: target.lng, zoom: target.zoom ?? internalViewState.zoom };
    
    setInternalViewState(prev => ({
      ...prev,
      longitude: target.lng,
      latitude: target.lat,
      zoom: target.zoom ?? prev.zoom,
      transitionDuration: duration ?? defaultTransition,
    }));
    
    setTimeout(() => {
      isAnimatingRef.current = false;
    }, (duration ?? defaultTransition) + 100);
  }, [defaultTransition, internalViewState.zoom]);

  const setPitch = useCallback((pitch: number, duration?: number) => {
    setInternalViewState(prev => ({
      ...prev,
      pitch,
      transitionDuration: duration ?? defaultTransition,
    }));
  }, [defaultTransition]);

  const setBearing = useCallback((bearing: number, duration?: number) => {
    setInternalViewState(prev => ({
      ...prev,
      bearing,
      transitionDuration: duration ?? defaultTransition,
    }));
  }, [defaultTransition]);

  const resetView = useCallback((duration?: number) => {
    setInternalViewState(prev => ({
      ...prev,
      pitch: defaultPitch,
      bearing: defaultBearing,
      transitionDuration: duration ?? defaultTransition,
    }));
  }, [defaultPitch, defaultBearing, defaultTransition]);

  return {
    /** Current internal view state for DeckGL */
    viewState: internalViewState,
    /** Handler for DeckGL onViewStateChange */
    handleViewStateChange,
    /** Programmatic fly to location */
    flyTo,
    /** Set camera pitch */
    setPitch,
    /** Set camera bearing */
    setBearing,
    /** Reset pitch/bearing to defaults */
    resetView,
    /** Directly set internal state (escape hatch) */
    setViewState: setInternalViewState,
    /** Check if currently animating */
    isAnimating: () => isAnimatingRef.current,
  };
}

export default useCameraControl;
