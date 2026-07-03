"""
Garuda v3 — AstraDB Collection Initialiser
Creates all collections (v2 + v3) with correct vector dimensions.

Run once on a fresh keyspace: python scripts/init_astra_v3.py

ADR-001: This script now delegates to config.bootstrap_collections()
so there is a single source of truth for collection definitions.
The main.py lifespan also calls bootstrap_collections() on every startup,
making this script useful primarily for CI and local dev setup.
"""
import os, sys, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

from astra_client import get_db
from config import bootstrap_collections, COLLECTIONS


def main():
    db = get_db()
    existing = set(db.list_collection_names())
    logger.info("Existing collections (%d): %s", len(existing), sorted(existing))
    logger.info("Expected collections (%d): %s", len(COLLECTIONS), sorted(COLLECTIONS.keys()))

    created = bootstrap_collections(db)

    if created:
        logger.info("Done — created %d collection(s): %s", len(created), created)
    else:
        logger.info("Done — all collections already present, nothing to create.")


if __name__ == "__main__":
    main()
