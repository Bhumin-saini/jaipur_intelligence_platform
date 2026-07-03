"""
Garuda v2 — AstraDB Storage Layer (astra_store.py)

Mirrors the CRUD interface previously spread across database.py and pipeline.py.
All reads and writes go through here once Phase 3 cutover is complete.

Key public functions:
    upsert_article()       → str | None
    semantic_dedup()       → dict | None
    insert_event()         → str
    resolve_entity()       → str | None
    upsert_entity()        → str
    link_event_entity()
    list_events()          → list[dict]
    get_event()            → dict | None
    list_entities()        → list[dict]
    get_entity()           → dict | None
    graph_data()           → dict
    stats()                → dict
    metrics()              → dict
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_list(val) -> list:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return []


def _clean_event(doc: dict) -> dict:
    """Normalise list fields and strip AstraDB internals for API responses."""
    if not doc:
        return doc
    for field in ("keywords", "locations", "organizations", "people", "related_topics", "causal_factors"):
        doc[field] = _parse_list(doc.get(field, []))
    # Deserialise actor_roles JSON string if needed
    ar = doc.get("actor_roles", {})
    if isinstance(ar, str):
        try: doc["actor_roles"] = json.loads(ar)
        except: doc["actor_roles"] = {}
    doc.pop("$vector", None)
    return doc


# ── Article operations ────────────────────────────────────────────────────────

def upsert_article(
    source: str,
    title: str,
    body: str,
    url: str,
    published_at: str,
) -> str | None:
    """
    Insert a new article.
    Returns the new _id string, or None if URL already exists (duplicate).
    """
    from astra_client import articles as _articles
    from embedder import embed_article

    try:
        existing = _articles().find_one({"url": url})
        if existing:
            return None

        doc_id = str(uuid.uuid4())
        vec = embed_article(title, body or "")
        _articles().insert_one({
            "_id":          doc_id,
            "source":       source,
            "title":        title,
            "body":         (body or "")[:6000],  # AstraDB 8000-byte index limit
            "url":          url,
            "published_at": published_at,
            "scraped_at":   _utc_now(),
            "nlp_status":   "pending",
            "$vector":      vec,
        })
        return doc_id
    except Exception as exc:
        logger.error("upsert_article error: %s", exc)
        return None


def mark_article_nlp_status(article_id: str, status: str):
    from astra_client import articles as _articles
    try:
        _articles().update_one(
            {"_id": article_id},
            {"$set": {"nlp_status": status}},
        )
    except Exception as exc:
        logger.warning("mark_article_nlp_status error: %s", exc)


# ── Semantic deduplication ────────────────────────────────────────────────────

def semantic_dedup(title: str, threshold: float = 0.92) -> dict | None:
    """
    Find a semantically similar existing event using AstraDB vector search.
    Returns the matching event doc or None.
    Replaces the SequenceMatcher-based _find_similar_event() from pipeline.py.
    """
    from astra_client import events as _events
    from embedder import embed_text

    if not title or len(title.strip()) < 12:
        return None

    try:
        vec = embed_text(title)
        results = list(_events().find(
            {},
            sort={"$vector": vec},
            limit=5,
            include_similarity=True,
            projection={"_id": 1, "summary": 1, "article_title": 1, "$similarity": 1},
        ))
        for r in results:
            if r.get("$similarity", 0) >= threshold:
                return r
    except Exception as exc:
        logger.warning("semantic_dedup error: %s", exc)
    return None


# ── Event operations ──────────────────────────────────────────────────────────

def insert_event(
    article_id: str,
    result: dict,
    source: str,
    article_title: str,
    article_url: str,
    published_at: str,
) -> str:
    """Store an extracted event. Returns its new _id."""
    from astra_client import events as _events
    from embedder import embed_event

    doc_id = str(uuid.uuid4())
    kw   = _parse_list(result.get("keywords", []))
    locs = _parse_list(result.get("locations", []))
    vec  = embed_event(result.get("event_type", ""), result.get("summary", ""), kw, locs)

    _events().insert_one({
        "_id":            doc_id,
        "article_id":     article_id,
        "event_type":     result.get("event_type", "other"),
        "summary":        result.get("summary", ""),
        "severity":       result.get("severity", "low"),
        "keywords":       kw,
        "locations":      locs,
        "organizations":    _parse_list(result.get("organizations", [])),
        "people":           _parse_list(result.get("people", [])),
        "related_topics":   _parse_list(result.get("related_topics", [])),
        "actor_roles":      json.dumps(result.get("actor_roles", {}), ensure_ascii=False),
        "causal_factors":   json.dumps(result.get("causal_factors", []), ensure_ascii=False),
        "event_status":     result.get("event_status", "unclear"),
        "impact":           result.get("impact", ""),
        "lat":              result.get("lat", 26.9124),
        "lng":              result.get("lng", 75.7873),
        "raw_llm_output":   json.dumps(result, ensure_ascii=False),
        "created_at":     _utc_now(),
        "source":         source,
        "article_title":  article_title,
        "article_url":    article_url,
        "published_at":   published_at,
        "$vector":        vec,
    })
    return doc_id


def list_events(
    severity: str = None,
    event_type: str = None,
    limit: int = 200,
    from_date: str = None,
    to_date: str = None,
) -> list[dict]:
    from astra_client import events as _events

    filt = {}
    if severity:   filt["severity"]   = severity
    if event_type: filt["event_type"] = event_type
    if from_date or to_date:
        date_filt = {}
        if from_date: date_filt["$gte"] = from_date
        if to_date:   date_filt["$lte"] = to_date + "T23:59:59"
        filt["created_at"] = date_filt

    try:
        rows = list(_events().find(
            filt,
            sort={"created_at": -1},
            limit=limit,
            projection={"body": 0, "$vector": 0},
        ))
        return [_clean_event(r) for r in rows]
    except Exception as exc:
        logger.error("list_events error: %s", exc)
        return []


def get_similar_events(event_id: str, limit: int = 5) -> list[dict]:
    """
    Find semantically similar events using vector search.
    Falls back to same event_type if no embeddings available.
    """
    from astra_client import events as _events
    try:
        source = _events().find_one({"_id": event_id},
                                    projection={"$vector": 1, "event_type": 1, "summary": 1})
        if not source:
            return []

        vec = source.get("$vector")
        # Vector search path
        if vec and max(abs(v) for v in vec[:5]) > 0.001:
            results = list(_events().find(
                {"_id": {"$ne": event_id}},
                sort={"$vector": vec},
                limit=limit + 1,
                include_similarity=True,
                projection={"summary": 1, "event_type": 1, "severity": 1,
                            "article_title": 1, "created_at": 1, "$vector": 0},
            ))
            return [_clean_event(r) for r in results if r["_id"] != event_id][:limit]

        # Fallback: same event_type
        rows = list(_events().find(
            {"_id": {"$ne": event_id}, "event_type": source.get("event_type", "other")},
            sort={"created_at": -1},
            limit=limit,
            projection={"summary": 1, "event_type": 1, "severity": 1,
                        "article_title": 1, "created_at": 1, "$vector": 0},
        ))
        return [_clean_event(r) for r in rows]
    except Exception as exc:
        logger.warning("get_similar_events error: %s", exc)
        return []


def get_timeline_summary(days: int = 30) -> list[dict]:
    """
    Returns per-day event counts grouped by severity for the past N days.
    Used by the Timeline page.
    """
    from astra_client import events as _events
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    day_map: dict = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0,
                                          "total": 0, "events": []})
    try:
        rows = list(_events().find(
            {"created_at": {"$gte": cutoff}},
            projection={"severity": 1, "event_type": 1, "created_at": 1,
                        "article_title": 1, "summary": 1, "$vector": 0},
            limit=5000,
        ))
        for doc in rows:
            day = (doc.get("created_at") or "")[:10]
            if not day:
                continue
            sev = doc.get("severity", "low")
            day_map[day][sev]    += 1
            day_map[day]["total"] += 1
            if len(day_map[day]["events"]) < 10:
                day_map[day]["events"].append(_clean_event(doc))

        return [
            {"day": day, **counts}
            for day, counts in sorted(day_map.items())
        ]
    except Exception as exc:
        logger.error("get_timeline_summary error: %s", exc)
        return []


def get_event(event_id: str) -> dict | None:
    from astra_client import events as _events, event_entities as _ee, entities as _ent

    try:
        doc = _events().find_one({"_id": event_id})
        if not doc:
            return None
        doc = _clean_event(doc)

        # Attach linked entities
        ee_rows = list(_ee().find({"event_id": event_id}, projection={"entity_id": 1, "role": 1}))
        entity_ids = [r["entity_id"] for r in ee_rows]
        roles      = {r["entity_id"]: r["role"] for r in ee_rows}
        linked = []
        for eid in entity_ids:
            ent = _ent().find_one({"_id": eid}, projection={"$vector": 0})
            if ent:
                ent["role"] = roles.get(eid, "")
                linked.append(ent)
        doc["entities"] = linked
        return doc
    except Exception as exc:
        logger.error("get_event error: %s", exc)
        return None


# ── Entity operations ─────────────────────────────────────────────────────────

def resolve_entity(
    name: str,
    entity_type: str,
    similarity_threshold: float = 0.88,
) -> str | None:
    """
    Use AstraDB vector search to find a semantically equivalent existing entity.
    Replaces the hard-coded ENTITY_ALIASES dict.
    Returns the matching entity _id or None.
    """
    from astra_client import entities as _ent
    from embedder import embed_entity

    try:
        vec = embed_entity(name, entity_type)
        results = list(_ent().find(
            {"type": entity_type},
            sort={"$vector": vec},
            limit=3,
            include_similarity=True,
            projection={"_id": 1, "name": 1, "$similarity": 1},
        ))
        for r in results:
            if r.get("$similarity", 0) >= similarity_threshold:
                logger.info(
                    "Entity resolved: '%s' → '%s' (sim=%.3f)",
                    name, r["name"], r["$similarity"],
                )
                return r["_id"]
    except Exception as exc:
        logger.warning("resolve_entity error: %s", exc)
    return None


def upsert_entity(name: str, entity_type: str) -> str:
    """
    Upsert an entity. First tries vector-based resolution; if matched,
    increments mention_count on the existing doc. Otherwise inserts new.
    Returns the entity _id.

    ADR-004-H01: The insert step now uses a deterministic _id derived from
    sha1(normalized_name:entity_type). Two concurrent inserts for the same
    entity produce the same _id; the second insert raises a duplicate-key
    error which is caught and treated as success — eliminating the
    check-then-act race condition that created duplicate entity documents.
    """
    from entity_resolver import resolve_canonical
    name = resolve_canonical(name, entity_type)
    from astra_client import entities as _ent
    from embedder import embed_entity

    # 1. Try embedding-based resolution
    existing_id = resolve_entity(name, entity_type)
    if existing_id:
        try:
            _ent().update_one(
                {"_id": existing_id},
                {"$inc": {"mention_count": 1}, "$set": {"last_seen_at": _utc_now()}},
            )
        except Exception as exc:
            logger.warning("upsert_entity increment error: %s", exc)
        return existing_id

    # 2. Exact normalized match (cheap fallback before embedding insert)
    normalized = name.casefold().strip()
    try:
        existing = _ent().find_one({"normalized_name": normalized, "type": entity_type})
        if existing:
            _ent().update_one(
                {"_id": existing["_id"]},
                {"$inc": {"mention_count": 1}, "$set": {"last_seen_at": _utc_now()}},
            )
            return existing["_id"]
    except Exception as exc:
        logger.warning("upsert_entity exact-match error: %s", exc)

    # 3. Insert new entity with a DETERMINISTIC _id (ADR-004-H01).
    #    sha1(normalized:type)[:24] is stable across concurrent calls for the
    #    same entity — a duplicate-key error means another thread just created
    #    it, which is fine: return the same _id.
    doc_id = hashlib.sha1(f"{normalized}:{entity_type}".encode()).hexdigest()[:24]
    vec = embed_entity(name, entity_type)
    try:
        _ent().insert_one({
            "_id":             doc_id,
            "name":            name,
            "type":            entity_type,
            "normalized_name": normalized,
            "mention_count":   1,
            "created_at":      _utc_now(),
            "first_seen_at":   _utc_now(),
            "last_seen_at":    _utc_now(),
            "$vector":         vec,
        })
    except Exception as exc:
        exc_str = str(exc).lower()
        if "already exists" in exc_str or "duplicate" in exc_str or "e11000" in exc_str:
            # Race condition: another concurrent call won the insert — that's fine.
            logger.debug("upsert_entity: concurrent insert resolved for '%s' (%s)", name, entity_type)
        else:
            logger.error("upsert_entity insert error: %s", exc)
    return doc_id


def link_event_entity(event_id: str, entity_id: str, role: str):
    from astra_client import event_entities as _ee

    doc_id = f"ee-{event_id[:8]}-{entity_id[:8]}-{uuid.uuid4().hex[:4]}"
    try:
        existing = _ee().find_one({"event_id": event_id, "entity_id": entity_id})
        if not existing:
            _ee().insert_one({
                "_id":        doc_id,
                "event_id":   event_id,
                "entity_id":  entity_id,
                "role":       role,
                "created_at": _utc_now(),
            })
    except Exception as exc:
        logger.warning("link_event_entity error: %s", exc)


def list_entities(entity_type: str = None, limit: int = 100) -> list[dict]:
    from astra_client import entities as _ent

    filt = {}
    if entity_type:
        filt["type"] = entity_type
    try:
        rows = list(_ent().find(
            filt,
            sort={"mention_count": -1},
            limit=limit,
            projection={"$vector": 0},
        ))
        return rows
    except Exception as exc:
        logger.error("list_entities error: %s", exc)
        return []


def get_entity(entity_id: str) -> dict | None:
    from astra_client import entities as _ent, event_entities as _ee, events as _events

    try:
        entity = _ent().find_one({"_id": entity_id}, projection={"$vector": 0})
        if not entity:
            return None

        # Timeline: events this entity appears in
        ee_rows = list(_ee().find({"entity_id": entity_id}, projection={"event_id": 1, "role": 1}))
        event_ids = [r["event_id"] for r in ee_rows]
        roles_map  = {r["event_id"]: r["role"] for r in ee_rows}
        timeline = []
        for eid in event_ids[:50]:
            ev = _events().find_one({"_id": eid}, projection={"$vector": 0, "raw_llm_output": 0})
            if ev:
                ev = _clean_event(ev)
                ev["role"] = roles_map.get(eid, "")
                timeline.append(ev)
        timeline.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Related entities: co-appear in same events
        co_entity_ids = set()
        for eid in event_ids[:30]:
            for row in _ee().find({"event_id": eid, "entity_id": {"$ne": entity_id}}):
                co_entity_ids.add(row["entity_id"])
        related = []
        for cid in list(co_entity_ids)[:10]:
            ent = _ent().find_one({"_id": cid}, projection={"$vector": 0})
            if ent:
                related.append(ent)
        related.sort(key=lambda x: x.get("mention_count", 0), reverse=True)

        return {
            **entity,
            "timeline": timeline,
            "related_entities": related,
        }
    except Exception as exc:
        logger.error("get_entity error: %s", exc)
        return None


# ── Graph data ────────────────────────────────────────────────────────────────

def graph_data(limit: int = 50, inferred: bool = False) -> dict:
    from astra_client import events as _events, event_entities as _ee, entities as _ent

    try:
        evs = list(_events().find(
            {},
            sort={"created_at": -1},
            limit=limit,
            projection={"summary": 1, "severity": 1, "event_type": 1, "$vector": 0},
        ))
        event_ids = [e["_id"] for e in evs]

        ee_rows = []
        for eid in event_ids:
            ee_rows.extend(list(_ee().find(
                {"event_id": eid},
                projection={"event_id": 1, "entity_id": 1, "role": 1},
            )))

        entity_ids = list({r["entity_id"] for r in ee_rows})
        ent_map = {}
        for eid in entity_ids:
            ent = _ent().find_one({"_id": eid}, projection={"name": 1, "type": 1, "$vector": 0})
            if ent:
                ent_map[eid] = ent

        nodes = []
        seen  = set()
        for ev in evs:
            nid = f"event-{ev['_id']}"
            if nid not in seen:
                nodes.append({
                    "id":         nid,
                    "label":      (ev.get("summary") or "Event")[:60],
                    "group":      "event",
                    "severity":   ev.get("severity"),
                    "event_type": ev.get("event_type"),
                })
                seen.add(nid)
        for eid, ent in ent_map.items():
            nid = f"entity-{eid}"
            if nid not in seen:
                nodes.append({
                    "id":    nid,
                    "label": ent.get("name", ""),
                    "group": ent.get("type", "unknown"),
                })
                seen.add(nid)

        links = [
            {
                "source":   f"event-{r['event_id']}",
                "target":   f"entity-{r['entity_id']}",
                "role":     r.get("role", ""),
                "inferred": False,
            }
            for r in ee_rows
        ]

        # Inferred edges: entity co-occurrence across events
        if inferred:
            from collections import defaultdict, Counter
            entity_to_events: dict[str, set] = defaultdict(set)
            for r in ee_rows:
                entity_to_events[r["entity_id"]].add(r["event_id"])

            co_counts: Counter = Counter()
            eid_list = list(entity_to_events.keys())
            for i in range(len(eid_list)):
                for j in range(i + 1, len(eid_list)):
                    a, b = eid_list[i], eid_list[j]
                    shared = len(entity_to_events[a] & entity_to_events[b])
                    if shared >= 3:
                        co_counts[(a, b)] = shared

            for (a, b), count in co_counts.most_common(40):
                na, nb = f"entity-{a}", f"entity-{b}"
                if na in seen and nb in seen:
                    links.append({
                        "source":   na,
                        "target":   nb,
                        "role":     "co-occurrence",
                        "inferred": True,
                        "strength": count,
                    })

        return {"nodes": nodes, "links": links}
    except Exception as exc:
        logger.error("graph_data error: %s", exc)
        return {"nodes": [], "links": []}


# ── Stats & metrics ────────────────────────────────────────────────────────────

def stats(scrape_status: dict = None) -> dict:
    from astra_client import articles as _art, events as _ev, entities as _ent

    try:
        total_articles = _art().count_documents({}, upper_bound=10000)
        total_events   = _ev().count_documents({}, upper_bound=10000)
        total_entities = _ent().count_documents({}, upper_bound=10000)

        # Severity breakdown
        by_severity = {"high": 0, "medium": 0, "low": 0}
        for sev in ("high", "medium", "low"):
            by_severity[sev] = _ev().count_documents({"severity": sev}, upper_bound=10000)

        # Event type breakdown (top 10 — requires iterating without aggregation)
        from collections import Counter
        type_counter: Counter = Counter()
        for doc in _ev().find({}, projection={"event_type": 1}, limit=2000):
            type_counter[doc.get("event_type", "other")] += 1
        by_type = dict(type_counter.most_common(10))

        # Latest scraped_at
        latest_docs = list(_art().find({}, sort={"scraped_at": -1}, limit=1, projection={"scraped_at": 1}))
        last_scraped = latest_docs[0].get("scraped_at") if latest_docs else None

        return {
            "total_articles": total_articles,
            "total_events":   total_events,
            "total_entities": total_entities,
            "by_severity":    by_severity,
            "by_type":        by_type,
            "last_scraped":   last_scraped,
            "scrape":         scrape_status or {},
        }
    except Exception as exc:
        logger.error("stats error: %s", exc)
        return {}


def metrics(scrape_status: dict = None) -> dict:
    """
    Single-pass metrics — scans each collection once to minimise AstraDB
    round-trips and cut response time from ~8s to ~2s.
    """
    from astra_client import (
        articles as _art, events as _ev, entities as _ent, event_entities as _ee
    )
    from collections import Counter, defaultdict

    try:
        # ── Single pass: articles ──────────────────────────────────────────
        nlp_counts: Counter = Counter()
        total_articles = 0
        for doc in _art().find({}, projection={"nlp_status": 1}, limit=5000):
            total_articles += 1
            nlp_counts[doc.get("nlp_status", "pending")] += 1

        # ── Single pass: events ────────────────────────────────────────────
        sev_counts:  Counter = Counter()
        type_counts: Counter = Counter()
        sev_by_day: dict = defaultdict(
            lambda: {"high": 0, "medium": 0, "low": 0, "total": 0}
        )
        total_events = 0
        for doc in _ev().find(
            {},
            projection={"event_type": 1, "severity": 1, "created_at": 1},
            limit=5000,
        ):
            total_events += 1
            sev = doc.get("severity", "low")
            typ = doc.get("event_type", "other")
            day = (doc.get("created_at") or "")[:10]
            sev_counts[sev]  += 1
            type_counts[typ] += 1
            if day:
                sev_by_day[day][sev]     += 1
                sev_by_day[day]["total"] += 1

        # ── Single pass: entities (top 10 by mention_count) ───────────────
        top_entities   = []
        total_entities = 0
        for doc in _ent().find(
            {},
            sort={"mention_count": -1},
            limit=5000,
            projection={"$vector": 0},
        ):
            total_entities += 1
            if len(top_entities) < 10:
                top_entities.append(doc)

        # ── Single pass: event_entities ────────────────────────────────────
        entity_mappings = 0
        unique_entities: set = set()
        for doc in _ee().find({}, projection={"entity_id": 1}, limit=5000):
            entity_mappings += 1
            unique_entities.add(doc.get("entity_id", ""))
        mapped_entities = len(unique_entities)

        # ── Derived values ─────────────────────────────────────────────────
        nlp_success  = nlp_counts.get("success",   0)
        nlp_failures = nlp_counts.get("failed",    0)
        deduplicated = nlp_counts.get("duplicate", 0)
        dedup_rate   = deduplicated / total_articles if total_articles else 0

        severity_by_day = [
            {"day": day, **counts}
            for day, counts in sorted(sev_by_day.items())[-30:]
        ]

        return {
            "summary": {
                "articles_ingested":  total_articles,
                "events_created":     total_events,
                "entities_total":     total_entities,
                "entities_mapped":    mapped_entities,
                "entity_mappings":    entity_mappings,
                "nlp_success":        nlp_success,
                "nlp_failures":       nlp_failures,
                "deduplicated":       deduplicated,
                "dedup_rate":         round(dedup_rate, 4),
                "dedup_rate_percent": round(dedup_rate * 100, 1),
            },
            "funnel": [
                {"key": "articles", "label": "Articles ingested", "value": total_articles},
                {"key": "events",   "label": "Events created",    "value": total_events},
                {"key": "entities", "label": "Entities mapped",   "value": mapped_entities},
            ],
            "nlp_status":             dict(nlp_counts),
            "severity_breakdown":     dict(sev_counts),
            "event_type_distribution": [
                {"event_type": k, "count": v}
                for k, v in type_counts.most_common()
            ],
            "severity_by_day": severity_by_day,
            "top_entities":    top_entities,
            "scrape":          scrape_status or {},
        }
    except Exception as exc:
        logger.error("metrics error: %s", exc)
        return {}
