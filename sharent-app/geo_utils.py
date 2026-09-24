import math
import re
from typing import Tuple, Optional

# Pre-indexed reference coordinates for cities and regions
KNOWN_COORDINATES = {
    # San Francisco Bay Area / Tri-Valley Hubs
    "san ramon": (37.7799, -121.9780),
    "dublin": (37.7022, -121.9358),
    "pleasanton": (37.6624, -121.8747),
    "danville": (37.8216, -122.0000),
    "livermore": (37.6819, -121.7680),
    "walnut creek": (37.9101, -122.0652),
    "concord": (37.9780, -122.0311),
    "fremont": (37.5485, -121.9886),
    "hayward": (37.6688, -122.0808),
    "oakland": (37.8044, -122.2712),
    "berkeley": (37.8715, -122.2730),
    "san francisco": (37.7749, -122.4194),
    "san jose": (37.3382, -121.8863),
    "santa clara": (37.3541, -121.9552),
    "sunnyvale": (37.3688, -122.0363),
    "palo alto": (37.4419, -122.1430),
    "mountain view": (37.3861, -122.0839),
    "san mateo": (37.5630, -122.3255),
    "redwood city": (37.4852, -122.2364),
    # Common zip codes
    "94583": (37.7799, -121.9780),  # San Ramon
    "94582": (37.7600, -121.9200),  # San Ramon Gale Ranch
    "94568": (37.7022, -121.9358),  # Dublin
    "94566": (37.6624, -121.8747),  # Pleasanton
    "94588": (37.6980, -121.8900),  # Pleasanton West
    "94526": (37.8216, -122.0000),  # Danville
    "94550": (37.6819, -121.7680),  # Livermore
    "94596": (37.9101, -122.0652),  # Walnut Creek
    "94102": (37.7749, -122.4194),  # San Francisco
    "95113": (37.3382, -121.8863),  # San Jose
    # Major US metro hubs for broad testing
    "los angeles": (34.0522, -118.2437),
    "san diego": (32.7157, -117.1611),
    "seattle": (47.6062, -122.3321),
    "new york": (40.7128, -74.0060),
    "austin": (30.2672, -97.7431),
    "chicago": (41.8781, -87.6298),
}

DEFAULT_COORDINATES = (37.7799, -121.9780)  # San Ramon, CA default

def resolve_coordinates(address: Optional[str]) -> Tuple[float, float]:
    """
    Resolve latitude and longitude coordinates from an address string,
    city name, or zip code using intelligent substring and regex matching.
    """
    if not address or not address.strip():
        return DEFAULT_COORDINATES

    clean_addr = address.lower().strip()

    # 1. Check for 5-digit zip code match
    zip_match = re.search(r'\b(9\d{4})\b', clean_addr)
    if zip_match:
        zip_code = zip_match.group(1)
        if zip_code in KNOWN_COORDINATES:
            return KNOWN_COORDINATES[zip_code]

    # 2. Check for city matches
    for city, coords in KNOWN_COORDINATES.items():
        if city in clean_addr:
            return coords

    # 3. Deterministic hash offset based on address text if unknown
    hash_val = sum(ord(c) for c in clean_addr)
    lat_offset = ((hash_val % 100) - 50) * 0.002
    lon_offset = (((hash_val // 10) % 100) - 50) * 0.002
    return (round(DEFAULT_COORDINATES[0] + lat_offset, 4), round(DEFAULT_COORDINATES[1] + lon_offset, 4))


def haversine_distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the great-circle distance between two points on the Earth
    specified in decimal degrees using the Haversine formula.
    Returns distance in miles rounded to 1 decimal place.
    """
    R = 3958.8  # Earth radius in miles

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    distance = R * c
    return round(distance, 1)
