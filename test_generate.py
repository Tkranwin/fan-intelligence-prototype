#!/usr/bin/env python3
"""
Test script for briefing generation.

Usage:
    # Test all 4 combinations:
    python test_generate.py

    # Test a specific combo:
    python test_generate.py david between
    python test_generate.py david matchday
    python test_generate.py maria matchday
    python test_generate.py maria between

    # Test with degraded sources (CRM removed):
    python test_generate.py david between --without CRM

    # Test with multiple sources removed:
    python test_generate.py david between --without CRM Marketing
"""

import sys
import json
import requests

BASE_URL = "http://localhost:5001"

ALL_SOURCES = [
    "Ticketing", "CRM", "Marketing", "Player Performance",
    "Finance", "Schedule", "Event Ops", "Weather",
]

COMBOS = [
    ("david", "between"),
    ("david", "matchday"),
    ("maria", "matchday"),
    ("maria", "between"),
]


def generate(persona, mode, active_sources=None, skip_cache=True):
    if active_sources is None:
        active_sources = ["all"]

    payload = {
        "persona": persona,
        "mode": mode,
        "active_sources": active_sources,
        "skip_cache": skip_cache,
    }

    print(f"\n{'='*70}")
    print(f"  {persona.upper()} — {mode.upper()}")
    print(f"  Sources: {', '.join(active_sources)}")
    print(f"{'='*70}\n")

    try:
        resp = requests.post(f"{BASE_URL}/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            print(f"  ERROR: {data['error']}")
            return

        briefing = data["briefing"]
        cached = data.get("cached", False)

        if cached:
            print("  [CACHED RESULT]\n")

        for section in briefing:
            title = section.get("title", "Untitled")
            content = section.get("content", "")
            sources = section.get("sources", [])

            print(f"  ## {title}")
            print(f"  Sources: {', '.join(sources)}")
            print(f"  {'-'*50}")
            # Indent content lines
            for line in content.split("\n"):
                print(f"  {line}")
            print()

    except requests.ConnectionError:
        print("  ERROR: Can't connect to Flask server. Run: python app.py")
    except requests.Timeout:
        print("  ERROR: Request timed out (60s). Claude may be slow.")
    except Exception as e:
        print(f"  ERROR: {e}")


def main():
    args = sys.argv[1:]

    # Parse --without flag
    without = []
    if "--without" in args:
        idx = args.index("--without")
        without = args[idx + 1:]
        args = args[:idx]

    if without:
        active = [s for s in ALL_SOURCES if s not in without]
    else:
        active = None  # defaults to ["all"]

    if len(args) >= 2:
        # Specific combo
        persona, mode = args[0], args[1]
        generate(persona, mode, active)
    elif len(args) == 1:
        # All modes for one persona
        persona = args[0]
        for p, m in COMBOS:
            if p == persona:
                generate(p, m, active)
    else:
        # All combos
        for persona, mode in COMBOS:
            generate(persona, mode, active)


if __name__ == "__main__":
    main()
