# ──────────────────────────────────────────────────────────────────────────────
# Garuda v2 — Windows PowerShell start script
# Run from the project root: .\start.ps1
# ──────────────────────────────────────────────────────────────────────────────

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  GARUDA v2 — Jaipur Intelligence Platform" -ForegroundColor Cyan
Write-Host ""

# ── Validate .env ─────────────────────────────────────────────────────────────
if (-not (Test-Path "$Root\.env")) {
    Write-Host "ERROR: .env not found. Copy .env.example and fill in your keys." -ForegroundColor Red
    exit 1
}

# ── Backend setup ─────────────────────────────────────────────────────────────
Write-Host "[ 1/4 ] Setting up backend..." -ForegroundColor Yellow
Set-Location "$Root\backend"

if (-not (Test-Path ".venv")) {
    Write-Host "        Creating virtualenv..."
    python -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"
Write-Host "        Installing Python dependencies..."
pip install -q -r requirements.txt

# ── Start backend ─────────────────────────────────────────────────────────────
Write-Host "[ 2/4 ] Starting backend (FastAPI :8000)..." -ForegroundColor Yellow
$backend = Start-Process -PassThru -NoNewWindow python -ArgumentList `
    "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"

# Wait for backend
Write-Host "        Waiting for backend..."
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}
if ($ready) { Write-Host "        Backend ready ✓" -ForegroundColor Green }
else         { Write-Host "        Backend slow to start — continuing anyway" -ForegroundColor Yellow }

# ── Embedding backfill (background) ───────────────────────────────────────────
Write-Host "[ 3/4 ] Starting embedding backfill (background)..." -ForegroundColor Yellow
$backfill = Start-Process -PassThru -NoNewWindow python -ArgumentList `
    "scripts\embed_backfill.py", "--delay", "2.0", "--loop" `
    -RedirectStandardOutput "$Root\backfill.log" `
    -RedirectStandardError  "$Root\backfill_err.log"
Write-Host "        Backfill PID: $($backfill.Id)  (logs → backfill.log)" -ForegroundColor Green

# ── Frontend ──────────────────────────────────────────────────────────────────
Write-Host "[ 4/4 ] Starting frontend (Vite :5173)..." -ForegroundColor Yellow
Set-Location "$Root\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "        Installing npm dependencies..."
    npm install --silent
}

$npmCmd = (Get-Command npm).Source
$frontend = Start-Process -PassThru -NoNewWindow -FilePath $npmCmd -ArgumentList "run", "dev"

Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────┐" -ForegroundColor Cyan
Write-Host "  │  ✓ Backend   → http://localhost:8000        │" -ForegroundColor Cyan
Write-Host "  │  ✓ Frontend  → http://localhost:5173        │" -ForegroundColor Cyan
Write-Host "  │  ✓ API docs  → http://localhost:8000/docs   │" -ForegroundColor Cyan
Write-Host "  │  ✓ Backfill  → Get-Content backfill.log -Wait│" -ForegroundColor Cyan
Write-Host "  └─────────────────────────────────────────────┘" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop all processes." -ForegroundColor Gray
Write-Host ""

# Keep running — kill all on Ctrl+C
try {
    Wait-Process -Id $backend.Id
} finally {
    Write-Host "Stopping all processes..." -ForegroundColor Yellow
    Stop-Process -Id $backend.Id   -ErrorAction SilentlyContinue
    Stop-Process -Id $backfill.Id  -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id  -ErrorAction SilentlyContinue
}
