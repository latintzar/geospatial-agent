#!/usr/bin/env python3
"""
Leo Test Suite - 100 Natural Language Tests
Tests all tools with user-like queries
"""

import requests
import json
import time
from datetime import datetime

API_URL = "http://localhost:8000/chat"

# All 100 tests grouped by category
TESTS = [
    # Location & Places (1-10)
    ("Location", "Where is the Shibuya crossing in Tokyo?"),
    ("Location", "Show me the boundary of Brooklyn, New York"),
    ("Location", "Find coffee shops in central Paris"),
    ("Location", "What restaurants are near the Colosseum in Rome?"),
    ("Location", "Show me the area of Soho, London"),
    ("Location", "Where is Wall Street exactly?"),
    ("Location", "Find gyms in downtown Miami"),
    ("Location", "What's the boundary of Manhattan?"),
    ("Location", "Show me bars in La Condesa, Mexico City"),
    ("Location", "Where is the Golden Gate Bridge?"),
    
    # Climate & Weather (11-20)
    ("Climate", "What's the flood risk in Miami?"),
    ("Climate", "How hot does it get in Phoenix, Arizona?"),
    ("Climate", "What's the elevation of Denver?"),
    ("Climate", "Is Bangkok at risk of flooding?"),
    ("Climate", "What's the weather risk at the Eiffel Tower?"),
    ("Climate", "How high is Mexico City above sea level?"),
    ("Climate", "What's the climate like in Dubai?"),
    ("Climate", "Does Singapore have flood problems?"),
    ("Climate", "What's the elevation of La Paz, Bolivia?"),
    ("Climate", "Is Houston prone to heat waves?"),
    
    # Population & Demographics (21-30)
    ("Population", "What's the population density in central Tokyo?"),
    ("Population", "How crowded is Manhattan?"),
    ("Population", "Show population density in Mumbai"),
    ("Population", "Where do most people live in Mexico City?"),
    ("Population", "What's the population like in central London?"),
    ("Population", "Show me the densest areas of Lagos"),
    ("Population", "How populated is downtown São Paulo?"),
    ("Population", "Where are the most people in Cairo?"),
    ("Population", "Show population in Berlin city center"),
    ("Population", "What's the density in Singapore?"),
    
    # Agriculture & Crops (31-40)
    ("Agriculture", "Where is cocoa grown in Ghana?"),
    ("Agriculture", "Show coffee production in Colombia"),
    ("Agriculture", "Where is rice farmed in Vietnam?"),
    ("Agriculture", "What crops are grown in Nigeria?"),
    ("Agriculture", "Show wheat production in India"),
    ("Agriculture", "Where is sugarcane produced in Brazil?"),
    ("Agriculture", "What's the banana production in Ecuador?"),
    ("Agriculture", "Show maize farming in Kenya"),
    ("Agriculture", "Where is cotton grown in Pakistan?"),
    ("Agriculture", "What about soybean production in Argentina?"),
    
    # Humanitarian Data (41-50)
    ("HDX", "Where are hospitals in Kenya?"),
    ("HDX", "Show me refugee camps in South Sudan"),
    ("HDX", "Find health facilities in Bangladesh"),
    ("HDX", "Where are food markets in Ethiopia?"),
    ("HDX", "Show schools in Uganda"),
    ("HDX", "Where are water points in Somalia?"),
    ("HDX", "Find airports in the DRC"),
    ("HDX", "Show conflict areas in Yemen"),
    ("HDX", "Where are aid organizations in Syria?"),
    ("HDX", "Find clinics in Afghanistan"),
    
    # News & Events (51-60)
    ("News", "What's happening in Ukraine right now?"),
    ("News", "Any protests in Paris this week?"),
    ("News", "Show me news about floods in Asia"),
    ("News", "What's the sentiment about Tesla in the news?"),
    ("News", "Are there any conflicts in the Middle East?"),
    ("News", "What's trending about climate change?"),
    ("News", "Show me photos of recent protests"),
    ("News", "Which countries are reporting on the US election?"),
    ("News", "What's the news about food prices globally?"),
    ("News", "Any disaster reports from South America?"),
    
    # Trade & Economics (61-70)
    ("Trade", "Who does Ghana export cocoa to?"),
    ("Trade", "Where does the US import coffee from?"),
    ("Trade", "Show oil trade flows from Saudi Arabia"),
    ("Trade", "Who buys Brazilian soybeans?"),
    ("Trade", "What are the top cocoa exporters?"),
    ("Trade", "Where does China export electronics to?"),
    ("Trade", "Show coffee export routes from Colombia"),
    ("Trade", "Who imports the most wheat?"),
    ("Trade", "What's the tea trade from India?"),
    ("Trade", "Show rubber exports from Thailand"),
    
    # Wealth & Income (71-80)
    ("Wealth", "Where are the wealthy areas in Mexico City?"),
    ("Wealth", "Show income levels in Lagos, Nigeria"),
    ("Wealth", "Find high-income neighborhoods in Mumbai"),
    ("Wealth", "Where are rich areas in São Paulo?"),
    ("Wealth", "What's the wealth distribution in Nairobi?"),
    ("Wealth", "Show spending power in Jakarta"),
    ("Wealth", "Where should I open a luxury store in Manila?"),
    ("Wealth", "Find affluent areas in Bogotá"),
    ("Wealth", "What's the wealth index in Cairo?"),
    ("Wealth", "Show economic levels in Bangkok"),
    
    # Routes & Transport (81-90)
    ("Routes", "How do I drive from Paris to Berlin?"),
    ("Routes", "Show the route from a cocoa farm in Ghana to Tema port"),
    ("Routes", "What's the distance from New York to Los Angeles?"),
    ("Routes", "Route from coffee production to Bogotá airport"),
    ("Routes", "How long to drive from London to Edinburgh?"),
    ("Routes", "Show supply chain from soybean farms to Santos port in Brazil"),
    ("Routes", "Route from Mumbai to Delhi"),
    ("Routes", "How far is it from Tokyo to Osaka?"),
    ("Routes", "Supply chain route for tea from Nairobi to Mombasa"),
    ("Routes", "Drive time from Mexico City to Guadalajara"),
    
    # Multi-Tool Complex (91-100)
    ("Complex", "Where should I open a coffee shop in Lisbon? Consider population and wealth."),
    ("Complex", "Analyze cocoa supply chain from Ghana farms to export ports"),
    ("Complex", "Find the best location for a clinic in rural Kenya"),
    ("Complex", "What's the investment opportunity for agriculture in Nigeria?"),
    ("Complex", "Compare flood risk and population density in Bangkok"),
    ("Complex", "Analyze coffee production areas and their proximity to ports in Colombia"),
    ("Complex", "Where are underserved health areas with high population in Ethiopia?"),
    ("Complex", "Best retail locations in Mexico City based on wealth and foot traffic"),
    ("Complex", "Map the cocoa-to-chocolate supply chain from Ivory Coast to Belgium"),
    ("Complex", "Strategic analysis: where to build a warehouse near São Paulo?"),
]

def run_test(test_num: int, category: str, query: str) -> dict:
    """Run a single test and return results"""
    print(f"\n{'='*60}")
    print(f"TEST {test_num}/100 [{category}]")
    print(f"Query: {query}")
    print("-"*60)
    
    start = time.time()
    
    try:
        response = requests.post(
            API_URL,
            json={"message": query, "model": "gemini-2.5-flash"},
            timeout=120
        )
        elapsed = time.time() - start
        
        if response.ok:
            data = response.json()
            tools_used = data.get("tools_used", [])
            text = data.get("text", "")[:300]
            layers = list(data.get("layers", {}).keys())
            
            # Check for errors in layers
            errors = []
            for layer_name, layer_data in data.get("layers", {}).items():
                if isinstance(layer_data.get("data"), str):
                    try:
                        parsed = json.loads(layer_data["data"])
                        if parsed.get("error"):
                            errors.append(f"{layer_name}: {parsed.get('message', 'error')[:50]}")
                    except:
                        pass
            
            status = "✅ PASS" if tools_used and not errors else "⚠️ PARTIAL" if tools_used else "❌ NO TOOLS"
            
            print(f"Status: {status}")
            print(f"Time: {elapsed:.1f}s")
            print(f"Tools: {tools_used}")
            print(f"Layers: {layers}")
            if errors:
                print(f"Errors: {errors}")
            print(f"Response: {text}...")
            
            return {
                "test_num": test_num,
                "category": category,
                "query": query,
                "status": status,
                "time": elapsed,
                "tools": tools_used,
                "layers": layers,
                "errors": errors,
                "text": text
            }
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            return {
                "test_num": test_num,
                "category": category,
                "query": query,
                "status": "❌ HTTP ERROR",
                "error": response.text[:200]
            }
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return {
            "test_num": test_num,
            "category": category,
            "query": query,
            "status": "❌ EXCEPTION",
            "error": str(e)
        }

def main():
    print("="*60)
    print("🧪 LEO TEST SUITE - 100 Natural Language Tests")
    print("="*60)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"API: {API_URL}")
    
    results = []
    
    for i, (category, query) in enumerate(TESTS, 1):
        result = run_test(i, category, query)
        results.append(result)
        
        # Brief pause between tests
        time.sleep(1)
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results if "PASS" in r.get("status", ""))
    partial = sum(1 for r in results if "PARTIAL" in r.get("status", ""))
    failed = sum(1 for r in results if "❌" in r.get("status", ""))
    
    print(f"✅ Passed: {passed}")
    print(f"⚠️ Partial: {partial}")
    print(f"❌ Failed: {failed}")
    print(f"Total: {len(results)}")
    
    # By category
    print("\nBy Category:")
    categories = {}
    for r in results:
        cat = r.get("category", "Unknown")
        if cat not in categories:
            categories[cat] = {"pass": 0, "partial": 0, "fail": 0}
        if "PASS" in r.get("status", ""):
            categories[cat]["pass"] += 1
        elif "PARTIAL" in r.get("status", ""):
            categories[cat]["partial"] += 1
        else:
            categories[cat]["fail"] += 1
    
    for cat, stats in categories.items():
        print(f"  {cat}: ✅{stats['pass']} ⚠️{stats['partial']} ❌{stats['fail']}")
    
    # Save results
    with open("test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to test_results.json")

if __name__ == "__main__":
    main()

