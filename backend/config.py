"""
Garuda — Collection Configuration & Bootstrap (config.py)

ADR-001: Single source of truth for AstraDB collection definitions.

Used by:
  - main.py     → calls bootstrap_collections() on every startup (idempotent)
  - scripts/init_astra_v3.py → delegates to bootstrap_collections()

Adding a new collection: put it here. Nowhere else.
"""
import logging
import os

logger = logging.getLogger(__name__)

DIM = int(os.environ.get("EMBEDDING_DIM", "3072"))

# Maps collection name → vector options dict  OR  None (non-vector / no SAI indexes)
# None collections use indexing={"deny": ["*"]} to stay within AstraDB free-tier
# index limits (100 SAI indexes max).
COLLECTIONS: dict[str, dict | None] = {
    # ── v2: Vector collections ────────────────────────────────────────────────
    "articles":            {"dimension": DIM, "metric": "cosine"},
    "events":              {"dimension": DIM, "metric": "cosine"},
    "entities":            {"dimension": DIM, "metric": "cosine"},
    "intelligence_briefs": {"dimension": DIM, "metric": "cosine"},

    # ── v2: Non-vector ────────────────────────────────────────────────────────
    "event_entities":      None,

    # ── v3: Knowledge Graph ───────────────────────────────────────────────────
    "graph_nodes":         None,
    "graph_edges":         None,
    "event_links":         None,

    # ── v3: Case Management ───────────────────────────────────────────────────
    "cases":               None,
    "case_events":         None,
    "annotations":         None,

    # ── v3: Watchlist ─────────────────────────────────────────────────────────
    "watchlist":           None,
    "watchlist_alerts":    None,

    # ── v3: Hypothesis & Evidence ─────────────────────────────────────────────
    "hypotheses":          None,
    "evidence":            None,

    # ── v3: Predictions & Source Credibility ──────────────────────────────────
    "predictions":         None,
    "source_scores":       None,

    # ── v3: Analyst Copilot ───────────────────────────────────────────────────
    "copilot_history":     None,

    # ── v3: Insights (C-01 fix) ───────────────────────────────────────────────
    "insights":            None,

    # ── v3: Ingestion & Dead-letter Logs ─────────────────────────────────────
    "ingestion_logs":      None,
}


def bootstrap_collections(db) -> list[str]:
    """
    Idempotent bootstrap: create any missing AstraDB collections.

    Safe to call on every startup — skips collections that already exist.
    Returns the list of collection names that were newly created (empty list
    means everything was already in place).

    Raises nothing — all errors are logged so a partial bootstrap failure
    never prevents the application from starting.
    """
    try:
        existing = set(db.list_collection_names())
    except Exception as exc:
        logger.error("bootstrap_collections: cannot list existing collections — %s", exc)
        return []

    logger.info(
        "Bootstrap: %d collections exist, %d expected",
        len(existing), len(COLLECTIONS),
    )

    created: list[str] = []
    for name, vector_opts in COLLECTIONS.items():
        if name in existing:
            logger.debug("  ✓ %s", name)
            continue
        try:
            if vector_opts:
                db.create_collection(
                    name,
                    dimension=vector_opts["dimension"],
                    metric=vector_opts["metric"],
                )
                logger.info("  + Created vector collection: %s (dim=%d)", name, vector_opts["dimension"])
            else:
                # indexing deny avoids SAI index creation (free tier = 100 index limit)
                db.create_collection(name, indexing={"deny": ["*"]})
                logger.info("  + Created collection: %s", name)
            created.append(name)
        except Exception as exc:
            logger.error("  ✗ Failed to create %s: %s", name, exc)

    if created:
        logger.warning(
            "Bootstrap created %d missing collection(s): %s",
            len(created), created,
        )
    else:
        logger.info("Bootstrap complete — all %d collections present.", len(COLLECTIONS))

    return created


def missing_collections(db) -> list[str]:
    """
    Return the list of expected collection names that are not yet in AstraDB.
    Used by /health to report readiness.
    """
    try:
        existing = set(db.list_collection_names())
        return [name for name in COLLECTIONS if name not in existing]
    except Exception as exc:
        logger.warning("missing_collections check failed: %s", exc)
        return list(COLLECTIONS.keys())
