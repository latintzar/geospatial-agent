"""
Agriculture & Crop Production Tools

Provides crop production data from MapSPAM 2020 v2.0 (Spatial Production Allocation Model).
Data source: data/mapspam/spam2020V2r0_global_*/

MapSPAM provides 10km (5 arc-minute) grid-level production estimates for 46 crops globally.
This tool converts them to H3 hexagons for integration with our mapping system.

Data Files:
- spam2020V2r0_global_production/   - Production in metric tons (mt)
- spam2020V2r0_global_harvested_area/ - Harvested area in hectares (ha)
- spam2020V2r0_global_physical_area/  - Physical area in hectares (ha)
- spam2020V2r0_global_yield/          - Yield in kg/ha

Technology Types:
- TA = All technologies (irrigated + rainfed)
- TI = Irrigated only
- TR = Rainfed only

Usage:
    from tools_agriculture import fetch_crop_production
    
    # Get cocoa production in Ghana
    result = fetch_crop_production("GHA", "cocoa")
    # Returns: [{'hex': '89...', 'production_mt': 5000}, ...]

System Prompt Context:
    'Use this tool when the user asks about crops, agriculture, raw material supply,
    or specific commodities like Cocoa, Coffee, Cotton, Maize, Rice, etc.'
"""

import duckdb
import pandas as pd
import h3
import logging
from typing import Optional, Literal, Dict, Any, Union, List
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import masking utility from utils_spatial (for Focus + Context pattern)
try:
    from ..utils_spatial import mask_layer_by_aoi
except ImportError:
    # When run directly or from different path
    try:
        from ..utils_spatial import mask_layer_by_aoi
    except ImportError:
        # Fallback: no masking available
        mask_layer_by_aoi = None
        logger.warning("mask_layer_by_aoi not available - Focus+Context masking disabled")

# Default H3 resolution for agriculture data
# Res 6 = ~3km edge, good for regional crop data (creates nice choropleth-style heatmap)
# Res 9 was too granular for 10km source data - looked like noise
DEFAULT_H3_RESOLUTION = 6

# Path to MapSPAM data (relative to this file's directory)
MAPSPAM_DATA_PATH = Path(__file__).parent.parent / "data" / "mapspam"

# =============================================================================
# COUNTRY NAME TO ISO3 MAPPING (for natural language queries)
# =============================================================================

COUNTRY_NAME_TO_ISO3 = {
    'ghana': 'GHA', 'nigeria': 'NGA', 'kenya': 'KEN', 'uganda': 'UGA',
    'ethiopia': 'ETH', 'tanzania': 'TZA', 'south africa': 'ZAF',
    'brazil': 'BRA', 'colombia': 'COL', 'mexico': 'MEX', 'peru': 'PER',
    'india': 'IND', 'vietnam': 'VNM', 'indonesia': 'IDN', 'thailand': 'THA',
    'philippines': 'PHL', 'china': 'CHN', 'pakistan': 'PAK', 'bangladesh': 'BGD',
    'usa': 'USA', 'united states': 'USA', 'uk': 'GBR', 'united kingdom': 'GBR',
    'france': 'FRA', 'germany': 'DEU', 'spain': 'ESP', 'italy': 'ITA',
    'ivory coast': 'CIV', 'cote divoire': 'CIV', 'cameroon': 'CMR',
    'ecuador': 'ECU', 'costa rica': 'CRI', 'honduras': 'HND', 'guatemala': 'GTM',
    'argentina': 'ARG', 'paraguay': 'PRY', 'bolivia': 'BOL', 'chile': 'CHL',
    'egypt': 'EGY', 'morocco': 'MAR', 'sudan': 'SDN', 'zimbabwe': 'ZWE',
    'zambia': 'ZMB', 'malawi': 'MWI', 'mozambique': 'MOZ', 'madagascar': 'MDG',
    'rwanda': 'RWA', 'burundi': 'BDI', 'democratic republic of congo': 'COD', 'dr congo': 'COD', 'drc': 'COD',
}

# =============================================================================
# ISO3 TO FIPS0 COUNTRY CODE MAPPING
# MapSPAM uses FIPS0 codes, not ISO3. This maps ISO3 -> FIPS0.
# =============================================================================

ISO3_TO_FIPS = {
    'AFG': 'AF',  # Afghanistan
    'ALB': 'AL',  # Albania
    'DZA': 'AG',  # Algeria
    'AGO': 'AO',  # Angola
    'ATG': 'AC',  # Antigua and Barbuda
    'ARG': 'AR',  # Argentina
    'ARM': 'AM',  # Armenia
    'AUS': 'AS',  # Australia
    'AUT': 'AU',  # Austria
    'AZE': 'AJ',  # Azerbaijan
    'BHS': 'BF',  # Bahamas
    'BHR': 'BA',  # Bahrain
    'BGD': 'BG',  # Bangladesh
    'BRB': 'BB',  # Barbados
    'BLR': 'BO',  # Belarus
    'BEL': 'BE',  # Belgium
    'BLZ': 'BH',  # Belize
    'BEN': 'BN',  # Benin
    'BTN': 'BT',  # Bhutan
    'BOL': 'BL',  # Bolivia
    'BIH': 'BK',  # Bosnia and Herzegovina
    'BWA': 'BC',  # Botswana
    'BRA': 'BR',  # Brazil
    'BRN': 'BX',  # Brunei Darussalam
    'BGR': 'BU',  # Bulgaria
    'BFA': 'UV',  # Burkina Faso
    'BDI': 'BY',  # Burundi
    'KHM': 'CB',  # Cambodia
    'CMR': 'CM',  # Cameroon
    'CAN': 'CA',  # Canada
    'CAF': 'CT',  # Central African Republic
    'TCD': 'CD',  # Chad
    'CHL': 'CI',  # Chile
    'CHN': 'CH',  # China
    'COL': 'CO',  # Colombia
    'COG': 'CF',  # Congo
    'CRI': 'CS',  # Costa Rica
    'CIV': 'IV',  # Cote d'Ivoire
    'HRV': 'HR',  # Croatia
    'CUB': 'CU',  # Cuba
    'CYP': 'CY',  # Cyprus
    'CZE': 'EZ',  # Czechia
    'PRK': 'KN',  # North Korea
    'COD': 'CG',  # Democratic Republic of the Congo
    'DNK': 'DA',  # Denmark
    'DJI': 'DJ',  # Djibouti
    'DMA': 'DO',  # Dominica
    'DOM': 'DR',  # Dominican Republic
    'ECU': 'EC',  # Ecuador
    'EGY': 'EG',  # Egypt
    'SLV': 'ES',  # El Salvador
    'GNQ': 'EK',  # Equatorial Guinea
    'ERI': 'ER',  # Eritrea
    'EST': 'EN',  # Estonia
    'ETH': 'ET',  # Ethiopia
    'FJI': 'FJ',  # Fiji
    'FIN': 'FI',  # Finland
    'FRA': 'FR',  # France
    'GAB': 'GB',  # Gabon
    'GMB': 'GA',  # Gambia
    'GEO': 'GG',  # Georgia
    'DEU': 'GM',  # Germany
    'GHA': 'GH',  # Ghana
    'GRC': 'GR',  # Greece
    'GRD': 'GJ',  # Grenada
    'GTM': 'GT',  # Guatemala
    'GIN': 'GV',  # Guinea
    'GNB': 'PU',  # Guinea-Bissau
    'GUY': 'GY',  # Guyana
    'HTI': 'HA',  # Haiti
    'HND': 'HO',  # Honduras
    'HUN': 'HU',  # Hungary
    'IND': 'IN',  # India
    'IDN': 'ID',  # Indonesia
    'IRN': 'IR',  # Iran
    'IRQ': 'IZ',  # Iraq
    'IRL': 'EI',  # Ireland
    'ISR': 'IS',  # Israel
    'ITA': 'IT',  # Italy
    'JAM': 'JM',  # Jamaica
    'JPN': 'JA',  # Japan
    'JOR': 'JO',  # Jordan
    'KAZ': 'KZ',  # Kazakhstan
    'KEN': 'KE',  # Kenya
    'KWT': 'KU',  # Kuwait
    'KGZ': 'KG',  # Kyrgyzstan
    'LAO': 'LA',  # Lao PDR
    'LVA': 'LG',  # Latvia
    'LBN': 'LE',  # Lebanon
    'LSO': 'LT',  # Lesotho
    'LBR': 'LI',  # Liberia
    'LBY': 'LY',  # Libya
    'LTU': 'LH',  # Lithuania
    'LUX': 'LU',  # Luxembourg
    'MDG': 'MA',  # Madagascar
    'MWI': 'MI',  # Malawi
    'MYS': 'MY',  # Malaysia
    'MLI': 'ML',  # Mali
    'MLT': 'MT',  # Malta
    'MRT': 'MR',  # Mauritania
    'MUS': 'MP',  # Mauritius
    'MEX': 'MX',  # Mexico
    'MNG': 'MG',  # Mongolia
    'MNE': 'MW',  # Montenegro
    'MAR': 'MO',  # Morocco
    'MOZ': 'MZ',  # Mozambique
    'MMR': 'BM',  # Myanmar
    'NAM': 'WA',  # Namibia
    'NPL': 'NP',  # Nepal
    'NLD': 'NL',  # Netherlands
    'NCL': 'NC',  # New Caledonia
    'NZL': 'NZ',  # New Zealand
    'NIC': 'NU',  # Nicaragua
    'NER': 'NG',  # Niger
    'NGA': 'NI',  # Nigeria
    'MKD': 'MK',  # North Macedonia
    'NOR': 'NO',  # Norway
    'OMN': 'MU',  # Oman
    'PAK': 'PK',  # Pakistan
    'PAN': 'PM',  # Panama
    'PNG': 'PP',  # Papua New Guinea
    'PRY': 'PA',  # Paraguay
    'PER': 'PE',  # Peru
    'PHL': 'RP',  # Philippines
    'POL': 'PL',  # Poland
    'PRT': 'PO',  # Portugal
    'PRI': 'PQ',  # Puerto Rico
    'QAT': 'QA',  # Qatar
    'MDA': 'MD',  # Republic of Moldova
    'ROU': 'RO',  # Romania
    'RUS': 'RS',  # Russian Federation
    'RWA': 'RW',  # Rwanda
    'KNA': 'SC',  # Saint Kitts and Nevis
    'LCA': 'ST',  # Saint Lucia
    'VCT': 'VC',  # Saint Vincent and the Grenadines
    'STP': 'TP',  # Sao Tome and Principe
    'SAU': 'SA',  # Saudi Arabia
    'SEN': 'SG',  # Senegal
    'SRB': 'RI',  # Serbia
    'SLE': 'SL',  # Sierra Leone
    'SVK': 'LO',  # Slovakia
    'SVN': 'SI',  # Slovenia
    'SLB': 'BP',  # Solomon Islands
    'SOM': 'SO',  # Somalia
    'ZAF': 'SF',  # South Africa
    'KOR': 'KS',  # South Korea
    'SSD': 'OD',  # South Sudan
    'ESP': 'SP',  # Spain
    'LKA': 'CE',  # Sri Lanka
    'SDN': 'SU',  # Sudan
    'SUR': 'NS',  # Suriname
    'SWZ': 'WZ',  # Eswatini (Swaziland)
    'SWE': 'SW',  # Sweden
    'CHE': 'SZ',  # Switzerland
    'SYR': 'SY',  # Syrian Arab Republic
    'TWN': 'TW',  # Taiwan
    'TJK': 'TI',  # Tajikistan
    'THA': 'TH',  # Thailand
    'TLS': 'TT',  # Timor-Leste
    'TGO': 'TG',  # Togo
    'TTO': 'TD',  # Trinidad and Tobago
    'TUN': 'TS',  # Tunisia
    'TUR': 'TU',  # Turkey
    'TKM': 'TX',  # Turkmenistan
    'UGA': 'UG',  # Uganda
    'UKR': 'UP',  # Ukraine
    'ARE': 'TC',  # United Arab Emirates
    'GBR': 'UK',  # United Kingdom
    'TZA': 'TZ',  # Tanzania
    'USA': 'US',  # United States of America
    'URY': 'UY',  # Uruguay
    'UZB': 'UZ',  # Uzbekistan
    'VUT': 'NH',  # Vanuatu
    'VEN': 'VE',  # Venezuela
    'VNM': 'VM',  # Vietnam
    'YEM': 'YM',  # Yemen
    'ZMB': 'ZA',  # Zambia
    'ZWE': 'ZI',  # Zimbabwe
}

# Reverse mapping for convenience
FIPS_TO_ISO3 = {v: k for k, v in ISO3_TO_FIPS.items()}

# =============================================================================
# MAPSPAM CROP CODES - ALL 46 CROPS
# Format in CSV: {CODE}_A where CODE is 4 letters
# =============================================================================

MAPSPAM_CROPS = {
    # Code: (Full Name, Category)
    'BANA': ('Banana', 'Fruits'),
    'BARL': ('Barley', 'Cereals'),
    'BEAN': ('Bean', 'Pulses'),
    'CASS': ('Cassava', 'Roots & Tubers'),
    'CHIC': ('Chickpea', 'Pulses'),
    'CITR': ('Citrus', 'Fruits'),
    'CNUT': ('Coconut', 'Oilseeds'),
    'COCO': ('Cocoa', 'Commodities'),
    'COFF': ('Coffee (Arabica)', 'Commodities'),
    'COTT': ('Cotton', 'Fibers'),
    'COWP': ('Cowpea', 'Pulses'),
    'GROU': ('Groundnut (Peanut)', 'Oilseeds'),
    'LENT': ('Lentil', 'Pulses'),
    'MAIZ': ('Maize (Corn)', 'Cereals'),
    'MILL': ('Millet (Small)', 'Cereals'),
    'OCER': ('Other Cereals', 'Cereals'),
    'OFIB': ('Other Fibers', 'Fibers'),
    'OILP': ('Oil Palm', 'Oilseeds'),
    'ONIO': ('Onion', 'Vegetables'),
    'OOIL': ('Other Oilseeds', 'Oilseeds'),
    'OPUL': ('Other Pulses', 'Pulses'),
    'ORTS': ('Other Roots', 'Roots & Tubers'),
    'PIGE': ('Pigeonpea', 'Pulses'),
    'PLNT': ('Plantain', 'Fruits'),
    'PMIL': ('Pearl Millet', 'Cereals'),
    'POTA': ('Potato', 'Roots & Tubers'),
    'RAPE': ('Rapeseed (Canola)', 'Oilseeds'),
    'RCOF': ('Coffee (Robusta)', 'Commodities'),
    'REST': ('Rest of Crops', 'Other'),
    'RICE': ('Rice', 'Cereals'),
    'RUBB': ('Rubber', 'Commodities'),
    'SESA': ('Sesame', 'Oilseeds'),
    'SORG': ('Sorghum', 'Cereals'),
    'SOYB': ('Soybean', 'Oilseeds'),
    'SUGB': ('Sugarbeet', 'Sugar Crops'),
    'SUGC': ('Sugarcane', 'Sugar Crops'),
    'SUNF': ('Sunflower', 'Oilseeds'),
    'SWPO': ('Sweet Potato', 'Roots & Tubers'),
    'TEAS': ('Tea', 'Commodities'),
    'TEMF': ('Temperate Fruits', 'Fruits'),
    'TOBA': ('Tobacco', 'Commodities'),
    'TOMA': ('Tomato', 'Vegetables'),
    'TROF': ('Tropical Fruits', 'Fruits'),
    'VEGE': ('Vegetables', 'Vegetables'),
    'WHEA': ('Wheat', 'Cereals'),
    'YAMS': ('Yams', 'Roots & Tubers'),
}

# =============================================================================
# CROP METADATA - Residue-to-Product Ratio (RPR) for Waste Biomass Calculation
# RPR = tons of agricultural waste per ton of crop produced
# Used to calculate waste potential for bioenergy, composting, etc.
# =============================================================================

CROP_METADATA = {
    'whea': {'name': 'Wheat', 'rpr': 1.3, 'note': 'Straw and stubble'},
    'rice': {'name': 'Rice', 'rpr': 1.5, 'note': 'Straw (1.3) + Husks (0.2 - high energy)'},
    'maiz': {'name': 'Maize', 'rpr': 1.3, 'note': 'Stover (stalks/leaves) + Cobs'},
    'barl': {'name': 'Barley', 'rpr': 1.2, 'note': 'Straw'},
    'mill': {'name': 'Small Millet', 'rpr': 1.4, 'note': 'Stalks'},
    'pmil': {'name': 'Pearl Millet', 'rpr': 1.4, 'note': 'Stalks'},
    'sorg': {'name': 'Sorghum', 'rpr': 1.4, 'note': 'Stalks'},
    'ocer': {'name': 'Other Cereals', 'rpr': 1.3, 'note': 'Mixed straw'},
    'pota': {'name': 'Potato', 'rpr': 0.4, 'note': 'Vines and tops'},
    'swpo': {'name': 'Sweet Potato', 'rpr': 0.5, 'note': 'Vines'},
    'yams': {'name': 'Yams', 'rpr': 0.4, 'note': 'Vines and peels'},
    'cass': {'name': 'Cassava', 'rpr': 0.8, 'note': 'Stalks (0.6) + Peels (0.2)'},
    'orts': {'name': 'Other Roots', 'rpr': 0.5, 'note': 'Mixed residues'},
    'bean': {'name': 'Bean', 'rpr': 1.2, 'note': 'Straw and pods'},
    'chic': {'name': 'Chickpea', 'rpr': 1.2, 'note': 'Straw'},
    'cowp': {'name': 'Cowpea', 'rpr': 1.5, 'note': 'High residue haulms'},
    'pige': {'name': 'Pigeon Pea', 'rpr': 1.5, 'note': 'Woody stalks'},
    'lent': {'name': 'Lentil', 'rpr': 1.2, 'note': 'Straw'},
    'opul': {'name': 'Other Pulses', 'rpr': 1.2, 'note': 'Mixed residues'},
    'soyb': {'name': 'Soybean', 'rpr': 1.3, 'note': 'Straw and pods'},
    'grou': {'name': 'Groundnut', 'rpr': 1.1, 'note': 'Hay (0.8) + Shells (0.3)'},
    'cnut': {'name': 'Coconut', 'rpr': 1.6, 'note': 'Husks (high volume) + Shells'},
    'oilp': {'name': 'Oilpalm', 'rpr': 0.9, 'note': 'Empty Fruit Bunches, Fiber, Shells'},
    'sunf': {'name': 'Sunflower', 'rpr': 1.8, 'note': 'Stalks and heads'},
    'rape': {'name': 'Rapeseed', 'rpr': 1.4, 'note': 'Straw'},
    'sesa': {'name': 'Sesame Seed', 'rpr': 1.5, 'note': 'Stalks'},
    'ooil': {'name': 'Other Oil Crops', 'rpr': 1.5, 'note': 'Mixed residues'},
    'sugc': {'name': 'Sugarcane', 'rpr': 0.3, 'note': 'Bagasse (wet weight)'},
    'sugb': {'name': 'Sugarbeet', 'rpr': 0.2, 'note': 'Pulp'},
    'cott': {'name': 'Cotton', 'rpr': 3.0, 'note': 'Woody stalks (often burned)'},
    'ofib': {'name': 'Other Fibre Crops', 'rpr': 2.5, 'note': 'Stalks'},
    'coff': {'name': 'Arabic Coffee', 'rpr': 2.0, 'note': 'Pulp and husks'},
    'rcof': {'name': 'Robust Coffee', 'rpr': 2.0, 'note': 'Pulp and husks'},
    'coco': {'name': 'Cocoa', 'rpr': 10.0, 'note': 'Pod husks (High volume waste)'},
    'teas': {'name': 'Tea', 'rpr': 0.8, 'note': 'Prunings'},
    'toba': {'name': 'Tobacco', 'rpr': 1.0, 'note': 'Stalks'},
    'bana': {'name': 'Banana', 'rpr': 2.0, 'note': 'Pseudo-stems and leaves'},
    'plnt': {'name': 'Plantain', 'rpr': 2.0, 'note': 'Pseudo-stems and leaves'},
    'citr': {'name': 'Citrus', 'rpr': 0.5, 'note': 'Peels and pulp'},
    'trof': {'name': 'Other Tropical Fruit', 'rpr': 0.8, 'note': 'Skins and seeds'},
    'temf': {'name': 'Temperate Fruit', 'rpr': 0.4, 'note': 'Pomace/skins'},
    'toma': {'name': 'Tomato', 'rpr': 0.3, 'note': 'Vines'},
    'onio': {'name': 'Onion', 'rpr': 0.2, 'note': 'Skins and tops'},
    'vege': {'name': 'Other Vegetables', 'rpr': 0.3, 'note': 'Mixed residues'},
    'rubb': {'name': 'Rubber', 'rpr': 1.0, 'note': 'Wood and seeds'},
    'rest': {'name': 'Rest Of Crops', 'rpr': 1.0, 'note': 'General biomass'},
}

# =============================================================================
# USER-FRIENDLY CROP NAME TO MAPSPAM CODE MAPPING
# Maps common names, aliases, and variations to MapSPAM codes
# =============================================================================

CROP_NAME_TO_CODE = {
    # Direct matches (lowercase)
    'banana': 'BANA',
    'bananas': 'BANA',
    'barley': 'BARL',
    'bean': 'BEAN',
    'beans': 'BEAN',
    'cassava': 'CASS',
    'yuca': 'CASS',
    'mandioca': 'CASS',
    'chickpea': 'CHIC',
    'chickpeas': 'CHIC',
    'garbanzo': 'CHIC',
    'citrus': 'CITR',
    'orange': 'CITR',
    'oranges': 'CITR',
    'lemon': 'CITR',
    'lemons': 'CITR',
    'grapefruit': 'CITR',
    'coconut': 'CNUT',
    'coconuts': 'CNUT',
    'coco': 'COCO',
    'cocoa': 'COCO',
    'cacao': 'COCO',
    'chocolate': 'COCO',
    'coffee': 'COFF',
    'arabica': 'COFF',
    'arabica coffee': 'COFF',
    'cotton': 'COTT',
    'cowpea': 'COWP',
    'cowpeas': 'COWP',
    'black-eyed pea': 'COWP',
    'groundnut': 'GROU',
    'groundnuts': 'GROU',
    'peanut': 'GROU',
    'peanuts': 'GROU',
    'lentil': 'LENT',
    'lentils': 'LENT',
    'maize': 'MAIZ',
    'corn': 'MAIZ',
    'millet': 'MILL',
    'small millet': 'MILL',
    'finger millet': 'MILL',
    'other cereals': 'OCER',
    'cereals': 'OCER',
    'other fibers': 'OFIB',
    'fibers': 'OFIB',
    'jute': 'OFIB',
    'sisal': 'OFIB',
    'hemp': 'OFIB',
    'oil palm': 'OILP',
    'palm oil': 'OILP',
    'palm': 'OILP',
    'onion': 'ONIO',
    'onions': 'ONIO',
    'other oilseeds': 'OOIL',
    'oilseeds': 'OOIL',
    'other pulses': 'OPUL',
    'pulses': 'OPUL',
    'other roots': 'ORTS',
    'roots': 'ORTS',
    'tubers': 'ORTS',
    'pigeonpea': 'PIGE',
    'pigeon pea': 'PIGE',
    'plantain': 'PLNT',
    'plantains': 'PLNT',
    'pearl millet': 'PMIL',
    'bajra': 'PMIL',
    'potato': 'POTA',
    'potatoes': 'POTA',
    'rapeseed': 'RAPE',
    'canola': 'RAPE',
    'robusta': 'RCOF',
    'robusta coffee': 'RCOF',
    'rest': 'REST',
    'other crops': 'REST',
    'rice': 'RICE',
    'paddy': 'RICE',
    'rubber': 'RUBB',
    'natural rubber': 'RUBB',
    'sesame': 'SESA',
    'sesamum': 'SESA',
    'sorghum': 'SORG',
    'jowar': 'SORG',
    'soybean': 'SOYB',
    'soybeans': 'SOYB',
    'soya': 'SOYB',
    'soy': 'SOYB',
    'sugarbeet': 'SUGB',
    'sugar beet': 'SUGB',
    'beet sugar': 'SUGB',
    'sugarcane': 'SUGC',
    'sugar cane': 'SUGC',
    'cane sugar': 'SUGC',
    'sunflower': 'SUNF',
    'sunflowers': 'SUNF',
    'sweet potato': 'SWPO',
    'sweetpotato': 'SWPO',
    'batata': 'SWPO',
    'camote': 'SWPO',
    'tea': 'TEAS',
    'temperate fruits': 'TEMF',
    'apple': 'TEMF',
    'apples': 'TEMF',
    'pear': 'TEMF',
    'pears': 'TEMF',
    'peach': 'TEMF',
    'peaches': 'TEMF',
    'tobacco': 'TOBA',
    'tomato': 'TOMA',
    'tomatoes': 'TOMA',
    'tropical fruits': 'TROF',
    'mango': 'TROF',
    'mangoes': 'TROF',
    'papaya': 'TROF',
    'pineapple': 'TROF',
    'pineapples': 'TROF',
    'avocado': 'TROF',
    'avocados': 'TROF',
    'vegetables': 'VEGE',
    'vegetable': 'VEGE',
    'wheat': 'WHEA',
    'yam': 'YAMS',
    'yams': 'YAMS',
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _h3_version() -> int:
    """Detect H3 library version (3 or 4)."""
    if hasattr(h3, 'latlng_to_cell'):
        return 4
    return 3


def _latlng_to_h3(lat: float, lng: float, resolution: int) -> str:
    """Convert lat/lng to H3 cell, handling version differences."""
    if _h3_version() >= 4:
        return h3.latlng_to_cell(lat, lng, resolution)
    else:
        return h3.geo_to_h3(lat, lng, resolution)


def _get_fips_code(country_code: str) -> Optional[str]:
    """
    Convert country code to FIPS0 code used by MapSPAM.
    Accepts ISO3, ISO2, or FIPS codes.
    """
    code_upper = country_code.upper().strip()
    
    # Already a FIPS code?
    if code_upper in FIPS_TO_ISO3:
        return code_upper
    
    # ISO3 code?
    if code_upper in ISO3_TO_FIPS:
        return ISO3_TO_FIPS[code_upper]
    
    # ISO2 might match FIPS (e.g., GH=GH, BR=BR)
    if len(code_upper) == 2:
        # Check if it's directly in FIPS
        if code_upper in FIPS_TO_ISO3:
            return code_upper
    
    return None


def _get_crop_code(crop_name: str) -> Optional[str]:
    """Convert user-friendly crop name to MapSPAM code."""
    crop_lower = crop_name.lower().strip()
    
    # Direct mapping
    if crop_lower in CROP_NAME_TO_CODE:
        return CROP_NAME_TO_CODE[crop_lower]
    
    # Try partial match
    for name, code in CROP_NAME_TO_CODE.items():
        if crop_lower in name or name in crop_lower:
            return code
    
    # Try matching against MapSPAM codes directly
    crop_upper = crop_name.upper().strip()
    if crop_upper in MAPSPAM_CROPS:
        return crop_upper
    
    return None


def _get_data_file(
    metric: Literal['production', 'harvested_area', 'physical_area', 'yield'] = 'production',
    technology: Literal['all', 'irrigated', 'rainfed'] = 'all'
) -> Optional[Path]:
    """Get the path to the appropriate MapSPAM CSV file."""
    
    # Metric to folder name
    metric_folders = {
        'production': 'spam2020V2r0_global_production',
        'harvested_area': 'spam2020V2r0_global_harvested_area',
        'physical_area': 'spam2020V2r0_global_physical_area',
        'yield': 'spam2020V2r0_global_yield',
    }
    
    # Metric to file prefix
    metric_codes = {
        'production': 'P',
        'harvested_area': 'H',
        'physical_area': 'A',
        'yield': 'Y',
    }
    
    # Technology to file suffix
    tech_codes = {
        'all': 'TA',
        'irrigated': 'TI',
        'rainfed': 'TR',
    }
    
    folder = MAPSPAM_DATA_PATH / metric_folders.get(metric, 'spam2020V2r0_global_production')
    code = metric_codes.get(metric, 'P')
    tech = tech_codes.get(technology, 'TA')
    
    filename = f"spam2020V2r0_global_{code}_{tech}.csv"
    filepath = folder / filename
    
    if filepath.exists():
        return filepath
    
    return None


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

def fetch_crop_production(
    country_code: str,
    crop_name: str,
    metric: Literal['production', 'harvested_area', 'physical_area', 'yield'] = 'production',
    technology: Literal['all', 'irrigated', 'rainfed'] = 'all',
    resolution: int = DEFAULT_H3_RESOLUTION,
    focus_geometry: Optional[Union[Dict[str, Any], Any]] = None,
) -> Optional[list[dict]]:
    """
    Fetch crop data from MapSPAM and aggregate to H3 hexagons.
    
    MapSPAM provides 10km grid-level production estimates. This function
    converts them to H3 hexagons at the specified resolution.
    
    Focus + Context Pattern (Google Earth style):
    - Fetches data for the entire country (no hard clipping)
    - focus_geometry: Marks data with is_inside for frontend styling
    - Data inside focus = 100% opacity, outside = 50% opacity
    
    Args:
        country_code: ISO3, ISO2, or FIPS country code (e.g., "GHA", "GH", "BR")
        crop_name: Crop name (e.g., "cocoa", "coffee", "maize")
        metric: Type of data to fetch:
            - 'production': Output in metric tons (default)
            - 'harvested_area': Area harvested in hectares
            - 'physical_area': Physical area in hectares
            - 'yield': Yield in kg/ha
        technology: Farming technology:
            - 'all': All technologies combined (default)
            - 'irrigated': Irrigated farming only
            - 'rainfed': Rainfed farming only
        resolution: H3 resolution (default 6, ~3km edge - good for regional crop data)
        focus_geometry: Optional GeoJSON Polygon/MultiPolygon or Shapely geometry.
            Marks hexagons with is_inside: True/False instead of deleting.
            Use this to highlight a region while showing surrounding context.
        
    Returns:
        List of dicts with production AND waste biomass data:
        [{
            'hex': 'h3_index',
            'value': production_amount,
            'unit': 'mt',
            'waste_mt': calculated_waste,
            'waste_rpr': residue_to_product_ratio,
            'waste_source_note': 'Description of waste type',
            'is_inside': bool  # if focus_geometry provided
        }, ...]
        or None if no data found
        
    Example:
        >>> result = fetch_crop_production("GHA", "cocoa")
        >>> print(result[0])
        {'hex': '86...', 'value': 5234.5, 'unit': 'mt', 
         'waste_mt': 52345.0, 'waste_rpr': 10.0, 
         'waste_source_note': 'Pod husks (High volume waste)'}
         
        >>> # With Focus + Context (highlight Ashanti region within Ghana)
        >>> from Leo.backend.utils_spatial import get_aoi
        >>> ashanti_aoi = get_aoi("Ashanti, Ghana")
        >>> result = fetch_crop_production("GHA", "cocoa", focus_geometry=ashanti_aoi['focus_geometry'])
        >>> # Returns ALL Ghana data, with is_inside marking for Ashanti
    """
    logger.info("=" * 60)
    logger.info(f"🌾 Fetching {crop_name} {metric} in {country_code}")
    logger.info("=" * 60)
    
    # Normalize country name to ISO3 if needed
    country_lower = country_code.lower().strip()
    if country_lower in COUNTRY_NAME_TO_ISO3:
        country_code = COUNTRY_NAME_TO_ISO3[country_lower]
        logger.info(f"  Normalized country name: {country_lower} -> {country_code}")
    
    # Convert country code to FIPS
    fips_code = _get_fips_code(country_code)
    if not fips_code:
        logger.error(f"  ❌ Unknown country code: {country_code}")
        logger.info(f"  Supported: ISO3 (GHA), ISO2 (GH), or FIPS (GH)")
        return None
    
    logger.info(f"  Country: {country_code} -> FIPS: {fips_code}")
    
    # Convert crop name to MapSPAM code
    crop_code = _get_crop_code(crop_name)
    if not crop_code:
        logger.error(f"  ❌ Unknown crop: {crop_name}")
        logger.info(f"  Available: {', '.join(sorted(MAPSPAM_CROPS.keys()))}")
        return None
    
    crop_info = MAPSPAM_CROPS.get(crop_code, (crop_name, 'Unknown'))
    logger.info(f"  Crop: {crop_name} -> {crop_code} ({crop_info[0]})")
    
    # Get the data file
    csv_path = _get_data_file(metric, technology)
    if not csv_path:
        logger.error(f"  ❌ MapSPAM data file not found")
        logger.info(f"  Expected: {MAPSPAM_DATA_PATH}/spam2020V2r0_global_*/")
        return None
    
    logger.info(f"  Data file: {csv_path.name}")
    
    # Determine units based on metric
    units = {
        'production': 'mt',
        'harvested_area': 'ha',
        'physical_area': 'ha',
        'yield': 'kg/ha',
    }
    unit = units.get(metric, 'mt')
    
    try:
        # Connect to DuckDB
        conn = duckdb.connect()
        
        # The crop column name format: {CODE}_A
        crop_column = f"{crop_code}_A"
        
        # Query the data with proper CSV parsing options
        # Some rows have commas in quoted fields that need proper handling
        query = f"""
        SELECT 
            x as lon,
            y as lat,
            "{crop_column}" as value
        FROM read_csv('{csv_path}', 
            ignore_errors=true,
            auto_detect=true,
            quote='"')
        WHERE FIPS0 = '{fips_code}'
          AND "{crop_column}" > 0
        """
        
        logger.info(f"  Querying MapSPAM data...")
        df = conn.execute(query).fetchdf()
        conn.close()
        
        logger.info(f"  Found {len(df):,} grid cells with {crop_name} data")
        
        if df.empty:
            logger.warning(f"  ❌ No {crop_name} data for {country_code}")
            return None
        
        # Convert to H3 and aggregate
        logger.info(f"  Converting to H3 (resolution {resolution})...")
        
        h3_data = {}
        for _, row in df.iterrows():
            lat, lon, value = row['lat'], row['lon'], row['value']
            
            # Skip invalid coordinates
            if pd.isna(lat) or pd.isna(lon) or pd.isna(value):
                continue
            
            hex_id = _latlng_to_h3(lat, lon, resolution)
            
            # Aggregate by H3 cell
            if hex_id in h3_data:
                h3_data[hex_id] += value
            else:
                h3_data[hex_id] = value
        
        # Look up waste/residue metadata for this crop
        crop_code_lower = crop_code.lower()
        waste_metadata = CROP_METADATA.get(crop_code_lower, {
            'name': crop_info[0],
            'rpr': 1.0,
            'note': 'General biomass (default RPR)'
        })
        rpr = waste_metadata['rpr']
        waste_note = waste_metadata['note']
        
        logger.info(f"  Waste RPR: {rpr} ({waste_note})")
        
        # Convert to output format with waste calculation
        result = []
        for hex_id, val in h3_data.items():
            if val > 0:
                production_mt = round(val, 2)
                waste_mt = round(val * rpr, 2)
                
                result.append({
                    'hex': hex_id,
                    'value': production_mt,
                    'unit': unit,
                    # Waste biomass fields
                    'waste_mt': waste_mt,
                    'waste_rpr': rpr,
                    'waste_source_note': waste_note,
                })
        
        # Sort by value descending
        result.sort(key=lambda x: x['value'], reverse=True)
        
        total_value = sum(h['value'] for h in result)
        total_waste = sum(h['waste_mt'] for h in result)
        
        logger.info(f"  ✅ Aggregated to {len(result)} H3 hexagons")
        logger.info(f"  Total {metric}: {total_value:,.0f} {unit}")
        logger.info(f"  🗑️  Total waste potential: {total_waste:,.0f} mt ({waste_note})")
        
        # Apply Focus + Context masking if focus_geometry provided
        if focus_geometry is not None and mask_layer_by_aoi is not None:
            logger.info(f"  🎯 Applying Focus + Context masking...")
            result = mask_layer_by_aoi(result, focus_geometry)
            inside_count = sum(1 for r in result if r.get('is_inside', False))
            context_count = len(result) - inside_count
            logger.info(f"  Focus: {inside_count}, Context: {context_count}")
        elif focus_geometry is not None and mask_layer_by_aoi is None:
            logger.warning(f"  ⚠️ focus_geometry provided but mask_layer_by_aoi not available")
        
        return result
        
    except Exception as e:
        logger.error(f"  ❌ Error querying MapSPAM: {e}")
        import traceback
        traceback.print_exc()
        return None


def list_available_crops() -> list[str]:
    """Return list of all 46 MapSPAM crop codes."""
    return sorted(MAPSPAM_CROPS.keys())


def list_crop_names() -> list[str]:
    """Return list of user-friendly crop name aliases."""
    return sorted(set(CROP_NAME_TO_CODE.keys()))


def get_crop_info(crop_name: str) -> Optional[dict]:
    """Get detailed info about a crop."""
    code = _get_crop_code(crop_name)
    if code and code in MAPSPAM_CROPS:
        full_name, category = MAPSPAM_CROPS[code]
        return {
            'code': code,
            'name': full_name,
            'category': category,
            'source': 'MapSPAM 2020 v2.0',
            'resolution_source': '~10km (5 arc-minute) grid',
            'resolution_h3_default': f'{DEFAULT_H3_RESOLUTION} (~3km edge)',
        }
    return None


def list_countries() -> list[dict]:
    """Return list of all supported countries with their codes."""
    return [
        {'iso3': iso3, 'fips': fips}
        for iso3, fips in sorted(ISO3_TO_FIPS.items())
    ]


def get_available_metrics() -> list[str]:
    """Return list of available metrics."""
    return ['production', 'harvested_area', 'physical_area', 'yield']


def get_available_technologies() -> list[str]:
    """Return list of available technologies."""
    return ['all', 'irrigated', 'rainfed']


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🌾 MapSPAM Agriculture Tools - Test Suite")
    print("=" * 70)
    
    print(f"\nMapSPAM data path: {MAPSPAM_DATA_PATH}")
    print(f"Data folders: {list(MAPSPAM_DATA_PATH.glob('spam*'))}")
    
    print(f"\n📊 Statistics:")
    print(f"  - Total crops: {len(MAPSPAM_CROPS)}")
    print(f"  - Crop name aliases: {len(CROP_NAME_TO_CODE)}")
    print(f"  - Countries supported: {len(ISO3_TO_FIPS)}")
    
    print(f"\n🌿 All 46 MapSPAM Crops:")
    for i, (code, (name, category)) in enumerate(sorted(MAPSPAM_CROPS.items()), 1):
        print(f"  {i:2}. {code}: {name} [{category}]")
    
    # Check if data exists before testing
    csv_path = _get_data_file('production', 'all')
    if csv_path:
        print("\n" + "-" * 70)
        print("--- Testing fetch_crop_production ---")
        print("-" * 70)
        
        # Test with Ghana cocoa (uses default resolution 6 for nice choropleth)
        print("\n🍫 Test: Ghana Cocoa Production + Waste Biomass")
        result = fetch_crop_production("GHA", "cocoa")  # Uses default resolution=6
        
        if result:
            print(f"✅ Success! Got {len(result)} hexagons")
            total_prod = sum(h['value'] for h in result)
            total_waste = sum(h['waste_mt'] for h in result)
            print(f"Total production: {total_prod:,.0f} {result[0]['unit']}")
            print(f"🗑️  Total waste potential: {total_waste:,.0f} mt")
            print(f"   Waste source: {result[0]['waste_source_note']}")
            print(f"   RPR: {result[0]['waste_rpr']}")
            print(f"Top hexagon: {result[0]}")
        else:
            print("❌ No data returned")
        
        # Test with Cote d'Ivoire cocoa
        print("\n🍫 Test: Côte d'Ivoire Cocoa Production")
        result = fetch_crop_production("CIV", "cocoa")  # Uses default resolution=6
        
        if result:
            print(f"✅ Success! Got {len(result)} hexagons")
            total = sum(h['value'] for h in result)
            print(f"Total production: {total:,.0f} {result[0]['unit']}")
        else:
            print("❌ No data returned")
        
        # Test with Brazil coffee
        print("\n☕ Test: Brazil Coffee Production")
        result = fetch_crop_production("BRA", "coffee")  # Uses default resolution=6
        
        if result:
            print(f"✅ Success! Got {len(result)} hexagons")
            total = sum(h['value'] for h in result)
            print(f"Total production: {total:,.0f} {result[0]['unit']}")
        else:
            print("❌ No data returned")
        
        # Test with Vietnam rice
        print("\n🍚 Test: Vietnam Rice Production")
        result = fetch_crop_production("VNM", "rice")  # Uses default resolution=6
        
        if result:
            print(f"✅ Success! Got {len(result)} hexagons")
            total = sum(h['value'] for h in result)
            print(f"Total production: {total:,.0f} {result[0]['unit']}")
        else:
            print("❌ No data returned")
        
        # Test yield metric
        print("\n📈 Test: Ghana Cocoa Yield (kg/ha)")
        result = fetch_crop_production("GHA", "cocoa", metric='yield')  # Uses default resolution=6
        
        if result:
            print(f"✅ Success! Got {len(result)} hexagons")
            avg_yield = sum(h['value'] for h in result) / len(result)
            print(f"Average yield: {avg_yield:,.0f} {result[0]['unit']}")
        else:
            print("❌ No data returned")
            
    else:
        print("\n⚠️  MapSPAM data not found - skipping tests")
        print("Files should be in: data/mapspam/spam2020V2r0_global_*/")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)


def fetch_crop_production_grid(
    country_code: str,
    crop_name: str,
    metric: Literal['production', 'harvested_area', 'physical_area', 'yield'] = 'production',
    technology: Literal['all', 'irrigated', 'rainfed'] = 'all',
    focus_geometry: Optional[Union[Dict[str, Any], Any]] = None,
) -> Optional[list[dict]]:
    """
    Fetch crop data at the RAW 10x10km grid level (no H3 aggregation).
    
    Returns the original MapSPAM grid cells with lat/lon coordinates.
    Each grid cell is ~10km (5 arc-minute) resolution.
    
    Focus + Context Pattern (Google Earth style):
    - Fetches data for the entire country (no hard clipping)
    - focus_geometry: Marks data with is_inside for frontend styling
    
    Args:
        country_code: ISO3, ISO2, or FIPS country code
        crop_name: Crop name (e.g., "cocoa", "coffee", "maize")
        metric: Type of data ('production', 'harvested_area', 'physical_area', 'yield')
        technology: Farming technology ('all', 'irrigated', 'rainfed')
        focus_geometry: Optional GeoJSON Polygon/MultiPolygon or Shapely geometry
            Marks grid points with is_inside: True/False instead of deleting.
        
    Returns:
        List of dicts with grid-level data:
        [{
            'lat': latitude,
            'lon': longitude,
            'production_mt': value,
            'waste_mt': calculated_waste,
            'waste_rpr': rpr,
            'waste_source_note': note,
            'is_inside': bool  # if focus_geometry provided
        }, ...]
        
    Example:
        >>> result = fetch_crop_production_grid("GHA", "cocoa")
        >>> len(result)  # ~2200 grid cells for Ghana cocoa
        2231
    """
    logger.info("=" * 60)
    logger.info(f"🌾 Fetching {crop_name} {metric} GRID data in {country_code}")
    logger.info("=" * 60)
    
    # Convert country code to FIPS
    fips_code = _get_fips_code(country_code)
    if not fips_code:
        logger.error(f"  ❌ Unknown country code: {country_code}")
        return None
    
    # Convert crop name to MapSPAM code
    crop_code = _get_crop_code(crop_name)
    if not crop_code:
        logger.error(f"  ❌ Unknown crop: {crop_name}")
        return None
    
    crop_info = MAPSPAM_CROPS.get(crop_code, (crop_name, 'Unknown'))
    logger.info(f"  Crop: {crop_name} -> {crop_code} ({crop_info[0]})")
    
    # Get the data file
    csv_path = _get_data_file(metric, technology)
    if not csv_path:
        logger.error(f"  ❌ MapSPAM data file not found")
        return None
    
    # Determine units
    units = {
        'production': 'mt',
        'harvested_area': 'ha',
        'physical_area': 'ha',
        'yield': 'kg/ha',
    }
    unit = units.get(metric, 'mt')
    
    # Get waste metadata
    crop_code_lower = crop_code.lower()
    waste_metadata = CROP_METADATA.get(crop_code_lower, {
        'name': crop_info[0],
        'rpr': 1.0,
        'note': 'General biomass (default RPR)'
    })
    rpr = waste_metadata['rpr']
    waste_note = waste_metadata['note']
    
    logger.info(f"  Waste RPR: {rpr} ({waste_note})")
    
    try:
        conn = duckdb.connect()
        crop_column = f"{crop_code}_A"
        
        query = f"""
        SELECT 
            y as lat,
            x as lon,
            "{crop_column}" as value
        FROM read_csv('{csv_path}', 
            ignore_errors=true,
            auto_detect=true,
            quote='"')
        WHERE FIPS0 = '{fips_code}'
          AND "{crop_column}" > 0
        ORDER BY "{crop_column}" DESC
        """
        
        logger.info(f"  Querying raw 10km grid data...")
        df = conn.execute(query).fetchdf()
        conn.close()
        
        if df.empty:
            logger.warning(f"  ❌ No {crop_name} data for {country_code}")
            return None
        
        logger.info(f"  Found {len(df):,} grid cells (10x10km each)")
        
        # Convert to output format with waste
        result = []
        for _, row in df.iterrows():
            lat, lon, value = float(row['lat']), float(row['lon']), float(row['value'])
            production_mt = round(value, 2)
            waste_mt = round(value * rpr, 2)
            
            result.append({
                'lat': lat,
                'lon': lon,
                'production_mt': production_mt,
                'unit': unit,
                'waste_mt': waste_mt,
                'waste_rpr': rpr,
                'waste_source_note': waste_note,
            })
        
        total_prod = sum(r['production_mt'] for r in result)
        total_waste = sum(r['waste_mt'] for r in result)
        
        logger.info(f"  ✅ Returned {len(result)} grid cells")
        logger.info(f"  Total {metric}: {total_prod:,.0f} {unit}")
        logger.info(f"  🗑️  Total waste potential: {total_waste:,.0f} mt")
        
        # Apply Focus + Context masking if focus_geometry provided
        if focus_geometry is not None and mask_layer_by_aoi is not None:
            logger.info(f"  🎯 Applying Focus + Context masking...")
            result = mask_layer_by_aoi(result, focus_geometry)
            inside_count = sum(1 for r in result if r.get('is_inside', False))
            context_count = len(result) - inside_count
            logger.info(f"  Focus: {inside_count}, Context: {context_count}")
        elif focus_geometry is not None and mask_layer_by_aoi is None:
            logger.warning(f"  ⚠️ focus_geometry provided but mask_layer_by_aoi not available")
        
        return result
        
    except Exception as e:
        logger.error(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None
