import json
import hashlib
import time

from flask import Flask, render_template, jsonify, request
from config import Config
from data_fetcher import load_persona, assemble_sources, get_all_source_labels, get_always_on_sources
from prompt_builder import build_prompt

import anthropic

app = Flask(__name__)
app.config.from_object(Config)

# Simple in-memory cache: {cache_key: {"briefing": ..., "timestamp": ...}}
_cache = {}


def _cache_key(persona_id, mode, active_sources):
    """Deterministic cache key from request params."""
    raw = f"{persona_id}:{mode}:{sorted(active_sources)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry["timestamp"]) < Config.CACHE_TIMEOUT:
        return entry["briefing"]
    return None


def _set_cached(key, briefing):
    _cache[key] = {"briefing": briefing, "timestamp": time.time()}


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    Generate a briefing for a persona + mode.

    Request JSON:
        persona: "david" | "maria"
        mode: "matchday" | "between"
        active_sources: list of source labels, or ["all"]
        skip_cache: bool (optional, default false)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    persona_id = data.get("persona")
    mode = data.get("mode")
    active_sources_raw = data.get("active_sources", ["all"])
    # Always include non-toggleable sources alongside whatever the frontend sends
    if "all" in active_sources_raw:
        active_sources = ["all"]
    else:
        active_sources = list(set(active_sources_raw + get_always_on_sources()))
    skip_cache = data.get("skip_cache", False)

    if persona_id not in ("david", "maria"):
        return jsonify({"error": "persona must be 'david' or 'maria'"}), 400
    if mode not in ("matchday", "between"):
        return jsonify({"error": "mode must be 'matchday' or 'between'"}), 400

    # Check cache
    key = _cache_key(persona_id, mode, active_sources)
    if not skip_cache:
        cached = _get_cached(key)
        if cached:
            return jsonify({
                "persona": persona_id,
                "mode": mode,
                "active_sources": active_sources,
                "briefing": cached,
                "cached": True,
            })

    # 1. Load persona data
    try:
        persona_data = load_persona(persona_id)
    except FileNotFoundError:
        return jsonify({"error": f"Persona '{persona_id}' not found"}), 404

    # 2. Assemble data from active sources
    assembled = assemble_sources(persona_data, active_sources)

    # 3. Build the prompt
    try:
        system_prompt = build_prompt(
            persona_id, mode, persona_data, assembled, active_sources
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # 4. Call Claude
    api_key = Config.ANTHROPIC_API_KEY
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=Config.CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": "Generate the briefing now.",
                }
            ],
        )

        raw_text = message.content[0].text

        # Parse the JSON response from Claude
        # Strip markdown code fences if present
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        briefing = json.loads(cleaned)

    except json.JSONDecodeError:
        # If Claude returns non-JSON, wrap it as a single section
        briefing = [
            {
                "title": "Briefing",
                "content": raw_text,
                "sources": active_sources,
            }
        ]
    except anthropic.APIError as e:
        return jsonify({"error": f"Claude API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Generation failed: {str(e)}"}), 500

    # 5. Cache the result
    _set_cached(key, briefing)

    return jsonify({
        "persona": persona_id,
        "mode": mode,
        "active_sources": active_sources,
        "briefing": briefing,
        "cached": False,
    })


@app.route("/api/sources", methods=["GET"])
def api_sources():
    """Return the list of all toggleable data source labels."""
    return jsonify({"sources": get_all_source_labels()})


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

PERSONA_DEFAULTS = {
    "david": "between",
    "maria": "matchday",
}

@app.route("/")
def index():
    personas = {}
    for pid in ("david", "maria"):
        p = load_persona(pid)
        personas[pid] = {
            "id": pid,
            "display_name": p["display_name"],
            "tagline": p["tagline"],
            "description": p["description"],
            "attribute_tags": p["attribute_tags"],
        }
    return render_template("index.html", personas=personas)


@app.route("/briefing/<persona>")
def briefing(persona):
    if persona not in ("david", "maria"):
        return "Persona not found", 404
    p = load_persona(persona)
    persona_meta = {
        "id": persona,
        "display_name": p["display_name"],
        "tagline": p["tagline"],
    }
    default_mode = PERSONA_DEFAULTS.get(persona, "between")
    other_persona = "maria" if persona == "david" else "david"
    other_p = load_persona(other_persona)
    other_meta = {
        "id": other_persona,
        "display_name": other_p["display_name"],
        "tagline": other_p["tagline"],
    }
    return render_template(
        "briefing.html",
        persona=persona_meta,
        other_persona=other_meta,
        default_mode=default_mode,
        sentences=json.dumps(BRIEFING_SENTENCES[persona]),
    )


# ---------------------------------------------------------------------------
# Hardcoded briefing sentences: 5 per persona/mode, each with one source
# ---------------------------------------------------------------------------
BRIEFING_SENTENCES = {
    "david": {
        "between": {
            "subject": "Portland is coming, David",
            "greeting": "Hey David,\n\nHope you\u2019ve been well.",
            "closing": "We\u2019d love to see you back in Section 122.\n\nSeattle Sounders FC",
            "segments": [
                {
                    "bridge": "We wanted to reach out because ",
                    "source": "Ticketing",
                    "color": "#3b82f6",
                    "personalized": "Portland is coming April 12 \u2014 you attended every Portland home match during your 3-year season ticket run, and Section 122 Row F has two seats available.",
                    "generic": "the next home match is April 12 vs Portland Timbers and tickets are available.",
                },
                {
                    "bridge": "We know you\u2019ve been away for a while, but ",
                    "source": "CRM",
                    "color": "#8b5cf6",
                    "personalized": "you\u2019re still following the team on Instagram, and you opened the Frei farewell email in January \u2014 the connection is still there.",
                    "generic": "we hope you\u2019re still keeping up with the team.",
                },
                {
                    "bridge": "There\u2019s a lot to be excited about this season. ",
                    "source": "Marketing",
                    "color": "#f97316",
                    "personalized": "Your Jordan Morris #13 jersey was a good call \u2014 he just hit 100 career goals and is having his best season in years.",
                    "generic": "The Sounders are off to a strong start.",
                },
                {
                    "bridge": "And we want to make it easy to come back. ",
                    "source": "Finance",
                    "color": "#22c55e",
                    "personalized": "Your Gold loyalty pricing: $45 per seat instead of $72. That\u2019s $54 saved on two tickets. Expires Thursday.",
                    "generic": "Tickets start at $72 at soundersfc.com.",
                },
                {
                    "bridge": "The matchday experience has gotten better too \u2014 ",
                    "source": "Event Ops",
                    "color": "#14b8a6",
                    "personalized": "the west concourse near your old section got a full renovation. Ramen Rendezvous and Cloud City Coffee are already fan favorites.",
                    "generic": "the stadium has been updated for the 2026 season.",
                },
            ],
            "cta": {
                "personalized": "Claim My Seats \u2014 $45/seat, Gold Pricing",
                "generic_finance_off": "View Available Tickets",
                "generic_ticketing_off": "Browse Upcoming Matches",
                "generic_multiple_off": "Visit soundersfc.com",
            },
        },
        "matchday": {
            "subject": "Seattle vs Real Salt Lake \u2014 tonight at 7:30",
            "greeting": "Hey David,\n\nBig night at Lumen Field.",
            "closing": "Enjoy the match tonight.\n\nSeattle Sounders FC",
            "segments": [
                {
                    "bridge": "",
                    "source": "Ticketing",
                    "color": "#3b82f6",
                    "personalized": "Real Salt Lake visits tonight \u2014 you saw this matchup twice during your season ticket years, splitting 1-1 with a tough loss in 2022 and a dominant win in 2023.",
                    "generic": "The Sounders host Real Salt Lake tonight at 7:30 PM.",
                },
                {
                    "bridge": "We figured you\u2019d want to know \u2014 ",
                    "source": "CRM",
                    "color": "#8b5cf6",
                    "personalized": "you\u2019re watching from home tonight, but we wanted to make sure you still feel connected to this team. Your three years in Row G earned that.",
                    "generic": "follow along with tonight\u2019s match on our social channels.",
                },
                {
                    "bridge": "Here\u2019s one to keep an eye on: ",
                    "source": "Marketing",
                    "color": "#f97316",
                    "personalized": "Jordan Morris \u2014 the guy on your #13 jersey \u2014 has 4 goals in 6 matches this season and looks the sharpest he has in years.",
                    "generic": "the Sounders are in strong form heading into tonight.",
                },
                {
                    "bridge": "Looking ahead, ",
                    "source": "Finance",
                    "color": "#22c55e",
                    "personalized": "Portland comes to Lumen Field April 12 \u2014 Gold members get early access at $45/seat instead of $72. Your status is still active.",
                    "generic": "Portland visits April 12. Tickets available at soundersfc.com.",
                },
                {
                    "bridge": "And when you do make it back, ",
                    "source": "Event Ops",
                    "color": "#14b8a6",
                    "personalized": "Section 122\u2019s concourse has been completely renovated \u2014 wider walkways, Ramen Rendezvous, Cloud City Coffee.",
                    "generic": "Lumen Field has new upgrades for the 2026 season.",
                },
            ],
            "cta": {
                "personalized": "Get Early Access to Portland Tickets \u2014 April 12",
                "generic_finance_off": "View Upcoming Matches",
                "generic_ticketing_off": "Browse Upcoming Matches",
                "generic_multiple_off": "Visit soundersfc.com",
            },
        },
    },
    "maria": {
        "matchday": {
            "subject": "Your matchday guide",
            "greeting": "Hey Maria!",
            "closing": "Have an amazing time tonight!",
            "segments": [
                {
                    "bridge": "We\u2019re so excited for you \u2014 ",
                    "source": "Ticketing",
                    "color": "#3b82f6",
                    "personalized": "welcome to your first Sounders match! You\u2019re in Section 305 \u2014 great sightlines from the upper bowl and a friendly, relaxed atmosphere.",
                    "generic": "welcome to Lumen Field for tonight\u2019s Sounders match.",
                },
                {
                    "bridge": "A few things to know: ",
                    "source": "CRM",
                    "color": "#8b5cf6",
                    "personalized": "since this is your first MLS match, here\u2019s the quick version \u2014 two 45-minute halves, no timeouts, and when the Sounders score, the whole stadium erupts.",
                    "generic": "enjoy tonight\u2019s match. Visit soundersfc.com for more info.",
                },
                {
                    "bridge": "Getting there is easy \u2014 ",
                    "source": "Event Ops",
                    "color": "#14b8a6",
                    "personalized": "from Fremont, take the E Line RapidRide to Downtown, transfer to the 1 Line southbound, and get off at Stadium Station. Head to the North Gate \u2014 about 35 minutes total.",
                    "generic": "Lumen Field is accessible by light rail at Stadium Station.",
                },
                {
                    "bridge": "Once you\u2019re settled in, here\u2019s who to watch: ",
                    "source": "Player Performance",
                    "color": "#f97316",
                    "personalized": "Jordan Morris (#13), the hometown hero from Mercer Island. Leo Chu (#7), the flashy Brazilian winger. Stefan Frei (#24), the legendary keeper in his final season.",
                    "generic": "check out tonight\u2019s starting lineup at soundersfc.com.",
                },
                {
                    "bridge": "And a little context on the game \u2014 ",
                    "source": "Schedule",
                    "color": "#22c55e",
                    "personalized": "tonight\u2019s opponent is Real Salt Lake, a scrappy team that always makes for a competitive match. Kickoff at 7:30 PM.",
                    "generic": "kickoff is at 7:30 PM.",
                },
            ],
            "cta": {
                "personalized": "Enjoy the Match \u2014 We\u2019ll Send You a Recap Tomorrow",
                "generic_finance_off": "Visit soundersfc.com for More",
                "generic_ticketing_off": "Visit soundersfc.com for More",
                "generic_multiple_off": "Visit soundersfc.com",
            },
        },
        "between": {
            "subject": "Your match recap",
            "greeting": "Hey Maria!",
            "closing": "We\u2019d love to see you there.",
            "segments": [
                {
                    "bridge": "What a first match \u2014 ",
                    "source": "Ticketing",
                    "color": "#3b82f6",
                    "personalized": "a 3-0 win! Not a bad way to start. You picked a great seat in Section 305 for seeing the full flow of the game.",
                    "generic": "thanks for attending a recent Sounders match.",
                },
                {
                    "bridge": "One moment worth knowing more about: ",
                    "source": "Player Performance",
                    "color": "#f97316",
                    "personalized": "that goal from Jordan Morris in the 23rd minute was his 103rd for the club \u2014 he grew up 15 minutes away in Mercer Island and chose to stay home instead of playing in Europe.",
                    "generic": "the Sounders have several exciting players to follow.",
                },
                {
                    "bridge": "Here\u2019s something fun to follow \u2014 ",
                    "source": "CRM",
                    "color": "#8b5cf6",
                    "personalized": "since you\u2019re new to Seattle, the Sounders are woven into the city. Leo Chu has been documenting his own Seattle exploration on social media \u2014 following along is a fun way to get to know both the team and your new home.",
                    "generic": "follow the Sounders on social media for updates.",
                },
                {
                    "bridge": "Ready for round two? ",
                    "source": "Schedule",
                    "color": "#22c55e",
                    "personalized": "The next home match is April 12 vs Portland Timbers \u2014 the biggest rivalry in MLS. Saturday night, 7 PM kickoff, and the atmosphere will be unlike anything you\u2019ve experienced.",
                    "generic": "Check soundersfc.com for the upcoming schedule.",
                },
                {
                    "bridge": "And the best part \u2014 ",
                    "source": "Finance",
                    "color": "#14b8a6",
                    "personalized": "tickets in Section 305, right where you sat, are available for $38. Only 3 seats left.",
                    "generic": "tickets available at soundersfc.com.",
                },
            ],
            "cta": {
                "personalized": "Reserve My Seats \u2014 Section 305, $38",
                "generic_finance_off": "Browse Upcoming Matches",
                "generic_ticketing_off": "Browse Upcoming Matches",
                "generic_multiple_off": "Visit soundersfc.com",
            },
        },
    },
}


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
