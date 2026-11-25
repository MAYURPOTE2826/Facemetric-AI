"""City + season context for India.

Maps a city to a broad climate zone, works out the current season from the month, and
returns the routine changes that season needs (lighter or richer moisturiser, matte or
hydrating sunscreen, pollution care) plus a heads-up for the next season. Recomputed on
every read, so a saved report keeps up with the weather.
"""
from __future__ import annotations

from datetime import date

ZONES = {
    "humid_coast": "Hot & humid coast",
    "north_plains": "North Indian plains",
    "arid": "Hot & dry",
    "deccan": "Mild Deccan plateau",
    "hills": "Hills & mountains",
    "northeast": "Humid north-east",
}

# city -> (zone, high-pollution winter)
CITIES: dict[str, tuple[str, bool]] = {
    "Mumbai": ("humid_coast", False), "Chennai": ("humid_coast", False), "Kolkata": ("humid_coast", True),
    "Kochi": ("humid_coast", False), "Thiruvananthapuram": ("humid_coast", False), "Goa": ("humid_coast", False),
    "Visakhapatnam": ("humid_coast", False), "Mangaluru": ("humid_coast", False), "Bhubaneswar": ("humid_coast", False),
    "Surat": ("humid_coast", False),
    "Delhi NCR": ("north_plains", True), "Lucknow": ("north_plains", True), "Kanpur": ("north_plains", True),
    "Patna": ("north_plains", True), "Chandigarh": ("north_plains", False), "Ludhiana": ("north_plains", True),
    "Amritsar": ("north_plains", True), "Varanasi": ("north_plains", True), "Agra": ("north_plains", True),
    "Indore": ("north_plains", False), "Bhopal": ("north_plains", False), "Raipur": ("north_plains", False),
    "Ranchi": ("north_plains", False), "Nagpur": ("north_plains", False),
    "Jaipur": ("arid", True), "Jodhpur": ("arid", False), "Ahmedabad": ("arid", True), "Rajkot": ("arid", False),
    "Bengaluru": ("deccan", False), "Pune": ("deccan", False), "Hyderabad": ("deccan", False),
    "Mysuru": ("deccan", False), "Coimbatore": ("deccan", False), "Nashik": ("deccan", False),
    "Shimla": ("hills", False), "Dehradun": ("hills", False), "Srinagar": ("hills", False),
    "Darjeeling": ("hills", False), "Manali": ("hills", False), "Ooty": ("hills", False),
    "Guwahati": ("northeast", False), "Shillong": ("northeast", False), "Imphal": ("northeast", False),
}

SEASON_LABELS = {"summer": "Summer", "monsoon": "Monsoon", "post_monsoon": "Post-monsoon", "winter": "Winter"}


def _season(zone: str, month: int, city: str) -> str:
    if city == "Chennai" and month in (10, 11, 12):
        return "monsoon"  # north-east monsoon
    if zone in ("humid_coast", "northeast", "deccan"):
        return {3: "summer", 4: "summer", 5: "summer", 6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon",
                10: "post_monsoon", 11: "post_monsoon"}.get(month, "winter")
    if zone == "hills":
        return {4: "summer", 5: "summer", 6: "summer", 7: "monsoon", 8: "monsoon", 9: "monsoon",
                10: "post_monsoon"}.get(month, "winter")
    # north plains + arid
    return {3: "summer", 4: "summer", 5: "summer", 6: "summer", 7: "monsoon", 8: "monsoon", 9: "monsoon",
            10: "post_monsoon", 11: "winter"}.get(month, "winter")


# (zone, season) -> moisturiser / sunscreen override and tips. Zone "*" applies to every zone.
ADVICE: dict[tuple[str, str], dict] = {
    ("*", "summer"): {"sunscreen": "matte", "moisturiser": "gel", "tips": [
        "Peak UV: SPF 50 PA++++ every morning, reapply every 2-3 hours outdoors - tan builds fastest now.",
        "Carry a cap or umbrella between 11am and 3pm; sunscreen alone isn't enough.",
        "Wash your face after sweaty commutes, but no more than 2-3 times a day."]},
    ("arid", "summer"): {"sunscreen": "hydrating", "moisturiser": "gel", "tips": [
        "Dry heat dehydrates skin even if it looks oily - layer a hyaluronic serum under a light moisturiser.",
        "Loo winds and dust: cleanse well at night and keep a lip balm with SPF."]},
    ("*", "monsoon"): {"sunscreen": "matte", "moisturiser": "gel", "tips": [
        "Humidity means more oil and clogged pores - switch to gel textures and skip heavy oils on the face.",
        "Clouds don't block UV - keep the sunscreen on.",
        "Dry your skin and hair fully after getting caught in the rain; damp folds breed fungal infections.",
        "Dandruff and scalp itch spike now - wash hair after rain and use an anti-dandruff shampoo if needed."]},
    ("*", "post_monsoon"): {"sunscreen": None, "moisturiser": None, "tips": [
        "Humidity is dropping - if skin starts feeling tight, move to a slightly richer moisturiser at night.",
        "A good time to start a new active (e.g. a night serum) before winter dryness or wedding season."]},
    ("north_plains", "winter"): {"sunscreen": "hydrating", "moisturiser": "cream", "tips": [
        "Cold, dry air: use a cream moisturiser even if your skin is oily (a gel-cream if you break out).",
        "Lukewarm water only - hot showers and geysers strip your skin barrier.",
        "Winter sun still tans: keep SPF on, especially on terraces and road trips."]},
    ("arid", "winter"): {"sunscreen": "hydrating", "moisturiser": "cream", "tips": [
        "Very dry air: cream moisturiser morning and night, and a thick balm on lips and heels."]},
    ("hills", "winter"): {"sunscreen": "hydrating", "moisturiser": "cream", "tips": [
        "Cold + altitude: UV is stronger in the hills and snow reflects it - SPF 50 even on cloudy days.",
        "Use a rich cream and a barrier balm on cheeks and lips against wind burn."]},
    ("hills", "summer"): {"sunscreen": "hydrating", "moisturiser": None, "tips": [
        "Altitude raises UV - reapply sunscreen when you're out walking."]},
    ("*", "winter"): {"sunscreen": None, "moisturiser": None, "tips": [
        "Mild winter: if your skin feels tight, add a slightly richer moisturiser at night."]},
}

POLLUTION_TIPS = [
    "Air quality is poor this time of year: double-cleanse at night (micellar water or cleansing oil, then face wash).",
    "An antioxidant serum (vitamin C or niacinamide) in the morning helps defend against pollution.",
]


def _advice(zone: str, season: str) -> dict:
    return ADVICE.get((zone, season)) or ADVICE.get(("*", season)) or {"sunscreen": None, "moisturiser": None, "tips": []}


def context(city: str | None, today: date | None = None) -> dict | None:
    if not city or city not in CITIES:
        return None
    today = today or date.today()
    zone, smoggy = CITIES[city]
    season = _season(zone, today.month, city)
    adv = _advice(zone, season)
    tips = list(adv["tips"])
    pollution = smoggy and today.month in (10, 11, 12, 1)
    if pollution:
        tips += POLLUTION_TIPS

    # Heads-up for the next season (look ~6 weeks ahead).
    ahead = date.fromordinal(today.toordinal() + 42)
    next_season = _season(zone, ahead.month, city)
    upcoming = None
    if next_season != season:
        nxt = _advice(zone, next_season)
        upcoming = {"season": next_season, "label": SEASON_LABELS[next_season],
                    "tip": nxt["tips"][0] if nxt["tips"] else ""}
    return {
        "city": city,
        "zone": zone,
        "zone_label": ZONES[zone],
        "season": season,
        "season_label": SEASON_LABELS[season],
        "pollution": pollution,
        "moisturiser": adv["moisturiser"],  # "gel" | "cream" | None (keep skin-type default)
        "sunscreen": adv["sunscreen"],  # "matte" | "hydrating" | None
        "tips": tips,
        "upcoming": upcoming,
    }
