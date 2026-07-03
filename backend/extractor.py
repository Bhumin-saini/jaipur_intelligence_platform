"""
Garuda v3 — NLP Extraction Layer (extractor.py)

Richer extraction: causal_factors, actor_roles, event_status, impact,
contradictions, plus existing fields. Primary: Gemini. Fallback: Groq.
"""
import json
import logging
import os
import re
import threading
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]
GEMINI_BASE   = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
GROQ_URL      = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.3-70b-versatile"

GEMINI_MIN_INTERVAL = float(os.environ.get("GEMINI_MIN_INTERVAL_SECONDS", "5.0"))
GROQ_MIN_INTERVAL   = float(os.environ.get("GROQ_MIN_INTERVAL_SECONDS", "2.5"))
_last_call          = {"Gemini": 0.0, "Groq": 0.0}
_lock               = threading.Lock()

# ── Jaipur geocoder ───────────────────────────────────────────────────────────

JAIPUR_COORDS: dict[str, tuple[float, float]] = {
    "jaipur": (26.9124, 75.7873),
    "jaipur district": (26.9124, 75.7873),
    "pink city": (26.9239, 75.8267),
    "walled city": (26.9239, 75.8267),
    "ajmer road": (26.9148, 75.7449),
    "mansarovar": (26.8570, 75.7760),
    "vaishali nagar": (26.9010, 75.7378),
    "malviya nagar": (26.8535, 75.8069),
    "tonk road": (26.8465, 75.8000),
    "civil lines": (26.9259, 75.8150),
    "c scheme": (26.9014, 75.8011),
    "sindhi camp": (26.9175, 75.7866),
    "bani park": (26.9250, 75.7966),
    "raja park": (26.8980, 75.8140),
    "amer": (26.9855, 75.8513),
    "amber": (26.9855, 75.8513),
    "sanganer": (26.8141, 75.7938),
    "sitapura": (26.7843, 75.8280),
    "pratap nagar": (26.8359, 75.8120),
    "durgapura": (26.8469, 75.7963),
    "vidyadhar nagar": (26.9579, 75.7755),
    "jhotwara": (26.9748, 75.7605),
    "murlipura": (26.9628, 75.7838),
    "jagatpura": (26.8161, 75.8593),
    "adarsh nagar": (26.8956, 75.7659),
    "chaksu": (26.6119, 75.9278),
    "chomu": (27.1584, 75.7217),
    "shahpura": (26.8785, 75.9602),
    "sikar road": (26.9650, 75.7600),
    "gopalpura": (26.8680, 75.7820),
    "shyam nagar": (26.9190, 75.7590),
    "mahesh nagar": (26.8791, 75.7876),
    "kalwar road": (26.9900, 75.7500),
    "amer road": (26.9500, 75.8200),
    "johari bazaar": (26.9239, 75.8267),
    "mi road": (26.9178, 75.8024),
    "station road": (26.9185, 75.7882),
}


def geocode(location_list: list) -> tuple[float, float]:
    for loc in location_list:
        key = str(loc).lower().strip()
        for known, coords in JAIPUR_COORDS.items():
            if known in key or key in known:
                return coords
    return 26.9124, 75.7873


# ── Rate-limited HTTP ─────────────────────────────────────────────────────────

def _post_throttled(name: str, min_interval: float, url: str, **kwargs) -> httpx.Response:
    with _lock:
        elapsed = time.time() - _last_call.get(name, 0.0)
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        resp = httpx.post(url, **kwargs)
        _last_call[name] = time.time()
        return resp


# ── Extraction Prompt ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
You are an intelligence analyst specialising in Jaipur, Rajasthan, India.

Extract structured intelligence from this news article. If the article is in Hindi,
process it internally and respond in English.

Return ONLY a valid JSON object with these exact keys. No markdown. No explanation.

{{
  "event_type": "crime|politics|accident|infrastructure|cultural|weather|business|health|other",
  "summary": "2-3 sentence factual summary in English. Be specific: who did what, where, outcome.",
  "severity": "low|medium|high",
  "event_status": "developing|ongoing|resolved|unclear",
  "locations": ["specific Jaipur place names"],
  "organizations": ["government agencies, political parties, companies, institutions"],
  "people": ["full names of individuals mentioned"],
  "actor_roles": {{
    "entity_name": "their role or action in this event (e.g. arrested, investigated, protested, allocated, delayed)"
  }},
  "causal_factors": ["what caused or triggered this event"],
  "impact": "who or what is affected and how (1 sentence)",
  "keywords": ["5-8 specific key terms"],
  "related_topics": ["broader themes: water crisis, road safety, electoral politics, etc."]
}}

Severity rules:
- high: death, violence, major accident, significant crime, policy crisis
- medium: injury, arrest, protest, disruption, fire, significant delay
- low: routine announcement, minor incident, informational

IMPORTANT:
- actor_roles must map EACH organization and person to their specific action/role
- causal_factors should explain WHY this event happened, not what happened
- event_status: 'developing' if ongoing situation; 'resolved' if concluded; 'unclear' if unknown
- If NOT about Jaipur: return event_type="other", summary="", empty lists

Article title: {title}
Article body: {body}
"""


def _build_prompt(title: str, body: str) -> str:
    return EXTRACTION_PROMPT.format(
        title=title,
        body=(body or "")[:4000],
    )


def _parse_json(raw: str) -> Optional[dict]:
    raw = re.sub(r"^```(?:json)?", "", raw.strip()).rstrip("`").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Backends ──────────────────────────────────────────────────────────────────

def _extract_gemini(title: str, body: str) -> Optional[dict]:
    if not GEMINI_API_KEY:
        return None
    payload = {
        "contents": [{"parts": [{"text": _build_prompt(title, body)}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1200},
    }
    for model in GEMINI_MODELS:
        url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)
        try:
            resp = _post_throttled("Gemini", GEMINI_MIN_INTERVAL, url, json=payload, timeout=30)
            if resp.status_code == 404:
                continue
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "30"))
                logger.warning("Gemini 429 — sleeping %.0fs", retry_after)
                time.sleep(min(retry_after, 60))
                resp = _post_throttled("Gemini", GEMINI_MIN_INTERVAL, url, json=payload, timeout=30)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            result = _parse_json(raw)
            if result:
                logger.info("Gemini OK — model=%s type=%s sev=%s status=%s",
                            model, result.get("event_type"), result.get("severity"),
                            result.get("event_status"))
            return result
        except Exception as exc:
            logger.warning("Gemini %s error: %s", model, exc)
            continue
    return None


def _extract_groq(title: str, body: str) -> Optional[dict]:
    if not GROQ_API_KEY:
        return None
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Extract Jaipur news intelligence. Return only valid JSON."},
            {"role": "user", "content": _build_prompt(title, body)},
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    try:
        resp = _post_throttled(
            "Groq", GROQ_MIN_INTERVAL, GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        result = _parse_json(raw)
        if result:
            logger.info("Groq OK — type=%s sev=%s", result.get("event_type"), result.get("severity"))
        return result
    except Exception as exc:
        logger.warning("Groq error: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def extract_intelligence(title: str, body: str) -> tuple:
    """
    Returns (structured_result | None, raw_json_str).
    structured_result includes all v3 fields: actor_roles, causal_factors,
    event_status, impact, plus geocoded lat/lng.
    """
    for name, fn in [("Gemini", _extract_gemini), ("Groq", _extract_groq)]:
        try:
            result = fn(title, body)
            if result:
                # Geocode
                lat, lng = geocode(result.get("locations", []))
                result["lat"] = lat
                result["lng"] = lng
                # Ensure all v3 fields exist with defaults
                result.setdefault("actor_roles", {})
                result.setdefault("causal_factors", [])
                result.setdefault("event_status", "unclear")
                result.setdefault("impact", "")
                result.setdefault("related_topics", [])
                return result, json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            logger.warning("[%s] failed: %s", name, exc)

    logger.error("All NLP backends failed for: %s", title[:80])
    return None, ""
