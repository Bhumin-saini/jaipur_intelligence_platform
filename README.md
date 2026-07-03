# Garuda v3 — Jaipur Intelligence Platform

A full-stack city intelligence platform that monitors local news in Jaipur, India.

## What's New in v3

### Knowledge Graph
- `ontology.py` — Entity type hierarchy and relationship taxonomy
- `knowledge_graph.py` — Graph nodes, typed edges, event linking, community detection, GraphRAG context builder
- New AstraDB collections: `graph_nodes`, `graph_edges`, `event_links`
- Pipeline now auto-builds co-occurrence edges on every article

### Source Credibility
- `credibility.py` — Per-source reliability scoring (tier, bias, correction/contradiction tracking)
- Events gain `confidence` and `source_credibility_score` fields
- Collection: `source_scores`

### Case Management
- `case_manager.py` — Investigation workspaces bundling events, annotations, and risk scores
- Full CRUD for cases, events within cases, and analyst annotations (note / hypothesis / finding / question / action)
- Collections: `cases`, `case_events`, `annotations`
- Frontend: `/cases`

### Watchlist & Alerts
- `watchlist.py` — Continuous monitors on keywords, locations, entities, event types
- Scheduled alert check every 60 minutes
- Alert deduplication, read/unread state
- Collections: `watchlist`, `watchlist_alerts`
- Frontend: `/watchlist`

### Hypothesis Testing
- `hypothesis.py` — Analyst-driven hypotheses with evidence scoring
- Auto-gather evidence via semantic search
- AI evaluation with Gemini: confidence score + verdict + reasoning + recommended actions
- Collections: `hypotheses`, `evidence`
- Frontend: `/hypotheses`

### Predictive Intelligence
- `predictor.py` — 7-day event forecasts using moving averages + linear trend
- Geographic hotspot detection with trend ratios
- Scheduled prediction generation every 6 hours
- Collection: `predictions`
- Frontend: `/predict`

### Analyst Copilot
- `copilot.py` — Natural language query interface grounded in live data via GraphRAG
- Multi-turn conversation with session memory
- Falls back to semantic search if graph context fails
- Collection: `copilot_history`
- Frontend: `/copilot`

## Architecture

```
RSS Sources → Scrapers → Articles (AstraDB)
    ↓
Gemini Embeddings
    ↓
LLM Extraction (Gemini/Groq)
    ↓
Events + Entities (AstraDB)
    ↓             ↓
Knowledge Graph   Source Credibility
(graph_nodes,     (source_scores)
 graph_edges,
 event_links)
    ↓
GraphRAG Context
    ↓
┌─────────────────────────────┐
│ Trend Detection             │
│ Anomaly Detection           │
│ Brief Generation            │
│ Watchlist Alerts            │
│ Prediction Engine           │
│ Case Management             │
│ Hypothesis Testing          │
│ Analyst Copilot             │
└─────────────────────────────┘
    ↓
React/Vite Dashboard
```

## Setup

### 1. Configure environment
```bash
cp .env.example .env
# Fill in ASTRA_DB_ID, ASTRA_DB_APPLICATION_TOKEN, GEMINI_API_KEY, GROQ_API_KEY
```

### 2. Initialise AstraDB collections
```bash
cd backend
pip install -r requirements.txt --break-system-packages
python scripts/init_astra_v3.py
```

### 3. Start
```bash
# Linux/macOS
bash start.sh

# Windows
powershell start.ps1
```

Frontend: http://localhost:5173  
API: http://localhost:8000/docs

## New API Endpoints (v3)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/graph/nodes` | Entity nodes |
| GET | `/graph/nodes/{id}` | Subgraph from node |
| GET | `/graph/communities` | Community detection |
| GET | `/cases` | List cases |
| POST | `/cases` | Create case |
| GET | `/watchlist` | List monitors |
| POST | `/watchlist` | Create monitor |
| GET | `/alerts` | Get alerts |
| GET | `/hypotheses` | List hypotheses |
| POST | `/hypotheses` | Create hypothesis |
| POST | `/hypotheses/{id}/evaluate` | AI evaluation |
| GET | `/predict/{event_type}` | 7-day forecast |
| GET | `/predict/hotspots` | Geographic hotspots |
| POST | `/copilot` | Analyst copilot query |
| GET | `/sources` | Source credibility scores |

## File Structure

```
backend/
  main.py              — FastAPI app (v2 + v3 endpoints)
  pipeline.py          — Ingestion pipeline (now builds graph)
  analyst.py           — Trend/anomaly/brief generation
  knowledge_graph.py   — Graph layer (NEW)
  ontology.py          — Entity/relationship taxonomy (NEW)
  credibility.py       — Source credibility scoring (NEW)
  case_manager.py      — Case management (NEW)
  watchlist.py         — Watchlist & alerts (NEW)
  hypothesis.py        — Hypothesis testing (NEW)
  predictor.py         — Predictive intelligence (NEW)
  copilot.py           — Analyst copilot (NEW)
  astra_client.py      — AstraDB collections (expanded)
  astra_store.py       — Storage layer
  extractor.py         — NLP extraction
  embedder.py          — Embedding generation
  scrapers.py          — RSS scrapers
  scripts/
    init_astra_v3.py   — Collection initialiser (NEW)

frontend/src/
  pages/
    Dashboard.jsx
    MapDashboard.jsx
    TimelinePage.jsx
    SearchPage.jsx
    BriefsPage.jsx
    EntityView.jsx
    GraphView.jsx
    EventDetail.jsx
    CasesPage.jsx       (NEW)
    WatchlistPage.jsx   (NEW)
    HypothesisPage.jsx  (NEW)
    PredictionsPage.jsx (NEW)
    CopilotPage.jsx     (NEW)
  api.js                (expanded)
  App.jsx               (new routes)
```
