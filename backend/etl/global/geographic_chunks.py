"""
Geographic Chunking Configuration for Earth Matrix Build

This module defines the geographic chunks (countries/regions) for parallel
processing of the global Earth Matrix. Countries are ordered by GDP to
prioritize high-value markets.

Usage:
    from geographic_chunks import COUNTRY_CHUNKS, generate_processing_queue
    
    # Get all chunks ordered by GDP
    queue = generate_processing_queue()
    
    # Get only top 20 economies
    queue = generate_processing_queue(max_gdp_rank=20)
    
    # Get total estimated cost
    total = sum(c['est_cost_usd'] for c in COUNTRY_CHUNKS.values() if 'est_cost_usd' in c)
    
    # TEST MODE: Run on a small region for benchmarking
    # Set environment variables:
    #   TEST_MODE=true
    #   TEST_REGION=hoxton  (or greater_london, uk)
"""

from typing import Dict, List, Optional, Tuple
import os

# =============================================================================
# TEST MODE CONFIGURATION
# =============================================================================

TEST_MODE = os.environ.get('TEST_MODE', 'false').lower() == 'true'
TEST_REGION = os.environ.get('TEST_REGION', 'hoxton')

# Test region definitions for benchmarking
TEST_REGIONS: Dict[str, Dict] = {
    'hoxton': {
        'chunk_id': 'TEST_HOXTON',
        'name': 'Hoxton, London (Test)',
        'bbox': [-0.095, 51.525, -0.070, 51.540],
        'area_km2': 4.25,
        'gdp_rank': 0,  # Test priority
        'emoji': '🧪',
    },
    'greater_london': {
        'chunk_id': 'TEST_LONDON',
        'name': 'Greater London (Test)',
        'bbox': [-0.5103, 51.2867, 0.3340, 51.6918],
        'area_km2': 1572,
        'gdp_rank': 0,
        'emoji': '🧪',
    },
    'uk': {
        'chunk_id': 'TEST_UK',
        'name': 'United Kingdom (Test)',
        'bbox': [-8.6, 49.9, 1.8, 60.9],
        'area_km2': 243610,
        'gdp_rank': 0,
        'emoji': '🧪',
    },
    'france': {
        'chunk_id': 'TEST_FRANCE',
        'name': 'France (Test)',
        'bbox': [-5.14, 41.36, 9.56, 51.09],
        'area_km2': 640679,
        'gdp_rank': 0,
        'emoji': '🇫🇷',
    },
}

# =============================================================================
# GEOGRAPHIC CHUNK DEFINITIONS
# =============================================================================

COUNTRY_CHUNKS: Dict[str, Dict] = {
    
    # =========================================================================
    # TIER 1: G7 + China (~65% of world GDP)
    # =========================================================================
    
    "USA": {
        "gdp_rank": 1,
        "gdp_trillion": 28.78,
        "name": "United States",
        "emoji": "🇺🇸",
        "bbox": [-125.0, 24.5, -66.9, 49.4],  # Continental US
        "sub_chunks": {
            "WEST": {"bbox": [-125.0, 31.3, -102.0, 49.4], "states": "CA, OR, WA, NV, AZ, UT, CO, NM"},
            "CENTRAL": {"bbox": [-102.0, 25.8, -89.0, 49.4], "states": "TX, OK, KS, NE, SD, ND, MN, IA, MO, AR, LA"},
            "EAST": {"bbox": [-89.0, 24.5, -66.9, 49.4], "states": "FL, GA, SC, NC, VA, WV, OH, MI, IN, IL, WI, NY, PA, NJ, etc."},
            "ALASKA": {"bbox": [-180.0, 51.2, -129.0, 71.4]},
            "HAWAII": {"bbox": [-160.3, 18.9, -154.8, 22.2]},
        },
        "est_hexes_millions": 4300,
        "est_cost_usd": 90,
    },
    
    "CHINA": {
        "gdp_rank": 2,
        "gdp_trillion": 18.53,
        "name": "China",
        "emoji": "🇨🇳",
        "bbox": [73.5, 18.2, 134.8, 53.6],
        "sub_chunks": {
            "NORTH": {"bbox": [73.5, 35.0, 134.8, 53.6], "regions": "Beijing, Tianjin, Hebei, Inner Mongolia"},
            "EAST": {"bbox": [116.0, 24.0, 134.8, 35.0], "regions": "Shanghai, Jiangsu, Zhejiang, Fujian"},
            "SOUTH": {"bbox": [97.5, 18.2, 116.0, 26.4], "regions": "Guangdong, Guangxi, Hainan, Hong Kong"},
            "WEST": {"bbox": [73.5, 26.4, 97.5, 45.0], "regions": "Xinjiang, Tibet, Qinghai, Gansu"},
            "CENTRAL": {"bbox": [97.5, 26.4, 116.0, 35.0], "regions": "Sichuan, Chongqing, Hubei, Hunan"},
        },
        "est_hexes_millions": 4200,
        "est_cost_usd": 80,
    },
    
    "GERMANY": {
        "gdp_rank": 3,
        "gdp_trillion": 4.59,
        "name": "Germany",
        "emoji": "🇩🇪",
        "bbox": [5.9, 47.3, 15.0, 55.1],
        "est_hexes_millions": 155,
        "est_cost_usd": 12,
    },
    
    "JAPAN": {
        "gdp_rank": 4,
        "gdp_trillion": 4.11,
        "name": "Japan",
        "emoji": "🇯🇵",
        "bbox": [122.9, 24.0, 153.99, 45.5],
        "est_hexes_millions": 165,
        "est_cost_usd": 12,
    },
    
    "INDIA": {
        "gdp_rank": 5,
        "gdp_trillion": 3.94,
        "name": "India",
        "emoji": "🇮🇳",
        "bbox": [68.2, 6.8, 97.4, 35.5],
        "sub_chunks": {
            "NORTH": {"bbox": [72.0, 26.0, 88.0, 35.5], "regions": "Delhi, UP, Punjab, Rajasthan"},
            "SOUTH": {"bbox": [73.0, 8.0, 80.3, 15.5], "regions": "Tamil Nadu, Kerala, Karnataka"},
            "WEST": {"bbox": [68.2, 15.5, 76.0, 26.0], "regions": "Gujarat, Maharashtra, Goa"},
            "EAST": {"bbox": [80.0, 15.0, 97.4, 28.0], "regions": "West Bengal, Odisha, Bihar"},
        },
        "est_hexes_millions": 1400,
        "est_cost_usd": 45,
    },
    
    "UK": {
        "gdp_rank": 6,
        "gdp_trillion": 3.50,
        "name": "United Kingdom",
        "emoji": "🇬🇧",
        "bbox": [-8.6, 49.9, 1.8, 60.9],
        "est_hexes_millions": 105,
        "est_cost_usd": 10,
    },
    
    "FRANCE": {
        "gdp_rank": 7,
        "gdp_trillion": 3.13,
        "name": "France",
        "emoji": "🇫🇷",
        "bbox": [-5.2, 41.3, 9.6, 51.1],
        "est_hexes_millions": 280,
        "est_cost_usd": 12,
        "notes": "Metropolitan France only; excludes overseas territories",
    },
    
    "ITALY": {
        "gdp_rank": 8,
        "gdp_trillion": 2.33,
        "name": "Italy",
        "emoji": "🇮🇹",
        "bbox": [6.6, 36.6, 18.5, 47.1],
        "est_hexes_millions": 131,
        "est_cost_usd": 10,
    },
    
    "CANADA": {
        "gdp_rank": 9,
        "gdp_trillion": 2.24,
        "name": "Canada",
        "emoji": "🇨🇦",
        "bbox": [-141.0, 41.7, -52.6, 83.1],
        "sub_chunks": {
            "WEST": {"bbox": [-141.0, 48.3, -110.0, 60.0], "provinces": "BC, Alberta"},
            "CENTRAL": {"bbox": [-110.0, 49.0, -89.0, 55.0], "provinces": "Saskatchewan, Manitoba"},
            "EAST": {"bbox": [-89.0, 41.7, -52.6, 52.0], "provinces": "Ontario, Quebec, Atlantic"},
        },
        "populated_only": True,
        "est_hexes_millions": 600,
        "est_cost_usd": 30,
        "notes": "Northern territories excluded (sparsely populated)",
    },
    
    # =========================================================================
    # TIER 2: Next 10 Economies (~15% of world GDP)
    # =========================================================================
    
    "BRAZIL": {
        "gdp_rank": 10,
        "gdp_trillion": 2.17,
        "name": "Brazil",
        "emoji": "🇧🇷",
        "bbox": [-73.99, -33.75, -28.85, 5.27],
        "sub_chunks": {
            "SOUTHEAST": {"bbox": [-53.0, -25.0, -39.0, -14.0], "states": "São Paulo, Rio, Minas Gerais"},
            "SOUTH": {"bbox": [-57.6, -33.75, -48.0, -22.5], "states": "Paraná, Santa Catarina, Rio Grande do Sul"},
            "NORTHEAST": {"bbox": [-48.0, -18.0, -34.8, -2.0], "states": "Bahia, Pernambuco, Ceará"},
            "NORTH": {"bbox": [-73.99, -10.0, -48.0, 5.27], "states": "Amazonas, Pará"},
            "CENTRAL": {"bbox": [-60.0, -24.0, -48.0, -10.0], "states": "Goiás, Mato Grosso"},
        },
        "est_hexes_millions": 3700,
        "est_cost_usd": 55,
    },
    
    "RUSSIA": {
        "gdp_rank": 11,
        "gdp_trillion": 2.06,
        "name": "Russia",
        "emoji": "🇷🇺",
        "bbox": [19.6, 41.2, 180.0, 81.9],
        "sub_chunks": {
            "EUROPEAN": {"bbox": [19.6, 45.0, 60.0, 70.0], "regions": "Moscow, St. Petersburg, European Russia"},
            "URAL": {"bbox": [55.0, 50.0, 75.0, 65.0], "regions": "Yekaterinburg, Chelyabinsk"},
            "SIBERIA_SOUTH": {"bbox": [75.0, 50.0, 120.0, 60.0], "regions": "Novosibirsk, Krasnoyarsk"},
            "FAR_EAST": {"bbox": [120.0, 42.0, 180.0, 55.0], "regions": "Vladivostok, Khabarovsk"},
        },
        "populated_only": True,
        "est_hexes_millions": 2500,
        "est_cost_usd": 40,
        "notes": "Arctic regions excluded",
    },
    
    "MEXICO": {
        "gdp_rank": 12,
        "gdp_trillion": 1.79,
        "name": "Mexico",
        "emoji": "🇲🇽",
        "bbox": [-118.4, 14.5, -86.7, 32.7],
        "est_hexes_millions": 855,
        "est_cost_usd": 22,
    },
    
    "SOUTH_KOREA": {
        "gdp_rank": 13,
        "gdp_trillion": 1.76,
        "name": "South Korea",
        "emoji": "🇰🇷",
        "bbox": [124.6, 33.1, 131.0, 38.6],
        "est_hexes_millions": 44,
        "est_cost_usd": 6,
    },
    
    "AUSTRALIA": {
        "gdp_rank": 14,
        "gdp_trillion": 1.72,
        "name": "Australia",
        "emoji": "🇦🇺",
        "bbox": [113.3, -43.6, 153.6, -10.7],
        "sub_chunks": {
            "EAST_COAST": {"bbox": [140.0, -39.0, 154.0, -10.7], "states": "NSW, Queensland, Victoria"},
            "SOUTH": {"bbox": [129.0, -38.0, 141.0, -31.0], "states": "South Australia"},
            "WEST_COAST": {"bbox": [113.3, -35.0, 129.0, -20.0], "states": "Western Australia (coastal)"},
        },
        "populated_only": True,
        "est_hexes_millions": 800,
        "est_cost_usd": 18,
        "notes": "Interior desert regions excluded",
    },
    
    "SPAIN": {
        "gdp_rank": 15,
        "gdp_trillion": 1.58,
        "name": "Spain",
        "emoji": "🇪🇸",
        "bbox": [-9.3, 35.9, 4.3, 43.8],
        "est_hexes_millions": 220,
        "est_cost_usd": 12,
    },
    
    "INDONESIA": {
        "gdp_rank": 16,
        "gdp_trillion": 1.47,
        "name": "Indonesia",
        "emoji": "🇮🇩",
        "bbox": [95.0, -11.0, 141.0, 6.1],
        "sub_chunks": {
            "JAVA": {"bbox": [105.2, -8.8, 114.6, -5.9], "notes": "Most populated island"},
            "SUMATRA": {"bbox": [95.0, -6.0, 108.0, 6.1]},
            "KALIMANTAN": {"bbox": [108.0, -4.0, 119.0, 4.2]},
            "SULAWESI": {"bbox": [119.0, -6.0, 125.0, 2.0]},
            "PAPUA": {"bbox": [129.0, -9.0, 141.0, 0.0]},
        },
        "est_hexes_millions": 830,
        "est_cost_usd": 22,
    },
    
    "NETHERLANDS": {
        "gdp_rank": 17,
        "gdp_trillion": 1.17,
        "name": "Netherlands",
        "emoji": "🇳🇱",
        "bbox": [3.4, 50.8, 7.2, 53.5],
        "est_hexes_millions": 18,
        "est_cost_usd": 4,
    },
    
    "SAUDI_ARABIA": {
        "gdp_rank": 18,
        "gdp_trillion": 1.11,
        "name": "Saudi Arabia",
        "emoji": "🇸🇦",
        "bbox": [34.5, 16.4, 55.7, 32.2],
        "populated_only": True,
        "est_hexes_millions": 400,
        "est_cost_usd": 10,
        "notes": "Desert interior regions reduced",
    },
    
    "TURKEY": {
        "gdp_rank": 19,
        "gdp_trillion": 1.11,
        "name": "Turkey",
        "emoji": "🇹🇷",
        "bbox": [26.0, 35.8, 44.8, 42.1],
        "est_hexes_millions": 340,
        "est_cost_usd": 12,
    },
    
    # =========================================================================
    # TIER 3: Emerging Markets (20-35)
    # =========================================================================
    
    "SWITZERLAND": {
        "gdp_rank": 20,
        "gdp_trillion": 0.91,
        "name": "Switzerland",
        "emoji": "🇨🇭",
        "bbox": [6.0, 45.8, 10.5, 47.8],
        "est_hexes_millions": 18,
        "est_cost_usd": 4,
    },
    
    "POLAND": {
        "gdp_rank": 21,
        "gdp_trillion": 0.84,
        "name": "Poland",
        "emoji": "🇵🇱",
        "bbox": [14.1, 49.0, 24.2, 54.8],
        "est_hexes_millions": 136,
        "est_cost_usd": 10,
    },
    
    "TAIWAN": {
        "gdp_rank": 22,
        "gdp_trillion": 0.79,
        "name": "Taiwan",
        "emoji": "🇹🇼",
        "bbox": [119.5, 21.9, 122.0, 25.3],
        "est_hexes_millions": 16,
        "est_cost_usd": 4,
    },
    
    "BELGIUM": {
        "gdp_rank": 23,
        "gdp_trillion": 0.63,
        "name": "Belgium",
        "emoji": "🇧🇪",
        "bbox": [2.5, 49.5, 6.4, 51.5],
        "est_hexes_millions": 13,
        "est_cost_usd": 4,
    },
    
    "SWEDEN": {
        "gdp_rank": 24,
        "gdp_trillion": 0.59,
        "name": "Sweden",
        "emoji": "🇸🇪",
        "bbox": [11.1, 55.3, 24.2, 69.1],
        "est_hexes_millions": 196,
        "est_cost_usd": 8,
    },
    
    "IRELAND": {
        "gdp_rank": 25,
        "gdp_trillion": 0.55,
        "name": "Ireland",
        "emoji": "🇮🇪",
        "bbox": [-10.5, 51.4, -6.0, 55.4],
        "est_hexes_millions": 30,
        "est_cost_usd": 5,
    },
    
    "AUSTRIA": {
        "gdp_rank": 26,
        "gdp_trillion": 0.52,
        "name": "Austria",
        "emoji": "🇦🇹",
        "bbox": [9.5, 46.4, 17.2, 49.0],
        "est_hexes_millions": 36,
        "est_cost_usd": 5,
    },
    
    "ISRAEL": {
        "gdp_rank": 27,
        "gdp_trillion": 0.52,
        "name": "Israel",
        "emoji": "🇮🇱",
        "bbox": [34.3, 29.5, 35.9, 33.3],
        "est_hexes_millions": 10,
        "est_cost_usd": 4,
    },
    
    "NORWAY": {
        "gdp_rank": 28,
        "gdp_trillion": 0.49,
        "name": "Norway",
        "emoji": "🇳🇴",
        "bbox": [4.6, 58.0, 31.1, 71.2],
        "populated_only": True,
        "est_hexes_millions": 140,
        "est_cost_usd": 8,
    },
    
    "UAE": {
        "gdp_rank": 29,
        "gdp_trillion": 0.50,
        "name": "United Arab Emirates",
        "emoji": "🇦🇪",
        "bbox": [51.5, 22.6, 56.4, 26.1],
        "est_hexes_millions": 36,
        "est_cost_usd": 5,
    },
    
    "SINGAPORE": {
        "gdp_rank": 30,
        "gdp_trillion": 0.50,
        "name": "Singapore",
        "emoji": "🇸🇬",
        "bbox": [103.6, 1.2, 104.0, 1.5],
        "est_hexes_millions": 0.3,
        "est_cost_usd": 2,
    },
    
    "THAILAND": {
        "gdp_rank": 31,
        "gdp_trillion": 0.50,
        "name": "Thailand",
        "emoji": "🇹🇭",
        "bbox": [97.3, 5.6, 105.6, 20.5],
        "est_hexes_millions": 223,
        "est_cost_usd": 12,
    },
    
    "VIETNAM": {
        "gdp_rank": 32,
        "gdp_trillion": 0.47,
        "name": "Vietnam",
        "emoji": "🇻🇳",
        "bbox": [102.1, 8.4, 109.5, 23.4],
        "est_hexes_millions": 144,
        "est_cost_usd": 10,
    },
    
    "MALAYSIA": {
        "gdp_rank": 33,
        "gdp_trillion": 0.44,
        "name": "Malaysia",
        "emoji": "🇲🇾",
        "bbox": [99.6, 0.9, 119.3, 7.4],
        "est_hexes_millions": 144,
        "est_cost_usd": 10,
    },
    
    "DENMARK": {
        "gdp_rank": 34,
        "gdp_trillion": 0.41,
        "name": "Denmark",
        "emoji": "🇩🇰",
        "bbox": [8.1, 54.6, 15.2, 57.8],
        "est_hexes_millions": 19,
        "est_cost_usd": 4,
    },
    
    "PHILIPPINES": {
        "gdp_rank": 35,
        "gdp_trillion": 0.44,
        "name": "Philippines",
        "emoji": "🇵🇭",
        "bbox": [116.9, 4.6, 126.6, 21.1],
        "est_hexes_millions": 130,
        "est_cost_usd": 10,
    },
    
    # =========================================================================
    # TIER 4: Regional Bundles (36+)
    # =========================================================================
    
    "EASTERN_EUROPE": {
        "gdp_rank": 36,
        "name": "Eastern Europe",
        "emoji": "🇪🇺",
        "bbox": [13.0, 40.0, 40.0, 55.0],
        "countries": [
            "Czech Republic", "Romania", "Hungary", "Ukraine", 
            "Slovakia", "Bulgaria", "Croatia", "Slovenia", 
            "Serbia", "Belarus", "Lithuania", "Latvia", "Estonia"
        ],
        "est_hexes_millions": 1200,
        "est_cost_usd": 35,
    },
    
    "SOUTH_AMERICA_OTHER": {
        "gdp_rank": 46,
        "name": "South America (excl. Brazil)",
        "emoji": "🌎",
        "bbox": [-81.4, -56.0, -34.8, 12.5],
        "countries": [
            "Argentina", "Chile", "Colombia", "Peru", 
            "Ecuador", "Venezuela", "Uruguay", "Paraguay", "Bolivia"
        ],
        "est_hexes_millions": 2800,
        "est_cost_usd": 40,
    },
    
    "MIDDLE_EAST_OTHER": {
        "gdp_rank": 56,
        "name": "Middle East (excl. Israel, UAE, Saudi)",
        "emoji": "🌍",
        "bbox": [24.7, 12.4, 63.3, 42.0],
        "countries": [
            "Egypt", "Iran", "Iraq", "Qatar", "Kuwait", 
            "Oman", "Jordan", "Lebanon", "Bahrain", "Syria"
        ],
        "populated_only": True,
        "est_hexes_millions": 1500,
        "est_cost_usd": 30,
    },
    
    "AFRICA": {
        "gdp_rank": 66,
        "name": "Africa",
        "emoji": "🌍",
        "bbox": [-17.5, -35.0, 51.4, 37.3],
        "countries": [
            "Nigeria", "South Africa", "Kenya", "Morocco", 
            "Algeria", "Tunisia", "Ghana", "Ethiopia", 
            "Tanzania", "Côte d'Ivoire", "Egypt"
        ],
        "populated_only": True,
        "est_hexes_millions": 5000,
        "est_cost_usd": 45,
        "notes": "Desert regions (Sahara) excluded",
    },
    
    "CENTRAL_ASIA": {
        "gdp_rank": 81,
        "name": "Central Asia",
        "emoji": "🌏",
        "bbox": [46.5, 35.1, 119.9, 55.4],
        "countries": [
            "Kazakhstan", "Uzbekistan", "Turkmenistan", 
            "Kyrgyzstan", "Tajikistan", "Mongolia"
        ],
        "populated_only": True,
        "est_hexes_millions": 800,
        "est_cost_usd": 18,
    },
    
    "SMALL_NATIONS": {
        "gdp_rank": 91,
        "name": "Small Nations",
        "emoji": "🏝️",
        "countries": [
            "Luxembourg", "Malta", "Iceland", "Cyprus", 
            "Monaco", "Liechtenstein", "Andorra", "San Marino"
        ],
        "est_hexes_millions": 5,
        "est_cost_usd": 12,
    },
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_processing_queue(
    max_gdp_rank: Optional[int] = None,
    include_sub_chunks: bool = True,
    test_mode: Optional[bool] = None,
    test_region: Optional[str] = None,
) -> List[Dict]:
    """
    Generate processing queue ordered by GDP.
    
    Args:
        max_gdp_rank: Only include countries up to this rank (for budget control)
        include_sub_chunks: If True, split countries with sub_chunks into separate jobs
        test_mode: If True, returns only the test region (overrides TEST_MODE env var)
        test_region: Test region name (overrides TEST_REGION env var)
    
    Returns:
        List of chunks to process, ordered by economic priority
    
    Environment Variables:
        TEST_MODE: Set to 'true' to enable test mode
        TEST_REGION: Set to 'hoxton', 'greater_london', or 'uk'
    """
    # Check for test mode (arg overrides env var)
    is_test_mode = test_mode if test_mode is not None else TEST_MODE
    region_name = test_region if test_region is not None else TEST_REGION
    
    # TEST MODE: Return only the test region
    if is_test_mode:
        if region_name not in TEST_REGIONS:
            raise ValueError(f"Unknown test region: {region_name}. Options: {list(TEST_REGIONS.keys())}")
        
        region = TEST_REGIONS[region_name]
        return [{
            'chunk_id': region['chunk_id'],
            'bbox': region['bbox'],
            'name': region['name'],
            'parent_country': 'TEST',
            'gdp_rank': 0,
            'gdp_trillion': 0,
            'priority': 0,
            'emoji': region.get('emoji', '🧪'),
            'populated_only': False,
            'area_km2': region.get('area_km2', 0),
            'is_test': True,
        }]
    
    # Normal mode: generate full queue
    queue = []
    
    for country_id, config in sorted(
        COUNTRY_CHUNKS.items(), 
        key=lambda x: x[1].get('gdp_rank', 999)
    ):
        if max_gdp_rank and config.get('gdp_rank', 999) > max_gdp_rank:
            continue
        
        base_info = {
            'parent_country': country_id,
            'gdp_rank': config['gdp_rank'],
            'gdp_trillion': config.get('gdp_trillion', 0),
            'name': config.get('name', country_id),
            'emoji': config.get('emoji', '🌍'),
            'populated_only': config.get('populated_only', False),
        }
        
        # If country has sub-chunks, add each as separate job
        if include_sub_chunks and 'sub_chunks' in config:
            for sub_id, sub_config in config['sub_chunks'].items():
                queue.append({
                    'chunk_id': f"{country_id}_{sub_id}",
                    'bbox': sub_config['bbox'],
                    'priority': config['gdp_rank'],
                    **base_info,
                })
        else:
            queue.append({
                'chunk_id': country_id,
                'bbox': config.get('bbox'),
                'priority': config['gdp_rank'],
                **base_info,
            })
    
    return queue


def get_total_estimated_cost(max_gdp_rank: Optional[int] = None) -> float:
    """
    Get total estimated cost for processing.
    
    Args:
        max_gdp_rank: Only include countries up to this rank
    
    Returns:
        Total estimated cost in USD
    """
    total = 0.0
    for config in COUNTRY_CHUNKS.values():
        if max_gdp_rank and config.get('gdp_rank', 999) > max_gdp_rank:
            continue
        total += config.get('est_cost_usd', 0)
    return total


def get_cumulative_gdp_coverage(max_gdp_rank: int) -> float:
    """
    Get cumulative GDP coverage for countries up to given rank.
    
    Args:
        max_gdp_rank: Include countries up to this rank
    
    Returns:
        Approximate percentage of world GDP covered
    """
    # World GDP ~$105 trillion (2024)
    WORLD_GDP = 105.0
    
    covered = 0.0
    for config in COUNTRY_CHUNKS.values():
        if config.get('gdp_rank', 999) <= max_gdp_rank:
            covered += config.get('gdp_trillion', 0)
    
    return (covered / WORLD_GDP) * 100


def get_chunk_by_bbox(
    lon: float, 
    lat: float
) -> Optional[str]:
    """
    Find which chunk a coordinate belongs to.
    
    Args:
        lon: Longitude
        lat: Latitude
    
    Returns:
        chunk_id or None if not in any defined chunk
    """
    for country_id, config in COUNTRY_CHUNKS.items():
        bbox = config.get('bbox')
        if not bbox:
            continue
        
        min_lon, min_lat, max_lon, max_lat = bbox
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            # Check sub-chunks for more specific match
            if 'sub_chunks' in config:
                for sub_id, sub_config in config['sub_chunks'].items():
                    sub_bbox = sub_config['bbox']
                    if (sub_bbox[0] <= lon <= sub_bbox[2] and 
                        sub_bbox[1] <= lat <= sub_bbox[3]):
                        return f"{country_id}_{sub_id}"
            return country_id
    
    return None


def print_queue_summary(queue: List[Dict]) -> None:
    """Print a summary of the processing queue."""
    print(f"\n{'='*70}")
    print(f"GEOGRAPHIC PROCESSING QUEUE")
    print(f"{'='*70}\n")
    
    total_cost = 0.0
    
    for i, chunk in enumerate(queue, 1):
        cost = COUNTRY_CHUNKS.get(chunk['parent_country'], {}).get('est_cost_usd', 0)
        if 'sub_chunks' in COUNTRY_CHUNKS.get(chunk['parent_country'], {}):
            # Distribute cost across sub-chunks
            num_sub = len(COUNTRY_CHUNKS[chunk['parent_country']]['sub_chunks'])
            cost = cost / num_sub
        
        total_cost += cost
        
        print(f"{i:3}. {chunk['emoji']} {chunk['chunk_id']:25} | "
              f"GDP Rank: {chunk['gdp_rank']:3} | "
              f"Est. ${cost:.0f}")
    
    print(f"\n{'='*70}")
    print(f"Total chunks: {len(queue)}")
    print(f"Estimated total cost: ${total_cost:.0f}")
    print(f"{'='*70}\n")


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    # Print full queue
    queue = generate_processing_queue()
    print_queue_summary(queue)
    
    # Print tier summaries
    print("\n📊 TIER SUMMARIES")
    print("-" * 50)
    
    for max_rank, tier_name in [(9, "Tier 1 (G7+China)"), 
                                 (19, "Tier 2 (+Next 10)"),
                                 (35, "Tier 3 (+Emerging)"),
                                 (100, "All Countries")]:
        cost = get_total_estimated_cost(max_rank)
        gdp = get_cumulative_gdp_coverage(max_rank)
        print(f"{tier_name:25} | Cost: ${cost:>6.0f} | GDP Coverage: {gdp:>5.1f}%")

