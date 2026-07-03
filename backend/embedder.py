"""
Garuda v2 — Embedding Generation (embedder.py)

Primary: Gemini gemini-embedding-001 via v1beta REST.
On 429 rate-limit: waits and retries with exponential backoff (up to 5 attempts).
No local fallback — Gemini only.

All public functions return list[float] of length DIM.
"""
import os
import time
import logging
import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
EMBED_MODEL    = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
DIM            = int(os.environ.get("EMBEDDING_DIM", "3072"))

_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:embedContent?key={key}"
)

# Retry settings for 429
_MAX_RETRIES    = 6
_RETRY_BASE_SEC = 10   # first wait: 10s, then 20s, 40s, 80s, 160s, 320s


def _gemini_embed(text: str) -> list[float]:
    """
    Call Gemini embedding API with automatic retry on 429.
    Raises RuntimeError if all retries exhausted or a non-retryable error occurs.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")

    url = _GEMINI_EMBED_URL.format(model=EMBED_MODEL, key=GEMINI_API_KEY)
    payload = {
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": "RETRIEVAL_DOCUMENT",
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=20)

            if resp.status_code == 429:
                wait = _RETRY_BASE_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini 429 rate limit (attempt %d/%d) — waiting %ds before retry",
                    attempt, _MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()["embedding"]["values"]

        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Gemini embed HTTP error: {exc}") from exc
        except Exception as exc:
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BASE_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "Gemini embed error (attempt %d/%d): %s — retrying in %ds",
                    attempt, _MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)
            else:
                raise RuntimeError(f"Gemini embed failed after {_MAX_RETRIES} attempts: {exc}") from exc

    raise RuntimeError(f"Gemini embed: all {_MAX_RETRIES} retry attempts exhausted")


# ── Public API ────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    """Embed a string. Returns a dense float vector of length DIM."""
    text = (text or "").strip()[:4000]
    if not text:
        return [0.0] * DIM
    return _gemini_embed(text)


def embed_article(title: str, body: str) -> list[float]:
    return embed_text(f"{title or ''} {(body or '')[:512]}")


def embed_event(
    event_type: str,
    summary: str,
    keywords: list[str],
    locations: list[str],
) -> list[float]:
    parts = [
        event_type or "",
        summary or "",
        *[str(k) for k in (keywords or [])],
        *[str(l) for l in (locations or [])],
    ]
    return embed_text(" ".join(p for p in parts if p))


def embed_entity(name: str, entity_type: str) -> list[float]:
    return embed_text(f"{entity_type}: {name}")


def embed_brief(body: str) -> list[float]:
    return embed_text(body[:3000])
