"""
Offline check of the Gemini retry rule: a 503 is retried once, a 429 never is.

Run: python -m api.gemini.test_retry   (also collected by pytest)
"""

import api.gemini as gemini
from api.gemini import generate_with_retry


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class _Client:
    """Fails with the given status codes in order, then succeeds."""

    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0
        self.models = self

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise _Err(self.failures.pop(0))
        return "ok"


def _raises(client, code):
    try:
        generate_with_retry(client, model="m")
    except _Err as e:
        return e.code == code
    return False


def test_retry_rule():
    gemini.time.sleep = lambda s: None  # no real pause in a test

    c = _Client([503])
    assert generate_with_retry(c, model="m") == "ok" and c.calls == 2, "503 retried once"

    c = _Client([429])
    assert _raises(c, 429) and c.calls == 1, "429 is quota, never retried"

    c = _Client([503, 503])
    assert _raises(c, 503) and c.calls == 2, "only one retry"


if __name__ == "__main__":
    test_retry_rule()
    print("[OK] 503 retried once, 429 not retried, retry capped at one")
