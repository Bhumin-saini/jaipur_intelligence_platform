"""
Garuda v3 — Hypothesis Testing (hypothesis.py)

Analyst-driven hypothesis framework:
  - Create a hypothesis statement
  - Gather supporting / contradictory evidence from events
  - Compute confidence score
  - Track hypothesis status over time

Public API:
  create_hypothesis()        → str
  update_hypothesis()        → None
  get_hypothesis()           → dict | None
  list_hypotheses()          → list[dict]
  add_evidence()             → str
  remove_evidence()          → None
  get_evidence()             → list[dict]
  evaluate_hypothesis()      → dict   ← LLM-powered
  search_evidence()          → list[dict]
  auto_gather_evidence()     → list[dict]
"""

from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hyps():
    from astra_client import hypotheses
    return hypotheses()


def _evidence_coll():
    from astra_client import evidence
    return evidence()


# ── Hypothesis CRUD ───────────────────────────────────────────────────────────

def create_hypothesis(
    statement: str,
    case_id: str | None = None,
    analyst: str = "analyst",
    tags: list[str] | None = None,
    initial_confidence: float = 0.5,
) -> str:
    """
    Create a new hypothesis.
    statement: The claim to be tested, e.g.
        'Illegal mining activity is causing road damage in region X'
    Returns hypothesis _id.
    """
    hyp_id = str(uuid.uuid4())
    _hyps().insert_one({
        "_id":               hyp_id,
        "statement":         statement,
        "case_id":           case_id,
        "analyst":           analyst,
        "tags":              tags or [],
        "status":            "open",       # open | confirmed | rejected | inconclusive
        "confidence":        initial_confidence,
        "supporting_count":  0,
        "contradicting_count": 0,
        "neutral_count":     0,
        "last_evaluated":    None,
        "evaluation_summary": None,
        "created_at":        _utc_now(),
        "updated_at":        _utc_now(),
    })
    logger.info("Hypothesis created: %s", statement[:80])
    return hyp_id


def update_hypothesis(hyp_id: str, **kwargs) -> None:
    allowed = {"statement", "status", "case_id", "analyst", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    updates["updated_at"] = _utc_now()
    try:
        _hyps().update_one({"_id": hyp_id}, {"$set": updates})
    except Exception as exc:
        logger.error("update_hypothesis error: %s", exc)


def get_hypothesis(hyp_id: str) -> dict | None:
    try:
        return _hyps().find_one({"_id": hyp_id})
    except Exception as exc:
        logger.error("get_hypothesis error: %s", exc)
        return None


def list_hypotheses(
    case_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    filt: dict = {}
    if case_id: filt["case_id"] = case_id
    if status:  filt["status"]  = status
    try:
        return list(_hyps().find(filt, sort={"updated_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("list_hypotheses error: %s", exc)
        return []


def delete_hypothesis(hyp_id: str) -> bool:
    try:
        _evidence_coll().delete_many({"hypothesis_id": hyp_id})
        _hyps().delete_one({"_id": hyp_id})
        return True
    except Exception as exc:
        logger.error("delete_hypothesis error: %s", exc)
        return False


# ── Evidence Operations ───────────────────────────────────────────────────────

def add_evidence(
    hypothesis_id: str,
    event_id: str | None = None,
    text: str = "",
    stance: str = "supporting",
    strength: float = 0.5,
    source: str = "",
    analyst: str = "analyst",
) -> str:
    """
    Add evidence to a hypothesis.
    stance: 'supporting' | 'contradicting' | 'neutral'
    strength: 0.0–1.0
    Returns evidence _id.
    """
    ev_id = str(uuid.uuid4())
    _evidence_coll().insert_one({
        "_id":           ev_id,
        "hypothesis_id": hypothesis_id,
        "event_id":      event_id,
        "text":          text,
        "stance":        stance,
        "strength":      strength,
        "source":        source,
        "analyst":       analyst,
        "created_at":    _utc_now(),
    })

    # Update counts
    field_map = {
        "supporting":    "supporting_count",
        "contradicting": "contradicting_count",
        "neutral":       "neutral_count",
    }
    field = field_map.get(stance, "neutral_count")
    try:
        _hyps().update_one(
            {"_id": hypothesis_id},
            {"$inc": {field: 1}, "$set": {"updated_at": _utc_now()}},
        )
    except Exception as exc:
        logger.warning("add_evidence update_hyp error: %s", exc)

    return ev_id


def remove_evidence(evidence_id: str) -> None:
    try:
        ev = _evidence_coll().find_one({"_id": evidence_id})
        if not ev:
            return
        _evidence_coll().delete_one({"_id": evidence_id})

        # Decrement count
        field_map = {
            "supporting":    "supporting_count",
            "contradicting": "contradicting_count",
            "neutral":       "neutral_count",
        }
        field = field_map.get(ev.get("stance", "neutral"), "neutral_count")
        _hyps().update_one(
            {"_id": ev["hypothesis_id"]},
            {"$inc": {field: -1}, "$set": {"updated_at": _utc_now()}},
        )
    except Exception as exc:
        logger.error("remove_evidence error: %s", exc)


def get_evidence(
    hypothesis_id: str,
    stance: str | None = None,
    limit: int = 50,
) -> list[dict]:
    filt: dict = {"hypothesis_id": hypothesis_id}
    if stance:
        filt["stance"] = stance
    try:
        return list(_evidence_coll().find(filt, sort={"strength": -1}, limit=limit))
    except Exception as exc:
        logger.error("get_evidence error: %s", exc)
        return []


# ── Evidence Search ───────────────────────────────────────────────────────────

def search_evidence(
    hypothesis_id: str,
    limit: int = 10,
    lookback_days: int = 90,
) -> list[dict]:
    """
    Semantically search for events that could serve as evidence
    for a hypothesis. Returns top matching events with suggested stance.
    """
    hyp = get_hypothesis(hypothesis_id)
    if not hyp:
        return []

    from astra_client import events as ev_coll
    from embedder import embed_text

    statement = hyp.get("statement", "")
    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    try:
        vec = embed_text(statement)
        results = list(ev_coll().find(
            {"created_at": {"$gte": since}},
            sort={"$vector": vec},
            limit=limit,
            include_similarity=True,
            projection={
                "_id": 1, "summary": 1, "event_type": 1,
                "severity": 1, "created_at": 1, "source": 1,
                "locations": 1, "$similarity": 1,
            },
        ))

        # Determine suggested stance based on similarity score
        annotated = []
        for r in results:
            sim = r.get("$similarity", 0)
            if sim >= 0.80:
                suggested_stance = "supporting"
            elif sim >= 0.65:
                suggested_stance = "neutral"
            else:
                suggested_stance = "neutral"

            locs = r.get("locations") or []
            if isinstance(locs, str):
                try: locs = json.loads(locs)
                except: locs = []

            annotated.append({
                "event_id":        r.get("_id"),
                "summary":         r.get("summary", "")[:300],
                "event_type":      r.get("event_type"),
                "severity":        r.get("severity"),
                "created_at":      r.get("created_at"),
                "source":          r.get("source"),
                "locations":       locs,
                "similarity":      round(sim, 3),
                "suggested_stance": suggested_stance,
            })

        return annotated

    except Exception as exc:
        logger.error("search_evidence error: %s", exc)
        return []


def auto_gather_evidence(
    hypothesis_id: str,
    limit: int = 10,
    lookback_days: int = 90,
) -> list[dict]:
    """
    Automatically gather and add evidence for a hypothesis via semantic search.
    Returns list of added evidence items.
    """
    candidates = search_evidence(hypothesis_id, limit=limit, lookback_days=lookback_days)
    added = []
    for c in candidates:
        ev_id = add_evidence(
            hypothesis_id=hypothesis_id,
            event_id=c["event_id"],
            text=c["summary"],
            stance=c["suggested_stance"],
            strength=c["similarity"],
            source=c.get("source", "auto"),
            analyst="auto",
        )
        added.append({**c, "_id": ev_id, "auto": True})
    return added


# ── LLM Evaluation ───────────────────────────────────────────────────────────

EVAL_PROMPT = """\
You are an intelligence analyst. Evaluate the following hypothesis based on the evidence provided.

HYPOTHESIS:
{statement}

SUPPORTING EVIDENCE ({n_supporting} items):
{supporting_text}

CONTRADICTING EVIDENCE ({n_contradicting} items):
{contradicting_text}

NEUTRAL EVIDENCE ({n_neutral} items):
{neutral_text}

Please provide:
1. CONFIDENCE SCORE: A number from 0.0 to 1.0 (0 = definitely false, 1 = definitely true)
2. VERDICT: one of: confirmed | rejected | inconclusive | needs_more_evidence
3. REASONING: 3-5 sentences explaining your assessment
4. KEY GAPS: What additional evidence is needed?
5. RECOMMENDED ACTIONS: 2-3 specific investigative actions

Return ONLY a JSON object with keys: confidence, verdict, reasoning, key_gaps, recommended_actions
"""


def evaluate_hypothesis(hypothesis_id: str) -> dict:
    """
    Use Gemini to evaluate the hypothesis given all evidence.
    Updates hypothesis with new confidence and verdict.
    Returns evaluation dict.
    """
    import os
    import httpx
    import re

    hyp = get_hypothesis(hypothesis_id)
    if not hyp:
        return {"error": "Hypothesis not found"}

    all_evidence = get_evidence(hypothesis_id, limit=50)

    def _fmt(items: list[dict]) -> str:
        if not items:
            return "(none)"
        return "\n".join(f"- {e['text'][:200]}" for e in items)

    supporting    = [e for e in all_evidence if e.get("stance") == "supporting"]
    contradicting = [e for e in all_evidence if e.get("stance") == "contradicting"]
    neutral       = [e for e in all_evidence if e.get("stance") == "neutral"]

    prompt = EVAL_PROMPT.format(
        statement=hyp["statement"],
        n_supporting=len(supporting),
        n_contradicting=len(contradicting),
        n_neutral=len(neutral),
        supporting_text=_fmt(supporting),
        contradicting_text=_fmt(contradicting),
        neutral_text=_fmt(neutral),
    )

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not set"}

    for model in ["gemini-2.0-flash", "gemini-1.5-flash-latest"]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{model}:generateContent?key={GEMINI_API_KEY}"
        )
        try:
            resp = httpx.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
                },
                timeout=45,
            )
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

            # Parse JSON from response
            raw = re.sub(r"^```(?:json)?", "", raw.strip()).rstrip("`").strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                result = {}

            confidence = float(result.get("confidence", 0.5))
            verdict    = result.get("verdict", "inconclusive")

            # Persist evaluation
            _hyps().update_one(
                {"_id": hypothesis_id},
                {"$set": {
                    "confidence":         confidence,
                    "status":             verdict,
                    "evaluation_summary": result.get("reasoning", ""),
                    "last_evaluated":     _utc_now(),
                    "updated_at":         _utc_now(),
                }},
            )

            return {
                "hypothesis_id":      hypothesis_id,
                "confidence":         confidence,
                "verdict":            verdict,
                "reasoning":          result.get("reasoning", ""),
                "key_gaps":           result.get("key_gaps", ""),
                "recommended_actions": result.get("recommended_actions", []),
                "evidence_summary": {
                    "supporting":    len(supporting),
                    "contradicting": len(contradicting),
                    "neutral":       len(neutral),
                },
            }

        except Exception as exc:
            logger.warning("evaluate_hypothesis model=%s error: %s", model, exc)
            continue

    return {"error": "Evaluation failed — check LLM API"}
