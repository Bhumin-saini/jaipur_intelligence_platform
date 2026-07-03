"""
Garuda v3 — Case Management (case_manager.py)

Analyst case files that bundle related events, entities, notes,
and risk scores into a persistent investigation workspace.

Public API:
  create_case()        → str
  update_case()        → None
  get_case()           → dict | None
  list_cases()         → list[dict]
  add_case_event()     → None
  remove_case_event()  → None
  get_case_events()    → list[dict]
  add_annotation()     → str
  get_annotations()    → list[dict]
  compute_case_risk()  → dict
  close_case()         → None
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cases():
    from astra_client import cases
    return cases()


def _case_events():
    from astra_client import case_events
    return case_events()


def _annotations():
    from astra_client import annotations
    return annotations()


# ── Case CRUD ─────────────────────────────────────────────────────────────────

def create_case(
    title: str,
    description: str = "",
    category: str = "general",
    priority: str = "medium",
    tags: list[str] | None = None,
    analyst: str = "analyst",
) -> str:
    """
    Create a new investigation case.
    category: 'crime' | 'infrastructure' | 'political' | 'health' | 'general'
    priority: 'low' | 'medium' | 'high' | 'critical'
    Returns the case _id.
    """
    case_id = str(uuid.uuid4())
    _cases().insert_one({
        "_id":         case_id,
        "title":       title,
        "description": description,
        "category":    category,
        "priority":    priority,
        "status":      "open",
        "tags":        tags or [],
        "analyst":     analyst,
        "event_count": 0,
        "risk_score":  0.0,
        "risk_label":  "unknown",
        "created_at":  _utc_now(),
        "updated_at":  _utc_now(),
        "closed_at":   None,
    })
    logger.info("Case created: %s — %s", case_id, title)
    return case_id


def update_case(
    case_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
) -> None:
    updates: dict = {"updated_at": _utc_now()}
    if title is not None:       updates["title"]       = title
    if description is not None: updates["description"] = description
    if priority is not None:    updates["priority"]    = priority
    if status is not None:      updates["status"]      = status
    if tags is not None:        updates["tags"]        = tags

    try:
        _cases().update_one({"_id": case_id}, {"$set": updates})
    except Exception as exc:
        logger.error("update_case error: %s", exc)


def get_case(case_id: str) -> dict | None:
    try:
        return _cases().find_one({"_id": case_id})
    except Exception as exc:
        logger.error("get_case error: %s", exc)
        return None


def list_cases(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> list[dict]:
    filt: dict = {}
    if status:   filt["status"]   = status
    if category: filt["category"] = category
    if priority: filt["priority"] = priority

    try:
        return list(_cases().find(filt, sort={"updated_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("list_cases error: %s", exc)
        return []


def close_case(case_id: str, resolution: str = "") -> None:
    try:
        _cases().update_one(
            {"_id": case_id},
            {"$set": {
                "status":     "closed",
                "resolution": resolution,
                "closed_at":  _utc_now(),
                "updated_at": _utc_now(),
            }},
        )
    except Exception as exc:
        logger.error("close_case error: %s", exc)


def delete_case(case_id: str) -> bool:
    """Delete a case and all its associated events and annotations."""
    try:
        _case_events().delete_many({"case_id": case_id})
        _annotations().delete_many({"case_id": case_id})
        result = _cases().delete_one({"_id": case_id})
        return True
    except Exception as exc:
        logger.error("delete_case error: %s", exc)
        return False


# ── Case Events ───────────────────────────────────────────────────────────────

def add_case_event(case_id: str, event_id: str, relevance_note: str = "") -> None:
    """Link an event to a case. Idempotent."""
    link_id = f"{case_id}__{event_id}"
    try:
        existing = _case_events().find_one({"_id": link_id})
        if not existing:
            _case_events().insert_one({
                "_id":          link_id,
                "case_id":      case_id,
                "event_id":     event_id,
                "relevance_note": relevance_note,
                "added_at":     _utc_now(),
            })
            _cases().update_one(
                {"_id": case_id},
                {"$inc": {"event_count": 1}, "$set": {"updated_at": _utc_now()}},
            )
    except Exception as exc:
        logger.error("add_case_event error: %s", exc)


def remove_case_event(case_id: str, event_id: str) -> None:
    link_id = f"{case_id}__{event_id}"
    try:
        _case_events().delete_one({"_id": link_id})
        _cases().update_one(
            {"_id": case_id},
            {"$inc": {"event_count": -1}, "$set": {"updated_at": _utc_now()}},
        )
    except Exception as exc:
        logger.error("remove_case_event error: %s", exc)


def get_case_events(case_id: str, limit: int = 100) -> list[dict]:
    """Return full event documents for a case."""
    from astra_client import events as ev_coll
    import json

    try:
        links = list(_case_events().find({"case_id": case_id}, limit=limit))
        if not links:
            return []

        event_ids = [lnk["event_id"] for lnk in links]
        events: list[dict] = []
        for eid in event_ids:
            doc = ev_coll().find_one(
                {"_id": eid},
                projection={"$vector": 0, "raw_llm_output": 0},
            )
            if doc:
                for field in ("locations", "organizations", "people", "keywords"):
                    val = doc.get(field, [])
                    if isinstance(val, str):
                        try: doc[field] = json.loads(val)
                        except: doc[field] = []
                events.append(doc)

        return events
    except Exception as exc:
        logger.error("get_case_events error: %s", exc)
        return []


# ── Annotations ───────────────────────────────────────────────────────────────

def add_annotation(
    case_id: str,
    text: str,
    annotation_type: str = "note",
    event_id: str | None = None,
    analyst: str = "analyst",
    tags: list[str] | None = None,
) -> str:
    """
    Add an analyst annotation to a case.
    annotation_type: 'note' | 'hypothesis' | 'finding' | 'question' | 'action'
    Returns annotation _id.
    """
    ann_id = str(uuid.uuid4())
    try:
        _annotations().insert_one({
            "_id":             ann_id,
            "case_id":         case_id,
            "text":            text,
            "annotation_type": annotation_type,
            "event_id":        event_id,
            "analyst":         analyst,
            "tags":            tags or [],
            "created_at":      _utc_now(),
            "updated_at":      _utc_now(),
        })
        _cases().update_one(
            {"_id": case_id},
            {"$set": {"updated_at": _utc_now()}},
        )
    except Exception as exc:
        logger.error("add_annotation error: %s", exc)
    return ann_id


def get_annotations(
    case_id: str,
    annotation_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    filt: dict = {"case_id": case_id}
    if annotation_type:
        filt["annotation_type"] = annotation_type

    try:
        return list(_annotations().find(filt, sort={"created_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("get_annotations error: %s", exc)
        return []


def delete_annotation(annotation_id: str) -> bool:
    try:
        _annotations().delete_one({"_id": annotation_id})
        return True
    except Exception as exc:
        logger.error("delete_annotation error: %s", exc)
        return False


# ── Case Risk Scoring ─────────────────────────────────────────────────────────

def compute_case_risk(case_id: str) -> dict:
    """
    Compute and persist a risk score for a case based on:
    - Severity distribution of linked events
    - Recency of high-severity events
    - Number of unique entities involved
    Returns {risk_score, risk_label, breakdown}.
    """
    events = get_case_events(case_id)
    if not events:
        return {"risk_score": 0.0, "risk_label": "unknown", "breakdown": {}}

    severity_weights = {"high": 1.0, "medium": 0.5, "low": 0.2}
    sev_counts = {"high": 0, "medium": 0, "low": 0}
    entity_set: set[str] = set()

    for ev in events:
        sev = ev.get("severity", "low")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

        for field in ("organizations", "people"):
            val = ev.get(field) or []
            entity_set.update(str(v) for v in val)

    total = len(events)
    sev_score = sum(
        sev_counts.get(s, 0) / total * w
        for s, w in severity_weights.items()
    )

    entity_factor = min(len(entity_set) / 10.0, 1.0)
    risk_score = round(sev_score * 0.7 + entity_factor * 0.3, 3)

    if risk_score >= 0.75:
        label = "critical"
    elif risk_score >= 0.5:
        label = "high"
    elif risk_score >= 0.3:
        label = "medium"
    else:
        label = "low"

    result = {
        "risk_score":    risk_score,
        "risk_label":    label,
        "breakdown": {
            "severity_distribution": sev_counts,
            "unique_entities":       len(entity_set),
            "total_events":          total,
        },
    }

    try:
        _cases().update_one(
            {"_id": case_id},
            {"$set": {"risk_score": risk_score, "risk_label": label, "updated_at": _utc_now()}},
        )
    except Exception as exc:
        logger.warning("compute_case_risk persist error: %s", exc)

    return result


# ── Case Export ───────────────────────────────────────────────────────────────

def export_case(case_id: str) -> dict:
    """
    Export a full case including metadata, events, and annotations.
    Used for analyst report generation.
    """
    case = get_case(case_id)
    if not case:
        return {}

    events      = get_case_events(case_id, limit=200)
    annotations = get_annotations(case_id, limit=100)
    risk        = compute_case_risk(case_id)

    return {
        "case":        case,
        "events":      events,
        "annotations": annotations,
        "risk":        risk,
        "exported_at": _utc_now(),
    }
