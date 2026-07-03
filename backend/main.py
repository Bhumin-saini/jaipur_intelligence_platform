"""
Garuda v3 — FastAPI Backend (AstraDB + Knowledge Graph + Intelligence Layer)

v2 Endpoints (preserved):
  GET  /events                → map markers
  GET  /events/{id}           → event detail
  GET  /events/{id}/similar   → semantically similar events
  GET  /entities              → entity list
  GET  /entities/{id}         → entity detail
  GET  /entities/{id}/network → co-occurrence graph
  GET  /graph-data            → nodes + edges
  GET  /stats                 → dashboard counters
  GET  /metrics               → full metrics
  GET  /search                → semantic event search
  GET  /trends                → trend alerts
  GET  /anomalies             → anomaly alerts
  GET  /briefs                → briefs index
  GET  /briefs/{id}           → full brief
  POST /briefs/generate       → on-demand brief
  GET  /heatmap               → lat/lng density
  GET  /timeline              → timeline summary
  GET  /health                → health check
  POST /scrape                → trigger scrape

v3 Endpoints (new):

Knowledge Graph:
  GET  /graph/nodes           → typed entity nodes
  GET  /graph/nodes/{id}      → single node + subgraph
  GET  /graph/edges           → relationship edges
  GET  /graph/communities     → community detection
  GET  /graph/stats           → graph statistics
  POST /graph/build           → rebuild graph from entities
  GET  /graph/event-links/{id}→ links for an event
  GET  /graph/event-chain/{id}→ causal chain from event

Cases:
  GET  /cases                 → list cases
  POST /cases                 → create case
  GET  /cases/{id}            → get case
  PUT  /cases/{id}            → update case
  DELETE /cases/{id}          → delete case
  POST /cases/{id}/close      → close case
  GET  /cases/{id}/events     → events in case
  POST /cases/{id}/events     → add event to case
  DELETE /cases/{id}/events/{eid} → remove event
  GET  /cases/{id}/annotations → case annotations
  POST /cases/{id}/annotations → add annotation
  DELETE /annotations/{id}    → delete annotation
  GET  /cases/{id}/risk       → compute risk score
  GET  /cases/{id}/export     → export full case

Watchlist:
  GET  /watchlist             → list watchlist items
  POST /watchlist             → create watchlist item
  GET  /watchlist/{id}        → get item
  PUT  /watchlist/{id}        → update item
  DELETE /watchlist/{id}      → delete item
  GET  /alerts                → get alerts
  POST /alerts/check          → trigger alert check
  POST /alerts/{id}/read      → mark alert read
  POST /alerts/read-all       → mark all read
  GET  /alerts/unread-count   → unread count

Hypothesis:
  GET  /hypotheses            → list hypotheses
  POST /hypotheses            → create hypothesis
  GET  /hypotheses/{id}       → get hypothesis
  PUT  /hypotheses/{id}       → update hypothesis
  DELETE /hypotheses/{id}     → delete hypothesis
  GET  /hypotheses/{id}/evidence → get evidence
  POST /hypotheses/{id}/evidence → add evidence
  DELETE /evidence/{id}       → remove evidence
  POST /hypotheses/{id}/evaluate → LLM evaluation
  POST /hypotheses/{id}/auto-evidence → auto gather

Predictions:
  GET  /predict               → get stored predictions
  GET  /predict/{event_type}  → forecast specific type
  GET  /predict/hotspots      → geographic hotspots
  POST /predict/generate      → run all predictions

Source Credibility:
  GET  /sources               → source credibility scores

Analyst Copilot:
  POST /copilot               → query copilot
  GET  /copilot/history       → session history
  GET  /copilot/sessions      → all sessions
  DELETE /copilot/history/{session_id} → clear session
"""
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline import get_scrape_status, run_scrape_cycle

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


# ── TTL Cache ─────────────────────────────────────────────────────────────────

class _TTLCache:
    def __init__(self):
        self._store: dict = {}
        self._lock  = Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry and time.monotonic() < entry["expires"]:
                return entry["value"], True
            return None, False

    def set(self, key: str, value, ttl: int):
        with self._lock:
            self._store[key] = {"value": value, "expires": time.monotonic() + ttl}

    def invalidate(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

_cache = _TTLCache()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Garuda v3 starting — AstraDB + Knowledge Graph mode")

    # ── ADR-001: Idempotent collection bootstrap ───────────────────────────────
    # Ensures all 21 AstraDB collections exist before any job or request runs.
    # Safe to call on every startup — skips collections that already exist.
    _missing: list[str] = []
    try:
        from astra_client import ping, get_db
        if ping():
            logger.info("AstraDB connection OK")
            from config import bootstrap_collections, missing_collections
            bootstrap_collections(get_db())
            _missing = missing_collections(get_db())
            if _missing:
                logger.warning("Collections still missing after bootstrap: %s", _missing)
        else:
            logger.warning("AstraDB ping failed — check ASTRA_DB_* env vars")
    except Exception as exc:
        logger.warning("AstraDB bootstrap skipped: %s", exc)

    # ── ADR-004-H02: Register cache invalidator with pipeline ──────────────────
    try:
        from pipeline import set_cache_invalidator
        set_cache_invalidator(_cache.clear)
        logger.info("Cache invalidator registered with pipeline")
    except Exception as exc:
        logger.warning("Cache invalidator registration failed: %s", exc)

    # ── ADR-003: Persistent APScheduler job store ──────────────────────────────
    # SQLAlchemyJobStore persists job state to a SQLite file so missed intervals
    # are recovered on restart (coalesce=True fires once, not N times per gap).
    scheduler_db = os.environ.get("SCHEDULER_DB_PATH", "./garuda_jobs.db")
    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{scheduler_db}")}
        logger.info("Scheduler using persistent SQLite job store: %s", scheduler_db)
    except ImportError:
        logger.warning(
            "SQLAlchemy not installed — scheduler using in-memory job store. "
            "Run: pip install sqlalchemy"
        )
        jobstores = {}

    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        job_defaults={"coalesce": True, "max_instances": 1},
    )

    interval = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "15"))
    scheduler.add_job(
        run_scrape_cycle, "interval", minutes=interval,
        id="scrape_cycle", misfire_grace_time=120, replace_existing=True,
    )

    try:
        from analyst import register_analysis_jobs
        register_analysis_jobs(scheduler)
    except Exception as exc:
        logger.warning("Could not register analysis jobs: %s", exc)

    # v3: Register watchlist check job (every 60 min)
    try:
        from watchlist import check_watchlist
        scheduler.add_job(
            check_watchlist, "interval", minutes=60,
            id="watchlist_check", misfire_grace_time=300,
            replace_existing=True,
        )
        logger.info("Watchlist check registered — every 60 minutes")
    except Exception as exc:
        logger.warning("Watchlist check job failed: %s", exc)

    # v3: Register prediction job (every 6 hours)
    try:
        from predictor import generate_predictions
        scheduler.add_job(
            generate_predictions, "interval", hours=6,
            id="prediction_job", misfire_grace_time=600,
            replace_existing=True,
        )
        logger.info("Prediction job registered — every 6 hours")
    except Exception as exc:
        logger.warning("Prediction job failed: %s", exc)

    # v3: Register graph build job (every 12 hours)
    try:
        from knowledge_graph import build_graph_from_entities
        scheduler.add_job(
            build_graph_from_entities, "interval", hours=12,
            id="graph_build", misfire_grace_time=1200,
            replace_existing=True, kwargs={"days": 30},
        )
        logger.info("Graph build job registered — every 12 hours")
    except Exception as exc:
        logger.warning("Graph build job failed: %s", exc)

    # ADR-002: Register graph reconciliation safety-net (every 6 hours)
    try:
        from knowledge_graph import reconcile_graph_nodes
        scheduler.add_job(
            reconcile_graph_nodes, "interval", hours=6,
            id="graph_reconcile", misfire_grace_time=600,
            replace_existing=True, kwargs={"days": 7},
        )
        logger.info("Graph reconciliation job registered — every 6 hours")
    except Exception as exc:
        logger.warning("Graph reconciliation job failed: %s", exc)

    # v3: Insight pipeline (every 4 hours)
    try:
        from insights import run_insight_pipeline
        scheduler.add_job(
            run_insight_pipeline, "interval", hours=4,
            id="insight_pipeline", misfire_grace_time=600,
            replace_existing=True,
        )
        logger.info("Insight pipeline registered — every 4 hours")
    except Exception as exc:
        logger.warning("Insight pipeline job failed: %s", exc)

    scheduler.start()
    logger.info("Scheduler started — scrape every %dm", interval)
    yield
    scheduler.shutdown(wait=False)


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Jaipur Intelligence Platform API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_admin(x_api_key: str | None):
    scrape_api_key = os.environ.get("SCRAPE_API_KEY", "")
    if scrape_api_key and x_api_key != scrape_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Pydantic Models ────────────────────────────────────────────────────────────

class CreateCaseBody(BaseModel):
    title: str
    description: str = ""
    category: str = "general"
    priority: str = "medium"
    tags: List[str] = []
    analyst: str = "analyst"

class UpdateCaseBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None

class AddCaseEventBody(BaseModel):
    event_id: str
    relevance_note: str = ""

class AddAnnotationBody(BaseModel):
    text: str
    annotation_type: str = "note"
    event_id: Optional[str] = None
    analyst: str = "analyst"
    tags: List[str] = []

class CreateWatchlistBody(BaseModel):
    name: str
    description: str = ""
    watch_type: str = "keyword"
    keywords: List[str] = []
    entity_ids: List[str] = []
    locations: List[str] = []
    event_types: List[str] = []
    min_severity: str = "medium"
    analyst: str = "analyst"

class UpdateWatchlistBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    entity_ids: Optional[List[str]] = None
    locations: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    min_severity: Optional[str] = None
    active: Optional[bool] = None

class CreateHypothesisBody(BaseModel):
    statement: str
    case_id: Optional[str] = None
    analyst: str = "analyst"
    tags: List[str] = []
    initial_confidence: float = 0.5

class AddEvidenceBody(BaseModel):
    event_id: Optional[str] = None
    text: str = ""
    stance: str = "supporting"
    strength: float = 0.5
    source: str = ""
    analyst: str = "analyst"

class CopilotQueryBody(BaseModel):
    query: str
    session_id: Optional[str] = None
    include_context: bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# V2 ENDPOINTS (preserved)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    from astra_client import ping, get_db
    astra_ok = ping()

    # ADR-001: Report any collections that are still missing after bootstrap
    missing: list[str] = []
    if astra_ok:
        try:
            from config import missing_collections
            missing = missing_collections(get_db())
        except Exception:
            pass

    # ADR-002: Report dead-letter count from the graph retry queue
    dead_letters = 0
    queue_depth  = 0
    try:
        import graph_queue
        dead_letters = graph_queue.get_dead_letter_count()
        queue_depth  = graph_queue.get_queue_depth()
    except Exception:
        pass

    status = "ok"
    if not astra_ok:
        status = "degraded"
    elif missing:
        status = "degraded"

    return {
        "status":             status,
        "astra":              astra_ok,
        "version":            "3.0.0",
        "scrape":             get_scrape_status(),
        "collections_ok":     len(missing) == 0,
        "missing_collections": missing,
        "graph_dead_letters": dead_letters,
        "graph_queue_depth":  queue_depth,
    }


@app.get("/events")
def list_events(severity: str = Query(None), event_type: str = Query(None),
                limit: int = Query(200, le=500), from_date: str = Query(None), to_date: str = Query(None)):
    cache_key = f"events_{severity}_{event_type}_{limit}_{from_date}_{to_date}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    result = store.list_events(severity=severity, event_type=event_type, limit=limit, from_date=from_date, to_date=to_date)
    _cache.set(cache_key, result, ttl=60)
    return result


@app.get("/events/{event_id}/similar")
def similar_events(event_id: str, limit: int = Query(5, le=10)):
    cache_key = f"similar_{event_id}_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    result = store.get_similar_events(event_id, limit=limit)
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/timeline")
def timeline(days: int = Query(30, ge=7, le=90)):
    cache_key = f"timeline_{days}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    result = store.get_timeline_summary(days=days)
    _cache.set(cache_key, result, ttl=120)
    return result


@app.get("/events/{event_id}")
def get_event(event_id: str):
    cache_key = f"event_{event_id}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    doc = store.get_event(event_id)
    if not doc: raise HTTPException(404, "Event not found")
    _cache.set(cache_key, doc, ttl=300)
    return doc


@app.get("/entities")
def list_entities(type: str = Query(None), limit: int = Query(100, le=500)):
    cache_key = f"entities_{type}_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    result = store.list_entities(entity_type=type, limit=limit)
    _cache.set(cache_key, result, ttl=120)
    return result


@app.get("/entities/{entity_id}/network")
def entity_network(entity_id: str, depth: int = Query(1, ge=1, le=2)):
    cache_key = f"network_{entity_id}_{depth}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from analyst import entity_network as _network
    result = _network(entity_id, depth=depth)
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/entities/{entity_id}")
def get_entity(entity_id: str):
    cache_key = f"entity_{entity_id}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    doc = store.get_entity(entity_id)
    if not doc: raise HTTPException(404, "Entity not found")
    _cache.set(cache_key, doc, ttl=300)
    return doc


@app.get("/graph-data")
def graph_data(limit: int = Query(50, le=200), inferred: bool = Query(False)):
    cache_key = f"graph_{limit}_{inferred}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    import astra_store as store
    result = store.graph_data(limit=limit, inferred=inferred)
    _cache.set(cache_key, result, ttl=120)
    return result


@app.get("/stats")
def stats():
    cached, hit = _cache.get("stats")
    if hit: return cached
    import astra_store as store
    result = store.stats(scrape_status=get_scrape_status())
    _cache.set("stats", result, ttl=60)
    return result


@app.get("/metrics")
def metrics():
    cached, hit = _cache.get("metrics")
    if hit: return cached
    import astra_store as store
    result = store.metrics(scrape_status=get_scrape_status())
    _cache.set("metrics", result, ttl=120)
    return result


@app.post("/scrape")
def trigger_scrape(bg: BackgroundTasks, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_admin(x_api_key)
    scrape = get_scrape_status()
    if scrape.get("running"):
        return {"status": "scrape already running", "running": True}
    _cache.clear()
    bg.add_task(run_scrape_cycle)
    return {"status": "scrape cycle queued", "running": False}


@app.get("/search")
def search_events(q: str = Query(..., min_length=1), severity: str = Query(None),
                  event_type: str = Query(None), limit: int = Query(20, le=50)):
    from analyst import semantic_search
    results = semantic_search(query=q, limit=limit, severity_filter=severity, event_type_filter=event_type)
    return {"query": q, "count": len(results), "results": results}


@app.get("/trends")
def trends(hours: int = Query(48, ge=6, le=168)):
    cache_key = f"trends_{hours}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from analyst import detect_trends
    result = {"trends": detect_trends(window_hours=hours)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/anomalies")
def anomalies(days: int = Query(30, ge=7, le=90)):
    cache_key = f"anomalies_{days}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from analyst import detect_anomalies
    result = {"anomalies": detect_anomalies(lookback_days=days)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/briefs")
def list_briefs(type: str = Query(None), limit: int = Query(20, le=100)):
    cache_key = f"briefs_{type}_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from analyst import get_briefs
    result = {"briefs": get_briefs(brief_type=type, limit=limit)}
    _cache.set(cache_key, result, ttl=120)
    return result


@app.get("/briefs/{brief_id}")
def get_brief(brief_id: str):
    from analyst import get_brief as _get
    doc = _get(brief_id)
    if not doc: raise HTTPException(404, "Brief not found")
    return doc


@app.post("/briefs/generate")
def generate_brief(brief_type: str = Body("daily_summary", embed=True),
                   date: str = Body(None, embed=True),
                   x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_admin(x_api_key)
    from analyst import generate_daily_brief, generate_weekly_brief
    _cache.invalidate("briefs_None_20")
    if brief_type == "weekly_briefing":
        brief_id = generate_weekly_brief()
    else:
        brief_id = generate_daily_brief(target_date=date)
    if not brief_id:
        raise HTTPException(500, "Brief generation failed")
    return {"brief_id": brief_id, "status": "generated"}


@app.get("/heatmap")
def heatmap(event_type: str = Query(None), severity: str = Query(None), days: int = Query(7, ge=1, le=90)):
    cache_key = f"heatmap_{event_type}_{severity}_{days}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from analyst import get_heatmap
    points = get_heatmap(event_type=event_type, severity=severity, days=days)
    result = {"count": len(points), "points": points}
    _cache.set(cache_key, result, ttl=300)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Knowledge Graph
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/graph/nodes")
def graph_nodes(node_type: str = Query(None), limit: int = Query(100, le=500),
                min_mentions: int = Query(1, ge=1)):
    cache_key = f"graph_nodes_{node_type}_{limit}_{min_mentions}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from knowledge_graph import list_nodes
    result = {"nodes": list_nodes(node_type=node_type, limit=limit, min_mentions=min_mentions)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/graph/nodes/{node_id}")
def graph_node_detail(node_id: str, depth: int = Query(2, ge=1, le=3)):
    from knowledge_graph import get_subgraph
    result = get_subgraph(center_id=node_id, depth=depth)
    if not result.get("nodes"):
        raise HTTPException(404, "Node not found")
    return result


@app.get("/graph/edges")
def graph_edges_list(limit: int = Query(200, le=1000)):
    cache_key = f"graph_edges_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from knowledge_graph import list_all_edges
    result = {"edges": list_all_edges(limit=limit)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/graph/communities")
def graph_communities():
    cache_key = "graph_communities"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from knowledge_graph import detect_communities
    result = {"communities": detect_communities()}
    _cache.set(cache_key, result, ttl=600)
    return result


@app.get("/graph/stats")
def graph_stats():
    cache_key = "graph_stats"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from knowledge_graph import graph_stats as _gs
    result = _gs()
    _cache.set(cache_key, result, ttl=120)
    return result


@app.post("/graph/build")
def build_graph(days: int = Body(30, embed=True),
                x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_admin(x_api_key)
    from knowledge_graph import build_graph_from_entities
    _cache.invalidate("graph_stats")
    edges = build_graph_from_entities(days=days)
    return {"status": "built", "edges_created": edges}


@app.get("/graph/event-links/{event_id}")
def event_links(event_id: str):
    from knowledge_graph import get_event_links
    return {"event_id": event_id, "links": get_event_links(event_id)}


@app.get("/graph/event-chain/{event_id}")
def event_chain(event_id: str, max_hops: int = Query(5, ge=1, le=10)):
    from knowledge_graph import get_event_chain
    return {"event_id": event_id, "chain": get_event_chain(event_id, max_hops=max_hops)}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Case Management
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/cases")
def list_cases(status: str = Query(None), category: str = Query(None),
               priority: str = Query(None), limit: int = Query(50, le=200)):
    from case_manager import list_cases as _list
    return {"cases": _list(status=status, category=category, priority=priority, limit=limit)}


@app.post("/cases")
def create_case(body: CreateCaseBody):
    from case_manager import create_case as _create
    case_id = _create(
        title=body.title, description=body.description,
        category=body.category, priority=body.priority,
        tags=body.tags, analyst=body.analyst,
    )
    return {"case_id": case_id, "status": "created"}


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    from case_manager import get_case as _get
    doc = _get(case_id)
    if not doc: raise HTTPException(404, "Case not found")
    return doc


@app.put("/cases/{case_id}")
def update_case(case_id: str, body: UpdateCaseBody):
    from case_manager import update_case as _update
    _update(case_id, **body.model_dump(exclude_none=True))
    return {"status": "updated"}


@app.delete("/cases/{case_id}")
def delete_case(case_id: str):
    from case_manager import delete_case as _delete
    ok = _delete(case_id)
    if not ok: raise HTTPException(500, "Delete failed")
    return {"status": "deleted"}


@app.post("/cases/{case_id}/close")
def close_case(case_id: str, resolution: str = Body("", embed=True)):
    from case_manager import close_case as _close
    _close(case_id, resolution=resolution)
    return {"status": "closed"}


@app.get("/cases/{case_id}/events")
def get_case_events(case_id: str, limit: int = Query(100, le=200)):
    from case_manager import get_case_events as _get
    return {"events": _get(case_id, limit=limit)}


@app.post("/cases/{case_id}/events")
def add_case_event(case_id: str, body: AddCaseEventBody):
    from case_manager import add_case_event as _add
    _add(case_id, body.event_id, relevance_note=body.relevance_note)
    return {"status": "added"}


@app.delete("/cases/{case_id}/events/{event_id}")
def remove_case_event(case_id: str, event_id: str):
    from case_manager import remove_case_event as _remove
    _remove(case_id, event_id)
    return {"status": "removed"}


@app.get("/cases/{case_id}/annotations")
def get_annotations(case_id: str, annotation_type: str = Query(None),
                    limit: int = Query(50, le=200)):
    from case_manager import get_annotations as _get
    return {"annotations": _get(case_id, annotation_type=annotation_type, limit=limit)}


@app.post("/cases/{case_id}/annotations")
def add_annotation(case_id: str, body: AddAnnotationBody):
    from case_manager import add_annotation as _add
    ann_id = _add(
        case_id=case_id, text=body.text, annotation_type=body.annotation_type,
        event_id=body.event_id, analyst=body.analyst, tags=body.tags,
    )
    return {"annotation_id": ann_id, "status": "added"}


@app.delete("/annotations/{annotation_id}")
def delete_annotation(annotation_id: str):
    from case_manager import delete_annotation as _del
    _del(annotation_id)
    return {"status": "deleted"}


@app.get("/cases/{case_id}/risk")
def case_risk(case_id: str):
    from case_manager import compute_case_risk
    return compute_case_risk(case_id)


@app.get("/cases/{case_id}/export")
def export_case(case_id: str):
    from case_manager import export_case as _export
    data = _export(case_id)
    if not data: raise HTTPException(404, "Case not found")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Watchlist & Alerts
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/watchlist")
def list_watchlist(active_only: bool = Query(True), limit: int = Query(50, le=200)):
    from watchlist import list_watchlist as _list
    return {"items": _list(active_only=active_only, limit=limit)}


@app.post("/watchlist")
def create_watchlist(body: CreateWatchlistBody):
    from watchlist import create_watchlist_item
    item_id = create_watchlist_item(
        name=body.name, description=body.description, watch_type=body.watch_type,
        keywords=body.keywords, entity_ids=body.entity_ids, locations=body.locations,
        event_types=body.event_types, min_severity=body.min_severity, analyst=body.analyst,
    )
    return {"item_id": item_id, "status": "created"}


@app.get("/watchlist/{item_id}")
def get_watchlist_item(item_id: str):
    from watchlist import get_watchlist_item as _get
    doc = _get(item_id)
    if not doc: raise HTTPException(404, "Watchlist item not found")
    return doc


@app.put("/watchlist/{item_id}")
def update_watchlist(item_id: str, body: UpdateWatchlistBody):
    from watchlist import update_watchlist_item
    update_watchlist_item(item_id, **body.model_dump(exclude_none=True))
    return {"status": "updated"}


@app.delete("/watchlist/{item_id}")
def delete_watchlist(item_id: str):
    from watchlist import delete_watchlist_item
    ok = delete_watchlist_item(item_id)
    if not ok: raise HTTPException(500, "Delete failed")
    return {"status": "deleted"}


@app.get("/alerts")
def get_alerts(watchlist_id: str = Query(None), unread_only: bool = Query(False),
               limit: int = Query(50, le=200)):
    from watchlist import get_alerts as _get
    return {"alerts": _get(watchlist_id=watchlist_id, unread_only=unread_only, limit=limit)}


@app.get("/alerts/unread-count")
def unread_alert_count():
    from watchlist import get_unread_alert_count
    return {"count": get_unread_alert_count()}


@app.post("/alerts/check")
def trigger_alert_check(bg: BackgroundTasks,
                        x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_admin(x_api_key)
    from watchlist import check_watchlist
    bg.add_task(check_watchlist)
    return {"status": "alert check queued"}


@app.post("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: str):
    from watchlist import mark_alert_read as _mark
    _mark(alert_id)
    return {"status": "marked read"}


@app.post("/alerts/read-all")
def mark_all_alerts_read():
    from watchlist import mark_all_alerts_read as _mark
    _mark()
    return {"status": "all marked read"}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Hypothesis Testing
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/hypotheses")
def list_hypotheses(case_id: str = Query(None), status: str = Query(None),
                    limit: int = Query(50, le=200)):
    from hypothesis import list_hypotheses as _list
    return {"hypotheses": _list(case_id=case_id, status=status, limit=limit)}


@app.post("/hypotheses")
def create_hypothesis(body: CreateHypothesisBody):
    from hypothesis import create_hypothesis as _create
    hyp_id = _create(
        statement=body.statement, case_id=body.case_id,
        analyst=body.analyst, tags=body.tags,
        initial_confidence=body.initial_confidence,
    )
    return {"hypothesis_id": hyp_id, "status": "created"}


@app.get("/hypotheses/{hyp_id}")
def get_hypothesis(hyp_id: str):
    from hypothesis import get_hypothesis as _get
    doc = _get(hyp_id)
    if not doc: raise HTTPException(404, "Hypothesis not found")
    return doc


@app.put("/hypotheses/{hyp_id}")
def update_hypothesis(hyp_id: str, body: dict = Body(...)):
    from hypothesis import update_hypothesis as _update
    _update(hyp_id, **{k: v for k, v in body.items() if k in {"statement", "status", "case_id", "tags"}})
    return {"status": "updated"}


@app.delete("/hypotheses/{hyp_id}")
def delete_hypothesis(hyp_id: str):
    from hypothesis import delete_hypothesis as _del
    _del(hyp_id)
    return {"status": "deleted"}


@app.get("/hypotheses/{hyp_id}/evidence")
def get_evidence(hyp_id: str, stance: str = Query(None), limit: int = Query(50, le=200)):
    from hypothesis import get_evidence as _get
    return {"evidence": _get(hyp_id, stance=stance, limit=limit)}


@app.post("/hypotheses/{hyp_id}/evidence")
def add_evidence(hyp_id: str, body: AddEvidenceBody):
    from hypothesis import add_evidence as _add
    ev_id = _add(
        hypothesis_id=hyp_id, event_id=body.event_id, text=body.text,
        stance=body.stance, strength=body.strength, source=body.source, analyst=body.analyst,
    )
    return {"evidence_id": ev_id, "status": "added"}


@app.delete("/evidence/{evidence_id}")
def remove_evidence(evidence_id: str):
    from hypothesis import remove_evidence as _remove
    _remove(evidence_id)
    return {"status": "removed"}


@app.post("/hypotheses/{hyp_id}/evaluate")
def evaluate_hypothesis(hyp_id: str):
    from hypothesis import evaluate_hypothesis as _eval
    result = _eval(hyp_id)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@app.get("/hypotheses/{hyp_id}/search-evidence")
def search_evidence(hyp_id: str, limit: int = Query(10, le=30), lookback_days: int = Query(90, ge=7)):
    from hypothesis import search_evidence as _search
    return {"candidates": _search(hyp_id, limit=limit, lookback_days=lookback_days)}


@app.post("/hypotheses/{hyp_id}/auto-evidence")
def auto_gather_evidence(hyp_id: str, limit: int = Body(10, embed=True),
                         lookback_days: int = Body(90, embed=True)):
    from hypothesis import auto_gather_evidence as _auto
    added = _auto(hyp_id, limit=limit, lookback_days=lookback_days)
    return {"added": len(added), "evidence": added}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Predictions
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/predict")
def get_predictions(prediction_type: str = Query(None), limit: int = Query(20, le=50)):
    cache_key = f"predictions_{prediction_type}_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from predictor import get_predictions as _get
    result = {"predictions": _get(prediction_type=prediction_type, limit=limit)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/predict/hotspots")
def get_hotspots(days: int = Query(7, ge=1, le=30), top_n: int = Query(10, le=20)):
    cache_key = f"hotspots_{days}_{top_n}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from predictor import predict_hotspots
    result = {"hotspots": predict_hotspots(days=days, top_n=top_n)}
    _cache.set(cache_key, result, ttl=300)
    return result


@app.get("/predict/{event_type}")
def forecast_event_type(event_type: str, lookback_days: int = Query(30, ge=7, le=90),
                        forecast_days: int = Query(7, ge=1, le=14)):
    cache_key = f"forecast_{event_type}_{lookback_days}_{forecast_days}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from predictor import forecast_event_type as _forecast
    result = _forecast(event_type=event_type, lookback_days=lookback_days, forecast_days=forecast_days)
    _cache.set(cache_key, result, ttl=300)
    return result


@app.post("/predict/generate")
def generate_predictions(bg: BackgroundTasks,
                         x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    _require_admin(x_api_key)
    _cache.invalidate("predictions_None_20")
    from predictor import generate_predictions as _gen
    bg.add_task(_gen)
    return {"status": "prediction generation queued"}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Source Credibility
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/sources")
def list_sources(limit: int = Query(50, le=200)):
    cache_key = f"sources_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit: return cached
    from credibility import list_source_scores
    result = {"sources": list_source_scores(limit=limit)}
    _cache.set(cache_key, result, ttl=300)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Analyst Copilot
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/copilot")
def copilot_query(body: CopilotQueryBody):
    from copilot import query as _query
    return _query(
        user_query=body.query,
        session_id=body.session_id,
        include_context=body.include_context,
    )


@app.get("/copilot/sessions")
def copilot_sessions():
    from copilot import get_all_sessions
    return {"sessions": get_all_sessions()}


@app.get("/copilot/history/{session_id}")
def copilot_history(session_id: str, limit: int = Query(20, le=50)):
    from copilot import get_history
    return {"history": get_history(session_id, limit=limit)}


@app.delete("/copilot/history/{session_id}")
def clear_copilot_history(session_id: str):
    from copilot import clear_history
    clear_history(session_id)
    return {"status": "cleared"}


# ═══════════════════════════════════════════════════════════════════════════════
# V3 ENDPOINTS — Insights
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/insights")
def list_insights(
    insight_type: str = Query(None),
    unread_only: bool = Query(False),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(50, le=200),
):
    cache_key = f"insights_{insight_type}_{unread_only}_{min_confidence}_{days}_{limit}"
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached
    from insights import get_insights
    result = {
        "insights": get_insights(
            insight_type=insight_type, limit=limit,
            unread_only=unread_only, min_confidence=min_confidence, days=days,
        )
    }
    _cache.set(cache_key, result, ttl=120)
    return result


@app.get("/insights/stats")
def insights_stats_endpoint():
    cache_key = "insights_stats"
    cached, hit = _cache.get(cache_key)
    if hit:
        return cached
    from insights import insight_stats
    result = insight_stats()
    _cache.set(cache_key, result, ttl=60)
    return result


@app.get("/insights/unread-count")
def insights_unread_count():
    from insights import get_unread_insight_count
    return {"count": get_unread_insight_count()}


@app.get("/insights/{insight_id}")
def get_insight_endpoint(insight_id: str):
    from insights import get_insight, mark_insight_read
    doc = get_insight(insight_id)
    if not doc:
        raise HTTPException(404, "Insight not found")
    mark_insight_read(insight_id)
    return doc


@app.post("/insights/generate")
def generate_insights(
    bg: BackgroundTasks,
    days: int = Body(14, embed=True),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_admin(x_api_key)
    _cache.invalidate("insights_stats")
    from insights import generate_all_insights
    bg.add_task(generate_all_insights, days)
    return {"status": "insight generation queued", "days": days}


@app.post("/insights/{insight_id}/read")
def mark_insight_read_endpoint(insight_id: str):
    from insights import mark_insight_read
    mark_insight_read(insight_id)
    return {"status": "marked read"}

