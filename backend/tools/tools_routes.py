"""
Transport Route Tools (OSRM)

Calculate and visualize transport routes between two points using OSRM.
Perfect for supply chain visualization - connecting production locations to logistics hubs.

Usage:
    from tools_routes import get_transport_route
    
    # Get driving route from cocoa farm to Tema Port, Ghana
    result = get_transport_route(
        start_lat=6.68, start_lon=-1.62,  # Cocoa region
        end_lat=5.63, end_lon=0.02,        # Tema Port
        transport_mode='driving'
    )

System Prompt Context:
    'Use this tool to visualize supply chains. Connect a Production Location 
    (from MapSPAM/Overture) to a Logistics Hub (Port/Market from HDX).'
"""

import requests
import json
import logging
from typing import Optional, Literal, List, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OSRM Public Demo Server
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1"

# Transport modes supported by OSRM
TRANSPORT_MODES = ['driving', 'walking', 'cycling']


def get_transport_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    transport_mode: Literal['driving', 'walking', 'cycling'] = 'driving',
    include_steps: bool = False,
) -> str:
    """
    Calculate a transport route between two points using OSRM.
    
    Args:
        start_lat: Starting point latitude
        start_lon: Starting point longitude
        end_lat: Ending point latitude
        end_lon: Ending point longitude
        transport_mode: Mode of transport ('driving', 'walking', 'cycling')
        include_steps: Whether to include turn-by-turn directions
        
    Returns:
        GeoJSON Feature string with LineString geometry,
        or error object if request fails
        
    Example:
        >>> # Route from cocoa farm to Tema Port, Ghana
        >>> result = get_transport_route(6.68, -1.62, 5.63, 0.02)
        >>> # Returns GeoJSON with route line, distance, duration
    """
    logger.info("=" * 60)
    logger.info(f"🚗 Calculating {transport_mode} route")
    logger.info(f"   From: ({start_lat:.4f}, {start_lon:.4f})")
    logger.info(f"   To:   ({end_lat:.4f}, {end_lon:.4f})")
    logger.info("=" * 60)
    
    # Validate transport mode
    if transport_mode not in TRANSPORT_MODES:
        logger.error(f"  ❌ Invalid transport mode: {transport_mode}")
        return json.dumps({
            'error': True,
            'error_type': 'invalid_mode',
            'message': f"Invalid transport mode '{transport_mode}'. Use: {TRANSPORT_MODES}",
        })
    
    # Validate coordinates
    if not (-90 <= start_lat <= 90 and -180 <= start_lon <= 180):
        return json.dumps({
            'error': True,
            'error_type': 'invalid_coordinates',
            'message': f'Invalid start coordinates: ({start_lat}, {start_lon})',
        })
    
    if not (-90 <= end_lat <= 90 and -180 <= end_lon <= 180):
        return json.dumps({
            'error': True,
            'error_type': 'invalid_coordinates',
            'message': f'Invalid end coordinates: ({end_lat}, {end_lon})',
        })
    
    # Build OSRM URL
    # Format: /route/v1/{mode}/{lon},{lat};{lon},{lat}
    url = f"{OSRM_BASE_URL}/{transport_mode}/{start_lon},{start_lat};{end_lon},{end_lat}"
    
    params = {
        'overview': 'full',
        'geometries': 'geojson',
    }
    
    if include_steps:
        params['steps'] = 'true'
    
    logger.info(f"  Calling OSRM API...")
    
    try:
        response = requests.get(
            url,
            params=params,
            headers={'User-Agent': 'PuedoCasa-AgenticMaps/1.0'},
            timeout=30,
        )
        
        if response.status_code == 429:
            logger.error("  ❌ Rate limited by OSRM")
            return json.dumps({
                'error': True,
                'error_type': 'rate_limit',
                'message': '⏳ OSRM demo server rate limit reached. Please wait before trying again.',
                'suggestion': 'The demo server has usage limits. Wait a moment and retry.',
            })
        
        if response.status_code != 200:
            logger.error(f"  ❌ OSRM error: HTTP {response.status_code}")
            return json.dumps({
                'error': True,
                'error_type': 'api_error',
                'message': f'OSRM API error (HTTP {response.status_code})',
            })
        
        data = response.json()
        
        # Check OSRM response code
        if data.get('code') != 'Ok':
            error_code = data.get('code', 'Unknown')
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"  ❌ OSRM error: {error_code} - {error_msg}")
            
            if error_code == 'NoRoute':
                return json.dumps({
                    'error': True,
                    'error_type': 'no_route',
                    'message': f'No {transport_mode} route found between these points.',
                    'suggestion': 'The points may be on disconnected road networks or over water.',
                })
            
            return json.dumps({
                'error': True,
                'error_type': 'osrm_error',
                'message': f'OSRM error: {error_code} - {error_msg}',
            })
        
        # Extract route data
        routes = data.get('routes', [])
        if not routes:
            logger.warning("  ⚠️ No routes returned")
            return json.dumps({
                'error': True,
                'error_type': 'no_route',
                'message': 'No route found between these points.',
            })
        
        route = routes[0]
        
        # Extract geometry (LineString)
        geometry = route.get('geometry')
        if not geometry:
            return json.dumps({
                'error': True,
                'error_type': 'no_geometry',
                'message': 'Route found but no geometry returned.',
            })
        
        # Extract metrics
        distance_meters = route.get('distance', 0)
        duration_seconds = route.get('duration', 0)
        
        # Convert to friendlier units
        distance_km = round(distance_meters / 1000, 2)
        duration_hours = round(duration_seconds / 3600, 2)
        duration_minutes = round(duration_seconds / 60, 1)
        
        logger.info(f"  ✅ Route found!")
        logger.info(f"     Distance: {distance_km} km")
        logger.info(f"     Duration: {duration_hours} hours ({duration_minutes} min)")
        
        # Build GeoJSON Feature
        feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'distance_km': distance_km,
                'distance_meters': distance_meters,
                'duration_hours': duration_hours,
                'duration_minutes': duration_minutes,
                'duration_seconds': duration_seconds,
                'transport_mode': transport_mode,
                'start_coords': [start_lon, start_lat],
                'end_coords': [end_lon, end_lat],
            }
        }
        
        # Add turn-by-turn steps if requested
        if include_steps and 'legs' in route:
            steps = []
            for leg in route['legs']:
                for step in leg.get('steps', []):
                    steps.append({
                        'instruction': step.get('maneuver', {}).get('type', ''),
                        'name': step.get('name', ''),
                        'distance_m': step.get('distance', 0),
                        'duration_s': step.get('duration', 0),
                    })
            feature['properties']['steps'] = steps
        
        return json.dumps(feature, indent=2)
        
    except requests.exceptions.Timeout:
        logger.error("  ❌ Request timed out")
        return json.dumps({
            'error': True,
            'error_type': 'timeout',
            'message': '⏳ OSRM request timed out. Please try again.',
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request failed: {e}")
        return json.dumps({
            'error': True,
            'error_type': 'request_error',
            'message': f'Network error: {str(e)}',
        })
    except Exception as e:
        logger.error(f"  ❌ Error: {e}")
        return json.dumps({
            'error': True,
            'error_type': 'processing_error',
            'message': str(e),
        })


def get_multi_stop_route(
    waypoints: List[Tuple[float, float]],
    transport_mode: Literal['driving', 'walking', 'cycling'] = 'driving',
) -> str:
    """
    Calculate a route through multiple waypoints.
    
    Args:
        waypoints: List of (lat, lon) tuples in order
        transport_mode: Mode of transport
        
    Returns:
        GeoJSON Feature with the complete route
        
    Example:
        >>> # Farm → Processing Plant → Port
        >>> waypoints = [(6.68, -1.62), (5.95, -0.98), (5.63, 0.02)]
        >>> result = get_multi_stop_route(waypoints)
    """
    if len(waypoints) < 2:
        return json.dumps({
            'error': True,
            'error_type': 'invalid_input',
            'message': 'At least 2 waypoints required.',
        })
    
    logger.info("=" * 60)
    logger.info(f"🚗 Calculating multi-stop {transport_mode} route")
    logger.info(f"   Waypoints: {len(waypoints)}")
    logger.info("=" * 60)
    
    # Build coordinates string: lon,lat;lon,lat;...
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in waypoints])
    
    url = f"{OSRM_BASE_URL}/{transport_mode}/{coords_str}"
    
    params = {
        'overview': 'full',
        'geometries': 'geojson',
    }
    
    try:
        response = requests.get(
            url,
            params=params,
            headers={'User-Agent': 'PuedoCasa-AgenticMaps/1.0'},
            timeout=30,
        )
        
        if response.status_code != 200:
            return json.dumps({
                'error': True,
                'error_type': 'api_error',
                'message': f'OSRM API error (HTTP {response.status_code})',
            })
        
        data = response.json()
        
        if data.get('code') != 'Ok':
            return json.dumps({
                'error': True,
                'error_type': 'osrm_error',
                'message': f"OSRM error: {data.get('code')} - {data.get('message', '')}",
            })
        
        routes = data.get('routes', [])
        if not routes:
            return json.dumps({
                'error': True,
                'error_type': 'no_route',
                'message': 'No route found through these waypoints.',
            })
        
        route = routes[0]
        geometry = route.get('geometry')
        
        distance_km = round(route.get('distance', 0) / 1000, 2)
        duration_hours = round(route.get('duration', 0) / 3600, 2)
        
        # Extract leg information
        legs = []
        for i, leg in enumerate(route.get('legs', [])):
            legs.append({
                'leg_index': i,
                'from_waypoint': i,
                'to_waypoint': i + 1,
                'distance_km': round(leg.get('distance', 0) / 1000, 2),
                'duration_minutes': round(leg.get('duration', 0) / 60, 1),
            })
        
        logger.info(f"  ✅ Route found!")
        logger.info(f"     Total distance: {distance_km} km")
        logger.info(f"     Total duration: {duration_hours} hours")
        
        feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'distance_km': distance_km,
                'duration_hours': duration_hours,
                'transport_mode': transport_mode,
                'waypoints': [[lon, lat] for lat, lon in waypoints],
                'num_stops': len(waypoints),
                'legs': legs,
            }
        }
        
        return json.dumps(feature, indent=2)
        
    except Exception as e:
        return json.dumps({
            'error': True,
            'error_type': 'error',
            'message': str(e),
        })


def get_supply_chain_route(
    production_coords: Tuple[float, float],
    hub_coords: Tuple[float, float],
    production_name: str = "Production Site",
    hub_name: str = "Logistics Hub",
) -> str:
    """
    Convenience function for supply chain visualization.
    
    Args:
        production_coords: (lat, lon) of production location
        hub_coords: (lat, lon) of logistics hub (port/market)
        production_name: Label for production site
        hub_name: Label for logistics hub
        
    Returns:
        GeoJSON FeatureCollection with route line and endpoint markers
    """
    logger.info("=" * 60)
    logger.info(f"📦 Supply Chain Route: {production_name} → {hub_name}")
    logger.info("=" * 60)
    
    # Get the route
    route_result = get_transport_route(
        start_lat=production_coords[0],
        start_lon=production_coords[1],
        end_lat=hub_coords[0],
        end_lon=hub_coords[1],
        transport_mode='driving',
    )
    
    route_data = json.loads(route_result)
    
    # Check for errors
    if route_data.get('error'):
        return route_result
    
    # Add labels to route
    route_data['properties']['production_name'] = production_name
    route_data['properties']['hub_name'] = hub_name
    route_data['properties']['route_type'] = 'supply_chain'
    
    # Create endpoint markers
    start_marker = {
        'type': 'Feature',
        'geometry': {
            'type': 'Point',
            'coordinates': [production_coords[1], production_coords[0]],
        },
        'properties': {
            'name': production_name,
            'type': 'production',
            'marker_type': 'start',
        }
    }
    
    end_marker = {
        'type': 'Feature',
        'geometry': {
            'type': 'Point',
            'coordinates': [hub_coords[1], hub_coords[0]],
        },
        'properties': {
            'name': hub_name,
            'type': 'logistics_hub',
            'marker_type': 'end',
        }
    }
    
    # Build FeatureCollection
    feature_collection = {
        'type': 'FeatureCollection',
        'features': [route_data, start_marker, end_marker],
        'properties': {
            'production_name': production_name,
            'hub_name': hub_name,
            'distance_km': route_data['properties']['distance_km'],
            'duration_hours': route_data['properties']['duration_hours'],
        }
    }
    
    return json.dumps(feature_collection, indent=2)


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🚗 Transport Route Tools - Test Suite")
    print("=" * 70)
    
    def handle_result(result, test_name):
        """Helper to handle responses."""
        data = json.loads(result)
        
        if data.get('error'):
            print(f"⚠️  {data.get('message', 'Unknown error')}")
            if 'suggestion' in data:
                print(f"   💡 {data['suggestion']}")
            return
        
        if data.get('type') == 'FeatureCollection':
            props = data.get('properties', {})
            print(f"✅ Route found!")
            print(f"   Distance: {props.get('distance_km')} km")
            print(f"   Duration: {props.get('duration_hours')} hours")
        else:
            props = data.get('properties', {})
            print(f"✅ Route found!")
            print(f"   Distance: {props.get('distance_km')} km")
            print(f"   Duration: {props.get('duration_hours')} hours ({props.get('duration_minutes')} min)")
            print(f"   Mode: {props.get('transport_mode')}")
    
    # Test 1: Ghana cocoa region to Tema Port
    print("\n🍫 Test 1: Ghana Cocoa Region → Tema Port")
    print("   From: Kumasi area (6.68, -1.62)")
    print("   To:   Tema Port (5.63, 0.02)")
    result = get_transport_route(6.68, -1.62, 5.63, 0.02, 'driving')
    handle_result(result, "Ghana Route")
    
    # Test 2: Côte d'Ivoire cocoa to Abidjan Port
    print("\n🍫 Test 2: Côte d'Ivoire Cocoa → Abidjan Port")
    print("   From: Daloa (6.88, -6.45)")
    print("   To:   Abidjan Port (5.26, -3.95)")
    result = get_transport_route(6.88, -6.45, 5.26, -3.95, 'driving')
    handle_result(result, "CIV Route")
    
    # Test 3: Brazil coffee to Santos Port
    print("\n☕ Test 3: Brazil Coffee Region → Santos Port")
    print("   From: Minas Gerais (19.92, -43.94)")
    print("   To:   Santos Port (-23.96, -46.30)")
    result = get_transport_route(-19.92, -43.94, -23.96, -46.30, 'driving')
    handle_result(result, "Brazil Route")
    
    # Test 4: Supply chain convenience function
    print("\n📦 Test 4: Supply Chain Route (Ghana)")
    result = get_supply_chain_route(
        production_coords=(6.68, -1.62),
        hub_coords=(5.63, 0.02),
        production_name="Ashanti Cocoa Farm",
        hub_name="Tema Port",
    )
    handle_result(result, "Supply Chain")
    
    # Test 5: Multi-stop route
    print("\n🚚 Test 5: Multi-Stop Route (Farm → Plant → Port)")
    waypoints = [
        (6.68, -1.62),   # Cocoa farm
        (5.95, -0.98),   # Processing plant
        (5.63, 0.02),    # Tema Port
    ]
    result = get_multi_stop_route(waypoints, 'driving')
    handle_result(result, "Multi-Stop")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)

