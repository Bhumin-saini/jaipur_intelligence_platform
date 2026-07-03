import React, { useEffect, useState } from 'react'
import { getBriefs, getBrief, isCanceled } from '../api'

const BRIEF_TYPE_META = {
  daily_summary:    { label: 'Daily Brief',    color: 'text-sky-300',    bg: 'bg-sky-500/15 border-sky-500/30' },
  trend_alert:      { label: 'Trend Alert',    color: 'text-amber-300',  bg: 'bg-amber-500/15 border-amber-500/30' },
  anomaly:          { label: 'Anomaly',        color: 'text-red-300',    bg: 'bg-red-500/15 border-red-500/30' },
  weekly_briefing:  { label: 'Weekly Brief',   color: 'text-violet-300', bg: 'bg-violet-500/15 border-violet-500/30' },
  entity_profile:   { label: 'Entity Profile', color: 'text-emerald-300',bg: 'bg-emerald-500/15 border-emerald-500/30' },
}

function BriefTypeBadge({ type }) {
  const meta = BRIEF_TYPE_META[type] || { label: type, color: 'text-slate-300', bg: 'bg-slate-500/15 border-slate-500/30' }
  return (
    <span className={`rounded border px-2 py-0.5 text-[11px] font-bold uppercase ${meta.color} ${meta.bg}`}>
      {meta.label}
    </span>
  )
}

function BriefCard({ brief, onSelect, selected }) {
  const isSelected = selected?._id === brief._id
  return (
    <button
      onClick={() => onSelect(brief)}
      className={`w-full text-left rounded-lg border p-4 transition-colors
        ${isSelected
          ? 'border-orange-500/60 bg-orange-500/10'
          : 'border-slate-700 bg-slate-800 hover:border-slate-600'
        }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <BriefTypeBadge type={brief.brief_type} />
            <span className="text-xs text-slate-500">
              {brief.generated_at ? new Date(brief.generated_at).toLocaleString('en-IN') : ''}
            </span>
          </div>
          <p className="text-sm font-medium text-slate-200 line-clamp-2">{brief.title}</p>
          {brief.body && (
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">{brief.body.slice(0, 120)}…</p>
          )}
        </div>
        {isSelected && <span className="text-orange-400 text-xs shrink-0">▶</span>}
      </div>
    </button>
  )
}

function BriefDetail({ brief }) {
  if (!brief) return (
    <div className="flex h-full items-center justify-center text-slate-500 text-sm">
      Select a brief to read it
    </div>
  )

  const meta = brief.metadata || {}

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <BriefTypeBadge type={brief.brief_type} />
        <span className="text-xs text-slate-400">
          Generated {brief.generated_at ? new Date(brief.generated_at).toLocaleString('en-IN') : 'unknown'}
        </span>
      </div>
      <h2 className="text-xl font-bold text-white mb-4 leading-snug">{brief.title}</h2>

      {/* Metadata pills */}
      {Object.keys(meta).length > 0 && (
        <div className="flex flex-wrap gap-2 mb-5">
          {meta.event_count != null && (
            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
              {meta.event_count} events
            </span>
          )}
          {meta.spike_ratio != null && (
            <span className="rounded bg-amber-500/20 border border-amber-500/30 px-2 py-0.5 text-xs text-amber-300">
              {meta.spike_ratio}× spike
            </span>
          )}
          {meta.sigma != null && (
            <span className="rounded bg-red-500/20 border border-red-500/30 px-2 py-0.5 text-xs text-red-300">
              {meta.sigma}σ outlier
            </span>
          )}
          {meta.event_type && (
            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
              {meta.event_type}
            </span>
          )}
          {meta.location && meta.location !== '_none' && (
            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
              📍 {meta.location}
            </span>
          )}
          {meta.date && (
            <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
              {meta.date}
            </span>
          )}
        </div>
      )}

      {/* Body */}
      <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap border-t border-slate-700 pt-5">
        {brief.body}
      </div>
    </div>
  )
}

const FILTER_OPTIONS = [
  { value: '',               label: 'All Briefs' },
  { value: 'daily_summary',  label: 'Daily Briefs' },
  { value: 'trend_alert',    label: 'Trend Alerts' },
  { value: 'anomaly',        label: 'Anomalies' },
  { value: 'weekly_briefing',label: 'Weekly' },
]

export default function BriefsPage() {
  const [briefs,    setBriefs]    = useState([])
  const [selected,  setSelected]  = useState(null)
  const [filter,    setFilter]    = useState('')
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')

    const params = { limit: 50 }
    if (filter) params.type = filter

    getBriefs(params, { signal: controller.signal })
      .then(r => {
        const list = r.data.briefs || []
        setBriefs(list)
        if (list.length > 0 && !selected) setSelected(list[0])
      })
      .catch(err => {
        if (!isCanceled(err)) setError('Could not load briefs.')
      })
      .finally(() => setLoading(false))

    return () => controller.abort()
  }, [filter])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Intelligence Briefs</h1>
          <p className="mt-1 text-sm text-slate-400">
            AI-generated daily summaries, trend alerts, and anomaly reports.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {FILTER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => { setFilter(opt.value); setSelected(null) }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
                ${filter === opt.value
                  ? 'bg-orange-500 text-white'
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-64 items-center justify-center text-slate-400 text-sm">
          Loading briefs…
        </div>
      ) : briefs.length === 0 ? (
        <div className="flex h-64 items-center justify-center flex-col gap-3 text-slate-500">
          <span className="text-3xl">📋</span>
          <p>No briefs generated yet.</p>
          <p className="text-xs">The daily brief runs at 07:00 IST. Trigger a scrape cycle to populate data.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[380px_1fr]" style={{ minHeight: '70vh' }}>
          {/* List column */}
          <div className="space-y-2 overflow-y-auto" style={{ maxHeight: '80vh' }}>
            {briefs.map(b => (
              <BriefCard key={b._id} brief={b} onSelect={setSelected} selected={selected} />
            ))}
          </div>

          {/* Detail column */}
          <div className="rounded-lg border border-slate-700 bg-slate-800 p-6" style={{ minHeight: '60vh' }}>
            <BriefDetail brief={selected} />
          </div>
        </div>
      )}
    </div>
  )
}
