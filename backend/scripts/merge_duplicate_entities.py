#!/usr/bin/env python
"""
Garuda v3 — Retroactive Entity Deduplication
scripts/merge_duplicate_entities.py

Run ONCE after deploying entity_resolver.py to clean up existing
duplicates already stored in AstraDB.

What it does
────────────
1. Loads every entity from the 'entities' collection
2. Resolves each name via entity_resolver.resolve_canonical()
3. Groups entities that resolve to the same canonical name
4. For each group, elects a WINNER (highest mention_count)
5. Re-points all event_entity and graph_edge links from losers → winner
6. Merges aliases and mention_counts onto the winner document
7. Deletes the loser documents

Dry-run mode (default):  prints what would be merged, touches nothing.
Live mode:               python merge_duplicate_entities.py --live

Usage
─────
  cd backend
  python scripts/merge_duplicate_entities.py            # dry-run
  python scripts/merge_duplicate_entities.py --live     # commit merges
  python scripts/merge_duplicate_entities.py --live --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make backend/ importable
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("merge")

# ─────────────────────────────────────────────────────────────────────────────

def load_all_entities() -> list[dict]:
    from astra_client import entities as _ent
    logger.info("Loading entities from AstraDB …")
    docs = list(_ent().find(
        {},
        projection={"_id": 1, "name": 1, "type": 1, "mention_count": 1,
                    "normalized_name": 1, "aliases": 1},
        limit=5000,
    ))
    logger.info("Loaded %d entities", len(docs))
    return docs


def group_by_canonical(entities: list[dict]) -> dict[str, list[dict]]:
    """
    Map canonical_name → [entity_doc, ...] for all entities that share a canonical.
    Groups with only one member are not duplicates and are skipped.
    """
    from entity_resolver import resolve_canonical

    groups: dict[str, list[dict]] = defaultdict(list)
    for doc in entities:
        name  = doc.get("name", "")
        etype = doc.get("type", "person")
        canonical = resolve_canonical(name, etype)
        groups[canonical].append(doc)

    # Return only groups with duplicates
    return {k: v for k, v in groups.items() if len(v) > 1}


def elect_winner(group: list[dict]) -> dict:
    """
    Winner = the entity with the most mentions.
    Tiebreak: prefer the one whose name equals the canonical form
    (longest name = most complete).
    """
    return max(
        group,
        key=lambda d: (d.get("mention_count", 0), len(d.get("name", ""))),
    )


def merge_group(
    canonical: str,
    group:     list[dict],
    live:      bool,
    verbose:   bool,
) -> int:
    """
    Merge all losers into winner.  Returns number of merges performed.
    """
    from astra_client import (
        entities as _ent,
        event_entities as _ee,
    )

    winner = elect_winner(group)
    losers = [d for d in group if d["_id"] != winner["_id"]]

    total_mentions = sum(d.get("mention_count", 0) for d in group)
    all_aliases    = set()
    for d in group:
        all_aliases.add(d.get("name", "").lower())
        all_aliases.update(d.get("aliases", []))
    all_aliases.discard(winner.get("name", "").lower())

    loser_names = [d["name"] for d in losers]

    if verbose:
        logger.info(
            "  MERGE → '%s'  (winner: '%s' | absorbing: %s | total_mentions=%d)",
            canonical, winner["name"], loser_names, total_mentions,
        )

    if not live:
        return len(losers)

    for loser in losers:
        loser_id  = loser["_id"]
        winner_id = winner["_id"]

        # 1. Re-point event_entity links
        try:
            ee_rows = list(_ee().find({"entity_id": loser_id}, projection={"_id": 1}))
            for row in ee_rows:
                # Check if winner already linked to same event (avoid duplicate links)
                ev_id = row.get("event_id")
                exists = _ee().find_one({"entity_id": winner_id, "event_id": ev_id})
                if exists:
                    _ee().delete_one({"_id": row["_id"]})
                else:
                    _ee().update_one(
                        {"_id": row["_id"]},
                        {"$set": {"entity_id": winner_id}},
                    )
        except Exception as exc:
            logger.warning("    event_entity re-point error for %s: %s", loser_id, exc)

        # 2. Re-point knowledge graph edges
        try:
            from astra_client import graph_edges as _ge
            _ge().update_many({"source_id": loser_id}, {"$set": {"source_id": winner_id}})
            _ge().update_many({"target_id": loser_id}, {"$set": {"target_id": winner_id}})
        except Exception as exc:
            logger.debug("    graph_edge re-point error (non-fatal): %s", exc)

        # 3. Delete the loser entity
        try:
            _ent().delete_one({"_id": loser_id})
        except Exception as exc:
            logger.warning("    delete loser %s error: %s", loser_id, exc)

    # 4. Update winner: merged mention count + aliases
    try:
        _ent().update_one(
            {"_id": winner_id},
            {"$set": {
                "mention_count":   total_mentions,
                "canonical_name":  canonical,
                "aliases":         sorted(all_aliases),
            }},
        )
    except Exception as exc:
        logger.warning("  winner update error: %s", exc)

    return len(losers)


def run(live: bool, verbose: bool) -> None:
    mode = "LIVE" if live else "DRY-RUN"
    logger.info("=== Entity Deduplication — %s ===", mode)

    entities = load_all_entities()
    if not entities:
        logger.info("No entities found. Nothing to do.")
        return

    groups = group_by_canonical(entities)
    logger.info("Found %d duplicate groups", len(groups))

    if not groups:
        logger.info("No duplicates detected. Database is clean.")
        return

    total_merged = 0
    for canonical, group in sorted(groups.items()):
        merged = merge_group(canonical, group, live=live, verbose=verbose or not live)
        total_merged += merged

    logger.info("")
    logger.info("─────────────────────────────────────────")
    if live:
        logger.info("Done. Merged %d duplicate entity documents.", total_merged)
    else:
        logger.info(
            "Dry-run complete. Would merge %d documents across %d groups.",
            total_merged, len(groups),
        )
        logger.info("Run with --live to apply changes.")


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retroactive entity deduplication for Garuda v3"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Apply merges (default: dry-run only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print every merge decision",
    )
    args = parser.parse_args()

    # Load .env if present
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
        logger.info("Loaded .env from %s", env_path)

    run(live=args.live, verbose=args.verbose)


if __name__ == "__main__":
    main()
