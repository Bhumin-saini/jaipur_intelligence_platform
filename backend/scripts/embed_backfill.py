"""
backend/scripts/embed_backfill.py

Slowly finds documents with zero/missing vectors in AstraDB and re-embeds them.
Runs forever in the background, processing one document every few seconds.
Safe to run alongside the main pipeline — won't touch already-embedded docs.

Usage:
    python scripts/embed_backfill.py
    python scripts/embed_backfill.py --batch 5 --delay 3.0
"""
import sys, os, time, logging, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from astra_client import articles, events, entities
from embedder import embed_article, embed_event, embed_entity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

DIM = int(os.environ.get("EMBEDDING_DIM", "3072"))
ZERO_THRESHOLD = 0.01   # treat vectors where max(abs) < this as "empty"


def is_zero_vector(vec):
    if not vec:
        return True
    return max(abs(v) for v in vec[:10]) < ZERO_THRESHOLD


def needs_embedding(doc):
    vec = doc.get("$vector")
    return not vec or is_zero_vector(vec)


def backfill_articles(batch, delay):
    coll = articles()
    total = done = skipped = failed = 0
    logger.info("── Articles ──────────────────────────────")
    cursor = coll.find({}, projection={"title": 1, "body": 1, "$vector": 1})
    for doc in cursor:
        total += 1
        if not needs_embedding(doc):
            skipped += 1
            continue
        try:
            vec = embed_article(doc.get("title", ""), doc.get("body", ""))
            if is_zero_vector(vec):
                failed += 1
                logger.warning("  article %s — still zero, skipping", doc["_id"])
                continue
            coll.update_one({"_id": doc["_id"]}, {"$set": {"$vector": vec}})
            done += 1
            logger.info("  ✓ article %s embedded (%d done)", doc["_id"][:12], done)
            time.sleep(delay)
        except Exception as e:
            failed += 1
            logger.warning("  article %s failed: %s", doc["_id"][:12], e)
    logger.info("Articles: %d total | %d newly embedded | %d skipped | %d failed",
                total, done, skipped, failed)
    return done


def backfill_events(batch, delay):
    coll = events()
    total = done = skipped = failed = 0
    logger.info("── Events ────────────────────────────────")
    cursor = coll.find({}, projection={
        "event_type": 1, "summary": 1, "keywords": 1, "locations": 1, "$vector": 1
    })
    for doc in cursor:
        total += 1
        if not needs_embedding(doc):
            skipped += 1
            continue
        try:
            vec = embed_event(
                doc.get("event_type", ""),
                doc.get("summary", ""),
                doc.get("keywords", []),
                doc.get("locations", [])
            )
            if is_zero_vector(vec):
                failed += 1
                logger.warning("  event %s — still zero, skipping", doc["_id"])
                continue
            coll.update_one({"_id": doc["_id"]}, {"$set": {"$vector": vec}})
            done += 1
            logger.info("  ✓ event %s embedded (%d done)", doc["_id"][:12], done)
            time.sleep(delay)
        except Exception as e:
            failed += 1
            logger.warning("  event %s failed: %s", doc["_id"][:12], e)
    logger.info("Events: %d total | %d newly embedded | %d skipped | %d failed",
                total, done, skipped, failed)
    return done


def backfill_entities(batch, delay):
    coll = entities()
    total = done = skipped = failed = 0
    logger.info("── Entities ──────────────────────────────")
    cursor = coll.find({}, projection={"name": 1, "type": 1, "$vector": 1})
    for doc in cursor:
        total += 1
        if not needs_embedding(doc):
            skipped += 1
            continue
        try:
            vec = embed_entity(doc.get("name", ""), doc.get("type", ""))
            if is_zero_vector(vec):
                failed += 1
                logger.warning("  entity %s — still zero, skipping", doc["_id"])
                continue
            coll.update_one({"_id": doc["_id"]}, {"$set": {"$vector": vec}})
            done += 1
            logger.info("  ✓ entity '%s' embedded (%d done)",
                        doc.get("name", doc["_id"])[:30], done)
            time.sleep(delay)
        except Exception as e:
            failed += 1
            logger.warning("  entity %s failed: %s", doc["_id"][:12], e)
    logger.info("Entities: %d total | %d newly embedded | %d skipped | %d failed",
                total, done, skipped, failed)
    return done


def run_once(batch, delay):
    total = 0
    total += backfill_articles(batch, delay)
    total += backfill_events(batch, delay)
    total += backfill_entities(batch, delay)
    return total


def main():
    parser = argparse.ArgumentParser(description="Slow background embedding backfill")
    parser.add_argument("--batch", type=int, default=1,
                        help="Docs per batch before sleeping (default 1)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to wait between each embed (default 2.0)")
    parser.add_argument("--loop", action="store_true",
                        help="Keep looping every 10 min to catch new un-embedded docs")
    parser.add_argument("--loop-interval", type=int, default=600,
                        help="Seconds between full sweeps when --loop is set (default 600)")
    args = parser.parse_args()

    logger.info("Starting embedding backfill  delay=%.1fs  loop=%s",
                args.delay, args.loop)

    while True:
        done = run_once(args.batch, args.delay)
        if not args.loop:
            logger.info("Backfill complete. %d documents newly embedded.", done)
            break
        if done == 0:
            logger.info("Nothing left to embed. Sleeping %ds before next sweep.",
                        args.loop_interval)
        else:
            logger.info("Pass complete (%d embedded). Sleeping %ds.", done, args.loop_interval)
        time.sleep(args.loop_interval)


if __name__ == "__main__":
    main()
