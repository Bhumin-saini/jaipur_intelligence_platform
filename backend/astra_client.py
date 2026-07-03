"""
Garuda v3 — AstraDB Connection Layer
Single import point for all AstraDB collection accessors.
Uses lru_cache so the connection is created once per process.
"""
import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

ASTRA_TOKEN    = os.environ.get("ASTRA_DB_APPLICATION_TOKEN", "")
ASTRA_DB_ID    = os.environ.get("ASTRA_DB_ID", "")
ASTRA_REGION   = os.environ.get("ASTRA_DB_REGION", "ap-south-1")
ASTRA_KEYSPACE = os.environ.get("ASTRA_DB_KEYSPACE", "garuda")


@lru_cache(maxsize=1)
def get_db():
    """Return a connected AstraDB Database object (cached)."""
    if not ASTRA_TOKEN or not ASTRA_DB_ID:
        raise EnvironmentError(
            "ASTRA_DB_APPLICATION_TOKEN and ASTRA_DB_ID must be set in .env"
        )
    from astrapy import DataAPIClient
    client = DataAPIClient(ASTRA_TOKEN)
    endpoint = (
        f"https://{ASTRA_DB_ID}-{ASTRA_REGION}.apps.astra.datastax.com"
    )
    db = client.get_database(endpoint, keyspace=ASTRA_KEYSPACE)
    logger.info("AstraDB connected — keyspace=%s", ASTRA_KEYSPACE)
    return db


# ── Core collections ──────────────────────────────────────────────────────────

def articles():
    return get_db().get_collection("articles")

def events():
    return get_db().get_collection("events")

def entities():
    return get_db().get_collection("entities")

def event_entities():
    return get_db().get_collection("event_entities")

def briefs():
    return get_db().get_collection("intelligence_briefs")


# ── v3: Knowledge Graph collections ──────────────────────────────────────────

def graph_nodes():
    return get_db().get_collection("graph_nodes")

def graph_edges():
    return get_db().get_collection("graph_edges")

def event_links():
    return get_db().get_collection("event_links")


# ── v3: Case Management collections ──────────────────────────────────────────

def cases():
    return get_db().get_collection("cases")

def case_events():
    return get_db().get_collection("case_events")

def annotations():
    return get_db().get_collection("annotations")


# ── v3: Watchlist & Alert collections ────────────────────────────────────────

def watchlist():
    return get_db().get_collection("watchlist")

def watchlist_alerts():
    return get_db().get_collection("watchlist_alerts")


# ── v3: Hypothesis & Evidence collections ────────────────────────────────────

def hypotheses():
    return get_db().get_collection("hypotheses")

def evidence():
    return get_db().get_collection("evidence")


# ── v3: Prediction & Source Credibility collections ───────────────────────────

def predictions():
    return get_db().get_collection("predictions")

def source_scores():
    return get_db().get_collection("source_scores")


# ── v3: Copilot History ───────────────────────────────────────────────────────

def copilot_history():
    return get_db().get_collection("copilot_history")


def insights():
    return get_db().get_collection("insights")


# ── Health check ──────────────────────────────────────────────────────────────
def ping() -> bool:
    """Return True if AstraDB is reachable."""
    try:
        get_db().list_collection_names()
        return True
    except Exception as exc:
        logger.warning("AstraDB ping failed: %s", exc)
        return False
