"""
api/gemini package: Gemini integrations for VayuSetu (google-genai SDK).
"""

import logging
import time

logger = logging.getLogger("vayusetu.gemini")


def generate_with_retry(client, **kwargs):
    """
    client.models.generate_content with one retry on 503 UNAVAILABLE.

    Flash Lite returns transient "high demand" 503s under load (seen 2026-09-10 on
    the photo endpoint). One retry after a short pause clears most of them.

    Deliberately NOT retried: 429. On this project that means the 500 requests/day
    quota is spent, and retrying would only spend more of it.
    """
    # ponytail: one fixed retry, no backoff schedule; widen only if 503s persist
    try:
        return client.models.generate_content(**kwargs)
    except Exception as e:
        if getattr(e, "code", None) != 503:
            raise
        logger.warning("Gemini 503, retrying once: %s", e)
        time.sleep(2)
        return client.models.generate_content(**kwargs)
