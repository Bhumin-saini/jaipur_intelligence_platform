import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getMetrics, getTrends, getBriefs, isCanceled } from '../api'

const STAT_STYLES = {
  articles: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
  events:   'border-orange-500/30 bg-orange-500/10 text-orange-300',
  mapped:   'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  failures: 'border-red-500/30 bg-red-500/10 text-red-300',
}

const fmt = v => Number(v || 0).toLocaleString()

function StatCard({ label, value, detail, tone }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div className={`inline-flex rounded border px-2 py-0.5 text-[11px] font-bold uppercase ${STAT_STYLES[tone]}`}>
        {label}
      </div>
      <div className="mt-3 text-3xl font-bold text-white">{fmt(value)}</div>
      <div className="mt-1 text-sm text-slate-400">{detail}</div>
    </div>
  )
}

function Funnel({ steps }) {
  const max = Math.max(...steps.map(s => s.value || 0), 1)
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="mb-5 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-white">Ingestion Funnel</h2>
          <p className="text-sm text-slate-400">Article → event → entity mapping health</p>
        </div>
        <Link to="/map" className="rounded-lg bg-orange-500 px-3 py-2 text-sm font-semibold text-white hover:bg-orange-600">
          Open Map
        </Link>
      </div>
      <div className="space-y-4">
        {steps.map((step, i) => {
          const width  = Math.max(8, Math.round(((step.value || 0) / max) * 100))
          const colors = ['bg-sky-500', 'bg-orange-500', 'bg-emerald-500']
          return (
            <div key={step.key}>
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="font-medium text-slate-200">{i + 1}. {step.label}</span>
                <span className="text-slate-400">{fmt(step.value)}</span>
              </div>
              <div className="h-7 rounded bg-slate-900">
                <div
                  className={`flex h-7 items-center justify-end rounded px-3 text-xs font-bold text-white ${colors[i] || 'bg-slate-500'}`}
                  style={{ width: `${width}%` }}
                >
                  {width > 20 ? `${width}%` : ''}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Search bar widget ─────────────────────────────────────────────────────────
function SearchWidget() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')

  const handleSubmit = e => {
    e.preventDefault()
    if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`)
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <h2 className="text-base font-semibold text-white mb-1">Semantic Search</h2>
      <p className="text-sm text-slate-400 mb-3">Query events in English or Hindi using natural language.</p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder='e.g. "road accident near Tonk Road" or "आग"'
          className="flex-1 rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white
                     placeholder-slate-500 outline-none focus:border-orange-500"
        />
        <button
          type="submit"
          disabled={!q.trim()}
          className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-semibold text-white
                     hover:bg-orange-600 disabled:opacity-40 transition-colors"
        >
          Search
        </button>
      </form>
    </div>
  )
}

// ── Trend alerts widget ───────────────────────────────────────────────────────
function TrendAlertsWidget({ count, previews }) {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-amber-200">Active Trend Alerts</h2>
        <Link to="/briefs?type=trend_alert" className="text-xs text-amber-400 hover:text-amber-300">
          View all →
        </Link>
      </div>
      {count === 0 ? (
        <p className="text-sm text-amber-300/60">No active trend spikes detected.</p>
      ) : (
        <>
          <div className="text-3xl font-bold text-amber-300 mb-3">{count}</div>
          <div className="space-y-2">
            {previews.map((t, i) => (
              <p key={i} className="text-xs text-amber-200/80 line-clamp-1">• {t.title}</p>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── Last brief widget ─────────────────────────────────────────────────────────
function LastBriefWidget({ brief }) {
  if (!brief) return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <h2 className="text-base font-semibold text-white mb-2">Last Brief Generated</h2>
      <p className="text-sm text-slate-500">No briefs generated yet.</p>
    </div>
  )
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-base font-semibold text-white">Last Brief Generated</h2>
        <Link to="/briefs" className="text-xs text-orange-400 hover:text-orange-300">View all →</Link>
      </div>
      <p className="text-xs text-slate-500 mb-2">
        {brief.generated_at ? new Date(brief.generated_at).toLocaleString('en-IN') : ''}
      </p>
      <Link to={`/briefs`} className="block">
        <p className="text-sm font-medium text-slate-200 line-clamp-1">{brief.title}</p>
        <p className="text-xs text-slate-400 mt-1 line-clamp-2">{(brief.body || '').slice(0, 140)}…</p>
      </Link>
    </div>
  )
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [metrics, setMetrics]   = useState(null)
  const [trends,  setTrends]    = useState([])
  const [brief,   setLastBrief] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error,   setError]     = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')

    Promise.all([
      getMetrics({ signal: controller.signal }),
      getTrends({ hours: 48 }, { signal: controller.signal }).catch(() => ({ data: { trends: [] } })),
      getBriefs({ type: 'daily_summary', limit: 1 }, { signal: controller.signal }).catch(() => ({ data: { briefs: [] } })),
    ])
      .then(([metricsRes, trendsRes, briefsRes]) => {
        setMetrics(metricsRes.data)
        setTrends(trendsRes.data.trends || [])
        const briefs = briefsRes.data.briefs || []
        setLastBrief(briefs[0] || null)
      })
      .catch(err => {
        if (!isCanceled(err)) setError('Could not load dashboard. Check that the backend is running on port 8000.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [])

  const summary = metrics?.summary || {}
  const funnel  = useMemo(() => metrics?.funnel || [], [metrics])
  const severity   = metrics?.severity_breakdown || {}
  const nlpStatus  = metrics?.nlp_status || {}
  const storageLabel = 'stored in AstraDB'

  if (loading) return (
    <div className="flex h-96 items-center justify-center text-slate-400">Loading metrics…</div>
  )

  if (error) return (
    <div className="mx-auto flex max-w-3xl items-center justify-center px-4 py-20">
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-5 py-4 text-sm text-red-300">{error}</div>
    </div>
  )

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 space-y-6">
      {/* Page title */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Data Health Dashboard</h1>
          <p className="mt-1 text-sm text-slate-400">Live visibility into ingestion, extraction, and intelligence.</p>
        </div>
        {metrics?.scrape?.running && (
          <span className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-300">
            Scrape running
          </span>
        )}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Articles" value={summary.articles_ingested} detail={storageLabel}                                                tone="articles" />
        <StatCard label="Events"   value={summary.events_created}    detail="created by NLP extraction"                                   tone="events" />
        <StatCard label="Mapped"   value={summary.entities_mapped}   detail={`${fmt(summary.entity_mappings)} event links`}               tone="mapped" />
        <StatCard label="Failures" value={summary.nlp_failures}      detail={`${fmt(summary.deduplicated)} dupes · ${summary.dedup_rate_percent || 0}% dedup`} tone="failures" />
      </div>

      {/* Search + trend alerts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
        <SearchWidget />
        <TrendAlertsWidget count={trends.length} previews={trends.slice(0, 3)} />
      </div>

      {/* Funnel + breakdown row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_0.8fr]">
        <Funnel steps={funnel} />
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
          <h2 className="text-base font-semibold text-white">Breakdown</h2>
          <div className="mt-4 space-y-4">
            <div>
              <div className="mb-2 text-xs font-bold uppercase text-slate-500">Severity</div>
              {['high', 'medium', 'low'].map(k => (
                <div key={k} className="mb-2 flex items-center justify-between text-sm">
                  <span className="capitalize text-slate-300">{k}</span>
                  <span className="font-semibold text-white">{fmt(severity[k])}</span>
                </div>
              ))}
            </div>
            <div className="border-t border-slate-700 pt-4">
              <div className="mb-2 text-xs font-bold uppercase text-slate-500">NLP Status</div>
              {['success', 'failed', 'duplicate', 'pending'].map(k => (
                <div key={k} className="mb-2 flex items-center justify-between text-sm">
                  <span className="capitalize text-slate-300">{k}</span>
                  <span className="font-semibold text-white">{fmt(nlpStatus[k])}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Last brief */}
      <LastBriefWidget brief={brief} />
    </div>
  )
}
