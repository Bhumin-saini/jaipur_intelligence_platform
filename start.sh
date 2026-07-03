#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Garuda v2 — Start script  (bash on Mac/Linux, Git Bash on Windows)
# ──────────────────────────────────────────────────────────────────────────────
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  ██████╗  █████╗ ██████╗ ██╗   ██╗██████╗  █████╗ "
echo "  ██╔════╝ ██╔══██╗██╔══██╗██║   ██║██╔══██╗██╔══██╗"
echo "  ██║  ███╗███████║██████╔╝██║   ██║██║  ██║███████║"
echo "  ██║   ██║██╔══██║██╔══██╗██║   ██║██║  ██║██╔══██║"
echo "  ╚██████╔╝██║  ██║██║  ██║╚██████╔╝██████╔╝██║  ██║"
echo "   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝"
echo "  Jaipur Intelligence Platform — v2"
echo ""

# ── Validate .env ─────────────────────────────────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your keys."
  exit 1
fi

source "$ROOT/.env" 2>/dev/null || true
if [ -z "$ASTRA_DB_APPLICATION_TOKEN" ]; then
  echo "WARNING: ASTRA_DB_APPLICATION_TOKEN missing from .env"
fi
if [ -z "$GEMINI_API_KEY" ]; then
  echo "WARNING: GEMINI_API_KEY missing from .env (needed for embeddings & briefs)"
fi

# ── Backend virtualenv ────────────────────────────────────────────────────────
echo "[ 1/4 ] Setting up backend…"
cd "$ROOT/backend"

if [ ! -d ".venv" ]; then
  echo "        Creating virtualenv…"
  python3 -m venv .venv
fi

# Activate venv (works on Mac/Linux/Git Bash)
if [ -f ".venv/Scripts/activate" ]; then
  source .venv/Scripts/activate   # Git Bash on Windows
else
  source .venv/bin/activate
fi

echo "        Installing Python dependencies…"
pip install -q -r requirements.txt

# ── Start backend ─────────────────────────────────────────────────────────────
echo "[ 2/4 ] Starting backend (FastAPI :8000)…"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to be ready (max 15s)
echo "        Waiting for backend to come up…"
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "        Backend ready ✓"
    break
  fi
  sleep 1
done

# ── Start embedding backfill (background, silent) ─────────────────────────────
echo "[ 3/4 ] Starting embedding backfill (background)…"
python scripts/embed_backfill.py --delay 2.0 --loop \
  >> "$ROOT/backfill.log" 2>&1 &
BACKFILL_PID=$!
echo "        Backfill PID: $BACKFILL_PID  (logs → backfill.log)"

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "[ 4/4 ] Starting frontend (Vite :5173)…"
cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
  echo "        Installing npm dependencies…"
  npm install --silent
fi

npm run dev &
FRONTEND_PID=$!

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  ✓ Backend   → http://localhost:8000        │"
echo "  │  ✓ Frontend  → http://localhost:5173        │"
echo "  │  ✓ API docs  → http://localhost:8000/docs   │"
echo "  │  ✓ Backfill  → tail -f backfill.log         │"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  Press Ctrl+C to stop everything."
echo ""

trap "echo 'Stopping…'; kill $BACKEND_PID $BACKFILL_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
