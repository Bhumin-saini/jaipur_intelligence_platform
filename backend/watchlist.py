"""
Garuda v3 — Watchlist & Alerting System (watchlist.py)

Monitors specific topics, entities, or locations continuously.
Generates alerts when new matching events appear.

Public API:
  create_watchlist_item()   → str
  update_watchlist_item()   → None
  delete_watchlist_item()   → None
  list_watchlist()          → list[dict]
  get_watchlist_item()      → dict | None
  check_watchlist()         → list[dict]   ← scheduled job
  get_alerts()              → list[dict]
  mark_alert_read()         → None
  clear_alerts()            → None
  get_unread_alert_count()  → int
"""

from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_ago(n: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=n)).isoformat()


def _watchlist():
    from astra_client import watchlist as _wl
    return _wl()


def _alerts():
    from astra_client import watchlist_alerts as _wa
    return _wa()


# ── Watchlist CRUD ────────────────────────────────────────────────────────────

def create_watchlist_item(
    name: str,
    watch_type: str = "keyword",
    keywords: list[str] | None = None,
    entity_ids: list[str] | None = None,
    locations: list[str] | None = None,
    event_types: list[str] | None = None,
    min_severity: str = "medium",
    description: str = "",
    analyst: str = "analyst",
) -> str:
    """
    Create a watchlist monitor item.
    watch_type: 'keyword' | 'entity' | 'location' | 'topic' | 'composite'
    min_severity: 'low' | 'medium' | 'high'
    Returns watchlist item _id.
    """
    item_id = str(uuid.uuid4())
    _watchlist().insert_one({
        "_id":          item_id,
        "name":         name,
        "description":  description,
        "watch_type":   watch_type,
        "keywords":     keywords or [],
        "entity_ids":   entity_ids or [],
        "locations":    locations or [],
        "event_types":  event_types or [],
        "min_severity": min_severity,
        "analyst":      analyst,
        "active":       True,
        "alert_count":  0,
        "last_checked": None,
        "last_alert":   None,
        "created_at":   _utc_now(),
        "updated_at":   _utc_now(),
    })
    logger.info("Watchlist item created: %s — %s", item_id, name)
    return item_id


def update_watchlist_item(
    item_id: str,
    **kwargs,
) -> None:
    """Update mutable fields: name, keywords, entity_ids, locations,
    event_types, min_severity, active, description."""
    allowed = {"name", "keywords", "entity_ids", "locations",
               "event_types", "min_severity", "active", "description"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    updates["updated_at"] = _utc_now()
    try:
        _watchlist().update_one({"_id": item_id}, {"$set": updates})
    except Exception as exc:
        logger.error("update_watchlist_item error: %s", exc)


def delete_watchlist_item(item_id: str) -> bool:
    try:
        _watchlist().delete_one({"_id": item_id})
        _alerts().delete_many({"watchlist_id": item_id})
        return True
    except Exception as exc:
        logger.error("delete_watchlist_item error: %s", exc)
        return False


def list_watchlist(active_only: bool = True, limit: int = 50) -> list[dict]:
    filt: dict = {}
    if active_only:
        filt["active"] = True
    try:
        return list(_watchlist().find(filt, sort={"updated_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("list_watchlist error: %s", exc)
        return []


def get_watchlist_item(item_id: str) -> dict | None:
    try:
        return _watchlist().find_one({"_id": item_id})
    except Exception as exc:
        logger.error("get_watchlist_item error: %s", exc)
        return None


# ── Alert Generation ──────────────────────────────────────────────────────────

def _event_matches_item(event: dict, item: dict) -> tuple[bool, str]:
    """
    Check if an event matches a watchlist item.
    Returns (matched: bool, reason: str).
    """
    # Severity filter
    sev_order = {"low": 0, "medium": 1, "high": 2}
    event_sev   = sev_order.get(event.get("severity", "low"), 0)
    min_sev     = sev_order.get(item.get("min_severity", "medium"), 1)
    if event_sev < min_sev:
        return False, ""

    # Event type filter
    event_types = item.get("event_types") or []
    if event_types and event.get("event_type") not in event_types:
        return False, ""

    # Collect all text for keyword matching
    text_fields: list[str] = [
        event.get("summary", ""),
        event.get("event_type", ""),
    ]
    for field in ("locations", "organizations", "people", "keywords"):
        val = event.get(field) or []
        if isinstance(val, str):
            try: val = json.loads(val)
            except: val = []
        text_fields.extend(str(v) for v in val)

    combined_text = " ".join(text_fields).lower()

    # Keyword matching
    keywords = item.get("keywords") or []
    for kw in keywords:
        if kw.lower() in combined_text:
            return True, f"Keyword match: '{kw}'"

    # Location matching
    locations = item.get("locations") or []
    ev_locs = event.get("locations") or []
    if isinstance(ev_locs, str):
        try: ev_locs = json.loads(ev_locs)
        except: ev_locs = []
    for loc in locations:
        for ev_loc in ev_locs:
            if loc.lower() in str(ev_loc).lower() or str(ev_loc).lower() in loc.lower():
                return True, f"Location match: '{loc}'"

    # Entity ID matching (requires checking event_entities)
    entity_ids = item.get("entity_ids") or []
    if entity_ids:
        from astra_client import event_entities as ee_coll
        try:
            ev_entities = list(ee_coll().find(
                {"event_id": event.get("_id"), "entity_id": {"$in": entity_ids}},
                limit=5,
            ))
            if ev_entities:
                return True, f"Entity match: {len(ev_entities)} watched entities"
        except Exception:
            pass

    return False, ""


def check_watchlist(lookback_hours: float = 1.5) -> list[dict]:
    """
    Scan recent events against all active watchlist items.
    Called by scheduler every hour.
    Returns list of generated alert dicts.
    """
    from astra_client import events as ev_coll

    items = list_watchlist(active_only=True)
    if not items:
        return []

    since = _hours_ago(lookback_hours)
    try:
        events = list(ev_coll().find(
            {"created_at": {"$gte": since}},
            projection={
                "_id": 1, "summary": 1, "event_type": 1, "severity": 1,
                "locations": 1, "organizations": 1, "people": 1,
                "keywords": 1, "article_url": 1, "source": 1, "created_at": 1,
            },
            limit=500,
        ))
    except Exception as exc:
        logger.error("check_watchlist fetch error: %s", exc)
        return []

    generated_alerts: list[dict] = []

    for item in items:
        item_id = item["_id"]
        for event in events:
            matched, reason = _event_matches_item(event, item)
            if not matched:
                continue

            # Dedup: avoid duplicate alert for same event + watchlist
            alert_dedup_id = f"{item_id}__{event['_id']}"
            try:
                existing = _alerts().find_one({"_id": alert_dedup_id})
                if existing:
                    continue
            except Exception:
                pass

            alert_id = alert_dedup_id
            sev = event.get("severity", "low")
            alert_doc = {
                "_id":          alert_id,
                "watchlist_id": item_id,
                "watchlist_name": item.get("name", ""),
                "event_id":     event.get("_id"),
                "event_summary": event.get("summary", "")[:300],
                "event_type":   event.get("event_type", ""),
                "severity":     sev,
                "reason":       reason,
                "read":         False,
                "created_at":   _utc_now(),
            }
            try:
                _alerts().insert_one(alert_doc)
                _watchlist().update_one(
                    {"_id": item_id},
                    {"$inc": {"alert_count": 1},
                     "$set": {"last_alert": _utc_now(), "last_checked": _utc_now()}},
                )
                generated_alerts.append(alert_doc)
                logger.info(
                    "Alert generated: watchlist=%s event=%s reason=%s",
                    item.get("name"), event.get("_id"), reason,
                )
            except Exception as exc:
                logger.error("Alert insert error: %s", exc)

    # Update last_checked for items that had no alerts
    for item in items:
        try:
            _watchlist().update_one(
                {"_id": item["_id"]},
                {"$set": {"last_checked": _utc_now()}},
            )
        except Exception:
            pass

    return generated_alerts


# ── Alert Retrieval ───────────────────────────────────────────────────────────

def get_alerts(
    watchlist_id: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    filt: dict = {}
    if watchlist_id:  filt["watchlist_id"] = watchlist_id
    if unread_only:   filt["read"] = False
    try:
        return list(_alerts().find(filt, sort={"created_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("get_alerts error: %s", exc)
        return []


def get_unread_alert_count() -> int:
    try:
        return _alerts().count_documents({"read": False})
    except Exception as exc:
        logger.error("get_unread_alert_count error: %s", exc)
        return 0


def mark_alert_read(alert_id: str) -> None:
    try:
        _alerts().update_one({"_id": alert_id}, {"$set": {"read": True}})
    except Exception as exc:
        logger.error("mark_alert_read error: %s", exc)


def mark_all_alerts_read() -> None:
    try:
        # AstraDB doesn't support update_many with {}, use find + update
        unread = list(_alerts().find({"read": False}, projection={"_id": 1}, limit=500))
        for doc in unread:
            _alerts().update_one({"_id": doc["_id"]}, {"$set": {"read": True}})
    except Exception as exc:
        logger.error("mark_all_alerts_read error: %s", exc)


def clear_alerts(watchlist_id: str | None = None, older_than_days: int = 7) -> int:
    """Delete old alerts. Returns count deleted."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    filt: dict = {"created_at": {"$lt": cutoff}}
    if watchlist_id:
        filt["watchlist_id"] = watchlist_id
    try:
        old_alerts = list(_alerts().find(filt, projection={"_id": 1}, limit=1000))
        count = len(old_alerts)
        for doc in old_alerts:
            _alerts().delete_one({"_id": doc["_id"]})
        return count
    except Exception as exc:
        logger.error("clear_alerts error: %s", exc)
        return 0
