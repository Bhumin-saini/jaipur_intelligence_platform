"""
Garuda v2 — Core pipeline (AstraDB primary storage).
scrape → persist → NLP extract → store entities → AstraDB.

All storage calls go through astra_store.py.
SQLite is no longer used in the pipeline.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time

from extractor import extract_intelligence
from scrapers import is_jaipur_article

logger = logging.getLogger(__name__)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        logger.warning("Invalid %s; using %.1f", name, default)
        return default


ARTICLE_PROCESS_DELAY_SECONDS = _float_env("ARTICLE_PROCESS_DELAY_SECONDS", 6.0)
SEMANTIC_DEDUP_THRESHOLD      = _float_env("SEMANTIC_DEDUP_THRESHOLD", 0.92)

_scrape_cycle_lock  = threading.Lock()
_scrape_status_lock = threading.Lock()
_scrape_status = {
    "running":            False,
    "started_at":         None,
    "last_finished_at":   None,
    "last_new_articles":  0,
    "last_candidates":    0,
}

# ADR-004-H02: Injected by main.py at startup so the scheduled scrape cycle
# can invalidate the API response cache without a circular import.
# Set via set_cache_invalidator(); defaults to a no-op.
_cache_invalidator: callable = lambda: None


def set_cache_invalidator(fn: callable) -> None:
    """Register the function to call after a scrape cycle that produces new events."""
    global _cache_invalidator
    _cache_invalidator = fn

DEATH_KEYWORDS = (
    "death", "dead", "died", "dies", "killed", "murder", "fatal", "body found",
    "मौत", "मृत्यु", "मृत", "हत्या", "शव",
)
MEDIUM_KEYWORDS = (
    "injured", "injury", "protest", "disruption", "blocked", "arrested", "fire",
    "घायल", "प्रदर्शन", "गिरफ्तार", "आग",
)
GENERIC_LOCATIONS = {"jaipur", "jaipur district", "pink city", "जयपुर"}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_scrape_status() -> dict:
    with _scrape_status_lock:
        return dict(_scrape_status)


def _set_scrape_status(**updates):
    with _scrape_status_lock:
        _scrape_status.update(updates)


def _override_severity(result: dict, article) -> dict:
    combined = " ".join([
        article.title or "",
        article.body or "",
        result.get("summary", "") or "",
        " ".join(result.get("keywords", []) or []),
    ]).casefold()
    if any(kw.casefold() in combined for kw in DEATH_KEYWORDS):
        result["severity"] = "high"
    elif result.get("severity") == "low" and any(kw.casefold() in combined for kw in MEDIUM_KEYWORDS):
        result["severity"] = "medium"
    return result


def _jitter_default_coords(result: dict, article) -> dict:
    lat = result.get("lat", 26.9124)
    lng = result.get("lng", 75.7873)
    locations = {str(loc).strip().casefold() for loc in result.get("locations", []) or []}
    generic_location = not locations or locations.issubset(GENERIC_LOCATIONS)
    if generic_location and abs(lat - 26.9124) < 0.000001 and abs(lng - 75.7873) < 0.000001:
        seed = hashlib.md5((article.url or article.title or "").encode("utf-8")).digest()
        result["lat"] = lat + ((seed[0] / 255) - 0.5) * 0.01
        result["lng"] = lng + ((seed[1] / 255) - 0.5) * 0.01
    return result


def _canonicalize_entities(result: dict) -> dict:
    from entity_resolver import resolve_canonical

    type_map = {
        "locations":     "location",
        "organizations": "organization",
        "people":        "person",
    }
    for field, etype in type_map.items():
        values = []
        seen   = set()
        for name in result.get(field, []) or []:
            cleaned = re.sub(r"\s+", " ", str(name)).strip()
            if not cleaned or len(cleaned) < 2:
                continue
            canonical = resolve_canonical(cleaned, etype)
            key = canonical.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(canonical)
        result[field] = values
    return result

def _post_process_result(result: dict, article) -> dict:
    result = _canonicalize_entities(result)
    result = _override_severity(result, article)
    result = _jitter_default_coords(result, article)
    return result


def process_article(article) -> bool:
    """
    Full v3 pipeline for one article.
    Returns True if a new article was processed (new or duplicate).
    """
    if not is_jaipur_article(article):
        logger.info("Skipping non-Jaipur article: %s", (article.title or "")[:80])
        return False

    import astra_store as store

    # 1. Upsert article — returns None if URL already exists
    article_id = store.upsert_article(
        source      = article.source,
        title       = article.title,
        body        = article.body,
        url         = article.url,
        published_at= article.published_at,
    )
    if article_id is None:
        logger.debug("URL duplicate skipped: %s", article.url)
        return False

    # 2. Semantic deduplication against existing events
    duplicate = store.semantic_dedup(article.title, threshold=SEMANTIC_DEDUP_THRESHOLD)
    if duplicate:
        sim = duplicate.get("$similarity", 0)
        logger.info(
            "Semantic duplicate (sim=%.3f) — article_id=%s matched event=%s",
            sim, article_id, duplicate.get("_id"),
        )
        store.mark_article_nlp_status(article_id, "duplicate")
        return True

    # 3. NLP extraction (Gemini → Groq fallback)
    result, raw = extract_intelligence(article.title, article.body)
    if result is None:
        logger.warning("NLP failed for article_id=%s", article_id)
        store.mark_article_nlp_status(article_id, "failed")
        return True

    # 4. Post-process
    result = _post_process_result(result, article)

    # 5. Store event
    event_id = store.insert_event(
        article_id    = article_id,
        result        = result,
        source        = article.source,
        article_title = article.title,
        article_url   = article.url,
        published_at  = article.published_at,
    )

    # 6. Upsert entities with vector-based resolution
    type_map = [
        ("locations",     "location"),
        ("organizations", "organization"),
        ("people",        "person"),
    ]
    entity_ids_created: list[tuple[str, str, str]] = []  # (entity_id, name, etype)
    for field, etype in type_map:
        for name in result.get(field, []):
            name = str(name).strip()
            if not name or len(name) < 2:
                continue
            try:
                entity_id = store.upsert_entity(name, etype)
                store.link_event_entity(event_id, entity_id, etype)
                entity_ids_created.append((entity_id, name, etype))
            except Exception as exc:
                logger.warning("Entity upsert error (%s / %s): %s", name, etype, exc)

    # 7. v3: Build knowledge graph nodes + co-occurrence edges
    # ADR-002: operations are enqueued for async retry (1 s → 4 s → 16 s backoff)
    # rather than discarded on the first transient AstraDB error.
    try:
        from knowledge_graph import upsert_node, upsert_edge, find_similar_and_link
        import graph_queue

        ops: list = []
        node_ids = [eid for eid, _, _ in entity_ids_created]

        # Node upserts
        for entity_id, name, etype in entity_ids_created:
            ops.append((
                upsert_node,
                (),
                {"entity_id": entity_id, "name": name, "entity_type": etype, "raw_type": etype},
                f"node:{entity_id}:{name[:30]}",
            ))

        # Co-occurrence edges
        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                ops.append((
                    upsert_edge,
                    (),
                    {
                        "source_id": node_ids[i], "target_id": node_ids[j],
                        "rel_type": "co_occurred_with", "weight": 0.6,
                        "evidence": [event_id], "inferred": False, "confidence": 0.9,
                    },
                    f"edge:{node_ids[i][:8]}--{node_ids[j][:8]}",
                ))

        # Event similarity links
        summary = result.get("summary", "")
        if summary:
            ops.append((
                find_similar_and_link,
                (),
                {
                    "event_id": event_id,
                    "event_summary": summary,
                    "event_type": result.get("event_type", "other"),
                    "threshold": 0.82,
                    "limit": 3,
                },
                f"simlink:{event_id[:12]}",
            ))

        graph_queue.enqueue(ops)
        logger.debug("Enqueued %d graph ops for event_id=%s", len(ops), event_id)

    except Exception as exc:
        logger.warning("v3 graph queue setup error: %s", exc)

    # 8. v3: Record source credibility activity
    try:
        from credibility import record_source_activity
        record_source_activity(source=article.source, article_id=article_id, event_id=event_id)
    except Exception as exc:
        logger.warning("v3 credibility record error: %s", exc)

    store.mark_article_nlp_status(article_id, "success")
    logger.info(
        "Stored event_id=%s | type=%s | severity=%s",
        event_id, result.get("event_type"), result.get("severity"),
    )
    return True


def run_scrape_cycle():
    """Called by APScheduler every N minutes."""
    if not _scrape_cycle_lock.acquire(blocking=False):
        logger.warning("Scrape cycle already running; skipping this trigger")
        return 0

    from scrapers import ALL_SCRAPERS

    try:
        _set_scrape_status(running=True, started_at=_utc_now())
        candidates = []

        for ScraperCls in ALL_SCRAPERS:
            scraper = ScraperCls()
            try:
                articles = scraper.scrape()
                candidates.extend(articles)
                logger.info("[%s] queued %d Jaipur articles", scraper.source_name, len(articles))
            except Exception as exc:
                logger.error("[%s] scrape cycle error: %s", scraper.source_name, exc)

        total_candidates = len(candidates)
        _set_scrape_status(last_candidates=total_candidates)
        logger.info("Processing %d Jaipur articles", total_candidates)

        new_total = 0
        for index, article in enumerate(candidates, start=1):
            logger.info("Processing %d/%d: %s", index, total_candidates, (article.title or "")[:100])
            if process_article(article):
                new_total += 1
                if ARTICLE_PROCESS_DELAY_SECONDS > 0 and index < total_candidates:
                    time.sleep(ARTICLE_PROCESS_DELAY_SECONDS)

        logger.info("Scrape cycle complete — %d new articles processed", new_total)
        _set_scrape_status(last_new_articles=new_total)

        # ADR-004-H02: Invalidate cached API responses so dashboards reflect
        # new events immediately instead of waiting for TTL expiry.
        if new_total > 0:
            try:
                _cache_invalidator()
                logger.info("Cache invalidated after scrape — %d new events ingested", new_total)
            except Exception as exc:
                logger.warning("Cache invalidation failed: %s", exc)

        return new_total
    finally:
        _set_scrape_status(running=False, last_finished_at=_utc_now())
        _scrape_cycle_lock.release()
