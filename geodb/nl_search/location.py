"""
Resolve place names, highways, rivers, and coordinates from a query string.
Focused on Punjab / North India since that is where the data lives.
"""
import math
import re


# ── Places (lon, lat) ────────────────────────────────────────────────────────
# Keys MUST be lowercase.  Sorted longest-first at lookup time.

PLACES = {
    # Places appearing in the actual DB filenames
    "kharkhra":         (76.5200, 31.0600),
    "sukhera bodla":    (74.1650, 30.5860),
    "nanagal kalmot":   (76.3200, 31.2750),
    "nangra kamlot":    (76.3100, 31.2800),
    "moga":             (75.1741, 30.8162),
    "burj":             (76.4200, 31.0500),
    "shahpur":          (76.4100, 30.7400),
    "chandpur":         (76.3600, 31.2700),
    "akkuwal":          (76.4900, 31.0700),
    "dhagra":           (76.4500, 31.0300),
    "jamaalpur":        (74.2400, 31.2700),
    "adarman":          (76.5000, 31.0400),
    "merra kalan":      (76.4800, 31.0500),
    "sbs nagar":        (76.1154, 31.1246),
    "burj tehal dass":  (76.4100, 31.0600),

    # Punjab cities & towns
    "ropar":            (76.5330, 31.0442),
    "rupnagar":         (76.5330, 31.0442),
    "chandigarh":       (76.7794, 30.7333),
    "mohali":           (76.7179, 30.7046),
    "sas nagar":        (76.7179, 30.7046),
    "panchkula":        (76.8606, 30.6942),
    "ludhiana":         (75.8573, 30.9010),
    "amritsar":         (74.8723, 31.6340),
    "jalandhar":        (75.5762, 31.3260),
    "patiala":          (76.3869, 30.3398),
    "bathinda":         (74.9455, 30.2110),
    "pathankot":        (75.6421, 32.2747),
    "hoshiarpur":       (75.9115, 31.5143),
    "firozpur":         (74.6225, 30.9331),
    "sangrur":          (75.8410, 30.2330),
    "barnala":          (75.5488, 30.3764),
    "kapurthala":       (75.3809, 31.3808),
    "gurdaspur":        (75.4069, 32.0414),
    "fatehgarh sahib":  (76.3962, 30.6416),
    "nawanshahr":       (76.1154, 31.1246),
    "mansa":            (75.3970, 29.9889),
    "faridkot":         (74.7579, 30.6769),
    "muktsar":          (74.5163, 30.4762),
    "tarn taran":       (74.9279, 31.4518),
    "anandpur sahib":   (76.5032, 31.2393),
    "nangal":           (76.3750, 31.3868),
    "kiratpur sahib":   (76.5870, 31.1800),

    # Haryana
    "ambala":           (76.7767, 30.3782),
    "karnal":           (76.9905, 29.6857),
    "kurukshetra":      (76.8606, 29.9695),
    "panipat":          (76.9635, 29.3909),
    "gurugram":         (77.0266, 28.4595),

    # Himachal
    "shimla":           (77.1734, 31.1048),
    "manali":           (77.1887, 32.2396),

    # Metros
    "delhi":            (77.2090, 28.6139),
    "new delhi":        (77.2090, 28.6139),
    "jaipur":           (75.7873, 26.9124),
    "dehradun":         (78.0322, 30.3165),
}

# ── Highways ──────────────────────────────────────────────────────────────────

HIGHWAYS = {
    "nh44":  (76.78, 30.73),   # Delhi–Chandigarh–Jalandhar
    "nh5":   (77.17, 31.10),   # Shimla highway
    "nh21":  (76.78, 31.50),   # Chandigarh–Manali
    "nh22":  (77.00, 31.00),   # Ambala–Shimla
    "nh1":   (75.50, 31.00),   # Delhi–Amritsar (old)
    "nh64":  (76.20, 30.80),   # Chandigarh–Ludhiana
    "nh105": (76.50, 31.20),   # Ropar–Nangal
    "nh205": (76.43, 30.89),   # Ropar–Chamkaur Sahib
}

# ── Rivers ────────────────────────────────────────────────────────────────────

RIVERS = {
    "sutlej":  (76.50, 31.10),
    "satluj":  (76.50, 31.10),
    "beas":    (75.90, 31.80),
    "ravi":    (75.20, 32.30),
    "ghaggar": (76.60, 30.40),
    "yamuna":  (77.25, 28.60),
    "chenab":  (75.10, 33.00),
}


# ── Public API ────────────────────────────────────────────────────────────────

def resolve(query: str) -> dict:
    """
    Extract spatial context from a natural-language query.

    Returns dict with any of:
        lon, lat, place, radius_km, delta_lon, delta_lat
    """
    ql = query.lower()
    result = {}

    # 1. Places — longest match first
    for place in sorted(PLACES, key=len, reverse=True):
        if place in ql:
            lon, lat = PLACES[place]
            result.update(lon=lon, lat=lat, place=place)
            break

    # 2. Highways — longest match first to avoid NH1 matching before NH105
    if "lon" not in result:
        ql_compact = ql.replace("-", "").replace(" ", "")
        for hw in sorted(HIGHWAYS, key=len, reverse=True):
            if hw in ql_compact:
                lon, lat = HIGHWAYS[hw]
                result.update(lon=lon, lat=lat, place=f"highway {hw.upper()}")
                break

    # 3. Rivers
    if "lon" not in result:
        for river, (lon, lat) in RIVERS.items():
            if river in ql:
                result.update(lon=lon, lat=lat, place=f"river {river.title()}")
                break

    # 4. Explicit coords  (76.5, 31.0)
    if "lon" not in result:
        m = re.search(r'(\d{1,3}\.\d+)\s*[,/]\s*(\d{1,3}\.\d+)', query)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a < 40:          # likely lat
                result.update(lat=a, lon=b)
            else:
                result.update(lon=a, lat=b)

    # 5. Radius
    rm = re.search(r'(\d+(?:\.\d+)?)\s*(?:km|kilometer|kilometres|kms)', ql)
    if rm:
        result["radius_km"] = float(rm.group(1))
    elif any(w in ql for w in ("near", "around", "within", "nearby",
                                "close to", "vicinity", "surrounding")):
        result["radius_km"] = 5.0

    # 6. Bbox deltas
    if "lon" in result:
        r_km = result.get("radius_km", 5.0)
        lat = result["lat"]
        result["delta_lat"] = r_km * 0.009
        result["delta_lon"] = r_km * 0.009 / max(math.cos(math.radians(lat)), 0.01)

    return result


# ── Reverse lookup ────────────────────────────────────────────────────────────

# Approx district centroids in Punjab + neighbours.  Used to label a bbox
# with "covers <district>" — coarse, name-only, no shapefiles.
DISTRICTS = {
    # Punjab
    "Amritsar":        (74.8723, 31.6340),
    "Tarn Taran":      (74.9279, 31.4518),
    "Gurdaspur":       (75.4069, 32.0414),
    "Pathankot":       (75.6421, 32.2747),
    "Hoshiarpur":      (75.9115, 31.5143),
    "Kapurthala":      (75.3809, 31.3808),
    "Jalandhar":       (75.5762, 31.3260),
    "SBS Nagar":       (76.1154, 31.1246),
    "Rupnagar":        (76.5330, 31.0442),
    "SAS Nagar":       (76.7179, 30.7046),
    "Fatehgarh Sahib": (76.3962, 30.6416),
    "Ludhiana":        (75.8573, 30.9010),
    "Moga":            (75.1741, 30.8162),
    "Firozpur":        (74.6225, 30.9331),
    "Faridkot":        (74.7579, 30.6769),
    "Muktsar":         (74.5163, 30.4762),
    "Bathinda":        (74.9455, 30.2110),
    "Mansa":           (75.3970, 29.9889),
    "Sangrur":         (75.8410, 30.2330),
    "Barnala":         (75.5488, 30.3764),
    "Patiala":         (76.3869, 30.3398),
    # Neighbours
    "Chandigarh":      (76.7794, 30.7333),
    "Panchkula":       (76.8606, 30.6942),
    "Ambala":          (76.7767, 30.3782),
    "Shimla":          (77.1734, 31.1048),
}


def _haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def reverse_lookup(bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                    max_districts: int = 5) -> dict:
    """
    Given a bbox, return coarse coverage info: nearest district to centre
    plus all districts whose centroid falls inside the bbox.
    """
    if None in (bbox_minx, bbox_miny, bbox_maxx, bbox_maxy):
        return {}

    cx = (bbox_minx + bbox_maxx) / 2
    cy = (bbox_miny + bbox_maxy) / 2

    # Districts whose centroid is inside the bbox
    inside = [
        name for name, (lon, lat) in DISTRICTS.items()
        if bbox_minx <= lon <= bbox_maxx and bbox_miny <= lat <= bbox_maxy
    ]

    # Distances from bbox centre, sorted
    dists = sorted(
        ((name, _haversine_km(cx, cy, lon, lat))
         for name, (lon, lat) in DISTRICTS.items()),
        key=lambda x: x[1],
    )
    nearest = dists[0]
    nearby = [(n, round(d, 1)) for n, d in dists[:max_districts]]

    # Approx area in km² (small-angle, fine for Punjab latitudes)
    width_km = (bbox_maxx - bbox_minx) * 0.0104 ** -1  # inverse of km->deg
    height_km = (bbox_maxy - bbox_miny) * 0.009 ** -1
    area_km2 = round(abs(width_km * height_km), 2)

    return {
        "centre": (round(cx, 5), round(cy, 5)),
        "approx_area_km2": area_km2,
        "districts_inside_bbox": inside,
        "nearest_district": {"name": nearest[0], "distance_km": round(nearest[1], 1)},
        "nearby_districts": nearby,
    }
