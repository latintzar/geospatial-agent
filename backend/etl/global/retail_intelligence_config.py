"""
Earth Matrix ULTRA-MAXED Schema Configuration
==============================================

Level-3 Granularity: EVERY POI subcategory gets its own columns.

Example:
    - italian_restaurant_count, italian_restaurant_walk_min, ...
    - japanese_restaurant_count, japanese_restaurant_walk_min, ...
    - wine_bar_count, wine_bar_walk_min, ...

Total: ~2,100 POI categories × 5 columns = ~10,500 POI columns
Grand Total: ~11,000 columns

Cost: ~$90 for global build (4 resolutions)
Storage: ~6 TB (fits on 10TB Hetzner box @ €25/month)

Usage:
    from retail_intelligence_config import (
        POI_CATEGORIES_L3,
        get_poi_sql_filter,
        get_column_count,
    )
"""

from typing import Dict, List, Tuple, Any

# =============================================================================
# VERSION INFO
# =============================================================================

SCHEMA_VERSION = "4.0"
SCHEMA_NAME = "earth_matrix_ultra_maxed"

# =============================================================================
# LEVEL-3 POI CATEGORIES
# Each subcategory is its OWN key for separate columns
# =============================================================================

# -----------------------------------------------------------------------------
# 1. EAT_AND_DRINK - Restaurants (36 types)
# -----------------------------------------------------------------------------
RESTAURANTS = [
    "restaurant",
    "afghan_restaurant",
    "african_restaurant", 
    "american_restaurant",
    "asian_restaurant",
    "barbecue_restaurant",
    "breakfast_and_brunch_restaurant",
    "burger_restaurant",
    "caribbean_restaurant",
    "chinese_restaurant",
    "diner",
    "fast_food_restaurant",
    "french_restaurant",
    "german_restaurant",
    "greek_restaurant",
    "indian_restaurant",
    "italian_restaurant",
    "japanese_restaurant",
    "korean_restaurant",
    "latin_american_restaurant",
    "mediterranean_restaurant",
    "mexican_restaurant",
    "middle_eastern_restaurant",
    "peruvian_restaurant",
    "pizza_restaurant",
    "polish_restaurant",
    "portuguese_restaurant",
    "russian_restaurant",
    "seafood_restaurant",
    "spanish_restaurant",
    "steakhouse",
    "sushi_restaurant",
    "thai_restaurant",
    "turkish_restaurant",
    "vegan_restaurant",
    "vegetarian_restaurant",
    "vietnamese_restaurant",
    "hot_dog_restaurant",
    "doner_kebab",
    "taco_restaurant",
    "chicken_restaurant",
    "fish_and_chips_restaurant",
    "ramen_restaurant",
    "pho_restaurant",
    "dim_sum_restaurant",
    "tapas_restaurant",
    "fondue_restaurant",
    "brazilian_restaurant",
    "ethiopian_restaurant",
    "moroccan_restaurant",
    "lebanese_restaurant",
    "syrian_restaurant",
    "israeli_restaurant",
    "hawaiian_restaurant",
    "cajun_restaurant",
    "soul_food_restaurant",
    "southern_restaurant",
    "tex_mex_restaurant",
    "cuban_restaurant",
    "puerto_rican_restaurant",
    "dominican_restaurant",
    "jamaican_restaurant",
    "haitian_restaurant",
    "trinidadian_restaurant",
    "filipino_restaurant",
    "indonesian_restaurant",
    "malaysian_restaurant",
    "singaporean_restaurant",
    "burmese_restaurant",
    "cambodian_restaurant",
    "laotian_restaurant",
    "nepalese_restaurant",
    "tibetan_restaurant",
    "afghan_restaurant",
    "pakistani_restaurant",
    "bangladeshi_restaurant",
    "sri_lankan_restaurant",
]

# -----------------------------------------------------------------------------
# 1. EAT_AND_DRINK - Bars (30 types)
# -----------------------------------------------------------------------------
BARS = [
    "bar",
    "airport_lounge",
    "beach_bar",
    "beer_bar",
    "beer_garden",
    "brewery",
    "champagne_bar",
    "cidery",
    "cocktail_bar",
    "dive_bar",
    "gay_bar",
    "hookah_bar",
    "hotel_bar",
    "irish_pub",
    "juice_bar",
    "karaoke_bar",
    "lounge",
    "mezcaleria",
    "nightclub",
    "pub",
    "rooftop_bar",
    "sake_bar",
    "speakeasy",
    "sports_bar",
    "tequila_bar",
    "tiki_bar",
    "whisky_bar",
    "wine_bar",
    "distillery",
    "taproom",
    "microbrewery",
    "brewpub",
    "piano_bar",
    "jazz_bar",
    "blues_bar",
    "country_bar",
    "latin_bar",
    "salsa_club",
    "reggae_bar",
    "hip_hop_club",
    "electronic_club",
    "techno_club",
    "house_club",
]

# -----------------------------------------------------------------------------
# 1. EAT_AND_DRINK - Cafes (20 types)
# -----------------------------------------------------------------------------
CAFES = [
    "cafe",
    "bagel_shop",
    "bakery",
    "bubble_tea",
    "coffee_roaster",
    "coffee_shop",
    "dessert_shop",
    "donut_shop",
    "gelato_shop",
    "ice_cream_shop",
    "internet_cafe",
    "patisserie",
    "tea_room",
    "matcha_cafe",
    "specialty_coffee",
    "third_wave_coffee",
    "espresso_bar",
    "french_bakery",
    "italian_bakery",
    "jewish_bakery",
    "asian_bakery",
    "cupcake_shop",
    "macaron_shop",
    "crepe_shop",
    "waffle_shop",
    "smoothie_bar",
    "acai_bowl",
    "frozen_yogurt",
    "shaved_ice",
    "boba_tea",
]

# -----------------------------------------------------------------------------
# 2. ACCOMMODATION (25 types)
# -----------------------------------------------------------------------------
ACCOMMODATION = [
    "hotel",
    "boutique_hotel",
    "luxury_hotel",
    "budget_hotel",
    "business_hotel",
    "airport_hotel",
    "resort",
    "beach_resort",
    "ski_resort",
    "spa_resort",
    "golf_resort",
    "motel",
    "hostel",
    "bed_and_breakfast",
    "inn",
    "lodge",
    "cabin",
    "cottage",
    "villa",
    "guest_house",
    "pension",
    "ryokan",
    "capsule_hotel",
    "love_hotel",
    "service_apartments",
    "extended_stay",
    "vacation_rental",
    "airbnb",
    "campground",
    "glamping",
    "rv_park",
    "caravan_park",
    "youth_hostel",
    "backpacker_hostel",
]

# -----------------------------------------------------------------------------
# 3. ACTIVE_LIFE - Sports Venues (60 types)
# -----------------------------------------------------------------------------
SPORTS_VENUES = [
    "gym",
    "fitness_center",
    "health_club",
    "crossfit",
    "boxing_gym",
    "mma_gym",
    "kickboxing_gym",
    "martial_arts",
    "karate_dojo",
    "judo_dojo",
    "taekwondo_dojo",
    "jiu_jitsu",
    "muay_thai",
    "wrestling_gym",
    "yoga_studio",
    "hot_yoga",
    "pilates_studio",
    "barre_studio",
    "dance_studio",
    "ballet_studio",
    "hip_hop_dance",
    "salsa_dance",
    "ballroom_dance",
    "pole_dance",
    "cycling_studio",
    "spin_class",
    "rowing_studio",
    "swimming_pool",
    "lap_pool",
    "aquatic_center",
    "tennis_court",
    "tennis_club",
    "squash_court",
    "racquetball_court",
    "badminton_court",
    "basketball_court",
    "volleyball_court",
    "beach_volleyball",
    "soccer_field",
    "football_field",
    "baseball_field",
    "softball_field",
    "cricket_ground",
    "rugby_field",
    "hockey_rink",
    "ice_skating_rink",
    "roller_skating_rink",
    "skateboard_park",
    "bmx_track",
    "golf_course",
    "driving_range",
    "mini_golf",
    "disc_golf",
    "bowling_alley",
    "pool_hall",
    "billiards",
    "darts",
    "archery_range",
    "shooting_range",
    "gun_range",
    "climbing_gym",
    "bouldering_gym",
    "trampoline_park",
    "gymnastics_center",
    "parkour_gym",
    "calisthenics_park",
    "outdoor_gym",
    "bootcamp",
    "personal_training",
    "weight_room",
    "powerlifting_gym",
    "bodybuilding_gym",
    "olympic_lifting",
    "strongman_gym",
]

# -----------------------------------------------------------------------------
# 4. ARTS_AND_ENTERTAINMENT (70 types)
# -----------------------------------------------------------------------------
ENTERTAINMENT = [
    "cinema",
    "movie_theater",
    "imax",
    "drive_in_theater",
    "arthouse_cinema",
    "multiplex",
    "theater",
    "playhouse",
    "broadway",
    "off_broadway",
    "community_theater",
    "dinner_theater",
    "opera_house",
    "ballet",
    "concert_hall",
    "symphony_hall",
    "music_venue",
    "live_music",
    "jazz_club",
    "blues_club",
    "rock_venue",
    "punk_venue",
    "metal_venue",
    "country_venue",
    "folk_venue",
    "comedy_club",
    "improv_club",
    "stand_up_comedy",
    "cabaret",
    "burlesque",
    "magic_show",
    "circus",
    "casino",
    "card_room",
    "poker_room",
    "slots",
    "bingo_hall",
    "arcade",
    "video_arcade",
    "pinball_arcade",
    "retro_arcade",
    "vr_arcade",
    "escape_room",
    "laser_tag",
    "paintball",
    "go_kart",
    "bowling",
    "mini_golf",
    "batting_cage",
    "axe_throwing",
    "trampoline_park",
    "amusement_park",
    "theme_park",
    "water_park",
    "carnival",
    "fair",
    "zoo",
    "aquarium",
    "planetarium",
    "science_center",
    "childrens_museum",
    "discovery_center",
    "indoor_playground",
    "bounce_house",
    "kids_gym",
    "family_entertainment",
    "adult_entertainment",
    "strip_club",
    "gentlemens_club",
]

# -----------------------------------------------------------------------------
# 5. ATTRACTIONS (50 types)
# -----------------------------------------------------------------------------
ATTRACTIONS = [
    "museum",
    "art_museum",
    "history_museum",
    "science_museum",
    "natural_history_museum",
    "war_museum",
    "military_museum",
    "maritime_museum",
    "aviation_museum",
    "automobile_museum",
    "sports_museum",
    "music_museum",
    "film_museum",
    "fashion_museum",
    "design_museum",
    "architecture_museum",
    "photography_museum",
    "contemporary_art_museum",
    "modern_art_museum",
    "folk_art_museum",
    "childrens_museum",
    "art_gallery",
    "gallery",
    "exhibition_space",
    "cultural_center",
    "heritage_center",
    "visitor_center",
    "tourist_attraction",
    "landmark",
    "monument",
    "memorial",
    "statue",
    "sculpture",
    "historic_site",
    "archaeological_site",
    "ruins",
    "castle",
    "palace",
    "fortress",
    "citadel",
    "tower",
    "lighthouse",
    "bridge",
    "viewpoint",
    "observation_deck",
    "scenic_lookout",
    "botanical_garden",
    "arboretum",
    "conservatory",
    "zoo",
    "safari_park",
    "wildlife_sanctuary",
    "bird_sanctuary",
    "aquarium",
    "marine_park",
    "planetarium",
    "observatory",
]

# -----------------------------------------------------------------------------
# 6. AUTOMOTIVE (25 types)
# -----------------------------------------------------------------------------
AUTOMOTIVE = [
    "gas_station",
    "petrol_station",
    "fuel_station",
    "truck_stop",
    "ev_charging_station",
    "tesla_supercharger",
    "car_dealer",
    "used_car_dealer",
    "motorcycle_dealer",
    "auto_parts_store",
    "tire_shop",
    "auto_repair",
    "mechanic",
    "oil_change",
    "brake_shop",
    "transmission_shop",
    "body_shop",
    "auto_glass",
    "car_wash",
    "auto_detailing",
    "car_rental",
    "truck_rental",
    "motorcycle_rental",
    "parking_garage",
    "parking_lot",
    "valet_parking",
    "towing_service",
    "roadside_assistance",
    "smog_check",
    "emissions_testing",
]

# -----------------------------------------------------------------------------
# 7. BEAUTY_AND_SPA (35 types)
# -----------------------------------------------------------------------------
BEAUTY_SPA = [
    "hair_salon",
    "barbershop",
    "mens_salon",
    "womens_salon",
    "unisex_salon",
    "hair_extensions",
    "hair_color",
    "keratin_treatment",
    "nail_salon",
    "manicure",
    "pedicure",
    "nail_art",
    "beauty_salon",
    "makeup_artist",
    "makeup_studio",
    "eyebrow_bar",
    "brow_bar",
    "lash_extensions",
    "lash_studio",
    "waxing",
    "laser_hair_removal",
    "electrolysis",
    "threading",
    "skin_care",
    "facial",
    "aesthetician",
    "dermatologist_spa",
    "med_spa",
    "day_spa",
    "spa",
    "massage",
    "massage_therapy",
    "thai_massage",
    "swedish_massage",
    "deep_tissue_massage",
    "hot_stone_massage",
    "couples_massage",
    "reflexology",
    "acupuncture",
    "cupping",
    "sauna",
    "steam_room",
    "hammam",
    "korean_spa",
    "japanese_onsen",
    "float_tank",
    "cryotherapy",
    "tanning_salon",
    "spray_tan",
    "tattoo_parlor",
    "tattoo_studio",
    "piercing_studio",
    "microblading",
    "permanent_makeup",
    "teeth_whitening",
]

# -----------------------------------------------------------------------------
# 8. EDUCATION (40 types)
# -----------------------------------------------------------------------------
EDUCATION = [
    "school",
    "elementary_school",
    "middle_school",
    "high_school",
    "private_school",
    "public_school",
    "charter_school",
    "magnet_school",
    "boarding_school",
    "international_school",
    "montessori_school",
    "waldorf_school",
    "religious_school",
    "catholic_school",
    "jewish_school",
    "islamic_school",
    "preschool",
    "kindergarten",
    "daycare",
    "nursery",
    "childcare",
    "after_school_program",
    "tutoring_center",
    "learning_center",
    "test_prep",
    "sat_prep",
    "college_prep",
    "university",
    "college",
    "community_college",
    "vocational_school",
    "trade_school",
    "technical_school",
    "art_school",
    "music_school",
    "dance_school",
    "drama_school",
    "film_school",
    "culinary_school",
    "language_school",
    "driving_school",
    "flight_school",
    "coding_bootcamp",
    "business_school",
    "law_school",
    "medical_school",
    "nursing_school",
    "dental_school",
    "pharmacy_school",
    "veterinary_school",
    "seminary",
    "library",
    "public_library",
]

# -----------------------------------------------------------------------------
# 9. FINANCIAL_SERVICE (30 types)
# -----------------------------------------------------------------------------
FINANCIAL = [
    "bank",
    "credit_union",
    "savings_bank",
    "investment_bank",
    "private_bank",
    "atm",
    "cash_machine",
    "currency_exchange",
    "money_transfer",
    "western_union",
    "check_cashing",
    "payday_loans",
    "pawn_shop",
    "accountant",
    "cpa",
    "bookkeeper",
    "tax_preparation",
    "tax_service",
    "financial_advisor",
    "wealth_management",
    "investment_advisor",
    "stockbroker",
    "insurance_agency",
    "insurance_broker",
    "mortgage_broker",
    "mortgage_lender",
    "real_estate_agent",
    "realtor",
    "title_company",
    "escrow_company",
    "notary",
]

# -----------------------------------------------------------------------------
# 10. HEALTH_AND_MEDICAL (80 types)
# -----------------------------------------------------------------------------
HEALTH_MEDICAL = [
    "hospital",
    "medical_center",
    "clinic",
    "urgent_care",
    "emergency_room",
    "trauma_center",
    "childrens_hospital",
    "maternity_hospital",
    "psychiatric_hospital",
    "rehabilitation_center",
    "nursing_home",
    "assisted_living",
    "hospice",
    "doctor",
    "physician",
    "family_doctor",
    "general_practitioner",
    "internist",
    "pediatrician",
    "obgyn",
    "gynecologist",
    "urologist",
    "cardiologist",
    "dermatologist",
    "neurologist",
    "psychiatrist",
    "psychologist",
    "therapist",
    "counselor",
    "oncologist",
    "orthopedist",
    "ophthalmologist",
    "optometrist",
    "ent_doctor",
    "allergist",
    "pulmonologist",
    "gastroenterologist",
    "endocrinologist",
    "rheumatologist",
    "nephrologist",
    "hematologist",
    "surgeon",
    "plastic_surgeon",
    "cosmetic_surgeon",
    "dentist",
    "dental_clinic",
    "orthodontist",
    "periodontist",
    "endodontist",
    "oral_surgeon",
    "pediatric_dentist",
    "cosmetic_dentist",
    "pharmacy",
    "drugstore",
    "compounding_pharmacy",
    "chiropractor",
    "physical_therapy",
    "occupational_therapy",
    "speech_therapy",
    "acupuncturist",
    "naturopath",
    "homeopath",
    "herbalist",
    "nutritionist",
    "dietitian",
    "personal_trainer",
    "health_coach",
    "wellness_center",
    "mental_health_clinic",
    "addiction_treatment",
    "rehab_center",
    "detox_center",
    "methadone_clinic",
    "cannabis_dispensary",
    "medical_marijuana",
    "fertility_clinic",
    "ivf_clinic",
    "blood_bank",
    "plasma_center",
    "dialysis_center",
    "sleep_clinic",
    "weight_loss_clinic",
    "lasik_center",
    "hearing_aid_center",
    "prosthetics",
    "medical_equipment",
    "home_health_care",
    "ambulance_service",
    "veterinarian",
    "animal_hospital",
    "pet_clinic",
    "emergency_vet",
]

# -----------------------------------------------------------------------------
# 11. RETAIL - Shopping (100 types)
# -----------------------------------------------------------------------------
RETAIL_SHOPPING = [
    "supermarket",
    "grocery_store",
    "organic_grocery",
    "health_food_store",
    "whole_foods",
    "trader_joes",
    "asian_grocery",
    "latin_grocery",
    "indian_grocery",
    "middle_eastern_grocery",
    "european_grocery",
    "butcher",
    "meat_market",
    "fish_market",
    "seafood_market",
    "farmers_market",
    "produce_market",
    "bakery",
    "cheese_shop",
    "deli",
    "specialty_food",
    "gourmet_food",
    "wine_shop",
    "liquor_store",
    "beer_store",
    "convenience_store",
    "corner_store",
    "bodega",
    "7_eleven",
    "gas_station_convenience",
    "department_store",
    "shopping_mall",
    "shopping_center",
    "outlet_mall",
    "strip_mall",
    "big_box_store",
    "warehouse_store",
    "costco",
    "walmart",
    "target",
    "clothing_store",
    "fashion_boutique",
    "designer_store",
    "luxury_store",
    "fast_fashion",
    "vintage_store",
    "thrift_store",
    "consignment_store",
    "mens_clothing",
    "womens_clothing",
    "childrens_clothing",
    "maternity_store",
    "plus_size_store",
    "athletic_wear",
    "activewear",
    "sportswear",
    "outdoor_gear",
    "camping_store",
    "hiking_store",
    "ski_shop",
    "surf_shop",
    "skateboard_shop",
    "bike_shop",
    "running_store",
    "shoe_store",
    "sneaker_store",
    "athletic_shoes",
    "dress_shoes",
    "boots",
    "sandals",
    "jewelry_store",
    "fine_jewelry",
    "costume_jewelry",
    "watch_store",
    "luxury_watches",
    "sunglasses_store",
    "optical_store",
    "eyewear",
    "handbag_store",
    "luggage_store",
    "leather_goods",
    "accessories_store",
    "hat_store",
    "scarf_store",
    "electronics_store",
    "computer_store",
    "apple_store",
    "phone_store",
    "mobile_phone_store",
    "camera_store",
    "audio_store",
    "video_game_store",
    "gamestop",
    "furniture_store",
    "home_decor",
    "home_goods",
    "bed_bath_beyond",
    "ikea",
    "pottery_barn",
    "crate_barrel",
    "west_elm",
    "restoration_hardware",
    "antique_store",
    "vintage_furniture",
    "mattress_store",
    "appliance_store",
    "kitchen_store",
    "cookware_store",
    "williams_sonoma",
    "sur_la_table",
    "hardware_store",
    "home_depot",
    "lowes",
    "ace_hardware",
    "garden_center",
    "nursery",
    "plant_store",
    "florist",
    "flower_shop",
    "pet_store",
    "pet_supplies",
    "petsmart",
    "petco",
    "aquarium_store",
    "bird_store",
    "toy_store",
    "game_store",
    "hobby_store",
    "craft_store",
    "michaels",
    "joann",
    "art_supply",
    "stationery_store",
    "office_supply",
    "staples",
    "office_depot",
    "book_store",
    "barnes_noble",
    "independent_bookstore",
    "used_bookstore",
    "comic_book_store",
    "record_store",
    "vinyl_store",
    "music_store",
    "instrument_store",
    "guitar_center",
    "sporting_goods",
    "dicks_sporting_goods",
    "rei",
    "bass_pro_shops",
    "gun_store",
    "hunting_store",
    "fishing_store",
    "dollar_store",
    "dollar_tree",
    "99_cents_store",
    "discount_store",
    "party_supply",
    "party_city",
    "costume_store",
    "halloween_store",
    "gift_shop",
    "souvenir_shop",
    "smoke_shop",
    "tobacco_shop",
    "vape_shop",
    "cbd_store",
    "head_shop",
    "sex_shop",
    "adult_store",
]

# -----------------------------------------------------------------------------
# 12. PROFESSIONAL_SERVICES (40 types)
# -----------------------------------------------------------------------------
PROFESSIONAL = [
    "lawyer",
    "attorney",
    "law_firm",
    "legal_services",
    "personal_injury_lawyer",
    "criminal_lawyer",
    "divorce_lawyer",
    "immigration_lawyer",
    "real_estate_lawyer",
    "business_lawyer",
    "corporate_lawyer",
    "patent_lawyer",
    "trademark_lawyer",
    "architect",
    "architectural_firm",
    "interior_designer",
    "graphic_designer",
    "web_designer",
    "photographer",
    "photo_studio",
    "videographer",
    "video_production",
    "marketing_agency",
    "advertising_agency",
    "pr_agency",
    "consulting_firm",
    "management_consulting",
    "it_consulting",
    "hr_consulting",
    "recruiting_agency",
    "staffing_agency",
    "temp_agency",
    "translation_services",
    "interpreter",
    "printing_services",
    "print_shop",
    "copy_center",
    "fedex_office",
    "ups_store",
    "mailbox_store",
    "coworking_space",
    "shared_office",
    "executive_suite",
    "virtual_office",
]

# -----------------------------------------------------------------------------
# 13. HOME_SERVICE (40 types)
# -----------------------------------------------------------------------------
HOME_SERVICE = [
    "plumber",
    "plumbing",
    "electrician",
    "electrical",
    "hvac",
    "heating",
    "cooling",
    "air_conditioning",
    "roofer",
    "roofing",
    "carpenter",
    "carpentry",
    "painter",
    "painting",
    "handyman",
    "general_contractor",
    "remodeling",
    "renovation",
    "kitchen_remodel",
    "bathroom_remodel",
    "flooring",
    "tile",
    "hardwood",
    "carpet",
    "window_installation",
    "door_installation",
    "garage_door",
    "fence",
    "deck",
    "patio",
    "landscaping",
    "lawn_care",
    "tree_service",
    "pool_service",
    "pool_cleaning",
    "pest_control",
    "exterminator",
    "cleaning_service",
    "maid_service",
    "house_cleaning",
    "carpet_cleaning",
    "window_cleaning",
    "pressure_washing",
    "junk_removal",
    "moving_company",
    "storage_facility",
    "self_storage",
    "locksmith",
    "security_system",
    "alarm_system",
    "home_security",
    "appliance_repair",
    "washer_repair",
    "dryer_repair",
    "refrigerator_repair",
    "dishwasher_repair",
]

# -----------------------------------------------------------------------------
# 14. PUBLIC_SERVICE (40 types)
# -----------------------------------------------------------------------------
PUBLIC_SERVICE = [
    "city_hall",
    "town_hall",
    "government_office",
    "federal_building",
    "state_office",
    "county_office",
    "dmv",
    "motor_vehicles",
    "post_office",
    "usps",
    "social_security_office",
    "welfare_office",
    "unemployment_office",
    "tax_office",
    "irs_office",
    "courthouse",
    "court",
    "police_station",
    "police_department",
    "sheriff",
    "fire_station",
    "fire_department",
    "ems",
    "ambulance",
    "jail",
    "prison",
    "community_center",
    "recreation_center",
    "senior_center",
    "youth_center",
    "public_library",
    "library",
    "park",
    "public_park",
    "playground",
    "dog_park",
    "skate_park",
    "swimming_pool",
    "public_pool",
    "beach",
    "public_beach",
]

# -----------------------------------------------------------------------------
# 15. RELIGIOUS (25 types)
# -----------------------------------------------------------------------------
RELIGIOUS = [
    "church",
    "cathedral",
    "chapel",
    "baptist_church",
    "catholic_church",
    "methodist_church",
    "lutheran_church",
    "presbyterian_church",
    "episcopal_church",
    "orthodox_church",
    "pentecostal_church",
    "evangelical_church",
    "non_denominational_church",
    "megachurch",
    "mosque",
    "islamic_center",
    "synagogue",
    "jewish_temple",
    "buddhist_temple",
    "hindu_temple",
    "sikh_temple",
    "gurdwara",
    "shinto_shrine",
    "taoist_temple",
    "monastery",
    "convent",
    "ashram",
    "meditation_center",
    "spiritual_center",
    "scientology_center",
    "kingdom_hall",
    "lds_temple",
    "mormon_church",
]

# -----------------------------------------------------------------------------
# 16. TRAVEL_TRANSIT (40 types)
# -----------------------------------------------------------------------------
TRAVEL_TRANSIT = [
    "airport",
    "international_airport",
    "domestic_airport",
    "regional_airport",
    "private_airport",
    "heliport",
    "train_station",
    "railway_station",
    "metro_station",
    "subway_station",
    "light_rail_station",
    "tram_stop",
    "bus_station",
    "bus_stop",
    "bus_terminal",
    "ferry_terminal",
    "cruise_terminal",
    "port",
    "marina",
    "yacht_club",
    "boat_dock",
    "car_rental",
    "rental_car",
    "hertz",
    "avis",
    "enterprise",
    "taxi_stand",
    "uber",
    "lyft",
    "rideshare",
    "limousine_service",
    "shuttle_service",
    "airport_shuttle",
    "travel_agency",
    "tour_operator",
    "cruise_agency",
    "visa_service",
    "passport_office",
    "currency_exchange",
    "luggage_storage",
]

# -----------------------------------------------------------------------------
# 17. REAL_ESTATE (20 types)
# -----------------------------------------------------------------------------
REAL_ESTATE_POI = [
    "real_estate_agency",
    "realtor",
    "real_estate_office",
    "property_management",
    "apartment_complex",
    "condo_building",
    "townhouse",
    "single_family_home",
    "mobile_home_park",
    "retirement_community",
    "senior_living",
    "student_housing",
    "affordable_housing",
    "public_housing",
    "coworking_space",
    "office_building",
    "commercial_property",
    "industrial_property",
    "warehouse",
    "self_storage",
]

# -----------------------------------------------------------------------------
# 18. FOOD_SPECIALTY (30 types)
# -----------------------------------------------------------------------------
FOOD_SPECIALTY = [
    "sushi",
    "ramen",
    "pho",
    "dim_sum",
    "hot_pot",
    "korean_bbq",
    "japanese_bbq",
    "hibachi",
    "teppanyaki",
    "omakase",
    "izakaya",
    "yakitori",
    "tempura",
    "udon",
    "soba",
    "curry",
    "tandoori",
    "biryani",
    "dosa",
    "poke",
    "acai",
    "salad",
    "soup",
    "sandwich",
    "sub_shop",
    "deli",
    "bagel",
    "croissant",
    "crepe",
    "waffle",
    "pancake",
    "brunch",
    "buffet",
    "all_you_can_eat",
    "food_truck",
    "food_court",
    "food_hall",
    "ghost_kitchen",
    "catering",
    "meal_prep",
    "juice_bar",
    "smoothie",
    "protein_shake",
    "health_food",
    "vegan",
    "vegetarian",
    "gluten_free",
    "organic",
    "farm_to_table",
    "sustainable",
    "local",
]

# =============================================================================
# COMBINE ALL POI CATEGORIES (Level-3 Granularity)
# =============================================================================

# Every category becomes its own key with itself as the only value
POI_CATEGORIES_L3: Dict[str, List[str]] = {}

# Add all category lists
ALL_POI_LISTS = [
    RESTAURANTS,
    BARS,
    CAFES,
    ACCOMMODATION,
    SPORTS_VENUES,
    ENTERTAINMENT,
    ATTRACTIONS,
    AUTOMOTIVE,
    BEAUTY_SPA,
    EDUCATION,
    FINANCIAL,
    HEALTH_MEDICAL,
    RETAIL_SHOPPING,
    PROFESSIONAL,
    HOME_SERVICE,
    PUBLIC_SERVICE,
    RELIGIOUS,
    TRAVEL_TRANSIT,
    REAL_ESTATE_POI,
    FOOD_SPECIALTY,
]

for poi_list in ALL_POI_LISTS:
    for poi in poi_list:
        # Each POI is its own category with itself as the match
        POI_CATEGORIES_L3[poi] = [poi]

# Total count
TOTAL_L3_POIS = len(POI_CATEGORIES_L3)

# =============================================================================
# BACKWARD COMPATIBILITY: POI_CATEGORIES alias
# =============================================================================

POI_CATEGORIES = POI_CATEGORIES_L3

# =============================================================================
# TOP-LEVEL CATEGORIES (for aggregate counts)
# =============================================================================

TOP_LEVEL_CATEGORIES = [
    "eat_and_drink",
    "accommodation", 
    "active_life",
    "arts_and_entertainment",
    "attractions_and_activities",
    "automotive",
    "beauty_and_spa",
    "business_to_business",
    "education",
    "financial_service",
    "health_and_medical",
    "home_service",
    "mass_media",
    "pets",
    "private_establishments_and_corporates",
    "professional_services",
    "public_service_and_government",
    "real_estate",
    "religious_organization",
    "retail",
    "structure_and_geography",
    "travel",
]

# =============================================================================
# LAND USE CLASSES (ALL)
# =============================================================================

LAND_USE_CLASSES = [
    "residential", "commercial", "industrial", "retail", "office",
    "park", "forest", "recreation_ground", "farmland", "vineyard",
    "orchard", "meadow", "grassland", "scrub", "heath",
    "quarry", "landfill", "construction", "brownfield",
    "cemetery", "allotments", "beach", "military",
    "education", "healthcare", "religious",
    # Nature reserves and protected areas
    "nature_reserve", "protected_area", "national_park",
]

# =============================================================================
# WATER TYPES (ALL)
# =============================================================================

WATER_TYPES = [
    "lake", "river", "sea", "ocean", "pond", "reservoir",
    "canal", "stream", "wetland", "bay", "lagoon", "estuary",
]

# =============================================================================
# INFRASTRUCTURE CLASSES (ALL)
# =============================================================================

INFRASTRUCTURE_CLASSES = [
    "power_line", "power_tower", "power_plant", "substation",
    "wind_turbine", "solar_farm", "dam", "water_tower",
    "telecommunications_tower", "cell_tower", "broadcast_tower",
    "pipeline", "pumping_station", "wastewater_plant", "water_treatment",
]

# =============================================================================
# ROAD CLASSES (ALL)
# =============================================================================

ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "service", "pedestrian", "cycleway", "footway",
    "track", "path", "motorway_link", "trunk_link", "primary_link",
]

# =============================================================================
# TRANSIT TYPES (ALL)
# =============================================================================

TRANSIT_TYPES = [
    "subway_station", "train_station", "bus_station", "tram_stop",
    "light_rail_station", "ferry_terminal", "airport",
]

# =============================================================================
# GREEN & BLUE PREMIUM (for size-tiered travel)
# =============================================================================

GREEN_FEATURES = {
    # Parks: 4 size tiers - small pocket parks to major urban parks
    "park": {"size_tiers": {"any": 0, "small": -20000, "20k": 20000, "2m": 2000000, "20m": 20000000}},
    # Forests: any size
    "forest": {"size_tiers": {"any": 0}},
    # Beaches: any size
    "beach": {"size_tiers": {"any": 0}},
    # Nature reserves: any size
    "nature_reserve": {"size_tiers": {"any": 0}},
}
# Note: "small" tier uses negative value to indicate ≤20k (upper bound instead of lower)

BLUE_FEATURES = {
    "lake": {"size_tiers": {"any": 0, "2m": 2000000}},
    "coastline": {"size_tiers": {"any": 0}},
    "river": {"size_tiers": {"any": 0}},
}

# =============================================================================
# TRAVEL SPEEDS
# =============================================================================

TRAVEL_SPEEDS = {
    "walk": 83,      # m/min (5 km/h)
    "cycle": 250,    # m/min (15 km/h)
    "drive": 833,    # m/min (50 km/h)
}

# =============================================================================
# H3 CONFIGURATION
# =============================================================================

H3_RESOLUTIONS = [5, 8, 10]  # res11 removed - too granular

H3_EDGE_LENGTHS = {
    5: 8544,   # meters
    8: 461,    # meters
    10: 66,    # meters
    11: 45,    # meters
    12: 17,    # meters (for base layer)
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_poi_sql_filter(category: str) -> str:
    """Generate SQL filter for a POI category."""
    if category in POI_CATEGORIES_L3:
        matches = POI_CATEGORIES_L3[category]
        quoted = [f"'{m}'" for m in matches]
        return f"categories.primary IN ({', '.join(quoted)})"
    raise ValueError(f"Unknown category: {category}")


def get_all_poi_filters() -> Dict[str, str]:
    """Get SQL filters for all POI categories."""
    result = {}
    for category, matches in POI_CATEGORIES_L3.items():
        quoted = [f"'{m}'" for m in matches]
        result[category] = f"categories.primary IN ({', '.join(quoted)})"
    return result


def get_column_count() -> Dict[str, int]:
    """Calculate total columns for the ULTRA-MAXED schema."""
    # Each L3 POI: count + walk + cycle + drive + score = 5 cols
    poi_cols = TOTAL_L3_POIS * 5
    
    # Top-level aggregates: just count
    toplevel_cols = len(TOP_LEVEL_CATEGORIES)
    
    # Land use: count + area_m2 + avg_area_m2 = 3 cols each
    landuse_cols = len(LAND_USE_CLASSES) * 3
    
    # Water: count + area_m2 + travel times = ~5 cols each
    water_cols = len(WATER_TYPES) * 5
    
    # Infrastructure: count + nearest_walk/cycle/drive = 4 cols each
    infra_cols = len(INFRASTRUCTURE_CLASSES) * 4
    
    # Roads: presence (4 types) + proximity (4 types)
    # pedestrian_in_hex, cycleway_in_hex, footway_in_hex, living_street_in_hex
    # motorway_road_walk_min, trunk_road_walk_min, primary_road_walk_min, secondary_road_walk_min
    road_cols = 4 + 4  # 8 columns
    
    # Transit: 7 types × 2 (walk_min + cycle_min)
    # subway, train, bus, tram, light_rail, ferry, airport
    transit_cols = 7 * 2  # 14 columns
    
    # Green/Blue: ~10 cols each with size tiers
    green_cols = sum(len(f["size_tiers"]) * 6 for f in GREEN_FEATURES.values())
    blue_cols = sum(len(f["size_tiers"]) * 6 for f in BLUE_FEATURES.values())
    
    # Buildings
    building_cols = 4
    
    return {
        "poi_l3": poi_cols,
        "poi_toplevel": toplevel_cols,
        "land_use": landuse_cols,
        "water": water_cols,
        "infrastructure": infra_cols,
        "roads": road_cols,
        "transit": transit_cols,
        "green_premium": green_cols,
        "blue_premium": blue_cols,
        "buildings": building_cols,
        "h3_index": 1,
        "total": 1 + poi_cols + toplevel_cols + landuse_cols + water_cols + 
                 infra_cols + road_cols + transit_cols + green_cols + blue_cols + building_cols,
    }


def get_decay_score(k: int) -> float:
    """Two-phase linear decay: k=0→10, k=7→1, k=10→0."""
    if k == 0:
        return 10.0
    elif k <= 7:
        return 10.0 - (9.0 * k / 7.0)
    elif k <= 10:
        return (10.0 - k) / 3.0
    else:
        return 0.0


# =============================================================================
# PRINT SUMMARY
# =============================================================================

if __name__ == "__main__":
    stats = get_column_count()
    
    print("=" * 70)
    print("EARTH MATRIX ULTRA-MAXED SCHEMA v4.0 (Level-3 Granularity)")
    print("=" * 70)
    print()
    print("POI Categories (Level-3):")
    print(f"  Restaurants:       {len(RESTAURANTS)}")
    print(f"  Bars:              {len(BARS)}")
    print(f"  Cafes:             {len(CAFES)}")
    print(f"  Accommodation:     {len(ACCOMMODATION)}")
    print(f"  Sports Venues:     {len(SPORTS_VENUES)}")
    print(f"  Entertainment:     {len(ENTERTAINMENT)}")
    print(f"  Attractions:       {len(ATTRACTIONS)}")
    print(f"  Automotive:        {len(AUTOMOTIVE)}")
    print(f"  Beauty/Spa:        {len(BEAUTY_SPA)}")
    print(f"  Education:         {len(EDUCATION)}")
    print(f"  Financial:         {len(FINANCIAL)}")
    print(f"  Health/Medical:    {len(HEALTH_MEDICAL)}")
    print(f"  Retail/Shopping:   {len(RETAIL_SHOPPING)}")
    print(f"  Professional:      {len(PROFESSIONAL)}")
    print(f"  Home Service:      {len(HOME_SERVICE)}")
    print(f"  Public Service:    {len(PUBLIC_SERVICE)}")
    print(f"  Religious:         {len(RELIGIOUS)}")
    print(f"  Travel/Transit:    {len(TRAVEL_TRANSIT)}")
    print(f"  Real Estate:       {len(REAL_ESTATE_POI)}")
    print(f"  Food Specialty:    {len(FOOD_SPECIALTY)}")
    print(f"  ─────────────────────────")
    print(f"  TOTAL L3 POIs:     {TOTAL_L3_POIS}")
    print()
    print("Other Features:")
    print(f"  Land Use:          {len(LAND_USE_CLASSES)}")
    print(f"  Water:             {len(WATER_TYPES)}")
    print(f"  Infrastructure:    {len(INFRASTRUCTURE_CLASSES)}")
    print(f"  Roads:             {len(ROAD_CLASSES)}")
    print(f"  Transit:           {len(TRANSIT_TYPES)}")
    print()
    print("Column Counts:")
    for section, count in stats.items():
        print(f"  {section:20s}: {count:,}")
    print()
    print(f"TOTAL COLUMNS: {stats['total']:,}")
    print()
    print("Estimated Costs:")
    print(f"  Compute (global, 4 res): ~$90 on-demand")
    print(f"  Storage (Hetzner 10TB):  €25/month")
    print(f"  Output size:             ~6 TB")
