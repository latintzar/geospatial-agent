#!/usr/bin/env python3
"""Quick test suite with shorter timeouts"""

import requests
import json
import time
from datetime import datetime

API_URL = "http://localhost:8000/chat"
TIMEOUT = 45  # Shorter timeout

TESTS = [
    # Location (1-10)
    ("Location", "Where is Shibuya in Tokyo?"),
    ("Location", "Show boundary of Brooklyn"),
    ("Location", "Coffee shops in Paris"),
    ("Location", "Restaurants near Colosseum Rome"),
    ("Location", "Area of Soho London"),
    ("Location", "Where is Wall Street?"),
    ("Location", "Gyms in Miami"),
    ("Location", "Boundary of Manhattan"),
    ("Location", "Bars in Mexico City"),
    ("Location", "Golden Gate Bridge location"),
    
    # Climate (11-20)
    ("Climate", "Flood risk Miami"),
    ("Climate", "Temperature in Phoenix"),
    ("Climate", "Elevation of Denver"),
    ("Climate", "Bangkok flood risk"),
    ("Climate", "Weather risk Paris"),
    ("Climate", "Mexico City elevation"),
    ("Climate", "Dubai climate"),
    ("Climate", "Singapore floods"),
    ("Climate", "La Paz elevation"),
    ("Climate", "Houston heat waves"),
    
    # Population (21-30)
    ("Population", "Population density Tokyo"),
    ("Population", "Crowded areas Manhattan"),
    ("Population", "Mumbai population density"),
    ("Population", "Mexico City population"),
    ("Population", "London population"),
    ("Population", "Lagos density"),
    ("Population", "São Paulo population"),
    ("Population", "Cairo population"),
    ("Population", "Berlin population"),
    ("Population", "Singapore density"),
    
    # Agriculture (31-40)
    ("Agriculture", "Cocoa production Ghana"),
    ("Agriculture", "Coffee Colombia"),
    ("Agriculture", "Rice Vietnam"),
    ("Agriculture", "Crops Nigeria"),
    ("Agriculture", "Wheat India"),
    ("Agriculture", "Sugarcane Brazil"),
    ("Agriculture", "Banana Ecuador"),
    ("Agriculture", "Maize Kenya"),
    ("Agriculture", "Cotton Pakistan"),
    ("Agriculture", "Soybean Argentina"),
    
    # HDX (41-50)
    ("HDX", "Hospitals Kenya"),
    ("HDX", "Refugee camps South Sudan"),
    ("HDX", "Health facilities Bangladesh"),
    ("HDX", "Food markets Ethiopia"),
    ("HDX", "Schools Uganda"),
    ("HDX", "Water points Somalia"),
    ("HDX", "Airports DRC"),
    ("HDX", "Conflict Yemen"),
    ("HDX", "Aid organizations Syria"),
    ("HDX", "Clinics Afghanistan"),
    
    # News (51-60)
    ("News", "Ukraine news"),
    ("News", "Paris protests"),
    ("News", "Asia floods"),
    ("News", "Tesla sentiment"),
    ("News", "Middle East conflicts"),
    ("News", "Climate change trends"),
    ("News", "Protest photos"),
    ("News", "US election coverage"),
    ("News", "Food prices news"),
    ("News", "South America disasters"),
    
    # Trade (61-70)
    ("Trade", "Ghana cocoa exports"),
    ("Trade", "US coffee imports"),
    ("Trade", "Saudi Arabia oil exports"),
    ("Trade", "Brazil soybean exports"),
    ("Trade", "Top cocoa exporters"),
    ("Trade", "China electronics exports"),
    ("Trade", "Colombia coffee routes"),
    ("Trade", "Wheat importers"),
    ("Trade", "India tea trade"),
    ("Trade", "Thailand rubber exports"),
    
    # Wealth (71-80)
    ("Wealth", "Wealthy areas Mexico City"),
    ("Wealth", "Income levels Lagos"),
    ("Wealth", "High income Mumbai"),
    ("Wealth", "Rich areas São Paulo"),
    ("Wealth", "Wealth Nairobi"),
    ("Wealth", "Spending power Jakarta"),
    ("Wealth", "Luxury store Manila"),
    ("Wealth", "Affluent Bogotá"),
    ("Wealth", "Wealth Cairo"),
    ("Wealth", "Economic levels Bangkok"),
    
    # Routes (81-90)
    ("Routes", "Drive Paris to Berlin"),
    ("Routes", "Ghana cocoa to port"),
    ("Routes", "Distance NYC to LA"),
    ("Routes", "Coffee farm to Bogotá"),
    ("Routes", "London to Edinburgh"),
    ("Routes", "Soybean to Santos port"),
    ("Routes", "Mumbai to Delhi route"),
    ("Routes", "Tokyo to Osaka"),
    ("Routes", "Nairobi to Mombasa"),
    ("Routes", "Mexico City to Guadalajara"),
    
    # Complex (91-100)
    ("Complex", "Coffee shop location Lisbon"),
    ("Complex", "Ghana cocoa supply chain"),
    ("Complex", "Best clinic location Kenya"),
    ("Complex", "Agriculture investment Nigeria"),
    ("Complex", "Bangkok flood vs population"),
    ("Complex", "Colombia coffee near ports"),
    ("Complex", "Underserved health Ethiopia"),
    ("Complex", "Retail Mexico City"),
    ("Complex", "Ivory Coast chocolate supply"),
    ("Complex", "Warehouse near São Paulo"),
]

def run_test(num, cat, query):
    print(f"\n[{num}/100] [{cat}] {query}")
    try:
        r = requests.post(API_URL, json={"message": query, "model": "gemini-2.5-flash"}, timeout=TIMEOUT)
        if r.ok:
            d = r.json()
            tools = d.get("tools_used", [])
            status = "✅" if tools else "⚠️"
            print(f"  {status} Tools: {tools}")
            return {"status": status, "tools": tools}
        else:
            print(f"  ❌ HTTP {r.status_code}")
            return {"status": "❌HTTP", "error": r.status_code}
    except requests.exceptions.Timeout:
        print(f"  ⏱️ TIMEOUT")
        return {"status": "⏱️TIMEOUT"}
    except Exception as e:
        print(f"  ❌ {e}")
        return {"status": "❌ERROR", "error": str(e)}

def main():
    print(f"🧪 LEO QUICK TESTS - {len(TESTS)} tests @ {TIMEOUT}s timeout")
    print(f"Started: {datetime.now()}")
    
    results = []
    cats = {}
    
    for i, (cat, q) in enumerate(TESTS, 1):
        r = run_test(i, cat, q)
        r["cat"] = cat
        r["query"] = q
        results.append(r)
        
        if cat not in cats:
            cats[cat] = {"pass": 0, "warn": 0, "timeout": 0, "error": 0}
        s = r["status"]
        if "✅" in s:
            cats[cat]["pass"] += 1
        elif "⚠" in s:
            cats[cat]["warn"] += 1
        elif "⏱" in s:
            cats[cat]["timeout"] += 1
        else:
            cats[cat]["error"] += 1
        
        time.sleep(0.5)
    
    print("\n" + "="*50)
    print("📊 SUMMARY")
    print("="*50)
    
    total = {"pass": 0, "warn": 0, "timeout": 0, "error": 0}
    for cat, s in cats.items():
        print(f"{cat:12} ✅{s['pass']:2} ⚠️{s['warn']:2} ⏱️{s['timeout']:2} ❌{s['error']:2}")
        for k in total:
            total[k] += s[k]
    
    print("-"*50)
    print(f"{'TOTAL':12} ✅{total['pass']:2} ⚠️{total['warn']:2} ⏱️{total['timeout']:2} ❌{total['error']:2}")
    
    with open("quick_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()

