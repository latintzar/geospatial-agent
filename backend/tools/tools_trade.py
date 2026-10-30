"""
Trade Flow Tools

Fetches UN Comtrade data and visualizes trade flows as lines between countries.
Creates GeoJSON LineStrings connecting trading partners for map visualization.

Usage:
    from tools_trade import fetch_trade_flows
    
    # Get Ghana's cocoa exports to top 10 partners
    result = fetch_trade_flows("GHA", "1801", flow_type='export')
    # Returns GeoJSON FeatureCollection with trade flow lines

System Prompt Context:
    'Use this tool when the user asks about trade flows, imports, exports,
    commodity trading partners, or international trade visualization.'
"""

import requests
import pandas as pd
import json
import logging
from typing import Optional, Literal, Tuple, List, Dict
from shapely.geometry import LineString, mapping

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# COUNTRY CENTROIDS (Approximate geographic centers)
# =============================================================================

COUNTRY_CENTROIDS = {
    # Major economies and trading nations
    'AFG': (33.93, 67.71),    # Afghanistan
    'ALB': (41.15, 20.17),    # Albania
    'DZA': (28.03, 1.66),     # Algeria
    'AGO': (-11.20, 17.87),   # Angola
    'ARG': (-38.42, -63.62),  # Argentina
    'ARM': (40.07, 45.04),    # Armenia
    'AUS': (-25.27, 133.78),  # Australia
    'AUT': (47.52, 14.55),    # Austria
    'AZE': (40.14, 47.58),    # Azerbaijan
    'BHR': (26.07, 50.56),    # Bahrain
    'BGD': (23.68, 90.36),    # Bangladesh
    'BLR': (53.71, 27.95),    # Belarus
    'BEL': (50.50, 4.47),     # Belgium
    'BEN': (9.31, 2.32),      # Benin
    'BOL': (-16.29, -63.59),  # Bolivia
    'BIH': (43.92, 17.68),    # Bosnia and Herzegovina
    'BWA': (-22.33, 24.68),   # Botswana
    'BRA': (-14.24, -51.93),  # Brazil
    'BRN': (4.54, 114.73),    # Brunei
    'BGR': (42.73, 25.49),    # Bulgaria
    'BFA': (12.24, -1.56),    # Burkina Faso
    'BDI': (-3.37, 29.92),    # Burundi
    'KHM': (12.57, 104.99),   # Cambodia
    'CMR': (7.37, 12.35),     # Cameroon
    'CAN': (56.13, -106.35),  # Canada
    'CAF': (6.61, 20.94),     # Central African Republic
    'TCD': (15.45, 18.73),    # Chad
    'CHL': (-35.68, -71.54),  # Chile
    'CHN': (35.86, 104.20),   # China
    'COL': (4.57, -74.30),    # Colombia
    'COG': (-0.23, 15.83),    # Congo
    'COD': (-4.04, 21.76),    # DR Congo
    'CRI': (9.75, -83.75),    # Costa Rica
    'CIV': (7.54, -5.55),     # Côte d'Ivoire
    'HRV': (45.10, 15.20),    # Croatia
    'CUB': (21.52, -77.78),   # Cuba
    'CYP': (35.13, 33.43),    # Cyprus
    'CZE': (49.82, 15.47),    # Czechia
    'DNK': (56.26, 9.50),     # Denmark
    'DOM': (18.74, -70.16),   # Dominican Republic
    'ECU': (-1.83, -78.18),   # Ecuador
    'EGY': (26.82, 30.80),    # Egypt
    'SLV': (13.79, -88.90),   # El Salvador
    'GNQ': (1.65, 10.27),     # Equatorial Guinea
    'ERI': (15.18, 39.78),    # Eritrea
    'EST': (58.60, 25.01),    # Estonia
    'SWZ': (-26.52, 31.47),   # Eswatini
    'ETH': (9.15, 40.49),     # Ethiopia
    'FIN': (61.92, 25.75),    # Finland
    'FRA': (46.23, 2.21),     # France
    'GAB': (-0.80, 11.61),    # Gabon
    'GMB': (13.44, -15.31),   # Gambia
    'GEO': (42.32, 43.36),    # Georgia
    'DEU': (51.17, 10.45),    # Germany
    'GHA': (7.95, -1.02),     # Ghana
    'GRC': (39.07, 21.82),    # Greece
    'GTM': (15.78, -90.23),   # Guatemala
    'GIN': (9.95, -9.70),     # Guinea
    'GNB': (11.80, -15.18),   # Guinea-Bissau
    'GUY': (4.86, -58.93),    # Guyana
    'HTI': (18.97, -72.29),   # Haiti
    'HND': (15.20, -86.24),   # Honduras
    'HKG': (22.40, 114.11),   # Hong Kong
    'HUN': (47.16, 19.50),    # Hungary
    'ISL': (64.96, -19.02),   # Iceland
    'IND': (20.59, 78.96),    # India
    'IDN': (-0.79, 113.92),   # Indonesia
    'IRN': (32.43, 53.69),    # Iran
    'IRQ': (33.22, 43.68),    # Iraq
    'IRL': (53.14, -7.69),    # Ireland
    'ISR': (31.05, 34.85),    # Israel
    'ITA': (41.87, 12.57),    # Italy
    'JAM': (18.11, -77.30),   # Jamaica
    'JPN': (36.20, 138.25),   # Japan
    'JOR': (30.59, 36.24),    # Jordan
    'KAZ': (48.02, 66.92),    # Kazakhstan
    'KEN': (-0.02, 37.91),    # Kenya
    'KWT': (29.31, 47.48),    # Kuwait
    'KGZ': (41.20, 74.77),    # Kyrgyzstan
    'LAO': (19.86, 102.50),   # Laos
    'LVA': (56.88, 24.60),    # Latvia
    'LBN': (33.85, 35.86),    # Lebanon
    'LSO': (-29.61, 28.23),   # Lesotho
    'LBR': (6.43, -9.43),     # Liberia
    'LBY': (26.34, 17.23),    # Libya
    'LTU': (55.17, 23.88),    # Lithuania
    'LUX': (49.82, 6.13),     # Luxembourg
    'MAC': (22.20, 113.55),   # Macao
    'MDG': (-18.77, 46.87),   # Madagascar
    'MWI': (-13.25, 34.30),   # Malawi
    'MYS': (4.21, 101.98),    # Malaysia
    'MLI': (17.57, -4.00),    # Mali
    'MLT': (35.94, 14.38),    # Malta
    'MRT': (21.01, -10.94),   # Mauritania
    'MUS': (-20.35, 57.55),   # Mauritius
    'MEX': (23.63, -102.55),  # Mexico
    'MDA': (47.41, 28.37),    # Moldova
    'MNG': (46.86, 103.85),   # Mongolia
    'MNE': (42.71, 19.37),    # Montenegro
    'MAR': (31.79, -7.09),    # Morocco
    'MOZ': (-18.67, 35.53),   # Mozambique
    'MMR': (21.91, 95.96),    # Myanmar
    'NAM': (-22.96, 18.49),   # Namibia
    'NPL': (28.39, 84.12),    # Nepal
    'NLD': (52.13, 5.29),     # Netherlands
    'NZL': (-40.90, 174.89),  # New Zealand
    'NIC': (12.87, -85.21),   # Nicaragua
    'NER': (17.61, 8.08),     # Niger
    'NGA': (9.08, 8.68),      # Nigeria
    'PRK': (40.34, 127.51),   # North Korea
    'MKD': (41.51, 21.75),    # North Macedonia
    'NOR': (60.47, 8.47),     # Norway
    'OMN': (21.51, 55.92),    # Oman
    'PAK': (30.38, 69.35),    # Pakistan
    'PAN': (8.54, -80.78),    # Panama
    'PNG': (-6.31, 143.96),   # Papua New Guinea
    'PRY': (-23.44, -58.44),  # Paraguay
    'PER': (-9.19, -75.02),   # Peru
    'PHL': (12.88, 121.77),   # Philippines
    'POL': (51.92, 19.15),    # Poland
    'PRT': (39.40, -8.22),    # Portugal
    'QAT': (25.35, 51.18),    # Qatar
    'ROU': (45.94, 24.97),    # Romania
    'RUS': (61.52, 105.32),   # Russia
    'RWA': (-1.94, 29.87),    # Rwanda
    'SAU': (23.89, 45.08),    # Saudi Arabia
    'SEN': (14.50, -14.45),   # Senegal
    'SRB': (44.02, 21.01),    # Serbia
    'SGP': (1.35, 103.82),    # Singapore
    'SVK': (48.67, 19.70),    # Slovakia
    'SVN': (46.15, 14.99),    # Slovenia
    'ZAF': (-30.56, 22.94),   # South Africa
    'KOR': (35.91, 127.77),   # South Korea
    'SSD': (6.88, 31.31),     # South Sudan
    'ESP': (40.46, -3.75),    # Spain
    'LKA': (7.87, 80.77),     # Sri Lanka
    'SDN': (12.86, 30.22),    # Sudan
    'SUR': (3.92, -56.03),    # Suriname
    'SWE': (60.13, 18.64),    # Sweden
    'CHE': (46.82, 8.23),     # Switzerland
    'SYR': (34.80, 39.00),    # Syria
    'TWN': (23.70, 120.96),   # Taiwan
    'TJK': (38.86, 71.28),    # Tajikistan
    'TZA': (-6.37, 34.89),    # Tanzania
    'THA': (15.87, 100.99),   # Thailand
    'TGO': (8.62, 0.82),      # Togo
    'TTO': (10.69, -61.22),   # Trinidad and Tobago
    'TUN': (33.89, 9.54),     # Tunisia
    'TUR': (38.96, 35.24),    # Turkey
    'TKM': (38.97, 59.56),    # Turkmenistan
    'UGA': (1.37, 32.29),     # Uganda
    'UKR': (48.38, 31.17),    # Ukraine
    'ARE': (23.42, 53.85),    # UAE
    'GBR': (55.38, -3.44),    # United Kingdom
    'USA': (37.09, -95.71),   # United States
    'URY': (-32.52, -55.77),  # Uruguay
    'UZB': (41.38, 64.59),    # Uzbekistan
    'VEN': (6.42, -66.59),    # Venezuela
    'VNM': (14.06, 108.28),   # Vietnam
    'YEM': (15.55, 48.52),    # Yemen
    'ZMB': (-13.13, 27.85),   # Zambia
    'ZWE': (-19.02, 29.15),   # Zimbabwe
    
    # Special aggregates (use geometric centers of major trading hubs)
    'WLD': (0.0, 0.0),        # World (center point)
    'EUR': (54.53, 15.26),    # Europe
    'AFR': (8.78, 34.51),     # Africa
    'ASI': (34.05, 100.62),   # Asia
    'AME': (54.53, -105.26),  # Americas
    'OCE': (-22.74, 140.02),  # Oceania
}

# =============================================================================
# ISO TO UN M49 CODE MAPPING
# UN Comtrade uses M49 numeric codes
# =============================================================================

ISO3_TO_M49 = {
    'AFG': '4', 'ALB': '8', 'DZA': '12', 'AND': '20', 'AGO': '24',
    'ATG': '28', 'ARG': '32', 'ARM': '51', 'AUS': '36', 'AUT': '40',
    'AZE': '31', 'BHS': '44', 'BHR': '48', 'BGD': '50', 'BRB': '52',
    'BLR': '112', 'BEL': '56', 'BLZ': '84', 'BEN': '204', 'BTN': '64',
    'BOL': '68', 'BIH': '70', 'BWA': '72', 'BRA': '76', 'BRN': '96',
    'BGR': '100', 'BFA': '854', 'BDI': '108', 'CPV': '132', 'KHM': '116',
    'CMR': '120', 'CAN': '124', 'CAF': '140', 'TCD': '148', 'CHL': '152',
    'CHN': '156', 'COL': '170', 'COM': '174', 'COG': '178', 'COD': '180',
    'CRI': '188', 'CIV': '384', 'HRV': '191', 'CUB': '192', 'CYP': '196',
    'CZE': '203', 'DNK': '208', 'DJI': '262', 'DMA': '212', 'DOM': '214',
    'ECU': '218', 'EGY': '818', 'SLV': '222', 'GNQ': '226', 'ERI': '232',
    'EST': '233', 'SWZ': '748', 'ETH': '231', 'FJI': '242', 'FIN': '246',
    'FRA': '250', 'GAB': '266', 'GMB': '270', 'GEO': '268', 'DEU': '276',
    'GHA': '288', 'GRC': '300', 'GRD': '308', 'GTM': '320', 'GIN': '324',
    'GNB': '624', 'GUY': '328', 'HTI': '332', 'HND': '340', 'HKG': '344',
    'HUN': '348', 'ISL': '352', 'IND': '356', 'IDN': '360', 'IRN': '364',
    'IRQ': '368', 'IRL': '372', 'ISR': '376', 'ITA': '380', 'JAM': '388',
    'JPN': '392', 'JOR': '400', 'KAZ': '398', 'KEN': '404', 'KIR': '296',
    'PRK': '408', 'KOR': '410', 'KWT': '414', 'KGZ': '417', 'LAO': '418',
    'LVA': '428', 'LBN': '422', 'LSO': '426', 'LBR': '430', 'LBY': '434',
    'LIE': '438', 'LTU': '440', 'LUX': '442', 'MAC': '446', 'MDG': '450',
    'MWI': '454', 'MYS': '458', 'MDV': '462', 'MLI': '466', 'MLT': '470',
    'MHL': '584', 'MRT': '478', 'MUS': '480', 'MEX': '484', 'FSM': '583',
    'MDA': '498', 'MCO': '492', 'MNG': '496', 'MNE': '499', 'MAR': '504',
    'MOZ': '508', 'MMR': '104', 'NAM': '516', 'NRU': '520', 'NPL': '524',
    'NLD': '528', 'NZL': '554', 'NIC': '558', 'NER': '562', 'NGA': '566',
    'MKD': '807', 'NOR': '578', 'OMN': '512', 'PAK': '586', 'PLW': '585',
    'PAN': '591', 'PNG': '598', 'PRY': '600', 'PER': '604', 'PHL': '608',
    'POL': '616', 'PRT': '620', 'QAT': '634', 'ROU': '642', 'RUS': '643',
    'RWA': '646', 'KNA': '659', 'LCA': '662', 'VCT': '670', 'WSM': '882',
    'SMR': '674', 'STP': '678', 'SAU': '682', 'SEN': '686', 'SRB': '688',
    'SYC': '690', 'SLE': '694', 'SGP': '702', 'SVK': '703', 'SVN': '705',
    'SLB': '90', 'SOM': '706', 'ZAF': '710', 'SSD': '728', 'ESP': '724',
    'LKA': '144', 'SDN': '729', 'SUR': '740', 'SWE': '752', 'CHE': '757',
    'SYR': '760', 'TWN': '158', 'TJK': '762', 'TZA': '834', 'THA': '764',
    'TLS': '626', 'TGO': '768', 'TON': '776', 'TTO': '780', 'TUN': '788',
    'TUR': '792', 'TKM': '795', 'TUV': '798', 'UGA': '800', 'UKR': '804',
    'ARE': '784', 'GBR': '826', 'USA': '842', 'URY': '858', 'UZB': '860',
    'VUT': '548', 'VEN': '862', 'VNM': '704', 'YEM': '887', 'ZMB': '894',
    'ZWE': '716',
}

# Reverse mapping
M49_TO_ISO3 = {v: k for k, v in ISO3_TO_M49.items()}

# M49 to Country Name mapping (for API responses without names)
M49_TO_NAME = {
    '4': 'Afghanistan', '8': 'Albania', '12': 'Algeria', '24': 'Angola',
    '32': 'Argentina', '36': 'Australia', '40': 'Austria', '50': 'Bangladesh',
    '56': 'Belgium', '68': 'Bolivia', '76': 'Brazil', '100': 'Bulgaria',
    '104': 'Myanmar', '112': 'Belarus', '116': 'Cambodia', '120': 'Cameroon',
    '124': 'Canada', '140': 'Central African Republic', '148': 'Chad',
    '152': 'Chile', '156': 'China', '170': 'Colombia', '178': 'Congo',
    '180': 'DR Congo', '188': 'Costa Rica', '191': 'Croatia', '192': 'Cuba',
    '196': 'Cyprus', '203': 'Czechia', '208': 'Denmark', '214': 'Dominican Republic',
    '218': 'Ecuador', '222': 'El Salvador', '231': 'Ethiopia', '233': 'Estonia',
    '246': 'Finland', '250': 'France', '266': 'Gabon', '268': 'Georgia',
    '270': 'Gambia', '276': 'Germany', '288': 'Ghana', '300': 'Greece',
    '320': 'Guatemala', '324': 'Guinea', '328': 'Guyana', '332': 'Haiti',
    '340': 'Honduras', '344': 'Hong Kong', '348': 'Hungary', '352': 'Iceland',
    '356': 'India', '360': 'Indonesia', '364': 'Iran', '368': 'Iraq',
    '372': 'Ireland', '376': 'Israel', '380': 'Italy', '384': "Côte d'Ivoire",
    '388': 'Jamaica', '392': 'Japan', '398': 'Kazakhstan', '400': 'Jordan',
    '404': 'Kenya', '408': 'North Korea', '410': 'South Korea', '414': 'Kuwait',
    '418': 'Laos', '422': 'Lebanon', '428': 'Latvia', '430': 'Liberia',
    '434': 'Libya', '440': 'Lithuania', '442': 'Luxembourg', '446': 'Macao',
    '450': 'Madagascar', '454': 'Malawi', '458': 'Malaysia', '462': 'Maldives',
    '466': 'Mali', '470': 'Malta', '478': 'Mauritania', '480': 'Mauritius',
    '484': 'Mexico', '496': 'Mongolia', '498': 'Moldova', '499': 'Montenegro',
    '504': 'Morocco', '508': 'Mozambique', '512': 'Oman', '516': 'Namibia',
    '524': 'Nepal', '528': 'Netherlands', '554': 'New Zealand', '558': 'Nicaragua',
    '562': 'Niger', '566': 'Nigeria', '578': 'Norway', '586': 'Pakistan',
    '591': 'Panama', '598': 'Papua New Guinea', '600': 'Paraguay', '604': 'Peru',
    '608': 'Philippines', '616': 'Poland', '620': 'Portugal', '634': 'Qatar',
    '642': 'Romania', '643': 'Russia', '646': 'Rwanda', '682': 'Saudi Arabia',
    '686': 'Senegal', '688': 'Serbia', '694': 'Sierra Leone', '702': 'Singapore',
    '703': 'Slovakia', '705': 'Slovenia', '706': 'Somalia', '710': 'South Africa',
    '716': 'Zimbabwe', '724': 'Spain', '728': 'South Sudan', '729': 'Sudan',
    '740': 'Suriname', '748': 'Eswatini', '752': 'Sweden', '757': 'Switzerland',
    '760': 'Syria', '762': 'Tajikistan', '764': 'Thailand', '768': 'Togo',
    '780': 'Trinidad and Tobago', '784': 'UAE', '788': 'Tunisia', '792': 'Turkey',
    '795': 'Turkmenistan', '800': 'Uganda', '804': 'Ukraine', '818': 'Egypt',
    '826': 'United Kingdom', '834': 'Tanzania', '842': 'United States',
    '854': 'Burkina Faso', '858': 'Uruguay', '860': 'Uzbekistan', '862': 'Venezuela',
    '887': 'Yemen', '894': 'Zambia', '704': 'Vietnam', '158': 'Taiwan',
}

# =============================================================================
# COMMON HS COMMODITY CODES
# =============================================================================

COMMODITY_CODES = {
    # Agricultural commodities
    'cocoa_beans': '1801',
    'cocoa_paste': '1803',
    'cocoa_butter': '1804',
    'coffee_green': '0901',
    'coffee_roasted': '090121',
    'tea': '0902',
    'cotton': '5201',
    'rubber': '4001',
    'tobacco': '2401',
    'sugar_cane': '1701',
    
    # Grains
    'wheat': '1001',
    'rice': '1006',
    'maize': '1005',
    'barley': '1003',
    'sorghum': '1007',
    
    # Oilseeds
    'soybeans': '1201',
    'palm_oil': '1511',
    'sunflower_oil': '1512',
    'groundnuts': '1202',
    
    # Fruits
    'bananas': '0803',
    'citrus': '0805',
    'mangoes': '080450',
    
    # Mining & Energy
    'crude_oil': '2709',
    'natural_gas': '2711',
    'coal': '2701',
    'iron_ore': '2601',
    'copper_ore': '2603',
    'gold': '7108',
    'diamonds': '7102',
    
    # Manufactured goods
    'vehicles': '87',
    'electronics': '85',
    'machinery': '84',
    'pharmaceuticals': '30',
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_country_centroid(iso_code: str) -> Optional[Tuple[float, float]]:
    """
    Get the approximate geographic center (centroid) of a country.
    
    Args:
        iso_code: ISO 2-letter or 3-letter country code
        
    Returns:
        Tuple of (latitude, longitude) or None if not found
    """
    code = iso_code.upper().strip()
    
    # Try ISO3 first
    if code in COUNTRY_CENTROIDS:
        return COUNTRY_CENTROIDS[code]
    
    # Try to convert ISO2 to ISO3
    try:
        import pycountry
        if len(code) == 2:
            country = pycountry.countries.get(alpha_2=code)
            if country:
                code = country.alpha_3
                if code in COUNTRY_CENTROIDS:
                    return COUNTRY_CENTROIDS[code]
        elif len(code) == 3:
            country = pycountry.countries.get(alpha_3=code)
            if country:
                # Already tried above, so country exists but not in our dict
                pass
    except ImportError:
        logger.warning("pycountry not available, using built-in centroids only")
    except Exception as e:
        logger.debug(f"pycountry lookup failed for {code}: {e}")
    
    return None


def _iso3_to_m49(iso3: str) -> Optional[str]:
    """Convert ISO3 country code to UN M49 numeric code."""
    return ISO3_TO_M49.get(iso3.upper())


def _m49_to_iso3(m49: str) -> Optional[str]:
    """Convert UN M49 numeric code to ISO3 country code."""
    return M49_TO_ISO3.get(str(m49))


def _normalize_country_code(code: str) -> Optional[str]:
    """Normalize country code to ISO3 format."""
    code = code.upper().strip()
    
    # Already ISO3
    if len(code) == 3 and code in ISO3_TO_M49:
        return code
    
    # Try ISO2 to ISO3 conversion
    if len(code) == 2:
        try:
            import pycountry
            country = pycountry.countries.get(alpha_2=code)
            if country:
                return country.alpha_3
        except:
            pass
    
    # Try M49 to ISO3
    if code.isdigit():
        iso3 = _m49_to_iso3(code)
        if iso3:
            return iso3
    
    return None


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def fetch_trade_flows(
    reporter_iso: str,
    commodity_code: str,
    flow_type: Literal['export', 'import'] = 'export',
    year: str = '2023',
    max_partners: int = 10
) -> Optional[str]:
    """
    Fetch UN Comtrade trade flow data and return as GeoJSON LineStrings.
    
    Args:
        reporter_iso: ISO 2/3-letter country code of the reporting country
        commodity_code: HS commodity code (e.g., '1801' for cocoa beans)
                       Can also use friendly names from COMMODITY_CODES dict
        flow_type: 'export' (X) or 'import' (M)
        year: Trade year (default '2023')
        max_partners: Maximum number of trading partners to include (default 10)
        
    Returns:
        GeoJSON FeatureCollection string with LineString geometries,
        or None if request fails
        
    Example:
        >>> result = fetch_trade_flows("GHA", "1801", "export")
        >>> # Returns GeoJSON with lines from Ghana to its cocoa export destinations
    """
    logger.info("=" * 60)
    logger.info(f"🚢 Fetching trade flows: {reporter_iso} {flow_type}s of {commodity_code}")
    logger.info("=" * 60)
    
    # Normalize reporter country code
    reporter_iso3 = _normalize_country_code(reporter_iso)
    if not reporter_iso3:
        logger.error(f"  ❌ Unknown country code: {reporter_iso}")
        return None
    
    # Get M49 code for API
    reporter_m49 = _iso3_to_m49(reporter_iso3)
    if not reporter_m49:
        logger.error(f"  ❌ No M49 code for: {reporter_iso3}")
        return None
    
    logger.info(f"  Reporter: {reporter_iso3} (M49: {reporter_m49})")
    
    # Resolve commodity code if using friendly name
    if commodity_code.lower() in COMMODITY_CODES:
        commodity_code = COMMODITY_CODES[commodity_code.lower()]
        logger.info(f"  Resolved commodity: {commodity_code}")
    
    # Flow code: X = Export, M = Import
    flow_code = 'X' if flow_type.lower() == 'export' else 'M'
    logger.info(f"  Flow type: {flow_type} ({flow_code})")
    
    # Get reporter centroid
    reporter_coords = get_country_centroid(reporter_iso3)
    if not reporter_coords:
        logger.error(f"  ❌ No centroid for reporter: {reporter_iso3}")
        return None
    
    logger.info(f"  Reporter coords: {reporter_coords}")
    
    # UN Comtrade API v1 (public/guest access)
    # Note: v2 requires subscription, v1 is free with limitations
    api_url = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
    
    params = {
        'reporterCode': reporter_m49,
        'period': year,
        'cmdCode': commodity_code,
        'flowCode': flow_code,
        'partnerCode': '',  # All partners
        'partner2Code': '',
        'customsCode': '',
        'motCode': '',
    }
    
    logger.info(f"  Calling UN Comtrade API...")
    logger.info(f"  URL: {api_url}")
    
    try:
        headers = {
            'User-Agent': 'PuedoCasa-AgenticMaps/1.0',
            'Accept': 'application/json',
        }
        
        response = requests.get(api_url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 429:
            logger.error("  ❌ Rate limited by UN Comtrade API")
            return json.dumps({
                'error': True,
                'error_type': 'rate_limit',
                'message': '⏳ UN Comtrade API rate limit reached. Please wait 1-2 minutes before trying again.',
                'retry_after_seconds': 60,
                'suggestion': 'The free tier allows ~100 requests per minute. Wait for the limit to reset.',
            })
        
        if response.status_code != 200:
            logger.error(f"  ❌ API returned status {response.status_code}")
            return json.dumps({
                'error': True,
                'error_type': 'api_error',
                'message': f'UN Comtrade API error (HTTP {response.status_code})',
                'status_code': response.status_code,
            })
        
        data = response.json()
        
        if not data or 'data' not in data or not data['data']:
            logger.warning(f"  ⚠️ No trade data found for this query")
            return json.dumps({
                'error': True,
                'error_type': 'no_data',
                'message': f'No trade data found for {reporter_iso3} {flow_type}ing HS {commodity_code} in {year}',
                'suggestion': 'Try a different commodity code, year, or check if this country reports to UN Comtrade.',
            })
        
        # Process the trade data
        records = data['data']
        logger.info(f"  Got {len(records)} trade records")
        
        # Convert to DataFrame for easier processing
        df = pd.DataFrame(records)
        
        # Filter out "World" aggregate and self-trade
        if 'partnerCode' in df.columns:
            df = df[df['partnerCode'] != 0]  # Remove World aggregate
            df = df[df['partnerCode'] != int(reporter_m49)]  # Remove self-trade
        
        # Aggregate by partner (sum trade values)
        value_col = 'primaryValue' if 'primaryValue' in df.columns else 'fobvalue'
        if value_col in df.columns:
            df[value_col] = pd.to_numeric(df[value_col], errors='coerce').fillna(0)
            df = df.groupby('partnerCode').agg({
                value_col: 'sum',
                'partnerDesc': 'first',
            }).reset_index()
        
        # Sort by trade value and take top N
        if value_col in df.columns:
            df = df.sort_values(value_col, ascending=False).head(max_partners)
        
        # Build GeoJSON features
        features = []
        
        for _, row in df.iterrows():
            partner_m49 = str(row.get('partnerCode', ''))
            partner_iso3 = _m49_to_iso3(partner_m49)
            
            if not partner_iso3:
                continue
            
            partner_coords = get_country_centroid(partner_iso3)
            if not partner_coords:
                continue
            
            # Get trade value
            trade_value = row.get('primaryValue') or row.get('fobvalue') or row.get('cifvalue') or 0
            
            # Get partner name (API preview endpoint often returns None)
            partner_name = row.get('partnerDesc')
            if not partner_name or partner_name == 'None':
                partner_name = M49_TO_NAME.get(partner_m49, partner_iso3)
            
            commodity_desc = row.get('cmdDesc')
            if not commodity_desc or commodity_desc == 'None':
                commodity_desc = f'HS {commodity_code}'
            
            # Create LineString from reporter to partner
            # Note: GeoJSON uses [lon, lat] order
            if flow_type.lower() == 'export':
                # Export: line goes FROM reporter TO partner
                line_coords = [
                    [reporter_coords[1], reporter_coords[0]],  # Start: reporter
                    [partner_coords[1], partner_coords[0]]     # End: partner
                ]
            else:
                # Import: line goes FROM partner TO reporter
                line_coords = [
                    [partner_coords[1], partner_coords[0]],    # Start: partner
                    [reporter_coords[1], reporter_coords[0]]   # End: reporter
                ]
            
            line = LineString(line_coords)
            
            feature = {
                'type': 'Feature',
                'geometry': mapping(line),
                'properties': {
                    'trade_value_usd': float(trade_value),
                    'reporter_iso': reporter_iso3,
                    'reporter_name': row.get('reporterDesc', reporter_iso3),
                    'partner_iso': partner_iso3,
                    'partner_name': partner_name,
                    'commodity_code': commodity_code,
                    'commodity_name': commodity_desc,
                    'flow_type': flow_type,
                    'year': year,
                }
            }
            
            features.append(feature)
        
        if not features:
            logger.warning("  ⚠️ No valid trade flows could be mapped")
            return json.dumps({
                'error': True,
                'error_type': 'no_mappable_data',
                'message': f'Trade data exists but partner countries could not be mapped to coordinates',
                'suggestion': 'This may be due to missing country centroid data for some trading partners.',
            })
        
        geojson = {
            'type': 'FeatureCollection',
            'features': features,
            'properties': {
                'reporter': reporter_iso3,
                'commodity': commodity_code,
                'flow_type': flow_type,
                'year': year,
                'total_partners': len(features),
            }
        }
        
        total_value = sum(f['properties']['trade_value_usd'] for f in features)
        logger.info(f"  ✅ Created {len(features)} trade flow lines")
        logger.info(f"  Total trade value: ${total_value:,.0f}")
        
        return json.dumps(geojson, indent=2)
        
    except requests.exceptions.Timeout:
        logger.error("  ❌ API request timed out")
        return json.dumps({
            'error': True,
            'error_type': 'timeout',
            'message': '⏳ UN Comtrade API request timed out. Please try again.',
            'suggestion': 'The API may be experiencing high load. Wait a moment and retry.',
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ API request failed: {e}")
        return json.dumps({
            'error': True,
            'error_type': 'request_error',
            'message': f'Network error contacting UN Comtrade API: {str(e)}',
            'suggestion': 'Check your internet connection and try again.',
        })
    except Exception as e:
        logger.error(f"  ❌ Error processing trade data: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({
            'error': True,
            'error_type': 'processing_error',
            'message': f'Error processing trade data: {str(e)}',
        })


def list_commodity_codes() -> Dict[str, str]:
    """Return dictionary of friendly names to HS codes."""
    return COMMODITY_CODES.copy()


def get_top_exporters(commodity_code: str) -> List[str]:
    """
    Get list of top exporting countries for a commodity.
    Useful for suggesting which countries to query.
    """
    TOP_EXPORTERS = {
        '1801': ['CIV', 'GHA', 'IDN', 'NGA', 'CMR', 'ECU', 'BRA', 'PER', 'DOM', 'COL'],  # Cocoa
        '0901': ['BRA', 'VNM', 'COL', 'IDN', 'ETH', 'HND', 'IND', 'UGA', 'MEX', 'GTM'],  # Coffee
        '5201': ['USA', 'IND', 'BRA', 'AUS', 'PAK', 'UZB', 'TUR', 'MLI', 'BFA', 'GRC'],  # Cotton
        '4001': ['THA', 'IDN', 'VNM', 'MYS', 'CIV', 'IND', 'CHN', 'LBR', 'CMR', 'GTM'],  # Rubber
        '1511': ['IDN', 'MYS', 'THA', 'COL', 'PNG', 'GTM', 'HND', 'NGA', 'CIV', 'ECU'],  # Palm oil
        '1006': ['IND', 'THA', 'VNM', 'PAK', 'USA', 'CHN', 'MMR', 'BRA', 'URY', 'ARG'],  # Rice
        '1001': ['RUS', 'AUS', 'CAN', 'USA', 'FRA', 'UKR', 'ARG', 'DEU', 'KAZ', 'ROM'],  # Wheat
    }
    return TOP_EXPORTERS.get(commodity_code, [])


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🚢 Trade Flow Tools - Test Suite")
    print("=" * 70)
    
    print(f"\n📊 Statistics:")
    print(f"  - Country centroids: {len(COUNTRY_CENTROIDS)}")
    print(f"  - ISO3 to M49 mappings: {len(ISO3_TO_M49)}")
    print(f"  - Commodity codes: {len(COMMODITY_CODES)}")
    
    print(f"\n🌍 Sample country centroids:")
    for code in ['GHA', 'CIV', 'BRA', 'VNM', 'CHN', 'USA', 'DEU', 'NLD']:
        coords = get_country_centroid(code)
        print(f"  {code}: {coords}")
    
    print(f"\n📦 Common commodity codes:")
    for name, code in list(COMMODITY_CODES.items())[:10]:
        print(f"  {name}: {code}")
    
    print("\n" + "-" * 70)
    print("--- Testing fetch_trade_flows ---")
    print("-" * 70)
    
    def handle_result(result, test_name):
        """Helper to handle both success and error responses."""
        if not result:
            print("❌ No data returned")
            return
        
        data = json.loads(result)
        
        # Check if it's an error response
        if data.get('error'):
            print(f"⚠️  {data.get('message', 'Unknown error')}")
            if 'suggestion' in data:
                print(f"   💡 {data['suggestion']}")
            return
        
        # Success - show trade flows
        print(f"✅ Got {len(data['features'])} trade flows")
        for f in data['features'][:3]:
            props = f['properties']
            print(f"   → {props['partner_name']}: ${props['trade_value_usd']:,.0f}")
        
        if len(data['features']) > 3:
            total = sum(f['properties']['trade_value_usd'] for f in data['features'])
            print(f"   ... and {len(data['features']) - 3} more (Total: ${total:,.0f})")
    
    # Test Ghana cocoa exports
    print("\n🍫 Test: Ghana Cocoa Exports")
    result = fetch_trade_flows("GHA", "1801", "export", max_partners=5)
    handle_result(result, "Ghana Cocoa")
    
    # Test Brazil coffee exports
    print("\n☕ Test: Brazil Coffee Exports")
    result = fetch_trade_flows("BRA", "coffee_green", "export", max_partners=5)
    handle_result(result, "Brazil Coffee")
    
    # Test Côte d'Ivoire cocoa exports
    print("\n🍫 Test: Côte d'Ivoire Cocoa Exports")
    result = fetch_trade_flows("CIV", "1801", "export", max_partners=5)
    handle_result(result, "CIV Cocoa")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)

