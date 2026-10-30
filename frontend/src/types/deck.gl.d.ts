/* eslint-disable @typescript-eslint/no-explicit-any */
declare module '@deck.gl/react' {
  import { ComponentType, ReactNode } from 'react';
  
  interface DeckGLProps {
    initialViewState?: {
      longitude: number;
      latitude: number;
      zoom: number;
      pitch?: number;
      bearing?: number;
      transitionDuration?: number;
      transitionInterpolator?: unknown;
    };
    viewState?: {
      longitude: number;
      latitude: number;
      zoom: number;
      pitch?: number;
      bearing?: number;
      transitionDuration?: number;
    };
    onViewStateChange?: (params: { viewState: any }) => void;
    controller?: boolean | object;
    layers?: any[];
    style?: React.CSSProperties;
    children?: ReactNode;
    getTooltip?: (info: any) => string | null;
    onHover?: (info: any) => void;
    onClick?: (info: { coordinate?: [number, number] }) => void;
    getCursor?: () => string;
  }
  
  const DeckGL: ComponentType<DeckGLProps>;
  export default DeckGL;
}

declare module '@deck.gl/core' {
  export interface MapViewState {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch?: number;
    bearing?: number;
    transitionDuration?: number;
  }
  
  export class FlyToInterpolator {
    constructor(options?: { speed?: number; curve?: number });
  }
}

declare module '@deck.gl/layers' {
  export class GeoJsonLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      stroked?: boolean;
      filled?: boolean;
      extruded?: boolean;
      wireframe?: boolean;
      lineWidthMinPixels?: number;
      getLineColor?: any;
      getFillColor?: any;
      getLineWidth?: number;
      getElevation?: (d: any) => number;
      pointRadiusMinPixels?: number;
      material?: {
        ambient?: number;
        diffuse?: number;
        shininess?: number;
        specularColor?: [number, number, number];
      };
      parameters?: { depthTest?: boolean };
      onHover?: (info: any) => void;
      operation?: 'mask' | 'draw';
      extensions?: any[];
      maskId?: string;
    });
  }
  
  export class ScatterplotLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      getPosition?: (d: any) => [number, number];
      getRadius?: number | ((d: any) => number);
      radiusMinPixels?: number;
      radiusMaxPixels?: number;
      radiusUnits?: 'meters' | 'pixels';
      radiusScale?: number;
      getFillColor?: any;
      getLineColor?: any;
      lineWidthMinPixels?: number;
      stroked?: boolean;
      onHover?: (info: any) => void;
      extensions?: any[];
      maskId?: string;
    });
  }
  
  export class PathLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      getPath?: (d: any) => number[][];
      getColor?: any;
      getWidth?: number;
      widthMinPixels?: number;
      widthMaxPixels?: number;
      capRounded?: boolean;
      jointRounded?: boolean;
      onHover?: (info: any) => void;
    });
  }
  
  export class ArcLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      getSourcePosition?: (d: any) => [number, number];
      getTargetPosition?: (d: any) => [number, number];
      getSourceColor?: any;
      getTargetColor?: any;
      getWidth?: number;
      greatCircle?: boolean;
      onHover?: (info: any) => void;
    });
  }
  
  export class PolygonLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      stroked?: boolean;
      filled?: boolean;
      extruded?: boolean;
      wireframe?: boolean;
      getPolygon?: (d: any) => number[][] | number[][][];
      getElevation?: (d: any) => number;
      getFillColor?: any;
      getLineColor?: any;
      lineWidthMinPixels?: number;
      material?: {
        ambient?: number;
        diffuse?: number;
        shininess?: number;
        specularColor?: [number, number, number];
      };
      parameters?: { depthTest?: boolean };
      onHover?: (info: any) => void;
    });
  }
}

declare module '@deck.gl/geo-layers' {
  export class H3HexagonLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      filled?: boolean;
      extruded?: boolean;
      elevationScale?: number;
      getHexagon?: (d: any) => string;
      getFillColor?: [number, number, number, number] | ((d: any) => [number, number, number, number]);
      getLineColor?: [number, number, number, number];
      lineWidthMinPixels?: number;
      stroked?: boolean;
      getElevation?: (d: any) => number;
      opacity?: number;
      coverage?: number;
      onHover?: (info: any) => void;
      extensions?: any[];
      maskId?: string;
    });
  }
}

declare module '@deck.gl/extensions' {
  export class MaskExtension {
    constructor();
  }
}

declare module '@deck.gl/aggregation-layers' {
  export class HeatmapLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      getPosition?: (d: any) => [number, number];
      getWeight?: (d: any) => number;
      radiusPixels?: number;
      intensity?: number;
      threshold?: number;
      opacity?: number;
      colorRange?: [number, number, number, number][];
      aggregation?: 'SUM' | 'MEAN';
      weightsTextureSize?: number;
      debounceTimeout?: number;
      parameters?: {
        blendFunc?: [number, number];
        blendEquation?: number;
      };
    });
  }
  
  export class ContourLayer {
    constructor(props: {
      id: string;
      data: any;
      pickable?: boolean;
      getPosition?: (d: any) => [number, number];
      getWeight?: (d: any) => number;
      cellSize?: number;
      contours?: { threshold: number; color: [number, number, number]; strokeWidth?: number }[];
      aggregation?: 'SUM' | 'MEAN';
    });
  }
}

declare module '@deck.gl/mapbox' {
  import type { IControl } from 'mapbox-gl';
  
  export interface MapboxOverlayProps {
    layers?: any[];
    interleaved?: boolean;
    beforeId?: string;
    onHover?: (info: any) => void;
  }
  
  export class MapboxOverlay implements IControl {
    constructor(props: MapboxOverlayProps);
    setProps(props: MapboxOverlayProps): void;
    onAdd(map: mapboxgl.Map): HTMLElement;
    onRemove(map: mapboxgl.Map): void;
  }
}
