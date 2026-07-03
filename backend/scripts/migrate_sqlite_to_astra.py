"""
Garuda v2 — SQLite → AstraDB Migration (data only, no embeddings)

Inserts all articles, events, entities and event_entities into AstraDB
WITHOUT generating any embeddings. Documents are stored immediately and
are fully queryable by field filters.

Vector search (semantic search) will not work until embed_backfill.py
has processed each document. Run that script separately after this one.

Usage:
    python scripts/migrate_sqlite_to_astra.py
    python scripts/migrate_sqlite_to_astra.py --dry-run
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from database import get_conn
from astra_client import articles, events, entities, event_entities

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

BATCH = 50  # AstraDB supports up to 100 per insert_many


def _parse_json(val):
    if isinstance(val, list): return val
    if isinstance(val, str):
        try: return json.loads(val)
        except Exception: return []
    return []


def _astra_exists(coll_fn, doc_id: str) -> bool:
    try:
        doc = coll_fn().find_one({"_id": doc_id}, projection={"_id": 1})
        return doc is not None
    except Exception:
        return False


def _bulk_upsert(coll_fn, docs, name):
    """Insert docs in batches; skip those that already exist."""
    inserted = skipped = failed = 0
    for i in range(0, len(docs), BATCH):
        chunk = docs[i:i + BATCH]
        try:
            coll_fn().insert_many(chunk, ordered=False)
            inserted += len(chunk)
        except Exception as exc:
            err = str(exc)
            # Count partial inserts — some may have succeeded
            if "already exists" in err.lower() or "duplicate" in err.lower():
                skipped += len(chunk)
            else:
                logger.warning("  [%s] batch %d error: %s", name, i // BATCH, err[:120])
                failed += len(chunk)
        time.sleep(0.1)  # brief pause between batches
    return inserted, skipped, failed


# ── Articles ──────────────────────────────────────────────────────────────────

def migrate_articles(dry_run: bool):
    logger.info("── Articles ──────────────────────────────────────────")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM articles ORDER BY id").fetchall()

    docs = []
    for r in rows:
        doc_id = f"art-{r['id']}"
        # AstraDB indexes strings up to 8000 bytes — truncate body to stay safe
        body = (r["body"] or "")[:6000]
        docs.append({
            "_id":          doc_id,
            "source":       r["source"],
            "title":        r["title"],
            "body":         body,
            "url":          r["url"],
            "published_at": r["published_at"],
            "scraped_at":   r["scraped_at"],
            "nlp_status":   r["nlp_status"],
            # No $vector — will be filled by embed_backfill.py
        })

    logger.info("  %d articles to insert", len(docs))
    if not dry_run:
        ins, skip, fail = _bulk_upsert(articles, docs, "articles")
        logger.info("  ✓ inserted=%d  skipped=%d  failed=%d", ins, skip, fail)
    else:
        logger.info("  DRY RUN — no writes")
    return len(docs)


# ── Events ────────────────────────────────────────────────────────────────────

def migrate_events(dry_run: bool):
    logger.info("── Events ────────────────────────────────────────────")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT e.*, a.source, a.title AS article_title,
                   a.url AS article_url, a.published_at
            FROM events e JOIN articles a ON a.id = e.article_id
            ORDER BY e.id
        """).fetchall()

    docs = []
    for r in rows:
        docs.append({
            "_id":            f"evt-{r['id']}",
            "article_id":     f"art-{r['article_id']}",
            "event_type":     r["event_type"],
            "summary":        r["summary"],
            "severity":       r["severity"],
            "keywords":       _parse_json(r["keywords"]),
            "locations":      _parse_json(r["locations"]),
            "organizations":  _parse_json(r["organizations"]),
            "people":         _parse_json(r["people"]),
            "related_topics": _parse_json(r["related_topics"]),
            "lat":            r["lat"],
            "lng":            r["lng"],
            "raw_llm_output": r["raw_llm_output"],
            "created_at":     r["created_at"],
            "source":         r["source"],
            "article_title":  r["article_title"],
            "article_url":    r["article_url"],
            "published_at":   r["published_at"],
            # No $vector
        })

    logger.info("  %d events to insert", len(docs))
    if not dry_run:
        ins, skip, fail = _bulk_upsert(events, docs, "events")
        logger.info("  ✓ inserted=%d  skipped=%d  failed=%d", ins, skip, fail)
    else:
        logger.info("  DRY RUN — no writes")
    return len(docs)


# ── Entities ──────────────────────────────────────────────────────────────────

def migrate_entities(dry_run: bool):
    logger.info("── Entities ──────────────────────────────────────────")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM entities ORDER BY id").fetchall()

    docs = []
    for r in rows:
        docs.append({
            "_id":             f"ent-{r['id']}",
            "name":            r["name"],
            "type":            r["type"],
            "normalized_name": r["normalized_name"],
            "mention_count":   r["mention_count"],
            "created_at":      r["created_at"],
            "first_seen_at":   r["first_seen_at"],
            "last_seen_at":    r["last_seen_at"],
            # No $vector
        })

    logger.info("  %d entities to insert", len(docs))
    if not dry_run:
        ins, skip, fail = _bulk_upsert(entities, docs, "entities")
        logger.info("  ✓ inserted=%d  skipped=%d  failed=%d", ins, skip, fail)
    else:
        logger.info("  DRY RUN — no writes")
    return len(docs)


# ── Event-entities ────────────────────────────────────────────────────────────

def migrate_event_entities(dry_run: bool):
    logger.info("── Event-entities ────────────────────────────────────")
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_entities").fetchall()

    docs = [
        {
            "_id":        f"ee-{r['event_id']}-{r['entity_id']}",
            "event_id":   f"evt-{r['event_id']}",
            "entity_id":  f"ent-{r['entity_id']}",
            "role":       r["role"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    logger.info("  %d event-entity links to insert", len(docs))
    if not dry_run:
        ins, skip, fail = _bulk_upsert(event_entities, docs, "event_entities")
        logger.info("  ✓ inserted=%d  skipped=%d  failed=%d", ins, skip, fail)
    else:
        logger.info("  DRY RUN — no writes")
    return len(docs)


# ── Verification ──────────────────────────────────────────────────────────────

def verify():
    print("\nVerification — record counts:")
    print(f"{'Collection':<25} {'SQLite':>8}  {'AstraDB':>8}  {'Status'}")
    print("-" * 55)
    with get_conn() as conn:
        sqlite_counts = {
            "articles":       conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "events":         conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "entities":       conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "event_entities": conn.execute("SELECT COUNT(*) FROM event_entities").fetchone()[0],
        }
    from astra_client import get_db
    db = get_db()
    for name, sq in sqlite_counts.items():
        try:
            astra = db.get_collection(name).count_documents({}, upper_bound=10000)
            ok = "✓" if astra >= sq else f"⚠ missing {sq - astra}"
        except Exception as e:
            astra = "error"
            ok = "✗"
        print(f"  {name:<25} {sq:>8}  {str(astra):>8}  {ok}")

    print("\nNext step: run embed_backfill.py to add vectors one-by-one.")
    print("  python scripts/embed_backfill.py --delay 2.0 --loop")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Garuda v2 — SQLite → AstraDB  (data only, no embeddings)")
    print(f"  Dry run: {args.dry_run}")
    print(f"{'='*55}\n")

    t0 = time.time()
    migrate_articles(args.dry_run)
    migrate_events(args.dry_run)
    migrate_entities(args.dry_run)
    migrate_event_entities(args.dry_run)

    logger.info("Migration complete in %.1fs", time.time() - t0)
    if not args.dry_run:
        verify()


if __name__ == "__main__":
    main()
