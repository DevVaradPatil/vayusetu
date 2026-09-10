"""
api/residents.py — The resident view's words, in the resident's language.

Two jobs:

1. Explain the episode in plain language, built deterministically from measured
   evidence. Nothing here is generated: "smoke from 35 fires is blowing in from the
   north-west" is a sentence template filled with numbers we observed. That keeps
   the simplest explanation on the page the one we can defend line by line.

2. Translate everything a resident reads, not only the advisory sentence, in one
   batched Cloud Translation request. A Hindi speaker should not have to read
   English headings to find the Hindi advice.

Health statements follow the CPCB National AQI health impacts for each band. Tips
match the English advisory templates in api/gemini/advisory.py, so the page and
the spoken advice say the same thing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vayusetu.api.residents")

BANDS = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]

HEALTH: Dict[str, str] = {
    "Good": "Minimal impact on health.",
    "Satisfactory": "May cause minor breathing discomfort for sensitive people.",
    "Moderate": "May cause breathing discomfort for people with asthma or lung disease, "
                "and discomfort for people with heart disease, children and older adults.",
    "Poor": "May cause breathing discomfort for most people after long exposure.",
    "Very Poor": "May cause breathing illness after long exposure.",
    "Severe": "Affects healthy people and seriously affects people who are already ill.",
}

TIPS: Dict[str, List[str]] = {
    "Good": ["Air is good. Enjoy being outdoors."],
    "Satisfactory": ["Air is fine for almost everyone.",
                     "Very sensitive people may notice minor discomfort."],
    "Moderate": ["Most people can carry on as normal.",
                 "People with asthma or heart disease should limit long outdoor exertion."],
    "Poor": ["Cut down on long or heavy outdoor activity.",
             "Children, older adults and people with asthma should spend less time outside.",
             "Wear a mask if you go outside."],
    "Very Poor": ["Avoid long outdoor exercise.",
                  "Children, older adults and people with breathing problems should stay indoors.",
                  "Keep windows closed and use an air purifier if you have one."],
    "Severe": ["Stay indoors and keep windows closed.",
               "Avoid all outdoor exercise.",
               "Wear a well-fitting N95 mask if you must go out.",
               "People with heart or lung conditions should get medical help if symptoms get worse."],
}

# Every fixed label on the resident page. Placeholder-free on purpose: numbers and
# names are placed next to these by the page, because machine translation mangles
# template slots.
UI: Dict[str, str] = {
    "air_now": "Air quality",
    "past_event": "A real past event, replayed",
    "city_average": "Delhi NCR average",
    "nearest_monitor": "Nearest air monitor",
    "health": "What this means for your health",
    "what_to_do": "What should I do?",
    "listen": "Listen",
    "stop": "Stop",
    "audio_unavailable": "Audio is not available right now.",
    "location_demo_set": "Demo location: central Delhi",
    "location_mine_set": "Using your location",
    "change_location": "Change location",
    "why": "Why is the air bad?",
    "why_note": "Worked out from air monitors, NASA fire satellites and weather data.",
    "report_title": "Seen haze or smoke? Send a photo",
    "report_body": "Take a photo of the sky. Our AI checks it for haze. Your photo helps "
                   "confirm what the monitors show, but it never changes a reading or "
                   "sends an alert on its own.",
    "report_privacy": "Your location is used only to know which area the photo is from. "
                      "Photos are checked and then discarded. They are never stored or published.",
    "choose_photo": "Take or choose a photo",
    "use_my_location": "Use my location",
    "use_demo_location": "Use a demo location in central Delhi",
    "location_note": "This page replays a past event in Delhi, so a demo location is offered.",
    "checking": "Checking your photo",
    "thanks": "Thank you. Your photo shows:",
    "adds_weight": "This adds weight to the monitor readings for your area. It does not change them.",
    "not_used": "We could not use this photo.",
    "busy": "The photo check is busy right now. Please try again in a minute.",
    "outside_area": "Photo reports are open only inside Delhi NCR for now.",
    "rate_limited": "You have sent several photos already. Please try again in an hour.",
    "bad_file": "Please send a JPG, PNG or WebP photo under 10 MB.",
    "location_denied": "Location permission was not given, so the photo cannot be placed on the map.",
    "try_another": "Try another photo",
    "visibility": "Visibility",
    "haze_level": "Haze level",
    "sources_seen": "Seen in photo",
    "translated_note": "Translated automatically",
    "rejected_indoor": "It looks like it was taken indoors.",
    "rejected_no_sky_visible": "The sky is not visible in it.",
    "rejected_screenshot_or_graphic": "It looks like a screenshot or a graphic, not a photo.",
    "rejected_too_dark": "It is too dark to see the sky.",
    "rejected_blurred": "It is too blurry to check.",
    "rejected_not_a_photo": "It does not look like a photo.",
    "rejected_other": "It could not be checked.",
    "sky_clear": "Clear sky", "sky_light_haze": "Light haze", "sky_moderate_haze": "Moderate haze",
    "sky_heavy_haze": "Heavy haze", "sky_fog": "Fog", "sky_overcast": "Cloudy", "sky_night": "Night",
    "src_crop_residue_burning": "Crop burning", "src_waste_burning": "Waste burning",
    "src_construction_dust": "Construction dust", "src_industrial_plume": "Factory smoke",
    "src_vehicular_smoke": "Vehicle smoke", "src_dust_storm": "Dust storm",
    "src_fog_only": "Fog only", "src_none_visible": "No clear source",
    **{f"band_{b.lower().replace(' ', '_')}": b for b in BANDS},
}

_DIRECTIONS = ["north", "north-east", "east", "south-east",
               "south", "south-west", "west", "north-west"]


def direction_words(bearing_deg: float) -> str:
    """'north-west' for 315. Eight points: finer than that means nothing to a reader."""
    return _DIRECTIONS[round((bearing_deg % 360) / 45) % 8]


def why(evidence: Dict[str, Any]) -> List[str]:
    """
    Plain sentences explaining the episode, each backed by one measured field.

    Thresholds are deliberately coarse. This is the explanation for someone who
    has never heard of a boundary layer; the officials' brief carries the detail.
    """
    out: List[str] = []

    ratio = (evidence.get("comparison") or {}).get("ratio_to_baseline")
    if ratio and ratio >= 1.3:
        out.append(f"The air is {ratio:.1f} times dirtier than the average of the past two weeks.")

    fires = (evidence.get("upwind_fires") or {}).get("count") or 0
    bearing = (evidence.get("wind") or {}).get("from_bearing_deg")
    if fires >= 5 and bearing is not None:
        out.append(f"Smoke from {fires} fires spotted by satellites is blowing in "
                   f"from the {direction_words(bearing)}.")
    elif fires >= 1:
        out.append(f"A few fires ({fires}) upwind may be adding some smoke.")
    elif bearing is not None:
        out.append("No fires were spotted upwind, so burning is not the main cause right now.")

    blh = evidence.get("boundary_layer_m")
    if blh is not None:
        if blh < 200:
            out.append("The air is very still, and a low layer of air is trapping "
                       "pollution close to the ground.")
        elif blh < 500:
            out.append("Low-lying air is slowing down how fast pollution clears.")
        else:
            out.append("The air is mixing well, which helps pollution clear.")

    return out


def _translate_batch(texts: List[str], lang: str) -> Optional[List[str]]:
    """One request for the whole page. None on failure; callers fall back to English."""
    try:
        from google.cloud import translate_v2 as translate
        client = translate.Client()
        rows = client.translate(texts, target_language=lang, source_language="en", format_="text")
        return [r["translatedText"] for r in rows]
    except Exception as e:
        logger.warning("batch translation to %s failed: %s", lang, e)
        return None


def bundle(evidence: Dict[str, Any], brief: Optional[Dict[str, Any]], lang: str) -> Dict[str, Any]:
    """
    Everything the resident view shows, in `lang`.

    If translation fails the whole bundle comes back in English with
    translated=False. Never a mix, and never English labelled as Hindi.
    """
    english: Dict[str, Any] = {
        "ui": dict(UI),
        "health": dict(HEALTH),
        "tips": {b: list(t) for b, t in TIPS.items()},
        "why": why(evidence),
        "advisory": (brief or {}).get("public_advisory"),
    }

    result = {
        "lang": "en",
        "translated": False,
        **english,
        "reading": {
            "city_pm25": evidence.get("city_pm25"),
            "aqi_band": evidence.get("aqi_band"),
            "n_stations": evidence.get("n_stations_reporting"),
            "ts": evidence.get("ts"),
        },
    }
    if lang == "en":
        return result

    # Flatten in a fixed order, translate once, then put every string back.
    flat: List[str] = []
    flat += list(english["ui"].values())
    flat += [english["health"][b] for b in BANDS]
    for b in BANDS:
        flat += english["tips"][b]
    flat += english["why"]
    if english["advisory"]:
        flat.append(english["advisory"])

    translated = _translate_batch(flat, lang)
    if translated is None or len(translated) != len(flat):
        return result

    it = iter(translated)
    result["ui"] = {k: next(it) for k in english["ui"]}
    result["health"] = {b: next(it) for b in BANDS}
    result["tips"] = {b: [next(it) for _ in english["tips"][b]] for b in BANDS}
    result["why"] = [next(it) for _ in english["why"]]
    if english["advisory"]:
        result["advisory"] = next(it)
    result["lang"] = lang
    result["translated"] = True
    return result


def demo() -> None:
    """Offline: the explanation must follow the evidence, and English needs no API."""
    hero = {
        "city_pm25": 406.6, "aqi_band": "Severe", "n_stations_reporting": 65,
        "comparison": {"ratio_to_baseline": 2.3},
        "upwind_fires": {"count": 35}, "wind": {"from_bearing_deg": 338.0},
        "boundary_layer_m": 65.0,
    }
    s = why(hero)
    assert any("2.3 times" in x for x in s), s
    # 338 deg is 22 deg from north and 23 from north-west: eight points say "north".
    assert any("35 fires" in x and "from the north." in x for x in s), s
    assert any("trapping" in x for x in s), s

    clean = {"comparison": {"ratio_to_baseline": 0.9}, "upwind_fires": {"count": 0},
             "wind": {"from_bearing_deg": 90.0}, "boundary_layer_m": 900.0}
    s = why(clean)
    assert not any("times dirtier" in x for x in s), "no ratio claim below 1.3x"
    assert any("not the main cause" in x for x in s), s
    assert any("mixing well" in x for x in s), s

    assert direction_words(338) == "north" and direction_words(315) == "north-west"
    assert direction_words(359.9) == "north" and direction_words(180) == "south"

    b = bundle(hero, {"public_advisory": "Stay indoors."}, "en")
    assert b["translated"] is False and b["lang"] == "en" and b["advisory"] == "Stay indoors."
    assert set(b["health"]) == set(BANDS) and set(b["tips"]) == set(BANDS)
    assert all(f"band_{x.lower().replace(' ', '_')}" in b["ui"] for x in BANDS)
    print("[OK] plain-language explanation follows the evidence; English bundle is complete")


if __name__ == "__main__":
    demo()
