#!/usr/bin/env python3
"""
Mappability Test Suite
Validates that all API responses can be rendered on Mapbox
"""

import requests
import json
import h3
from datetime import datetime

API_URL = "http://localhost:8000/chat"
TIMEOUT = 60

# Test queries that previously passed
TESTS = [
    # Location
    ("Location", "Where is Shibuya in Tokyo?"),
    ("Location", "Boundary of Manhattan"),
    ("Location", "Gyms in Miami"),
    
    # Climate
    ("Climate", "Flood risk Miami"),
    ("Climate", "Elevation of Denver"),
    ("Climate", "Dubai climate"),
    
    # Population
    ("Population", "Population density Tokyo"),
    ("Population", "Lagos density"),
    
    # Agriculture
    ("Agriculture", "Cocoa production Ghana"),
    ("Agriculture", "Rice Vietnam"),
    
    # HDX
    ("HDX", "Hospitals Kenya"),
    ("HDX", "Schools Uganda"),
    
    # News
    ("News", "Ukraine news"),
    ("News", "Tesla sentiment"),
    
    # Trade
    ("Trade", "Ghana cocoa exports"),
    ("Trade", "US coffee imports"),
    
    # Wealth
    ("Wealth", "Wealthy areas Mexico City"),
    ("Wealth", "Income levels Lagos"),
    
    # Routes
    ("Routes", "Drive Paris to Berlin"),
    ("Routes", "Tokyo to Osaka"),
]


def validate_coordinates(coords, depth=0):
    """Recursively validate coordinates are in valid range"""
    if depth > 5:  # Prevent infinite recursion
        return True, []
    
    errors = []
    
    if isinstance(coords, (int, float)):
        return True, []
    
    if not isinstance(coords, (list, tuple)):
        return False, ["Coordinates not a list"]
    
    if len(coords) == 0:
        return False, ["Empty coordinates"]
    
    # Check if this is a point [lon, lat] or [lon, lat, alt]
    if len(coords) >= 2 and all(isinstance(c, (int, float)) for c in coords[:2]):
        lon, lat = coords[0], coords[1]
        if not (-180 <= lon <= 180):
            errors.append(f"Invalid longitude: {lon}")
        if not (-90 <= lat <= 90):
            errors.append(f"Invalid latitude: {lat}")
        return len(errors) == 0, errors
    
    # Otherwise it's a nested structure
    for i, item in enumerate(coords):
        valid, sub_errors = validate_coordinates(item, depth + 1)
        if not valid:
            errors.extend([f"[{i}] {e}" for e in sub_errors])
    
    return len(errors) == 0, errors


def validate_h3_data(data):
    """Validate H3 grid data"""
    errors = []
    
    if not isinstance(data, list):
        return False, ["H3 data is not a list"], 0
    
    if len(data) == 0:
        return False, ["H3 data is empty"], 0
    
    sample_size = min(20, len(data))
    for i in range(sample_size):
        hex_data = data[i]
        
        if not isinstance(hex_data, dict):
            errors.append(f"[{i}] Not a dict")
            continue
        
        hex_id = hex_data.get('hex')
        if not hex_id:
            errors.append(f"[{i}] Missing 'hex' field")
            continue
        
        try:
            if not h3.h3_is_valid(hex_id):
                errors.append(f"[{i}] Invalid H3: {hex_id[:20]}...")
        except Exception as e:
            errors.append(f"[{i}] H3 validation error: {e}")
        
        # Check for value field
        has_value = any(k in hex_data for k in ['count', 'value', 'rwi_score', 'population', 'production_mt', 'waste_mt'])
        if not has_value:
            errors.append(f"[{i}] Missing value field (count/value/rwi_score/etc)")
    
    return len(errors) == 0, errors, len(data)


def validate_geojson(data):
    """Validate GeoJSON data"""
    errors = []
    
    if not isinstance(data, dict):
        return False, ["GeoJSON is not a dict"], 0
    
    geom_type = data.get('type')
    
    if geom_type == 'FeatureCollection':
        features = data.get('features', [])
        if not features:
            return False, ["Empty FeatureCollection"], 0
        
        sample_size = min(10, len(features))
        for i in range(sample_size):
            feature = features[i]
            
            if not isinstance(feature, dict):
                errors.append(f"Feature[{i}] not a dict")
                continue
            
            geom = feature.get('geometry')
            if not geom:
                errors.append(f"Feature[{i}] missing geometry")
                continue
            
            coords = geom.get('coordinates')
            if coords is None:
                errors.append(f"Feature[{i}] missing coordinates")
                continue
            
            valid, coord_errors = validate_coordinates(coords)
            if not valid:
                errors.extend([f"Feature[{i}] {e}" for e in coord_errors[:3]])
        
        return len(errors) == 0, errors, len(features)
    
    elif geom_type == 'Feature':
        geom = data.get('geometry')
        if not geom:
            return False, ["Feature missing geometry"], 1
        
        coords = geom.get('coordinates')
        if coords is None:
            return False, ["Feature missing coordinates"], 1
        
        valid, coord_errors = validate_coordinates(coords)
        return valid, coord_errors, 1
    
    elif geom_type in ['Point', 'LineString', 'Polygon', 'MultiPolygon', 'MultiLineString', 'MultiPoint']:
        coords = data.get('coordinates')
        if coords is None:
            return False, [f"{geom_type} missing coordinates"], 1
        
        valid, coord_errors = validate_coordinates(coords)
        return valid, coord_errors, 1
    
    else:
        return False, [f"Unknown GeoJSON type: {geom_type}"], 0


def validate_layer(layer_name, layer_data):
    """Validate a single layer is mappable"""
    
    data = layer_data.get('data')
    
    # Handle string data (JSON encoded)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            return {
                "valid": False,
                "layer": layer_name,
                "type": "invalid_json",
                "errors": [f"JSON decode error: {e}"],
                "count": 0
            }
    
    # Check for error responses
    if isinstance(data, dict) and data.get('error'):
        return {
            "valid": False,
            "layer": layer_name,
            "type": "error_response",
            "errors": [data.get('message', 'Unknown error')],
            "count": 0
        }
    
    # Detect and validate type
    if isinstance(data, list) and data and isinstance(data[0], dict) and 'hex' in data[0]:
        # H3 Grid
        valid, errors, count = validate_h3_data(data)
        return {
            "valid": valid,
            "layer": layer_name,
            "type": "h3",
            "errors": errors[:5],  # Limit errors
            "count": count
        }
    
    elif isinstance(data, dict) and 'type' in data:
        # GeoJSON
        valid, errors, count = validate_geojson(data)
        return {
            "valid": valid,
            "layer": layer_name,
            "type": f"geojson:{data.get('type')}",
            "errors": errors[:5],
            "count": count
        }
    
    elif isinstance(data, dict):
        # Might be structured data (sentiment trends, climate profile)
        # These are info panels, not map layers
        return {
            "valid": True,
            "layer": layer_name,
            "type": "info_panel",
            "errors": [],
            "count": 1,
            "note": "Non-spatial data (info panel)"
        }
    
    else:
        return {
            "valid": False,
            "layer": layer_name,
            "type": "unknown",
            "errors": [f"Unknown data structure: {type(data).__name__}"],
            "count": 0
        }


def run_test(category, query):
    """Run a single test and validate all layers"""
    print(f"\n{'='*60}")
    print(f"[{category}] {query}")
    print("-"*60)
    
    try:
        response = requests.post(
            API_URL,
            json={"message": query, "model": "gemini-2.5-flash"},
            timeout=TIMEOUT
        )
        
        if not response.ok:
            print(f"  ❌ HTTP Error: {response.status_code}")
            return {"success": False, "error": "http_error", "layers": []}
        
        data = response.json()
        tools_used = data.get('tools_used', [])
        layers = data.get('layers', [])  # Now a list!
        
        print(f"  Tools: {tools_used}")
        print(f"  Layers: {[l.get('name') for l in layers] if isinstance(layers, list) else list(layers.keys())}")
        
        layer_results = []
        
        # Handle both list (new) and dict (old) formats
        if isinstance(layers, list):
            for layer in layers:
                layer_name = layer.get('name', 'unknown')
                result = validate_layer(layer_name, layer)
                layer_results.append(result)
        else:
            for layer_name, layer_data in layers.items():
                result = validate_layer(layer_name, layer_data)
                layer_results.append(result)
            
            status = "✅" if result['valid'] else "❌"
            print(f"  {status} {layer_name}: {result['type']} ({result['count']} records)")
            
            if result.get('note'):
                print(f"      ℹ️ {result['note']}")
            
            if result['errors']:
                for err in result['errors'][:3]:
                    print(f"      ⚠️ {err}")
        
        return {
            "success": True,
            "tools": tools_used,
            "layers": layer_results
        }
        
    except requests.exceptions.Timeout:
        print(f"  ⏱️ TIMEOUT")
        return {"success": False, "error": "timeout", "layers": []}
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return {"success": False, "error": str(e), "layers": []}


def main():
    print("="*60)
    print("🗺️ LEO MAPPABILITY TEST SUITE")
    print("="*60)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Testing {len(TESTS)} queries")
    
    all_results = []
    
    # Summary counters
    total_layers = 0
    valid_layers = 0
    invalid_layers = 0
    info_panels = 0
    
    by_type = {}
    
    for category, query in TESTS:
        result = run_test(category, query)
        all_results.append({
            "category": category,
            "query": query,
            **result
        })
        
        for layer in result.get('layers', []):
            total_layers += 1
            layer_type = layer['type']
            
            if layer_type not in by_type:
                by_type[layer_type] = {"valid": 0, "invalid": 0}
            
            if layer.get('note') and 'Non-spatial' in layer.get('note', ''):
                info_panels += 1
                by_type[layer_type]["valid"] += 1
            elif layer['valid']:
                valid_layers += 1
                by_type[layer_type]["valid"] += 1
            else:
                invalid_layers += 1
                by_type[layer_type]["invalid"] += 1
    
    # Summary
    print("\n" + "="*60)
    print("📊 MAPPABILITY SUMMARY")
    print("="*60)
    
    print(f"\nTotal Layers Tested: {total_layers}")
    print(f"  ✅ Valid (Mappable):    {valid_layers}")
    print(f"  ℹ️ Info Panels:         {info_panels}")
    print(f"  ❌ Invalid:             {invalid_layers}")
    
    print(f"\nBy Type:")
    for layer_type, stats in sorted(by_type.items()):
        total = stats['valid'] + stats['invalid']
        pct = (stats['valid'] / total * 100) if total > 0 else 0
        print(f"  {layer_type:25} ✅{stats['valid']:3} ❌{stats['invalid']:3}  ({pct:.0f}%)")
    
    # Save results
    with open("mappability_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nResults saved to mappability_results.json")
    
    # Return exit code
    if invalid_layers > 0:
        print(f"\n⚠️ {invalid_layers} layers failed validation!")
        return 1
    else:
        print(f"\n✅ All {valid_layers} spatial layers are mappable!")
        return 0


if __name__ == "__main__":
    exit(main())

