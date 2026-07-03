"""
Garuda v2 — AstraDB Collection Initialisation

Run once before deploying v2:
    cd backend && python scripts/init_astra.py

Creates all five collections with correct vector dimensions and indexes.
Safe to re-run (check_exists=True on all creates).
"""
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Allow running from backend/ or project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

COLLECTIONS = [
    # (name,               vector_dim)
    ("articles",            DIM),
    ("events",              DIM),
    ("entities",            DIM),
    ("event_entities",      None),   # relational only — no vector
    ("intelligence_briefs", DIM),
]


def main():
    from astra_client import get_db
    db = get_db()

    print(f"\n{'='*50}")
    print(f"  Garuda v2 — AstraDB Init")
    print(f"  Keyspace : {os.environ.get('ASTRA_DB_KEYSPACE', 'garuda')}")
    print(f"  Embedding: {DIM}-dim")
    print(f"{'='*50}\n")

    # ── Create collections ────────────────────────────────────────────────────
    print("Creating collections…")
    for name, dim in COLLECTIONS:
        try:
            if dim:
                db.create_collection(
                    name,
                    dimension=dim,
                    metric="cosine",
                    check_exists=True,
                )
            else:
                db.create_collection(name, check_exists=True)
            print(f"  ✓ {name}" + (f" ({dim}-dim cosine)" if dim else " (relational)"))
        except Exception as exc:
            print(f"  ✗ {name}: {exc}")

    # ── Create indexes ────────────────────────────────────────────────────────
    print("\nCreating indexes…")

    def _idx(coll_name, idx_name, field, unique=False):
        try:
            coll = db.get_collection(coll_name)
            kwargs = {"field": field}
            if unique:
                kwargs["unique"] = True
            coll.create_index(idx_name, **kwargs)
            print(f"  ✓ {coll_name}.{field}" + (" [unique]" if unique else ""))
        except Exception as exc:
            # Index may already exist — that's fine
            print(f"  ~ {coll_name}.{field}: {exc}")

    # articles
    _idx("articles", "url_idx",        "url",        unique=True)
    _idx("articles", "nlp_status_idx", "nlp_status")
    _idx("articles", "scraped_at_idx", "scraped_at")

    # events
    _idx("events", "severity_idx",   "severity")
    _idx("events", "event_type_idx", "event_type")
    _idx("events", "created_at_idx", "created_at")

    # entities
    _idx("entities", "normalized_name_idx", "normalized_name")
    _idx("entities", "type_idx",            "type")
    _idx("entities", "mention_count_idx",   "mention_count")

    # event_entities
    _idx("event_entities", "event_id_idx",  "event_id")
    _idx("event_entities", "entity_id_idx", "entity_id")

    # intelligence_briefs
    _idx("intelligence_briefs", "brief_type_idx",   "brief_type")
    _idx("intelligence_briefs", "generated_at_idx", "generated_at")

    print(f"\n{'='*50}")
    print("  All collections and indexes ready.")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
