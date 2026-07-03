"""
Garuda v3 — Insight Engine (insights.py)

The missing layer between raw events and actionable intelligence.

Generates 6 types of insights from event patterns:
  1. PATTERN      — recurring actor/location/type combinations
  2. ESCALATION   — events forming a causal or temporal chain
  3. ACTOR        — entity behavior summaries and changes
  4. LOCATION     — area risk profiles and hotspots
  5. THREAD       — ongoing multi-event situations
  6. CONTRADICTION— conflicting reports about same subject

Each insight has:
  - title, body, insight_type, confidence (0-1), evidence_count,
    entity_ids[], location, tags[], severity_signal, created_at

Public API:
  generate_all_insights()   → list[dict]  (main scheduled job)
  get_insights()            → list[dict]
  get_insight()             → dict | None
  run_insight_pipeline()    → int          (count generated)
"""

from __future__ import annotations
import json
import logging
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS  = ["gemini-2.0-flash", "gemini-1.5-flash-latest"]
GEMINI_BASE    = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _parse_list(val) -> list:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return []


def _call_gemini(prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> str | None:
    if not GEMINI_API_KEY:
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    for model in GEMINI_MODELS:
        url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)
        try:
            resp = httpx.post(url, json=payload, timeout=45)
            resp.raise_for_status()
            parts = resp.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:
            logger.warning("Gemini %s failed: %s", model, exc)
    return None


# ── AstraDB insight collection ────────────────────────────────────────────────

def _insights_coll():
    from astra_client import get_db
    return get_db().get_collection("insights")


def _events_coll():
    from astra_client import events
    return events()


# ── Store / Retrieve ──────────────────────────────────────────────────────────

def store_insight(
    insight_type: str,
    title: str,
    body: str,
    confidence: float,
    evidence_count: int,
    entity_refs: list[str] | None = None,
    location: str | None = None,
    tags: list[str] | None = None,
    severity_signal: str = "medium",
    metadata: dict | None = None,
    dedupe_key: str | None = None,
) -> str | None:
    """
    Store an insight. Uses dedupe_key to avoid re-inserting within 6 hours.
    Returns _id or None if deduplicated.
    """
    if dedupe_key:
        try:
            existing = _insights_coll().find_one({"dedupe_key": dedupe_key})
            if existing:
                # Refresh timestamp but don't duplicate
                _insights_coll().update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"updated_at": _utc_now()}},
                )
                return None
        except Exception:
            pass

    doc_id = str(uuid.uuid4())
    try:
        _insights_coll().insert_one({
            "_id":            doc_id,
            "insight_type":   insight_type,
            "title":          title,
            "body":           body,
            "confidence":     round(confidence, 3),
            "evidence_count": evidence_count,
            "entity_refs":    entity_refs or [],
            "location":       location,
            "tags":           tags or [],
            "severity_signal": severity_signal,
            "metadata":       metadata or {},
            "dedupe_key":     dedupe_key,
            "read":           False,
            "created_at":     _utc_now(),
            "updated_at":     _utc_now(),
        })
        logger.info("Insight stored: [%s] %s", insight_type, title[:70])
    except Exception as exc:
        logger.error("store_insight error: %s", exc)
        return None
    return doc_id


def get_insights(
    insight_type: str | None = None,
    limit: int = 50,
    unread_only: bool = False,
    min_confidence: float = 0.0,
    days: int = 30,
) -> list[dict]:
    filt: dict = {"created_at": {"$gte": _days_ago(days)}}
    if insight_type:  filt["insight_type"] = insight_type
    if unread_only:   filt["read"] = False
    if min_confidence > 0:
        filt["confidence"] = {"$gte": min_confidence}
    try:
        return list(_insights_coll().find(filt, sort={"created_at": -1}, limit=limit))
    except Exception as exc:
        logger.error("get_insights error: %s", exc)
        return []


def get_insight(insight_id: str) -> dict | None:
    try:
        return _insights_coll().find_one({"_id": insight_id})
    except Exception as exc:
        logger.error("get_insight error: %s", exc)
        return None


def mark_insight_read(insight_id: str) -> None:
    try:
        _insights_coll().update_one({"_id": insight_id}, {"$set": {"read": True}})
    except Exception:
        pass


def get_unread_insight_count() -> int:
    try:
        return _insights_coll().count_documents({"read": False})
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# INSIGHT GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Pattern Insights ───────────────────────────────────────────────────────

def _generate_pattern_insights(events: list[dict], days: int = 7) -> int:
    """
    Detect recurring (actor, location, event_type) combinations.
    Generates an insight when 3+ events share the same actor + location,
    or 4+ events share the same event_type + location.
    """
    generated = 0
    cutoff = _days_ago(days)

    # Filter to time window
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]
    if not recent:
        return 0

    # Build actor×location matrix
    actor_loc: dict[tuple, list] = defaultdict(list)
    type_loc:  dict[tuple, list] = defaultdict(list)

    for ev in recent:
        locs = _parse_list(ev.get("locations", []))
        orgs = _parse_list(ev.get("organizations", []))
        ppl  = _parse_list(ev.get("people", []))
        etype = ev.get("event_type", "other")
        sev   = ev.get("severity", "low")

        primary_loc = locs[0] if locs else "Jaipur"

        for actor in (orgs + ppl)[:5]:
            actor_loc[(str(actor).strip(), primary_loc)].append(ev)

        type_loc[(etype, primary_loc)].append(ev)

    # Actor + location patterns (3+ events)
    for (actor, loc), evs in actor_loc.items():
        if len(evs) < 3:
            continue
        dedupe_key = f"pattern_actor_{actor}_{loc}_{days}d"
        sevs = [e.get("severity", "low") for e in evs]
        sig_sev = "high" if "high" in sevs else "medium" if "medium" in sevs else "low"
        types = Counter(e.get("event_type", "other") for e in evs)
        top_type = types.most_common(1)[0][0]

        summaries = [e.get("summary", "")[:150] for e in evs[:5]]
        prompt = f"""You are a Jaipur intelligence analyst.
The entity "{actor}" appears in {len(evs)} events in "{loc}" over the last {days} days.
Primary event type: {top_type}. Severity pattern: {dict(Counter(sevs))}.

Event summaries:
{chr(10).join(f"- {s}" for s in summaries)}

Write a 2-3 sentence intelligence insight explaining:
1. What pattern this represents
2. Why it matters for {loc}
3. What to watch for next

Be specific. Avoid generic phrases. No bullet points."""

        body = _call_gemini(prompt, max_tokens=300)
        if not body:
            body = (
                f"{actor} is involved in {len(evs)} {top_type} events in {loc} "
                f"over the past {days} days, suggesting a recurring pattern of activity."
            )

        store_insight(
            insight_type="pattern",
            title=f"{actor} pattern in {loc}: {len(evs)} events in {days} days",
            body=body,
            confidence=min(0.5 + len(evs) * 0.08, 0.92),
            evidence_count=len(evs),
            entity_refs=[actor],
            location=loc,
            tags=["pattern", actor, loc, top_type],
            severity_signal=sig_sev,
            metadata={"actor": actor, "location": loc, "event_type": top_type, "count": len(evs)},
            dedupe_key=dedupe_key,
        )
        generated += 1

    # Type + location spikes (4+ events same type+location)
    for (etype, loc), evs in type_loc.items():
        if len(evs) < 4 or etype == "other":
            continue
        dedupe_key = f"pattern_type_{etype}_{loc}_{days}d"
        sevs = [e.get("severity", "low") for e in evs]
        sig_sev = "high" if "high" in sevs else "medium"

        store_insight(
            insight_type="pattern",
            title=f"Concentration of {etype} events in {loc} ({len(evs)} in {days}d)",
            body=(
                f"{len(evs)} {etype} events have been recorded in {loc} over the past {days} days. "
                f"Severity breakdown: {dict(Counter(sevs))}. "
                f"This concentration suggests a systemic issue rather than isolated incidents."
            ),
            confidence=min(0.45 + len(evs) * 0.07, 0.88),
            evidence_count=len(evs),
            location=loc,
            tags=["pattern", "concentration", etype, loc],
            severity_signal=sig_sev,
            metadata={"event_type": etype, "location": loc, "count": len(evs)},
            dedupe_key=dedupe_key,
        )
        generated += 1

    return generated


# ── 2. Escalation Insights ────────────────────────────────────────────────────

ESCALATION_CHAINS = [
    ("accident", "infrastructure", "politics"),
    ("accident", "politics"),
    ("infrastructure", "politics"),
    ("crime", "politics"),
    ("weather", "accident"),
    ("weather", "infrastructure"),
    ("infrastructure", "crime"),
]


def _generate_escalation_insights(events: list[dict], days: int = 14) -> int:
    """
    Detect when one event type precedes another in same location,
    suggesting a causal chain (accident → protest → politics).
    """
    generated = 0
    cutoff = _days_ago(days)
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]
    if not recent:
        return 0

    # Group by primary location
    loc_events: dict[str, list] = defaultdict(list)
    for ev in recent:
        locs = _parse_list(ev.get("locations", []))
        loc  = locs[0] if locs else "Jaipur"
        loc_events[loc].append(ev)

    for loc, evs in loc_events.items():
        if len(evs) < 3:
            continue

        # Sort by created_at
        evs_sorted = sorted(evs, key=lambda x: x.get("created_at") or "")
        type_seq = [e.get("event_type", "other") for e in evs_sorted]

        for chain in ESCALATION_CHAINS:
            # Check if chain types appear in sequence (not necessarily consecutive)
            positions = []
            for chain_type in chain:
                for i, t in enumerate(type_seq):
                    if t == chain_type and (not positions or i > positions[-1]):
                        positions.append(i)
                        break

            if len(positions) < len(chain):
                continue

            chain_events = [evs_sorted[p] for p in positions]
            dedupe_key = f"escalation_{'_'.join(chain)}_{loc}_{days}d"

            summaries = [
                f"[{e.get('event_type')}] {e.get('summary', '')[:120]}"
                for e in chain_events
            ]
            prompt = f"""You are a Jaipur intelligence analyst.
In {loc}, the following event sequence was detected over {days} days:

{chr(10).join(f"{i+1}. {s}" for i, s in enumerate(summaries))}

Write a 2-3 sentence intelligence insight explaining:
1. How these events are causally connected
2. What this escalation pattern means for {loc}
3. What intervention or development to watch for

Be specific and analytical. No generic phrases."""

            body = _call_gemini(prompt, max_tokens=300)
            if not body:
                body = (
                    f"In {loc}, a {' → '.join(chain)} sequence has been detected over {days} days. "
                    f"This escalation pattern suggests events are causally linked and the situation may continue to develop."
                )

            sevs = [e.get("severity", "low") for e in chain_events]
            sig_sev = "high" if "high" in sevs else "medium"

            store_insight(
                insight_type="escalation",
                title=f"Escalation in {loc}: {' → '.join(chain)}",
                body=body,
                confidence=0.65,
                evidence_count=len(chain_events),
                location=loc,
                tags=["escalation"] + list(chain) + [loc],
                severity_signal=sig_sev,
                metadata={"chain": list(chain), "location": loc},
                dedupe_key=dedupe_key,
            )
            generated += 1

    return generated


# ── 3. Actor Behavior Insights ────────────────────────────────────────────────

def _generate_actor_insights(events: list[dict], days: int = 14) -> int:
    """
    Track entities appearing across many events and summarize their behavior pattern.
    Generates insights for entities with 5+ events showing a clear role pattern.
    """
    generated = 0
    cutoff = _days_ago(days)
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]

    # Build entity → events map
    entity_events: dict[str, list] = defaultdict(list)
    entity_roles:  dict[str, list] = defaultdict(list)

    for ev in recent:
        actor_roles = ev.get("actor_roles") or {}
        if isinstance(actor_roles, str):
            try: actor_roles = json.loads(actor_roles)
            except: actor_roles = {}

        orgs = _parse_list(ev.get("organizations", []))
        ppl  = _parse_list(ev.get("people", []))

        for actor in (orgs + ppl)[:6]:
            actor = str(actor).strip()
            entity_events[actor].append(ev)
            role = actor_roles.get(actor, "")
            if role:
                entity_roles[actor].append(role)

    for actor, evs in entity_events.items():
        if len(evs) < 5 or len(actor) < 3:
            continue

        dedupe_key = f"actor_{actor}_{days}d"
        types  = Counter(e.get("event_type", "other") for e in evs)
        sevs   = Counter(e.get("severity", "low") for e in evs)
        roles  = entity_roles.get(actor, [])
        locs   = [_parse_list(e.get("locations", []))[0] for e in evs if _parse_list(e.get("locations", []))]
        top_locs = [loc for loc, _ in Counter(locs).most_common(3)]

        sig_sev = "high" if sevs.get("high", 0) >= 2 else "medium" if sevs.get("medium", 0) >= 2 else "low"
        summaries = [e.get("summary", "")[:120] for e in evs[:6]]

        prompt = f"""You are a Jaipur intelligence analyst.
The entity "{actor}" appears in {len(evs)} events over {days} days.
Event types: {dict(types.most_common(3))}.
Severity: {dict(sevs)}.
Locations: {top_locs}.
Known roles: {roles[:5]}.

Sample events:
{chr(10).join(f"- {s}" for s in summaries)}

Write a 2-3 sentence intelligence profile of this entity's activity:
1. What are they doing and where?
2. Is the pattern concerning, routine, or noteworthy?
3. What is their significance for Jaipur?

Be specific. No generic phrases."""

        body = _call_gemini(prompt, max_tokens=300)
        if not body:
            body = (
                f"{actor} is active in {len(evs)} events over {days} days, "
                f"primarily {types.most_common(1)[0][0]} events. "
                f"Active locations: {', '.join(top_locs[:2])}."
            )

        store_insight(
            insight_type="actor",
            title=f"Actor profile: {actor} ({len(evs)} events in {days}d)",
            body=body,
            confidence=min(0.4 + len(evs) * 0.06, 0.88),
            evidence_count=len(evs),
            entity_refs=[actor],
            location=top_locs[0] if top_locs else None,
            tags=["actor", actor] + [t for t, _ in types.most_common(2)],
            severity_signal=sig_sev,
            metadata={"actor": actor, "event_types": dict(types), "severity": dict(sevs), "locations": top_locs},
            dedupe_key=dedupe_key,
        )
        generated += 1

    return generated


# ── 4. Location Risk Insights ─────────────────────────────────────────────────

def _generate_location_insights(events: list[dict], days: int = 7) -> int:
    """
    Score each location by weighted event count (high=3, medium=1.5, low=1)
    and generate an insight for the top-risk locations.
    """
    generated = 0
    cutoff = _days_ago(days)
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]

    SEV_W = {"high": 3.0, "medium": 1.5, "low": 1.0}
    loc_data: dict[str, dict] = defaultdict(
        lambda: {"weight": 0.0, "events": [], "types": Counter(), "sevs": Counter()}
    )

    for ev in recent:
        locs = _parse_list(ev.get("locations", []))
        sev  = ev.get("severity", "low")
        etype = ev.get("event_type", "other")
        w    = SEV_W.get(sev, 1.0)
        primary = locs[0] if locs else None
        if not primary:
            continue
        loc_data[primary]["weight"]   += w
        loc_data[primary]["events"].append(ev)
        loc_data[primary]["types"][etype] += 1
        loc_data[primary]["sevs"][sev]    += 1

    # Top 5 locations by weighted score
    top_locs = sorted(loc_data.items(), key=lambda x: x[1]["weight"], reverse=True)[:5]

    for loc, data in top_locs:
        evs = data["events"]
        if len(evs) < 3:
            continue

        dedupe_key = f"location_{loc}_{days}d"
        score      = round(data["weight"], 1)
        top_types  = [t for t, _ in data["types"].most_common(2)]
        sevs       = data["sevs"]
        sig_sev    = "high" if sevs.get("high", 0) >= 1 else "medium"

        body = (
            f"{loc} has a risk score of {score:.1f} over the past {days} days "
            f"({len(evs)} events: {sevs.get('high', 0)} high, {sevs.get('medium', 0)} medium, "
            f"{sevs.get('low', 0)} low severity). "
            f"Primary event types: {', '.join(top_types)}. "
            f"This area requires elevated monitoring."
        )

        store_insight(
            insight_type="location",
            title=f"Location risk: {loc} — score {score:.0f} ({len(evs)} events)",
            body=body,
            confidence=0.75,
            evidence_count=len(evs),
            location=loc,
            tags=["location", "risk", loc] + top_types,
            severity_signal=sig_sev,
            metadata={"location": loc, "score": score, "count": len(evs),
                      "event_types": dict(data["types"]), "severity": dict(sevs)},
            dedupe_key=dedupe_key,
        )
        generated += 1

    return generated


# ── 5. Thread Insights (ongoing situations) ───────────────────────────────────

THREAD_KEYWORDS: list[tuple[str, str]] = [
    ("metro", "Jaipur Metro Project"),
    ("jda", "JDA Development Activity"),
    ("water", "Water Supply Crisis"),
    ("flood", "Flooding Situation"),
    ("protest", "Public Protests"),
    ("election", "Electoral Activity"),
    ("mining", "Mining Activity"),
    ("traffic", "Traffic Disruptions"),
    ("power", "Power Supply Issues"),
    ("road", "Road Infrastructure"),
    ("crime", "Crime Wave"),
    ("fire", "Fire Incidents"),
]


def _generate_thread_insights(events: list[dict], days: int = 14) -> int:
    """
    Track ongoing narrative threads by keyword clustering.
    Generates a thread insight when 4+ events share a common theme keyword.
    """
    generated = 0
    cutoff = _days_ago(days)
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]

    for keyword, thread_name in THREAD_KEYWORDS:
        matching = [
            e for e in recent
            if keyword.lower() in (e.get("summary") or "").lower()
            or any(keyword.lower() in str(k).lower() for k in _parse_list(e.get("keywords", [])))
        ]
        if len(matching) < 4:
            continue

        dedupe_key = f"thread_{keyword}_{days}d"
        sevs  = Counter(e.get("severity", "low") for e in matching)
        types = Counter(e.get("event_type", "other") for e in matching)
        locs  = [_parse_list(e.get("locations", []))[0]
                 for e in matching if _parse_list(e.get("locations", []))]
        top_locs = [l for l, _ in Counter(locs).most_common(2)]

        # Check if status is developing or resolved
        statuses = Counter(e.get("event_status", "unclear") for e in matching)
        is_ongoing = statuses.get("ongoing", 0) + statuses.get("developing", 0) >= len(matching) * 0.3

        sig_sev = "high" if sevs.get("high", 0) >= 2 else "medium"

        summaries = [e.get("summary", "")[:120] for e in sorted(
            matching, key=lambda x: x.get("created_at") or ""
        )[:6]]

        prompt = f"""You are a Jaipur intelligence analyst tracking the "{thread_name}" situation.
{len(matching)} events in {days} days are related to this thread.
Severity: {dict(sevs)}. Locations: {top_locs}. Ongoing: {is_ongoing}.

Key events (chronological):
{chr(10).join(f"- {s}" for s in summaries)}

Write a 3-4 sentence intelligence thread update:
1. What is the current state of this situation?
2. How has it evolved over the past {days} days?
3. What are the key actors/locations involved?
4. What outcome or escalation is most likely?

Be specific, analytical, and grounded in the events listed."""

        body = _call_gemini(prompt, max_tokens=400)
        if not body:
            body = (
                f"The {thread_name} thread shows {len(matching)} related events over {days} days. "
                f"{'Situation appears ongoing.' if is_ongoing else 'Status unclear.'} "
                f"Primary locations: {', '.join(top_locs[:2]) if top_locs else 'Jaipur'}."
            )

        store_insight(
            insight_type="thread",
            title=f"Ongoing thread: {thread_name} ({len(matching)} events)",
            body=body,
            confidence=min(0.5 + len(matching) * 0.05, 0.90),
            evidence_count=len(matching),
            location=top_locs[0] if top_locs else None,
            tags=["thread", keyword, thread_name] + top_locs[:2],
            severity_signal=sig_sev,
            metadata={"thread": thread_name, "keyword": keyword, "count": len(matching),
                      "ongoing": is_ongoing, "locations": top_locs},
            dedupe_key=dedupe_key,
        )
        generated += 1

    return generated


# ── 6. Contradiction Insights ─────────────────────────────────────────────────

def _generate_contradiction_insights(events: list[dict]) -> int:
    """
    Detect events with contradictory status or severity about the same subject.
    Uses keyword overlap between summaries from different sources.
    """
    generated = 0
    cutoff = _days_ago(3)  # Only last 3 days for contradictions
    recent = [e for e in events if (e.get("created_at") or "") >= cutoff]

    # Group by primary location + event_type
    group: dict[tuple, list] = defaultdict(list)
    for ev in recent:
        locs  = _parse_list(ev.get("locations", []))
        loc   = locs[0] if locs else None
        etype = ev.get("event_type", "other")
        if loc:
            group[(loc, etype)].append(ev)

    for (loc, etype), evs in group.items():
        if len(evs) < 2:
            continue

        # Check for status contradictions (resolved vs ongoing) or severity gaps
        statuses = [e.get("event_status", "unclear") for e in evs]
        sevs     = [e.get("severity", "low") for e in evs]
        sources  = [e.get("source", "") for e in evs]

        has_conflict = (
            ("resolved" in statuses and "ongoing" in statuses) or
            ("high" in sevs and "low" in sevs and len(set(sources)) >= 2)
        )

        if not has_conflict:
            continue

        dedupe_key = f"contradiction_{loc}_{etype}"
        summaries  = [f"[{e.get('source', '?')} / {e.get('severity')}] {e.get('summary', '')[:120]}"
                      for e in evs[:4]]

        body = (
            f"Conflicting reports detected about {etype} events in {loc}. "
            f"Sources disagree on status or severity: "
            + " vs ".join(f"{e.get('source', '?')} ({e.get('severity')})" for e in evs[:3])
            + ". Verify through additional sources before acting on either report."
        )

        store_insight(
            insight_type="contradiction",
            title=f"Conflicting reports: {etype} in {loc}",
            body=body,
            confidence=0.55,
            evidence_count=len(evs),
            location=loc,
            tags=["contradiction", loc, etype],
            severity_signal="medium",
            metadata={"location": loc, "event_type": etype, "sources": sources},
            dedupe_key=dedupe_key,
        )
        generated += 1

    return generated


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def generate_all_insights(days: int = 14) -> int:
    """
    Main insight generation job. Runs all 6 generators.
    Called by APScheduler every 4 hours.
    Returns total insights generated.
    """
    logger.info("Insight pipeline starting — lookback=%dd", days)

    # Fetch events once and reuse
    cutoff = _days_ago(days)
    try:
        events = list(_events_coll().find(
            {"created_at": {"$gte": cutoff}},
            projection={
                "_id": 1, "event_type": 1, "summary": 1, "severity": 1,
                "event_status": 1, "locations": 1, "organizations": 1,
                "people": 1, "actor_roles": 1, "causal_factors": 1,
                "keywords": 1, "source": 1, "created_at": 1,
            },
            limit=2000,
        ))
    except Exception as exc:
        logger.error("Insight pipeline: event fetch failed: %s", exc)
        return 0

    if not events:
        logger.info("No events to analyze")
        return 0

    logger.info("Analyzing %d events for insights", len(events))
    total = 0

    for generator, name, kwargs in [
        (_generate_pattern_insights,      "pattern",      {"days": 7}),
        (_generate_escalation_insights,   "escalation",   {"days": 14}),
        (_generate_actor_insights,        "actor",        {"days": 14}),
        (_generate_location_insights,     "location",     {"days": 7}),
        (_generate_thread_insights,       "thread",       {"days": 14}),
        (_generate_contradiction_insights,"contradiction", {}),
    ]:
        try:
            n = generator(events, **kwargs)
            logger.info("  %s: %d insights", name, n)
            total += n
        except Exception as exc:
            logger.error("  %s generator failed: %s", name, exc)

    logger.info("Insight pipeline complete — %d total generated", total)
    return total


def run_insight_pipeline() -> int:
    """Alias for scheduler."""
    return generate_all_insights(days=14)


# ── Insight stats ─────────────────────────────────────────────────────────────

def insight_stats() -> dict:
    try:
        docs = list(_insights_coll().find(
            {}, projection={"insight_type": 1, "confidence": 1, "read": 1}, limit=2000
        ))
        type_counts  = Counter(d.get("insight_type") for d in docs)
        unread_count = sum(1 for d in docs if not d.get("read"))
        avg_conf     = (sum(d.get("confidence", 0) for d in docs) / len(docs)) if docs else 0
        return {
            "total":         len(docs),
            "unread":        unread_count,
            "by_type":       dict(type_counts),
            "avg_confidence": round(avg_conf, 3),
        }
    except Exception as exc:
        logger.error("insight_stats error: %s", exc)
        return {"total": 0, "unread": 0, "by_type": {}, "avg_confidence": 0}
