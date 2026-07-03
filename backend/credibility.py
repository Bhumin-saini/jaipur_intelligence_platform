"""
Garuda v3 — Source Credibility Layer (credibility.py)

Tracks reliability, bias, and contradiction history per news source.
Provides confidence-weighted event scoring.

Public API:
  record_source_activity()   — log an article from a source
  update_source_score()      — recalculate credibility score
  get_source_score()         — retrieve credibility record
  list_source_scores()       — all sources with scores
  adjust_event_confidence()  — weight event by source credibility
  flag_contradiction()       — mark conflicting reports
"""

from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _scores():
    from astra_client import source_scores
    return source_scores()


# ── Predefined source metadata ────────────────────────────────────────────────

SOURCE_METADATA: dict[str, dict] = {
    "dainik_bhaskar":    {"bias": "neutral",     "tier": 1, "language": "hindi"},
    "rajasthan_patrika": {"bias": "neutral",     "tier": 1, "language": "hindi"},
    "times_of_india":    {"bias": "centrist",    "tier": 1, "language": "english"},
    "hindustan_times":   {"bias": "centrist",    "tier": 1, "language": "english"},
    "ndtv":              {"bias": "centrist",    "tier": 1, "language": "english"},
    "aaj_tak":           {"bias": "tabloid",     "tier": 2, "language": "hindi"},
    "zee_news":          {"bias": "right-lean",  "tier": 2, "language": "hindi"},
    "jaipur_beat":       {"bias": "local",       "tier": 2, "language": "english"},
    "jaipur_today":      {"bias": "local",       "tier": 2, "language": "english"},
    "news18":            {"bias": "right-lean",  "tier": 2, "language": "hindi"},
}

TIER_BASE_SCORE = {1: 0.85, 2: 0.70, 3: 0.50}
BIAS_PENALTY    = {"neutral": 0.0, "centrist": 0.0, "local": 0.0,
                   "left-lean": -0.05, "right-lean": -0.05, "tabloid": -0.15}


# ── Record & Score ────────────────────────────────────────────────────────────

def record_source_activity(source: str, article_id: str, event_id: str | None = None) -> None:
    """Log that a source published an article. Creates score doc if missing."""
    try:
        existing = _scores().find_one({"_id": source})
        if existing:
            _scores().update_one(
                {"_id": source},
                {"$inc": {"article_count": 1, "recent_articles": 1},
                 "$set": {"last_seen": _utc_now()}},
            )
        else:
            meta = SOURCE_METADATA.get(source, {"bias": "unknown", "tier": 3, "language": "unknown"})
            tier = meta.get("tier", 3)
            _scores().insert_one({
                "_id":              source,
                "display_name":     source.replace("_", " ").title(),
                "bias":             meta.get("bias", "unknown"),
                "tier":             tier,
                "language":         meta.get("language", "unknown"),
                "base_score":       TIER_BASE_SCORE.get(tier, 0.5),
                "credibility_score": TIER_BASE_SCORE.get(tier, 0.5),
                "article_count":    1,
                "recent_articles":  1,
                "correction_count": 0,
                "contradiction_count": 0,
                "last_seen":        _utc_now(),
                "created_at":       _utc_now(),
            })
    except Exception as exc:
        logger.warning("record_source_activity error (%s): %s", source, exc)


def update_source_score(source: str) -> float:
    """
    Recalculate and persist credibility score for a source.
    Score = base_score - contradiction_penalty - correction_penalty
    Returns new score.
    """
    try:
        doc = _scores().find_one({"_id": source})
        if not doc:
            return 0.5

        meta = SOURCE_METADATA.get(source, {})
        base = doc.get("base_score", 0.5)

        corrections    = doc.get("correction_count", 0)
        contradictions = doc.get("contradiction_count", 0)
        articles       = max(doc.get("article_count", 1), 1)

        corr_penalty  = min(corrections / articles * 2.0, 0.3)
        contra_penalty = min(contradictions / articles * 1.5, 0.2)
        bias_pen = BIAS_PENALTY.get(meta.get("bias", "unknown"), 0.0)

        score = max(0.1, min(1.0, base - corr_penalty - contra_penalty + bias_pen))

        _scores().update_one(
            {"_id": source},
            {"$set": {"credibility_score": round(score, 3), "updated_at": _utc_now()}},
        )
        return score
    except Exception as exc:
        logger.warning("update_source_score error: %s", exc)
        return 0.5


def get_source_score(source: str) -> dict | None:
    try:
        return _scores().find_one({"_id": source})
    except Exception as exc:
        logger.warning("get_source_score error: %s", exc)
        return None


def list_source_scores(limit: int = 50) -> list[dict]:
    try:
        return list(_scores().find({}, sort={"credibility_score": -1}, limit=limit))
    except Exception as exc:
        logger.warning("list_source_scores error: %s", exc)
        return []


def adjust_event_confidence(event: dict) -> dict:
    """
    Add a `confidence` field to an event dict based on source credibility.
    Also adds source_credibility_score for display.
    """
    source = event.get("source", "")
    score_doc = get_source_score(source)
    score = score_doc.get("credibility_score", 0.5) if score_doc else 0.5

    severity_weight = {"high": 1.0, "medium": 0.8, "low": 0.6}.get(
        event.get("severity", "low"), 0.6
    )
    confidence = round(score * severity_weight, 3)

    event["source_credibility_score"] = score
    event["confidence"] = confidence
    return event


def flag_contradiction(
    source_a: str,
    event_id_a: str,
    source_b: str,
    event_id_b: str,
    description: str = "",
) -> None:
    """
    Mark two events as contradicting each other.
    Increments contradiction count for both sources.
    """
    try:
        for source in (source_a, source_b):
            existing = _scores().find_one({"_id": source})
            if existing:
                _scores().update_one(
                    {"_id": source},
                    {"$inc": {"contradiction_count": 1}},
                )
                update_source_score(source)

        # Also store the contradiction record
        from astra_client import get_db
        try:
            coll = get_db().get_collection("contradictions")
            coll.insert_one({
                "source_a":   source_a,
                "event_id_a": event_id_a,
                "source_b":   source_b,
                "event_id_b": event_id_b,
                "description": description,
                "created_at": _utc_now(),
            })
        except Exception:
            pass  # contradictions collection may not exist yet

    except Exception as exc:
        logger.warning("flag_contradiction error: %s", exc)
