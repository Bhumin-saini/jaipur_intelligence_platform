"""
Garuda v3 — Intelligence & Analysis Layer (analyst.py)

Key changes from v2:
  - Daily/weekly briefs now pre-process events through clustering + insight
    summaries before sending to Gemini — dramatically better output quality
  - Trend detection generates narrative explanations not just spike ratios
  - Anomaly detection adds contextual analysis of what makes the day anomalous
  - semantic_search() unchanged (already works well)
  - entity_network() unchanged
  - get_heatmap() unchanged
"""

import json
import logging
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS   = ["gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]
GEMINI_BASE     = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)
TREND_SPIKE_RATIO = float(os.environ.get("TREND_SPIKE_RATIO", "2.0"))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _iso(dt: datetime) -> str:
    return dt.isoformat()

def _days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)

def _hours_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=n)

def _parse_list(val) -> list:
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except: return []
    return []


def _call_gemini(prompt: str, max_tokens: int = 2048, temperature: float = 0.2) -> str | None:
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set")
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
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:
            logger.warning("Gemini %s failed: %s", model, exc)
    return None


# ── Semantic Search ────────────────────────────────────────────────────────────

def semantic_search(
    query: str,
    limit: int = 20,
    severity_filter: str | None = None,
    event_type_filter: str | None = None,
) -> list[dict]:
    from astra_client import events as ev_coll
    from embedder import embed_text

    if not query or not query.strip():
        return []
    try:
        vec  = embed_text(query.strip())
        filt: dict = {}
        if severity_filter:    filt["severity"]   = severity_filter
        if event_type_filter:  filt["event_type"] = event_type_filter

        results = list(ev_coll().find(
            filt,
            sort={"$vector": vec},
            limit=limit,
            include_similarity=True,
            projection={"raw_llm_output": 0, "body": 0, "$vector": 0},
        ))
        for r in results:
            for field in ("keywords", "locations", "organizations", "people", "related_topics"):
                r[field] = _parse_list(r.get(field, []))
        return results
    except Exception as exc:
        logger.error("semantic_search error: %s", exc)
        return []


# ── Trend Detection ────────────────────────────────────────────────────────────

def detect_trends(window_hours: int = 48, baseline_days: int = 7) -> list[dict]:
    """
    Detect frequency spikes with narrative context.
    Returns trend list and stores trend_alert briefs with explanations.
    """
    from astra_client import events as ev_coll

    now           = datetime.now(timezone.utc)
    window_start  = _iso(now - timedelta(hours=window_hours))
    baseline_start = _iso(now - timedelta(days=baseline_days))

    try:
        recent_docs = list(ev_coll().find(
            {"created_at": {"$gte": window_start}},
            projection={"event_type": 1, "locations": 1, "severity": 1,
                        "summary": 1, "organizations": 1, "people": 1},
            limit=2000,
        ))
        baseline_docs = list(ev_coll().find(
            {"created_at": {"$gte": baseline_start, "$lt": window_start}},
            projection={"event_type": 1, "locations": 1},
            limit=5000,
        ))
    except Exception as exc:
        logger.error("detect_trends fetch error: %s", exc)
        return []

    def _keys(docs):
        counter: Counter = Counter()
        for doc in docs:
            et   = doc.get("event_type") or "other"
            locs = _parse_list(doc.get("locations", []))
            locs = locs[:1] or ["_none"]
            for loc in locs:
                counter[(et, str(loc).strip())] += 1
        return counter

    recent_cnt   = _keys(recent_docs)
    baseline_cnt = _keys(baseline_docs)
    baseline_hours = baseline_days * 24 - window_hours
    scale = window_hours / max(baseline_hours, 1)

    trends = []
    for key, recent_n in recent_cnt.items():
        baseline_n = baseline_cnt.get(key, 0) * scale
        if baseline_n < 1:
            if recent_n < 3:
                continue
            ratio = float(recent_n)
        else:
            ratio = recent_n / baseline_n

        if ratio >= TREND_SPIKE_RATIO:
            event_type, location = key
            # Gather example summaries for context
            examples = [
                d.get("summary", "")[:120]
                for d in recent_docs
                if d.get("event_type") == event_type
                and location in str(_parse_list(d.get("locations", [])))
            ][:4]

            trends.append({
                "event_type":   event_type,
                "location":     location,
                "recent_count": recent_n,
                "baseline_avg": round(baseline_n, 2),
                "spike_ratio":  round(ratio, 2),
                "examples":     examples,
            })

    trends.sort(key=lambda x: x["spike_ratio"], reverse=True)

    # Store top trends with narrative context
    for t in trends[:8]:
        loc_label = t["location"] if t["location"] != "_none" else "Jaipur"
        examples_text = "\n".join(f"- {e}" for e in t["examples"])

        # Generate narrative explanation
        if t["examples"]:
            prompt = f"""You are a Jaipur intelligence analyst.
A spike of {t['spike_ratio']:.1f}x in '{t['event_type']}' events was detected in {loc_label}
({t['recent_count']} events in {window_hours}h vs baseline of {t['baseline_avg']} per window).

Recent examples:
{examples_text}

Write 2 sentences:
1. What this spike likely represents
2. What should be monitored next"""
            explanation = _call_gemini(prompt, max_tokens=150, temperature=0.2)
        else:
            explanation = None

        title = f"{t['event_type'].title()} spike in {loc_label} — {t['spike_ratio']}× above baseline"
        body  = (
            f"Detected a {t['spike_ratio']}× frequency spike in '{t['event_type']}' events "
            f"at {loc_label}.\nRecent {window_hours}h: {t['recent_count']} events. "
            f"Baseline avg: {t['baseline_avg']} events per equivalent window."
        )
        if explanation:
            body += f"\n\nAnalysis: {explanation}"

        store_brief(
            brief_type="trend_alert",
            title=title,
            body=body,
            metadata={
                "event_type":   t["event_type"],
                "location":     t["location"],
                "spike_ratio":  t["spike_ratio"],
                "recent_count": t["recent_count"],
                "window_hours": window_hours,
            },
        )

    return trends


# ── Anomaly Detection ──────────────────────────────────────────────────────────

def detect_anomalies(lookback_days: int = 30) -> list[dict]:
    """
    Flag anomalous days with contextual explanation of what drove the spike.
    """
    from astra_client import events as ev_coll
    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy not installed — anomaly detection skipped")
        return []

    start = _iso(_days_ago(lookback_days))
    try:
        docs = list(ev_coll().find(
            {"created_at": {"$gte": start}, "severity": "high"},
            projection={"created_at": 1, "event_type": 1, "summary": 1,
                        "locations": 1, "organizations": 1},
            limit=5000,
        ))
    except Exception as exc:
        logger.error("detect_anomalies fetch error: %s", exc)
        return []

    day_counts:  Counter = Counter()
    day_events:  dict[str, list] = defaultdict(list)
    for doc in docs:
        day = (doc.get("created_at") or "")[:10]
        if day:
            day_counts[day] += 1
            day_events[day].append(doc)

    if len(day_counts) < 3:
        return []

    days   = sorted(day_counts.keys())
    counts = np.array([day_counts[d] for d in days], dtype=float)
    mean   = counts.mean()
    std    = counts.std()

    if std == 0:
        return []

    threshold = mean + 2 * std
    anomalies = []

    for day, count in zip(days, counts):
        if count <= threshold:
            continue
        sigma  = (count - mean) / std
        evs    = day_events[day]
        types  = Counter(e.get("event_type") for e in evs)
        locs   = [_parse_list(e.get("locations", []))[0] for e in evs if _parse_list(e.get("locations", []))]
        top_locs = [l for l, _ in Counter(locs).most_common(3)]
        summaries = [e.get("summary", "")[:100] for e in evs[:5]]

        # Narrative explanation
        prompt = f"""You are a Jaipur intelligence analyst.
On {day}, {int(count)} high-severity events occurred ({sigma:.1f} standard deviations above normal).
Normal rate: {mean:.1f} events/day.
Event types on this day: {dict(types.most_common(3))}.
Locations: {top_locs}.
Sample summaries:
{chr(10).join(f"- {s}" for s in summaries)}

Write 2 sentences explaining:
1. What drove the anomaly on this day
2. Whether this is part of a broader pattern or an isolated spike"""
        explanation = _call_gemini(prompt, max_tokens=150, temperature=0.2)

        title = f"High-severity anomaly on {day} — {int(count)} events ({sigma:.1f}σ)"
        body  = (
            f"On {day}, {int(count)} high-severity events were detected "
            f"({sigma:.1f} standard deviations above the {lookback_days}-day mean of "
            f"{mean:.1f} events/day).\n\n"
            f"Event types: {dict(types.most_common(3))}\n"
            f"Locations: {', '.join(top_locs)}\n\n"
            f"Examples:\n" + "\n".join(f"• {e}" for e in summaries)
        )
        if explanation:
            body += f"\n\nAnalysis: {explanation}"

        anomalies.append({
            "date": day, "count": int(count),
            "mean": round(float(mean), 2), "sigma": round(float(sigma), 2),
            "top_types": dict(types.most_common(3)),
            "locations": top_locs,
        })

        store_brief(
            brief_type="anomaly",
            title=title,
            body=body,
            metadata={"date": day, "count": int(count), "sigma": round(float(sigma), 2)},
        )

    return anomalies


# ── Brief Storage & Retrieval ──────────────────────────────────────────────────

def store_brief(brief_type: str, title: str, body: str, metadata: dict | None = None) -> str:
    from astra_client import briefs as briefs_coll
    from embedder import embed_brief

    doc_id = str(uuid.uuid4())
    try:
        vec = embed_brief(body)
        briefs_coll().insert_one({
            "_id":          doc_id,
            "brief_type":   brief_type,
            "title":        title,
            "body":         body,
            "metadata":     metadata or {},
            "generated_at": _utc_now(),
            "$vector":      vec,
        })
    except Exception as exc:
        logger.error("store_brief error: %s", exc)
    return doc_id


def get_briefs(brief_type: str | None = None, limit: int = 20) -> list[dict]:
    from astra_client import briefs as briefs_coll
    filt: dict = {}
    if brief_type:
        filt["brief_type"] = brief_type
    try:
        return list(briefs_coll().find(filt, sort={"generated_at": -1}, limit=limit,
                                       projection={"$vector": 0}))
    except Exception as exc:
        logger.error("get_briefs error: %s", exc)
        return []


def get_brief(brief_id: str) -> dict | None:
    from astra_client import briefs as briefs_coll
    try:
        return briefs_coll().find_one({"_id": brief_id}, projection={"$vector": 0})
    except Exception as exc:
        logger.error("get_brief error: %s", exc)
        return None


# ── Daily Brief — insight-driven ──────────────────────────────────────────────

DAILY_BRIEF_PROMPT = """\
You are a senior intelligence analyst covering Jaipur, Rajasthan, India.

PRE-PROCESSED INTELLIGENCE for {date}:

ACTIVE PATTERNS:
{patterns}

ONGOING THREADS:
{threads}

ACTOR ACTIVITY:
{actors}

HIGH-SEVERITY EVENTS (last 24h):
{high_events}

ALL EVENTS SUMMARY ({event_count} total):
{event_clusters}

Generate a professional daily intelligence brief with exactly these sections:

1. EXECUTIVE SUMMARY
   3-4 sentences covering the most significant developments and their implications.

2. CRITICAL INCIDENTS
   Bullet list of high-severity events with specific locations, actors, and outcomes.
   Skip this section if no high-severity events.

3. PATTERN ANALYSIS
   What recurring patterns or themes emerged today? Reference specific actors and locations.
   Focus on what changed vs. yesterday.

4. ENTITY WATCH
   Which people or organizations drove the most activity today? What are they doing?

5. SITUATIONAL FORECAST
   Based on today's patterns, what developments are most likely in the next 48 hours?
   Be specific about locations and event types.

Rules:
- Be factual and specific. Use location names, organization names, people's names.
- Never write generic phrases like "remains a concern" or "requires attention".
- If a trend is worsening, say so explicitly.
- Forecast section must make specific, falsifiable predictions.
"""


def _preprocess_events_for_brief(docs: list[dict]) -> dict:
    """Extract structured context from events for better LLM prompting."""
    # Cluster by type
    by_type: dict[str, list] = defaultdict(list)
    for d in docs:
        by_type[d.get("event_type", "other")].append(d)

    # High severity events
    high_evs = [d for d in docs if d.get("severity") == "high"]

    # Top actors
    actor_counts: Counter = Counter()
    for d in docs:
        for actor in _parse_list(d.get("organizations", [])) + _parse_list(d.get("people", [])):
            actor_counts[str(actor).strip()] += 1
    top_actors = actor_counts.most_common(8)

    # Location risk
    loc_counts: Counter = Counter()
    for d in docs:
        locs = _parse_list(d.get("locations", []))
        if locs:
            loc_counts[locs[0]] += 1
    top_locs = loc_counts.most_common(5)

    # Load recent insights for context
    insights_text = ""
    try:
        from insights import get_insights
        recent_insights = get_insights(limit=10, days=2)
        if recent_insights:
            insights_text = "\n".join(
                f"- [{i.get('insight_type')}] {i.get('title')}: {i.get('body', '')[:150]}"
                for i in recent_insights[:6]
            )
    except Exception:
        pass

    # Event clusters (type → summary)
    clusters = []
    for etype, evs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        cluster_locs = Counter()
        for e in evs:
            locs = _parse_list(e.get("locations", []))
            if locs: cluster_locs[locs[0]] += 1
        sample = evs[0].get("summary", "")[:120] if evs else ""
        clusters.append(
            f"{etype.upper()} ({len(evs)} events, top loc: {cluster_locs.most_common(1)[0][0] if cluster_locs else '?'}): {sample}"
        )

    # High severity text
    high_text = "\n".join(
        f"- [{e.get('severity').upper()}] {e.get('event_type')} @ "
        f"{', '.join(_parse_list(e.get('locations', []))[:1]) or 'Jaipur'}: {e.get('summary', '')[:150]}"
        for e in high_evs[:10]
    ) or "None"

    # Actor text
    actor_text = "\n".join(
        f"- {actor}: {count} events"
        for actor, count in top_actors
        if len(actor) > 2
    ) or "No dominant actors"

    return {
        "patterns":       insights_text or "No active patterns detected.",
        "threads":        "See pattern analysis above.",
        "actors":         actor_text,
        "high_events":    high_text,
        "event_clusters": "\n".join(clusters[:12]),
        "event_count":    len(docs),
        "top_locations":  [loc for loc, _ in top_locs],
    }


def generate_daily_brief(target_date: str | None = None) -> str | None:
    from astra_client import events as ev_coll

    if target_date:
        try:
            day = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
        except Exception:
            day = datetime.now(timezone.utc)
    else:
        day = datetime.now(timezone.utc)

    since      = _iso(day - timedelta(hours=24))
    date_label = day.strftime("%Y-%m-%d")

    try:
        docs = list(ev_coll().find(
            {"created_at": {"$gte": since}},
            sort={"severity": -1},
            limit=100,
            projection={
                "event_type": 1, "summary": 1, "severity": 1,
                "locations": 1, "organizations": 1, "people": 1,
                "actor_roles": 1, "causal_factors": 1, "event_status": 1,
                "created_at": 1, "$vector": 0, "raw_llm_output": 0,
            },
        ))
    except Exception as exc:
        logger.error("generate_daily_brief fetch error: %s", exc)
        return None

    if not docs:
        logger.info("No events in last 24h — skipping daily brief for %s", date_label)
        return None

    ctx    = _preprocess_events_for_brief(docs)
    prompt = DAILY_BRIEF_PROMPT.format(date=date_label, **ctx)

    logger.info("Generating daily brief for %s (%d events)…", date_label, len(docs))
    body = _call_gemini(prompt, max_tokens=2500, temperature=0.2)

    if not body:
        logger.warning("Gemini returned no content for daily brief %s", date_label)
        return None

    return store_brief(
        brief_type="daily_summary",
        title=f"Daily Intelligence Brief — {date_label}",
        body=body,
        metadata={"date": date_label, "event_count": len(docs),
                  "top_locations": ctx["top_locations"]},
    )


# ── Weekly Brief ───────────────────────────────────────────────────────────────

WEEKLY_BRIEF_PROMPT = """\
You are a senior intelligence analyst covering Jaipur, Rajasthan, India.

WEEKLY INTELLIGENCE PACKAGE (past 7 days):

INSIGHT SUMMARY:
{insights_summary}

TREND ANALYSIS:
{trend_summary}

EVENT DISTRIBUTION:
{event_distribution}

TOP ACTORS (by frequency):
{top_actors}

TOP LOCATIONS (by event count):
{top_locations}

HIGH-SEVERITY EVENTS ({high_count} total):
{high_events}

Produce a comprehensive weekly intelligence briefing:

1. WEEK IN REVIEW
   5-6 sentences capturing the dominant narrative of this week for Jaipur.

2. CRITICAL INCIDENTS
   Top 5 most significant events with dates, locations, actors, and outcomes.

3. TREND ANALYSIS
   What patterns intensified, emerged, or resolved this week?
   Compare to what was expected vs. what actually happened.

4. KEY ACTORS
   Top 5 people/organizations and their significance this week.
   What changed about their position or activity?

5. STRATEGIC OUTLOOK
   3 specific predictions for the coming week based on current patterns.
   Each prediction should name specific actors, locations, and event types.

Write professionally. Be specific. Reference actual names and places.
"""


def generate_weekly_brief() -> str | None:
    from astra_client import events as ev_coll

    since      = _iso(_days_ago(7))
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        docs = list(ev_coll().find(
            {"created_at": {"$gte": since}},
            sort={"severity": -1},
            limit=300,
            projection={
                "event_type": 1, "summary": 1, "severity": 1,
                "locations": 1, "organizations": 1, "people": 1,
                "created_at": 1, "$vector": 0, "raw_llm_output": 0,
            },
        ))
    except Exception as exc:
        logger.error("generate_weekly_brief fetch error: %s", exc)
        return None

    if not docs:
        return None

    # Pre-process
    type_counts: Counter = Counter(d.get("event_type", "other") for d in docs)
    sev_counts:  Counter = Counter(d.get("severity", "low") for d in docs)
    actor_counts: Counter = Counter()
    loc_counts:  Counter = Counter()
    for d in docs:
        for a in _parse_list(d.get("organizations", [])) + _parse_list(d.get("people", [])):
            actor_counts[str(a).strip()] += 1
        locs = _parse_list(d.get("locations", []))
        if locs:
            loc_counts[locs[0]] += 1

    high_evs  = [d for d in docs if d.get("severity") == "high"]
    high_text = "\n".join(
        f"- [{(d.get('created_at') or '')[:10]}] {d.get('event_type')} @ "
        f"{', '.join(_parse_list(d.get('locations', []))[:1]) or 'Jaipur'}: "
        f"{d.get('summary', '')[:150]}"
        for d in high_evs[:12]
    ) or "None"

    # Load insights
    insights_text = ""
    try:
        from insights import get_insights
        week_insights = get_insights(limit=15, days=7)
        insights_text = "\n".join(
            f"- [{i.get('insight_type').upper()}] {i.get('title')}: {i.get('body', '')[:200]}"
            for i in week_insights[:8]
        )
    except Exception:
        pass

    # Trends
    try:
        trends = detect_trends(window_hours=168, baseline_days=21)
        trend_text = "\n".join(
            f"- {t['event_type']} in {t['location']}: {t['spike_ratio']}× spike ({t['recent_count']} events)"
            for t in trends[:6]
        ) or "No significant spikes detected."
    except Exception:
        trend_text = "Trend data unavailable."

    prompt = WEEKLY_BRIEF_PROMPT.format(
        insights_summary   = insights_text or "No insights generated yet.",
        trend_summary      = trend_text,
        event_distribution = "\n".join(f"- {t}: {c}" for t, c in type_counts.most_common(8)),
        top_actors         = "\n".join(f"- {a}: {c} events" for a, c in actor_counts.most_common(8) if len(a) > 2),
        top_locations      = "\n".join(f"- {l}: {c} events" for l, c in loc_counts.most_common(8)),
        high_count         = len(high_evs),
        high_events        = high_text,
    )

    logger.info("Generating weekly brief (%d events)…", len(docs))
    body = _call_gemini(prompt, max_tokens=3000, temperature=0.2)

    if not body:
        return None

    return store_brief(
        brief_type="weekly_briefing",
        title=f"Weekly Intelligence Briefing — w/e {date_label}",
        body=body,
        metadata={"date": date_label, "event_count": len(docs)},
    )


# ── Entity Co-occurrence ───────────────────────────────────────────────────────

def compute_entity_relationships(min_cooccurrence: int = 3, days: int = 30) -> list[dict]:
    from astra_client import event_entities as ee_coll

    start = _iso(_days_ago(days))
    try:
        ee_docs = list(ee_coll().find(
            {"created_at": {"$gte": start}},
            projection={"event_id": 1, "entity_id": 1},
            limit=10000,
        ))
    except Exception as exc:
        logger.error("compute_entity_relationships error: %s", exc)
        return []

    event_to_entities: dict[str, set] = defaultdict(set)
    for doc in ee_docs:
        event_to_entities[doc["event_id"]].add(doc["entity_id"])

    pair_counts: Counter = Counter()
    for eid_set in event_to_entities.values():
        eid_list = sorted(eid_set)
        for i in range(len(eid_list)):
            for j in range(i + 1, len(eid_list)):
                pair_counts[(eid_list[i], eid_list[j])] += 1

    return [
        {"entity_a": a, "entity_b": b, "count": c}
        for (a, b), c in pair_counts.most_common(100)
        if c >= min_cooccurrence
    ]


# ── Heatmap ────────────────────────────────────────────────────────────────────

def get_heatmap(event_type: str | None = None, severity: str | None = None, days: int = 7) -> list[dict]:
    from astra_client import events as ev_coll

    WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
    since  = _iso(_days_ago(days))
    filt: dict = {"created_at": {"$gte": since}}
    if event_type: filt["event_type"] = event_type
    if severity:   filt["severity"]   = severity

    try:
        docs = list(ev_coll().find(filt, projection={"lat": 1, "lng": 1, "severity": 1}, limit=5000))
    except Exception as exc:
        logger.error("get_heatmap error: %s", exc)
        return []

    return [
        {"lat": doc["lat"], "lng": doc["lng"], "weight": WEIGHT.get(doc.get("severity", "low"), 0.3)}
        for doc in docs if doc.get("lat") and doc.get("lng")
    ]


# ── Entity Network ─────────────────────────────────────────────────────────────

def entity_network(entity_id: str, depth: int = 1) -> dict:
    from astra_client import event_entities as ee_coll, entities as ent_coll

    def _neighbours(eid: str) -> set[str]:
        ev_ids = {
            r["event_id"]
            for r in ee_coll().find({"entity_id": eid}, projection={"event_id": 1}, limit=200)
        }
        nbrs: set[str] = set()
        for ev_id in ev_ids:
            for r in ee_coll().find(
                {"event_id": ev_id, "entity_id": {"$ne": eid}},
                projection={"entity_id": 1}, limit=50,
            ):
                nbrs.add(r["entity_id"])
        return nbrs

    try:
        root = ent_coll().find_one({"_id": entity_id}, projection={"$vector": 0})
        if not root:
            return {"nodes": [], "links": []}

        nodes_map: dict[str, dict] = {entity_id: root}
        links: list[dict] = []
        hop1 = _neighbours(entity_id)

        for nid in list(hop1)[:30]:
            if nid not in nodes_map:
                ent = ent_coll().find_one({"_id": nid}, projection={"$vector": 0})
                if ent:
                    nodes_map[nid] = ent
            links.append({"source": entity_id, "target": nid, "depth": 1})

        if depth >= 2:
            for hop1_id in list(hop1)[:10]:
                for nid in _neighbours(hop1_id):
                    if nid not in nodes_map:
                        ent = ent_coll().find_one({"_id": nid}, projection={"$vector": 0})
                        if ent:
                            nodes_map[nid] = ent
                    links.append({"source": hop1_id, "target": nid, "depth": 2})

        seen_links: set[frozenset] = set()
        deduped = []
        for lnk in links:
            key = frozenset([lnk["source"], lnk["target"]])
            if key not in seen_links:
                seen_links.add(key)
                deduped.append(lnk)

        nodes = [
            {"id": eid, "label": n.get("name", ""), "type": n.get("type", ""),
             "count": n.get("mention_count", 0), "isRoot": eid == entity_id}
            for eid, n in nodes_map.items()
        ]
        return {"nodes": nodes, "links": deduped}

    except Exception as exc:
        logger.error("entity_network error: %s", exc)
        return {"nodes": [], "links": []}


# ── Scheduler Registration ─────────────────────────────────────────────────────

def register_analysis_jobs(scheduler) -> None:
    trend_interval   = int(os.environ.get("TREND_DETECTION_INTERVAL_HOURS",  "6"))
    anomaly_interval = int(os.environ.get("ANOMALY_DETECTION_INTERVAL_HOURS", "4"))
    brief_time_ist   = os.environ.get("BRIEF_GENERATION_TIME_IST", "07:00")
    brief_h, brief_m = map(int, brief_time_ist.split(":"))
    brief_h_utc = (brief_h - 5) % 24
    brief_m_utc = (brief_m - 30) % 60
    if brief_m < 30:
        brief_h_utc = (brief_h_utc - 1) % 24

    scheduler.add_job(detect_trends,    "interval", hours=trend_interval,
                      id="trend_detection",   max_instances=1, misfire_grace_time=300, replace_existing=True)
    scheduler.add_job(detect_anomalies, "interval", hours=anomaly_interval,
                      id="anomaly_detection", max_instances=1, misfire_grace_time=300, replace_existing=True)
    scheduler.add_job(generate_daily_brief, "cron", hour=brief_h_utc, minute=brief_m_utc,
                      id="daily_brief",  max_instances=1, misfire_grace_time=600, replace_existing=True)
    scheduler.add_job(generate_weekly_brief, "cron", day_of_week="sun",
                      hour=brief_h_utc, minute=(brief_m_utc + 30) % 60,
                      id="weekly_brief", max_instances=1, misfire_grace_time=600, replace_existing=True)

    logger.info("Analysis jobs registered — trends every %dh, anomalies every %dh, "
                "daily brief at %02d:%02d UTC", trend_interval, anomaly_interval, brief_h_utc, brief_m_utc)
