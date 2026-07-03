# Garuda — Jaipur Intelligence Platform (v3)

A self-hosted, Palantir-style city intelligence platform that continuously scrapes local news, extracts structured events and entities with an LLM, builds a persistent knowledge graph, and layers analyst tooling (cases, watchlists, hypotheses, predictions, and a RAG copilot) on top — all served through a FastAPI backend and a React/Vite dashboard.

> Domain focus: Jaipur, Rajasthan. Architecture is otherwise city-agnostic — swap the scrapers and geocoder to point it anywhere else.

---

## 1. What this is

Garuda turns unstructured local news into a queryable intelligence layer:

```
News articles  →  structured events + entities  →  knowledge graph  →  analyst workflows
```

It answers questions like "what's trending in Jaipur this week," "who is connected to whom," "is this a coordinated pattern or a one-off," and "what's likely to happen next" — without any manual tagging.

### Core capabilities
| Layer | What it does |
|---|---|
| **Ingestion** | Scrapes RSS feeds from 3 local sources, filters for Jaipur relevance, dedupes by URL and semantically by title embedding |
| **Extraction** | LLM (Gemini, Groq fallback) pulls event type, severity, actors, locations, causal factors, and a summary out of each article |
| **Entity Resolution** | Collapses messy name variants ("CM", "Bhajan Lal", "CM Sharma") into one canonical entity before it touches storage |
| **Knowledge Graph** | Persists entities as nodes and co-occurrence/typed relationships as edges; links semantically similar events into chains |
| **Source Credibility** | Scores each outlet's reliability and flags contradictions across sources |
| **Analyst Tools** | Case files, watchlists with alerting, hypothesis testing with evidence scoring, 7-day event forecasting, geographic hotspot detection |
| **Insight Engine** | Auto-generates pattern/escalation/actor/location/thread/contradiction insights from event clusters |
| **Copilot** | GraphRAG-grounded natural-language Q&A over the live dataset, multi-turn with session memory |
| **Dashboard** | React SPA — map, timeline, search, graph explorer, briefs, cases, watchlist, predictions, insights, copilot |

---

## 2. Architecture

### 2.1 System overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              SCHEDULED JOBS (APScheduler)                     │
│  scrape_cycle (15m) · watchlist_check (60m) · prediction_job (6h)            │
│  graph_build (12h) · graph_reconcile (6h) · insight_pipeline (4h)            │
│  trend/anomaly detection + daily brief (analyst.py, configurable)           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
 RSS Sources (Times of India, Rajasthan Patrika, Dainik Bhaskar)
                                       │  scrapers.py (feedparser + BeautifulSoup)
                                       │  → filters non-Jaipur articles
                                       ▼
                              ┌─────────────────┐
                              │   pipeline.py    │   process_article() — per article
                              │  (orchestrator)  │
                              └────────┬─────────┘
        1. upsert_article() ──────────┤ URL dedup (astra_store.py → `articles`)
        2. semantic_dedup()  ─────────┤ title-embedding cosine sim vs recent events
        3. extract_intelligence() ────┤ extractor.py — Gemini → Groq fallback
        4. post-process + severity ───┤ keyword override (death/injury/protest…)
        5. insert_event() ────────────┤ astra_store.py → `events` (+ embedding)
        6. entity resolution + link ──┤ entity_resolver.py → astra_store.py
        7. graph node/edge writes ────┤ knowledge_graph.py, queued via graph_queue.py
        8. source credibility log ────┤ credibility.py → `source_scores`
                                       ▼
                              ┌─────────────────┐
                              │     AstraDB      │  21 collections (vector + non-vector)
                              │ (Serverless Vec) │  articles · events · entities ·
                              └────────┬─────────┘  graph_nodes/edges · cases ·
                                       │             watchlist · hypotheses · predictions ·
                                       │             source_scores · insights · ingestion_logs
                                       ▼
                    ┌──────────────────────────────────┐
                    │        Analyst Intelligence       │
                    │  analyst.py    — trends/anomalies/briefs
                    │  knowledge_graph.py — GraphRAG context, communities
                    │  predictor.py  — 7-day forecast, hotspots
                    │  insights.py   — pattern/escalation/actor/location/thread/contradiction
                    │  case_manager.py, watchlist.py, hypothesis.py, copilot.py
                    └────────────────┬───────────────────┘
                                     ▼
                        FastAPI (main.py) — ~75 REST endpoints
                                     │
                                     ▼
                    React 18 + Vite + Tailwind dashboard (frontend/)
                    Leaflet map · Cytoscape graph view · Recharts-style pages
```

### 2.2 Per-article ingestion flow (the core loop)

Each scrape cycle (`run_scrape_cycle`, `pipeline.py`) runs every `SCRAPE_INTERVAL_MINUTES` (default 15) and does, for every candidate article:

1. **URL dedup** — `astra_store.upsert_article()` returns `None` if the URL already exists → skip.
2. **Semantic dedup** — embeds the title and checks cosine similarity against recent events (`SEMANTIC_DEDUP_THRESHOLD`, default 0.92). A match marks the article `duplicate` and stops.
3. **NLP extraction** — `extractor.extract_intelligence()` calls Gemini first (`gemini-2.0-flash` → `gemini-1.5-flash-latest` → `gemini-1.5-flash`), falls back to Groq (`llama-3.3-70b-versatile`) on failure. Extracts event type, severity, actors, locations, causal factors, actor roles, event status, impact, and a summary.
4. **Severity override** — keyword pass (death/injury/protest/fire, Hindi equivalents included) can escalate the LLM's severity classification.
5. **Event storage** — `astra_store.insert_event()` writes to the `events` vector collection with an embedding of the summary.
6. **Entity resolution + linking** — for each extracted person/org/location, `entity_resolver.py` runs a 6-stage cascade (exact alias → normalized → token-subset → abbreviation expansion → fuzzy match ≥0.82 → vector fallback in `upsert_entity`) to avoid creating duplicate entities, then links the entity to the event.
7. **Knowledge graph writes** — node upserts for each entity, co-occurrence edges between every pair of entities in the article, and a similarity-link job against existing events — all pushed onto `graph_queue.py`, an in-process retry queue (1s → 4s → 16s backoff, 3 attempts, dead-letters to `ingestion_logs` on exhaustion) so a transient AstraDB error never silently orphans data.
8. **Source credibility logging** — `credibility.record_source_activity()` logs the article against its source for later reliability scoring.

### 2.3 Backend module map

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, lifespan startup (collection bootstrap, scheduler registration), ~75 REST endpoints, TTL response cache |
| `pipeline.py` | Ingestion orchestrator — the loop described above |
| `scrapers.py` | `BaseScraper` + 3 concrete scrapers (Patrika, TOI, Dainik Bhaskar); Jaipur-relevance filter |
| `extractor.py` | LLM extraction (Gemini→Groq), rate-limited, includes a hardcoded Jaipur locality geocoder |
| `embedder.py` | Gemini embedding generation (`gemini-embedding-001`, 3072-dim by default) with exponential backoff on 429 |
| `entity_resolver.py` | Pre-storage name canonicalization (alias table → fuzzy match → vector fallback) |
| `astra_client.py` | Single cached AstraDB connection/collection accessor |
| `astra_store.py` | CRUD layer — articles, events, entities, semantic dedup, event-entity links |
| `config.py` | Single source of truth for all 21 AstraDB collection definitions; idempotent bootstrap on every startup |
| `knowledge_graph.py` | Graph nodes/edges, subgraph queries, community detection (label propagation), GraphRAG context builder, event-chain linking |
| `graph_queue.py` | Bounded retry queue + dead-letter logging for graph writes |
| `ontology.py` | Entity type hierarchy + relationship taxonomy used by the graph layer |
| `credibility.py` | Per-source reliability/bias scoring, contradiction flagging, confidence-weighting of events |
| `analyst.py` | Trend detection, anomaly detection, daily/weekly brief generation (event clustering → Gemini summary), semantic search, heatmap, entity network |
| `case_manager.py` | Investigation workspaces — CRUD for cases, case events, annotations, risk scoring, export |
| `watchlist.py` | Continuous monitors (keyword/entity/location/event-type), scheduled alert generation, read/unread state |
| `hypothesis.py` | Analyst hypotheses with evidence gathering (manual + auto semantic search) and LLM-based confidence evaluation |
| `predictor.py` | 7-day forecasts (moving average + linear trend), geographic hotspot detection |
| `insights.py` | Six insight types generated from event clustering (pattern, escalation, actor, location, thread, contradiction) |
| `copilot.py` | GraphRAG-grounded natural language query interface with session history, falls back to plain semantic search |
| `database.py` | Legacy SQLite layer (WAL mode) — retained only for historical dual-write compatibility, not used in the active pipeline |

### 2.4 Data model (AstraDB collections)

Defined centrally in `config.py::COLLECTIONS` and bootstrapped idempotently on every startup.

**Vector collections** (embedded, cosine similarity):
`articles`, `events`, `entities`, `intelligence_briefs`

**Non-vector collections** (`indexing={"deny": ["*"]}` to stay under the AstraDB free-tier 100-SAI-index limit):
`event_entities` · `graph_nodes` · `graph_edges` · `event_links` · `cases` · `case_events` · `annotations` · `watchlist` · `watchlist_alerts` · `hypotheses` · `evidence` · `predictions` · `source_scores` · `copilot_history` · `insights` · `ingestion_logs`

### 2.5 Scheduled jobs (APScheduler, persistent SQLite job store)

| Job | Interval | Source |
|---|---|---|
| `scrape_cycle` | `SCRAPE_INTERVAL_MINUTES` (default 15m) | `pipeline.run_scrape_cycle` |
| Trend / anomaly detection + daily brief | configurable (`analyst.py`) | `analyst.register_analysis_jobs` |
| `watchlist_check` | 60m | `watchlist.check_watchlist` |
| `prediction_job` | 6h | `predictor.generate_predictions` |
| `graph_build` | 12h (30-day window) | `knowledge_graph.build_graph_from_entities` |
| `graph_reconcile` | 6h (7-day window, safety net) | `knowledge_graph.reconcile_graph_nodes` |
| `insight_pipeline` | 4h | `insights.run_insight_pipeline` |

Job state persists to `garuda_jobs.db` (SQLite) so missed intervals recover on restart; `coalesce=True` means a missed window fires once, not N times.

### 2.6 Frontend

React 18 + Vite + Tailwind SPA (`frontend/`), routed with `react-router-dom`:

| Route | Page | Notes |
|---|---|---|
| `/` | `Dashboard.jsx` | Overview stats, recent events |
| `/map` | `MapDashboard.jsx` | Leaflet event map |
| `/timeline` | `TimelinePage.jsx` | Chronological event feed |
| `/search` | `SearchPage.jsx` | Semantic search over events |
| `/briefs` | `BriefsPage.jsx` | Generated intelligence briefs |
| `/entities`, `/entities/:id` | `EntityView.jsx` | Entity profile + co-occurrence network |
| `/graph` | `GraphView.jsx` | Cytoscape knowledge graph explorer |
| `/events/:id` | `EventDetail.jsx` | Full event detail + similar events |
| `/cases` | `CasesPage.jsx` | Case management |
| `/watchlist` | `WatchlistPage.jsx` | Monitors + alerts |
| `/hypotheses` | `HypothesisPage.jsx` | Hypothesis testing |
| `/predict` | `PredictionsPage.jsx` | Forecasts + hotspots |
| `/insights` | `InsightsPage.jsx` | Generated insights |
| `/copilot` | `CopilotPage.jsx` | Analyst chat interface |

All API calls go through `src/api.js` to the FastAPI backend.

---

## 3. API reference

Full interactive docs at `http://localhost:8000/docs` once running. Grouped summary:

| Group | Endpoints |
|---|---|
| **Core** | `GET /health`, `GET /stats`, `GET /metrics`, `POST /scrape` |
| **Events** | `GET /events`, `GET /events/{id}`, `GET /events/{id}/similar`, `GET /timeline`, `GET /search`, `GET /heatmap` |
| **Entities** | `GET /entities`, `GET /entities/{id}`, `GET /entities/{id}/network` |
| **Graph** | `GET /graph-data`, `GET /graph/nodes`, `GET /graph/nodes/{id}`, `GET /graph/edges`, `GET /graph/communities`, `GET /graph/stats`, `POST /graph/build`, `GET /graph/event-links/{id}`, `GET /graph/event-chain/{id}` |
| **Analysis** | `GET /trends`, `GET /anomalies`, `GET /briefs`, `GET /briefs/{id}`, `POST /briefs/generate` |
| **Cases** | `GET/POST /cases`, `GET/PUT/DELETE /cases/{id}`, `POST /cases/{id}/close`, `GET/POST/DELETE /cases/{id}/events[/{eid}]`, `GET/POST /cases/{id}/annotations`, `DELETE /annotations/{id}`, `GET /cases/{id}/risk`, `GET /cases/{id}/export` |
| **Watchlist** | `GET/POST /watchlist`, `GET/PUT/DELETE /watchlist/{id}`, `GET /alerts`, `GET /alerts/unread-count`, `POST /alerts/check`, `POST /alerts/{id}/read`, `POST /alerts/read-all` |
| **Hypotheses** | `GET/POST /hypotheses`, `GET/PUT/DELETE /hypotheses/{id}`, `GET/POST /hypotheses/{id}/evidence`, `DELETE /evidence/{id}`, `POST /hypotheses/{id}/evaluate`, `GET /hypotheses/{id}/search-evidence`, `POST /hypotheses/{id}/auto-evidence` |
| **Predictions** | `GET /predict`, `GET /predict/hotspots`, `GET /predict/{event_type}`, `POST /predict/generate` |
| **Source credibility** | `GET /sources` |
| **Insights** | `GET /insights`, `GET /insights/stats`, `GET /insights/unread-count`, `GET /insights/{id}`, `POST /insights/generate`, `POST /insights/{id}/read` |
| **Copilot** | `POST /copilot`, `GET /copilot/sessions`, `GET /copilot/history/{session_id}`, `DELETE /copilot/history/{session_id}` |

`POST /scrape` and other admin-sensitive routes can optionally be protected with `SCRAPE_API_KEY` (see env vars below) — pass it as `X-Api-Key` header.

---

## 4. How to reproduce

### 4.1 Prerequisites
- Python 3.10+
- Node.js 18+ / npm
- A free [AstraDB Serverless (Vector)](https://astra.datastax.com) database — region `ap-south-1` recommended for Jaipur latency
- A [Gemini API key](https://aistudio.google.com/app/apikey) (extraction, embeddings, briefs)
- A [Groq API key](https://console.groq.com/keys) (NLP fallback)

### 4.2 Configure environment

```bash
cd garuda_v2
cp .env.example .env
```

Fill in `.env`:

```env
ASTRA_DB_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ASTRA_DB_REGION=ap-south-1
ASTRA_DB_KEYSPACE=garuda
ASTRA_DB_APPLICATION_TOKEN=AstraCS:...

EMBEDDING_MODEL=text-embedding-004
EMBEDDING_DIM=768        # match your AstraDB collection dimension

GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here

SCRAPE_INTERVAL_MINUTES=15
MAX_ARTICLES_PER_SOURCE=8
ARTICLE_PROCESS_DELAY_SECONDS=6.0
GEMINI_MIN_INTERVAL_SECONDS=5.0
GROQ_MIN_INTERVAL_SECONDS=2.5

TREND_DETECTION_INTERVAL_HOURS=6
ANOMALY_DETECTION_INTERVAL_HOURS=4
BRIEF_GENERATION_TIME_IST=07:00
SEMANTIC_DEDUP_THRESHOLD=0.92
ENTITY_RESOLUTION_THRESHOLD=0.88
TREND_SPIKE_RATIO=2.0

# Optional — protect POST /scrape
# SCRAPE_API_KEY=your_secret_here
# VITE_SCRAPE_API_KEY=your_secret_here   # must match, used by the UI scrape button
```

> `EMBEDDING_DIM` must match whatever dimension you create the AstraDB vector collections with (`config.py` reads `EMBEDDING_DIM`, default 3072 — align it with your chosen Gemini embedding model's output size).

### 4.3 Initialize AstraDB collections

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt --break-system-packages
python scripts/init_astra_v3.py
```

This creates all 21 collections defined in `config.py`. It's idempotent — safe to re-run. (The backend also self-heals on every startup via `bootstrap_collections()`, so this step is a convenience, not a hard requirement.)

### 4.4 One-command start (recommended)

```bash
# Linux / macOS / Git Bash on Windows
bash start.sh
```

```powershell
# Native Windows
powershell -ExecutionPolicy Bypass -File start.ps1
```

This will, in order:
1. Create/activate the backend virtualenv and install dependencies
2. Start FastAPI on `:8000` and wait for `/health` to respond
3. Kick off `scripts/embed_backfill.py --loop` in the background to backfill embeddings for any events missing them (logs to `backfill.log`)
4. Install frontend npm dependencies (first run only) and start Vite on `:5173`

```
✓ Backend   → http://localhost:8000
✓ Frontend  → http://localhost:5173
✓ API docs  → http://localhost:8000/docs
✓ Backfill  → tail -f backfill.log
```

Ctrl+C stops all three processes.

### 4.5 Manual start (if you want each piece separately)

```bash
# Terminal 1 — backend
cd backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev

# Terminal 3 — optional embedding backfill for pre-existing events
cd backend
python scripts/embed_backfill.py --delay 2.0 --loop
```

### 4.6 Verify it's working

```bash
curl http://localhost:8000/health
```

Expect `"status": "ok"`, `"astra": true`, `"collections_ok": true`. If `status` is `"degraded"`, check `missing_collections` in the response and re-run `init_astra_v3.py`, or check your `.env` credentials.

Trigger a manual scrape instead of waiting for the 15-minute schedule:

```bash
curl -X POST http://localhost:8000/scrape
# with SCRAPE_API_KEY set:
curl -X POST http://localhost:8000/scrape -H "X-Api-Key: your_secret_here"
```

Then open `http://localhost:5173` — events should start appearing on the Dashboard/Map within a few minutes as the pipeline processes each article (rate-limited by `ARTICLE_PROCESS_DELAY_SECONDS` to respect Gemini/Groq quotas).

### 4.7 Useful maintenance scripts (`backend/scripts/`)

| Script | Purpose |
|---|---|
| `init_astra.py` / `init_astra_v3.py` | Bootstrap AstraDB collections |
| `embed_backfill.py` | Backfill missing embeddings on existing events/articles |
| `merge_duplicate_entities.py` | One-off cleanup pass to merge entities the resolver missed |
| `migrate_sqlite_to_astra.py` | Migration path from the legacy SQLite store (v1) to AstraDB |

---

## 5. Design notes / ADRs baked into the code

- **ADR-001** (`config.py`) — single source of truth for collection schema; idempotent bootstrap on every startup so a partial AstraDB setup never blocks the app from booting.
- **ADR-002** (`graph_queue.py`) — graph writes are queued with exponential backoff instead of being silently dropped on transient AstraDB errors; exhausted retries are dead-lettered to `ingestion_logs` for later inspection. A 6-hourly `graph_reconcile` job acts as a safety net.
- **ADR-003** (`main.py` lifespan) — APScheduler uses a persistent `SQLAlchemyJobStore` (SQLite-backed) so scheduled jobs survive process restarts and missed windows coalesce into a single run.
- **ADR-004-H02** (`pipeline.py`, `main.py`) — the API response TTL cache is invalidated immediately after a scrape cycle produces new events, instead of waiting for TTL expiry, so the dashboard reflects new intelligence without a stale delay.

---

## 6. Known constraints

- Scrapers currently cover 3 Hindi/English Jaipur outlets (Times of India, Rajasthan Patrika, Dainik Bhaskar) — extend `scrapers.py`'s `ALL_SCRAPERS` list to add more.
- Non-vector AstraDB collections use `indexing={"deny": ["*"]}` to stay within the free-tier 100-SAI-index cap — don't expect SAI-backed filtering on those collections without revisiting indexing strategy.
- `database.py` (SQLite) is legacy/dual-write scaffolding from the v1→v2 migration and is not part of the active ingestion path; safe to ignore unless you're doing a from-scratch migration.
- Gemini/Groq calls are globally rate-limited in-process (`GEMINI_MIN_INTERVAL_SECONDS`, `GROQ_MIN_INTERVAL_SECONDS`) — a large backlog of articles will process serially and can take a while on first run.
