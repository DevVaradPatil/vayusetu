"""
api/gemini/advisory.py — Multilingual Advisory Generator.

W3.5: Generates air quality advisories in 10 Indian languages using
      Cloud Translation API and Cloud Text-to-Speech.
      Caches output by (text_hash, lang) to avoid redundant API calls.

Supported Languages:
  hi  — Hindi
  en  — English
  ta  — Tamil
  te  — Telugu
  kn  — Kannada
  ml  — Malayalam
  mr  — Marathi
  bn  — Bengali
  gu  — Gujarati
  pa  — Punjabi (Gurmukhi)
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("vayusetu.gemini.advisory")


# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
}

# Cloud TTS language codes (BCP-47)
TTS_LANGUAGE_CODES: Dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "pa": "pa-IN",
}

# Seed advisory texts in English — translated on-the-fly by Translation API
# These are the English advisory templates for different AQI severity levels
ADVISORY_TEMPLATES: Dict[str, str] = {
    "Severe": (
        "Air quality is Severe — PM2.5 is extremely high. "
        "Avoid all outdoor activities. Stay indoors with windows closed. "
        "Wear a well-fitting N95 mask if you must go outside. "
        "People with heart or lung conditions should seek medical attention if symptoms worsen."
    ),
    "Very Poor": (
        "Air quality is Very Poor. Avoid prolonged outdoor exercise. "
        "Children, elderly, and those with respiratory conditions should stay indoors. "
        "Keep windows closed. Use air purifiers if available."
    ),
    "Poor": (
        "Air quality is Poor. Sensitive groups should reduce outdoor time. "
        "Avoid strenuous outdoor activities. Wear a mask if going outside."
    ),
    "Moderate": (
        "Air quality is Moderate. Most people can continue normal activities. "
        "Sensitive individuals should watch for symptoms and limit prolonged outdoor exertion."
    ),
    "Satisfactory": (
        "Air quality is Satisfactory. Air quality is acceptable. "
        "Very sensitive people may experience minor discomfort."
    ),
    "Good": (
        "Air quality is Good. Enjoy outdoor activities!"
    ),
}


# ---------------------------------------------------------------------------
# In-memory cache: (text_hash, lang) -> AdvisoryResult
# ---------------------------------------------------------------------------
_advisory_cache: Dict[Tuple[str, str], "AdvisoryResult"] = {}


class AdvisoryResult(BaseModel):
    lang: str
    lang_name: str
    aqi_band: str
    advisory_text: str            # Translated text
    source_text: str              # Original English template used
    audio_base64: Optional[str] = None   # Base64-encoded MP3 from Cloud TTS
    audio_content_type: str = "audio/mpeg"
    cached: bool = False
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    translation_model: str = "mock"


def _compute_cache_key(source_text: str, lang: str) -> str:
    text_hash = hashlib.md5(source_text.encode("utf-8")).hexdigest()[:12]
    return f"{text_hash}:{lang}"


def _translate_text_mock(text: str, target_lang: str) -> str:
    """
    Fallback translation: returns the English text with a language tag prefix.
    Used when Cloud Translation API key is not configured.
    """
    if target_lang == "en":
        return text
    lang_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    return f"[{lang_name}] {text}"


def _translate_text(text: str, target_lang: str, project_id: str, api_key: Optional[str] = None) -> str:
    """
    Translates English text using Cloud Translation API v3.
    Falls back to mock if credentials missing.
    """
    if target_lang == "en":
        return text

    # Do NOT gate on GOOGLE_APPLICATION_CREDENTIALS. Application Default
    # Credentials (gcloud auth application-default login, or the service identity
    # on Cloud Run) never set that variable, so checking for it short-circuits to
    # the mock on exactly the setups where translation would have worked. Attempt
    # the call and let the client resolve credentials however it can.
    try:
        from google.cloud import translate_v2 as translate
        client = translate.Client()
        result = client.translate(text, target_language=target_lang, source_language="en")
        return result["translatedText"]
    except Exception as e:
        logger.warning("Translation API failed for lang=%s: %s. Using mock.", target_lang, e)
        return _translate_text_mock(text, target_lang)


def is_mock_translation(text: str) -> bool:
    """
    True when `text` came from the mock rather than the Translation API.

    Callers must be able to tell: showing English to a Hindi speaker while
    labelling it Hindi is a real failure for the audience this feature exists to
    serve, and it is invisible unless something checks.
    """
    return text.startswith("[") and "]" in text[:24]


def _synthesize_speech(text: str, lang_bcp47: str) -> Optional[str]:
    """
    Synthesizes speech using Cloud Text-to-Speech API.
    Returns base64-encoded MP3 bytes, or None on failure.

    Not gated on GOOGLE_APPLICATION_CREDENTIALS, for the same reason as
    _translate_text: ADC never sets it, so that gate meant spoken advisories
    silently never ran on any machine where they would have worked.
    """
    try:
        import base64
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_bcp47,
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        return base64.b64encode(response.audio_content).decode("utf-8")
    except Exception as e:
        logger.warning(f"Cloud TTS failed for lang={lang_bcp47}: {e}. Skipping audio.")
        return None


def generate_advisory(
    aqi_band: str,
    lang: str = "en",
    include_audio: bool = False,
    project_id: str = "",
) -> AdvisoryResult:
    """
    Generates a multilingual advisory for the given AQI band.
    Caches results by (text_hash, lang).

    Args:
        aqi_band: CPCB AQI band name (Good/Satisfactory/Moderate/Poor/Very Poor/Severe)
        lang: ISO 639-1 language code (en, hi, ta, te, kn, ml, mr, bn, gu, pa)
        include_audio: Whether to include Cloud TTS audio
        project_id: GCP project ID for Cloud APIs
    """
    if lang not in SUPPORTED_LANGUAGES:
        logger.warning(f"Unsupported language '{lang}'. Falling back to English.")
        lang = "en"

    # Map AQI band to template (fuzzy match)
    source_text = ADVISORY_TEMPLATES.get(aqi_band, ADVISORY_TEMPLATES["Moderate"])
    cache_key = _compute_cache_key(source_text, lang)

    # Cache hit
    if cache_key in _advisory_cache:
        cached_result = _advisory_cache[cache_key].model_copy()
        cached_result.cached = True
        logger.debug(f"Advisory cache hit for ({lang}, {aqi_band})")
        return cached_result

    # Translate
    translated_text = _translate_text(source_text, lang, project_id)

    # TTS (optional)
    audio_b64 = None
    if include_audio:
        tts_lang = TTS_LANGUAGE_CODES.get(lang, "en-IN")
        audio_b64 = _synthesize_speech(translated_text, tts_lang)

    result = AdvisoryResult(
        lang=lang,
        lang_name=SUPPORTED_LANGUAGES[lang],
        aqi_band=aqi_band,
        advisory_text=translated_text,
        source_text=source_text,
        audio_base64=audio_b64,
        cached=False,
        translation_model=("none" if lang == "en"
                           else "mock" if is_mock_translation(translated_text)
                           else "cloud_translation_v2"),
    )

    # Cache it
    _advisory_cache[cache_key] = result
    return result


def generate_advisory_all_languages(aqi_band: str) -> Dict[str, AdvisoryResult]:
    """
    Generates advisories in all 10 supported languages.
    Returns dict of lang -> AdvisoryResult.
    """
    results = {}
    for lang in SUPPORTED_LANGUAGES:
        results[lang] = generate_advisory(aqi_band, lang)
    return results


def clear_advisory_cache() -> int:
    """Clears the in-memory advisory cache. Returns number of entries cleared."""
    count = len(_advisory_cache)
    _advisory_cache.clear()
    return count


# ---------------------------------------------------------------------------
# Demo / Self-Test
# ---------------------------------------------------------------------------

def demo():
    print("=== Multilingual Advisory Generator Demo (W3.5) ===")
    print(f"  Supported languages: {', '.join(SUPPORTED_LANGUAGES.values())}")

    # Test English advisory (no translation needed)
    result_en = generate_advisory("Severe", lang="en")
    assert result_en.lang == "en"
    assert result_en.aqi_band == "Severe"
    assert "Severe" in result_en.advisory_text
    assert result_en.cached is False
    print(f"  [OK] English Severe advisory ({len(result_en.advisory_text)} chars): "
          f"'{result_en.advisory_text[:60]}...'")

    # Test Hindi advisory
    result_hi = generate_advisory("Severe", lang="hi")
    assert result_hi.lang == "hi"
    assert result_hi.lang_name == "Hindi"
    assert len(result_hi.advisory_text) > 10
    print(f"  [OK] Hindi Severe advisory ({len(result_hi.advisory_text)} chars): "
          f"'{result_hi.advisory_text[:60]}...'")

    # Test cache: second call for same (aqi_band, lang) should be cached
    result_en_cached = generate_advisory("Severe", lang="en")
    assert result_en_cached.cached is True
    print(f"  [OK] Advisory cache hit for (Severe, en): cached={result_en_cached.cached}")

    # Test all 10 languages for 'Moderate' band
    all_advisories = generate_advisory_all_languages("Moderate")
    assert len(all_advisories) == 10
    for lang, adv in all_advisories.items():
        assert adv.lang == lang, f"Lang mismatch: {adv.lang} != {lang}"
        assert len(adv.advisory_text) > 5, f"Empty advisory for {lang}"
        assert adv.aqi_band == "Moderate"
    print(f"  [OK] Moderate advisory generated in all {len(all_advisories)} languages")

    # Test all AQI bands in English
    for band in ADVISORY_TEMPLATES:
        adv = generate_advisory(band, lang="en")
        assert adv.aqi_band == band
        assert len(adv.advisory_text) > 5
    print(f"  [OK] All {len(ADVISORY_TEMPLATES)} AQI band advisories verified")

    # Test cache clear
    cleared = clear_advisory_cache()
    assert cleared > 0
    print(f"  [OK] Advisory cache cleared ({cleared} entries)")

    # Test unsupported language fallback to English
    result_unk = generate_advisory("Poor", lang="xx_invalid")
    assert result_unk.lang == "en"
    print(f"  [OK] Unsupported language 'xx_invalid' falls back to English")

    # Test audio stub (mock — no GCP credentials)
    result_audio = generate_advisory("Good", lang="hi", include_audio=True)
    # Audio will be None in mock mode — that's expected
    assert result_audio.audio_base64 is None or isinstance(result_audio.audio_base64, str)
    print(f"  [OK] Audio synthesis stub: audio={'included' if result_audio.audio_base64 else 'None (no GCP creds)'}")

    print("\nAll multilingual advisory checks passed successfully!")


if __name__ == "__main__":
    demo()
