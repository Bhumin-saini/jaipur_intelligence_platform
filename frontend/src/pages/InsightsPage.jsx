import React, { useState, useEffect, useCallback, useRef } from 'react'
import { isCanceled } from '../api'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const api = (path, params = {}) =>
  axios.get(`${API}${path}`, { params })

const TYPE_META = {
  pattern:       { label: 'Pattern',       icon: '🔁', color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/30' },
  escalation:    { label: 'Escalation',    icon: '📈', color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30' },
  actor:         { label: 'Actor',         icon: '👤', color: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/30' },
  location:      { label: 'Location',      icon: '📍', color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30' },
  thread:        { label: 'Thread',        icon: '🧵', color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
  contradiction: { label: 'Contradiction', icon: '⚠️', color: 'text-pink-400',  bg: 'bg-pink-500/10',   border: 'border-pink-500/30' },
}

const SEV_COLORS = {
  high:   'text-red-400',
  medium: 'text-yellow-400',
  low:    'text-green-400',
}

function Spinner() {
  return <div className="h-5 w-5 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

function ConfidenceRing({ value }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 45 ? '#f59e0b' : '#ef4444'
  return (
    <div className="relative flex items-center justify-center w-10 h-10 shrink-0">
      <svg className="absolute inset-0 -rotate-90" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="15" fill="none" stroke="#1e293b" strokeWidth="3" />
        <circle cx="18" cy="18" r="15" fill="none" stroke={color} strokeWidth="3"
          strokeDasharray={`${pct * 0.942} 94.2`} strokeLinecap="round" />
      </svg>
      <span className="text-[10px] font-bold text-white">{pct}</span>
    </div>
  )
}

// ── Insight Card ──────────────────────────────────────────────────────────────
function InsightCard({ insight, onClick }) {
  const meta = TYPE_META[insight.insight_type] || TYPE_META.pattern
  const sev  = insight.severity_signal || 'medium'

  return (
    <div
      onClick={() => onClick(insight)}
      className={`group cursor-pointer bg-slate-900 border rounded-xl p-4 transition-all hover:scale-[1.01]
        ${insight.read ? 'border-slate-800 opacity-75' : `border-slate-700 hover:${meta.border}`}`}
    >
      <div className="flex items-start gap-3">
        <ConfidenceRing value={insight.confidence || 0} />

        <div className="flex-1 min-w-0">
          {/* Type badge + severity */}
          <div className="flex items-center gap-2 mb-1.5">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${meta.color} ${meta.bg} ${meta.border}`}>
              {meta.icon} {meta.label}
            </span>
            <span className={`text-xs font-bold uppercase ${SEV_COLORS[sev]}`}>{sev}</span>
            {!insight.read && (
              <span className="w-2 h-2 rounded-full bg-orange-400 shrink-0" />
            )}
          </div>

          {/* Title */}
          <h3 className={`text-sm font-semibold leading-snug mb-1.5 ${insight.read ? 'text-slate-300' : 'text-white group-hover:text-orange-300'}`}>
            {insight.title}
          </h3>

          {/* Body preview */}
          <p className="text-slate-400 text-xs leading-relaxed line-clamp-2">
            {insight.body}
          </p>

          {/* Footer */}
          <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-600">
            {insight.location && <span>📍 {insight.location}</span>}
            <span>📋 {insight.evidence_count} events</span>
            <span>{(insight.created_at || '').slice(0, 16).replace('T', ' ')}</span>
            {insight.tags?.slice(0, 3).map(tag => (
              <span key={tag} className="bg-slate-800 text-slate-500 rounded px-1.5 py-0.5">{tag}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Insight Detail Modal ──────────────────────────────────────────────────────
function InsightDetailModal({ insight, onClose }) {
  const meta = TYPE_META[insight.insight_type] || TYPE_META.pattern
  const sev  = insight.severity_signal || 'medium'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className={`p-5 border-b border-slate-800 ${meta.bg}`}>
          <div className="flex items-start gap-3">
            <ConfidenceRing value={insight.confidence || 0} />
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${meta.color} ${meta.bg} ${meta.border}`}>
                  {meta.icon} {meta.label}
                </span>
                <span className={`text-xs font-bold uppercase ${SEV_COLORS[sev]}`}>{sev} signal</span>
                <span className="text-xs text-slate-500">{insight.evidence_count} supporting events</span>
              </div>
              <h2 className="text-base font-bold text-white leading-snug">{insight.title}</h2>
            </div>
            <button onClick={onClose} className="text-slate-500 hover:text-white text-xl shrink-0">✕</button>
          </div>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          <div className="bg-slate-800/50 rounded-xl p-4 border border-slate-700/50">
            <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Intelligence Assessment</div>
            <p className="text-slate-200 text-sm leading-relaxed whitespace-pre-wrap">{insight.body}</p>
          </div>

          {/* Metadata grid */}
          <div className="grid grid-cols-2 gap-3">
            {insight.location && (
              <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                <div className="text-xs text-slate-500 mb-1">Location</div>
                <div className="text-sm text-white font-medium">📍 {insight.location}</div>
              </div>
            )}
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <div className="text-xs text-slate-500 mb-1">Confidence</div>
              <div className="text-sm text-white font-medium">{Math.round((insight.confidence || 0) * 100)}%</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <div className="text-xs text-slate-500 mb-1">Evidence</div>
              <div className="text-sm text-white font-medium">{insight.evidence_count} events</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <div className="text-xs text-slate-500 mb-1">Generated</div>
              <div className="text-sm text-white font-medium">{(insight.created_at || '').slice(0, 16).replace('T', ' ')}</div>
            </div>
          </div>

          {/* Entity refs */}
          {insight.entity_refs?.length > 0 && (
            <div>
              <div className="text-xs text-slate-500 uppercase tracking-wider mb-2">Key Entities</div>
              <div className="flex flex-wrap gap-2">
                {insight.entity_refs.map(e => (
                  <span key={e} className="px-2 py-1 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300">{e}</span>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          {insight.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {insight.tags.map(tag => (
                <span key={tag} className="px-2 py-0.5 bg-slate-800 text-slate-500 rounded text-xs">{tag}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Stats Bar ─────────────────────────────────────────────────────────────────
function StatsBar({ stats, onGenerate, generating }) {
  if (!stats) return null
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 text-center">
        <div className="text-2xl font-black text-white">{stats.total || 0}</div>
        <div className="text-xs text-slate-500 mt-0.5">Total Insights</div>
      </div>
      <div className="bg-slate-900 border border-orange-500/20 rounded-xl p-3 text-center">
        <div className="text-2xl font-black text-orange-400">{stats.unread || 0}</div>
        <div className="text-xs text-slate-500 mt-0.5">Unread</div>
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 text-center">
        <div className="text-2xl font-black text-green-400">{Math.round((stats.avg_confidence || 0) * 100)}%</div>
        <div className="text-xs text-slate-500 mt-0.5">Avg Confidence</div>
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-3 text-center flex items-center justify-center">
        <button onClick={onGenerate} disabled={generating}
          className="px-3 py-1.5 bg-orange-500 hover:bg-orange-600 text-white text-xs font-semibold rounded-lg disabled:opacity-50 transition-colors">
          {generating ? '⟳ Running…' : '⟳ Generate'}
        </button>
      </div>
    </div>
  )
}

// ── Main InsightsPage ─────────────────────────────────────────────────────────
export default function InsightsPage() {
  const [insights, setInsights]       = useState([])
  const [stats, setStats]             = useState(null)
  const [loading, setLoading]         = useState(true)
  const [selected, setSelected]       = useState(null)
  const [filterType, setFilterType]   = useState('')
  const [filterDays, setFilterDays]   = useState(14)
  const [minConf, setMinConf]         = useState(0)
  const [generating, setGenerating]   = useState(false)
  const [searchQ, setSearchQ]         = useState('')
  const abortRef = useRef(null)

  const load = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    try {
      const params = { days: filterDays, limit: 100 }
      if (filterType) params.insight_type = filterType
      if (minConf > 0) params.min_confidence = minConf / 100

      const [insR, statR] = await Promise.all([
        api('/insights', params),
        api('/insights/stats'),
      ])
      setInsights(insR.data?.insights || [])
      setStats(statR.data)
    } catch (e) {
      if (!isCanceled(e)) setInsights([])
    }
    setLoading(false)
  }, [filterType, filterDays, minConf])

  useEffect(() => { load() }, [load])

  const handleSelect = (insight) => {
    setSelected(insight)
    // Mark as read locally
    setInsights(prev => prev.map(i => i._id === insight._id ? { ...i, read: true } : i))
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      await axios.post(`${API}/insights/generate`, { days: filterDays },
        { headers: { 'Content-Type': 'application/json' } })
      setTimeout(() => { load(); setGenerating(false) }, 3000)
    } catch { setGenerating(false) }
  }

  // Filter by search query
  const displayed = searchQ.trim()
    ? insights.filter(i =>
        i.title.toLowerCase().includes(searchQ.toLowerCase()) ||
        i.body.toLowerCase().includes(searchQ.toLowerCase()) ||
        (i.location || '').toLowerCase().includes(searchQ.toLowerCase())
      )
    : insights

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {selected && (
        <InsightDetailModal insight={selected} onClose={() => setSelected(null)} />
      )}

      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">Intelligence Insights</h1>
        <p className="text-slate-400 text-sm mt-0.5">
          AI-synthesised patterns, escalations, actor profiles, and ongoing threads
        </p>
      </div>

      {/* Stats */}
      <StatsBar stats={stats} onGenerate={handleGenerate} generating={generating} />

      {/* Type breakdown */}
      {stats?.by_type && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.by_type).map(([type, count]) => {
            const meta = TYPE_META[type] || TYPE_META.pattern
            return (
              <button key={type} onClick={() => setFilterType(filterType === type ? '' : type)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                  filterType === type
                    ? `${meta.color} ${meta.bg} ${meta.border}`
                    : 'text-slate-400 bg-slate-800 border-slate-700 hover:text-white'
                }`}>
                {meta.icon} {meta.label}
                <span className={`ml-1 font-bold ${filterType === type ? meta.color : 'text-slate-500'}`}>{count}</span>
              </button>
            )
          })}
          {filterType && (
            <button onClick={() => setFilterType('')} className="px-3 py-1.5 text-xs text-slate-500 hover:text-white">
              Clear filter ✕
            </button>
          )}
        </div>
      )}

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <input
          value={searchQ}
          onChange={e => setSearchQ(e.target.value)}
          placeholder="Search insights…"
          className="flex-1 min-w-48 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500"
        />

        {/* Days filter */}
        <div className="flex gap-1">
          {[7, 14, 30].map(d => (
            <button key={d} onClick={() => setFilterDays(d)}
              className={`px-3 py-2 text-sm rounded-lg border transition-colors ${
                filterDays === d
                  ? 'bg-orange-500/20 text-orange-400 border-orange-500/30'
                  : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
              }`}>
              {d}d
            </button>
          ))}
        </div>

        {/* Min confidence */}
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span className="text-xs">Min confidence:</span>
          <select value={minConf} onChange={e => setMinConf(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-sm text-white focus:outline-none">
            <option value={0}>Any</option>
            <option value={50}>50%+</option>
            <option value={70}>70%+</option>
            <option value={85}>85%+</option>
          </select>
        </div>
      </div>

      {/* Insights list */}
      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : displayed.length === 0 ? (
        <div className="text-center py-16 space-y-3">
          <div className="text-5xl">🔍</div>
          <p className="text-slate-400">
            {insights.length === 0
              ? 'No insights generated yet.'
              : 'No insights match your filters.'}
          </p>
          {insights.length === 0 && (
            <button onClick={handleGenerate} disabled={generating}
              className="mt-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold rounded-lg disabled:opacity-50">
              {generating ? '⟳ Generating…' : 'Generate Insights Now'}
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-xs text-slate-600 mb-2">{displayed.length} insights</div>
          {displayed.map(insight => (
            <InsightCard key={insight._id} insight={insight} onClick={handleSelect} />
          ))}
        </div>
      )}
    </div>
  )
}
