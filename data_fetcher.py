"""
Data fetcher — loads all data sources (real + mock).

Each fetch function returns a dict with a "source_label" key identifying
the department, plus the relevant data. The assembler collects them into
a single dict keyed by source label for prompt injection.
"""

import json
import os
import requests
from config import Config

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PERSONAS_DIR = os.path.join(DATA_DIR, "personas")


# ---------------------------------------------------------------------------
# Static JSON loaders
# ---------------------------------------------------------------------------

def _load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def load_persona(persona_id):
    """Load a persona's full JSON profile."""
    path = os.path.join(PERSONAS_DIR, f"{persona_id}.json")
    with open(path, "r") as f:
        return json.load(f)


def load_stadium():
    return _load_json("stadium.json")


def load_schedule():
    return _load_json("schedule.json")


def load_players():
    return _load_json("players.json")


# ---------------------------------------------------------------------------
# Live data fetchers
# ---------------------------------------------------------------------------

def fetch_weather():
    """Fetch current weather for Seattle from OpenWeatherMap."""
    api_key = Config.OPENWEATHER_API_KEY
    if not api_key:
        return {
            "source_label": "Weather",
            "available": False,
            "fallback": "Weather data unavailable. Dress in layers — Seattle evenings can be cool."
        }

    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": "Seattle,WA,US",
            "appid": api_key,
            "units": "imperial"
        }
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        return {
            "source_label": "Weather",
            "available": True,
            "temperature_f": round(data["main"]["temp"]),
            "feels_like_f": round(data["main"]["feels_like"]),
            "description": data["weather"][0]["description"],
            "wind_mph": round(data["wind"]["speed"]),
            "humidity_pct": data["main"]["humidity"],
            "recommendation": _weather_recommendation(data)
        }
    except Exception:
        return {
            "source_label": "Weather",
            "available": False,
            "fallback": "Weather data unavailable. Dress in layers — Seattle evenings can be cool."
        }


def _weather_recommendation(data):
    temp = data["main"]["temp"]
    desc = data["weather"][0]["main"].lower()
    wind = data["wind"]["speed"]

    parts = []
    if temp < 50:
        parts.append("It'll be chilly — bring a warm jacket.")
    elif temp < 60:
        parts.append("Cool evening — a hoodie or light jacket is a good idea.")
    else:
        parts.append("Comfortable temps tonight.")

    if "rain" in desc or "drizzle" in desc:
        parts.append("Rain is likely — bring a rain jacket (umbrellas block views).")
    elif "cloud" in desc:
        parts.append("Overcast but dry.")

    if wind > 15:
        parts.append(f"Windy ({round(wind)} mph) — layers help.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Source assembly — collects data by department for prompt injection
# ---------------------------------------------------------------------------

# Maps source labels to the persona JSON keys that belong to them
PERSONA_SOURCE_KEYS = {
    "Ticketing": "ticketing",
    "CRM": "crm",
    "Marketing": "marketing",
    "Finance": "finance",
    "Event Ops": "event_ops",
}

# Non-persona sources that come from static files or live APIs
STATIC_SOURCES = {
    "Schedule": load_schedule,
    "Player Performance": load_players,
    "Event Ops Stadium": load_stadium,
    "Weather": fetch_weather,
}


def assemble_sources(persona_data, active_sources):
    """
    Assemble all data sources into a dict keyed by department label.

    Only includes sources listed in active_sources. If active_sources
    contains "all", every source is included.

    Returns:
        dict: {source_label: source_data_dict}
    """
    include_all = "all" in active_sources
    assembled = {}

    # Persona-specific sources (from the persona JSON)
    for label, key in PERSONA_SOURCE_KEYS.items():
        if include_all or label in active_sources:
            if key in persona_data:
                assembled[label] = persona_data[key]

    # Schedule
    if include_all or "Schedule" in active_sources:
        assembled["Schedule"] = load_schedule()

    # Player Performance
    if include_all or "Player Performance" in active_sources:
        assembled["Player Performance"] = load_players()

    # Stadium data merged into Event Ops if Event Ops is active
    if include_all or "Event Ops" in active_sources:
        stadium = load_stadium()
        if "Event Ops" in assembled:
            assembled["Event Ops"]["stadium"] = stadium
        else:
            assembled["Event Ops"] = {"stadium": stadium}

    # Weather (live)
    if include_all or "Weather" in active_sources:
        assembled["Weather"] = fetch_weather()

    return assembled


def get_all_source_labels():
    """Return the full list of toggleable source labels (shown in sidebar)."""
    return [
        "Ticketing",
        "CRM",
        "Marketing",
        "Player Performance",
        "Finance",
    ]


def get_always_on_sources():
    """Sources always included but not shown as toggles."""
    return ["Schedule", "Event Ops", "Weather"]
