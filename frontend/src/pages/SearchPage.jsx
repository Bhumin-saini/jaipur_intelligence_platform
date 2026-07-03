import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { searchEvents, isCanceled } from '../api'

const SEVERITY_STYLES = {
  high:   'bg-red-500/20 text-red-300 border-red-500/40',
  medium: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  low:    'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
}

const EVENT_TYPE_COLORS = {
  crime:     'text-red-400',
  politics:  'text-violet-400',
  accident:  'text-orange-400',
  fire:      'text-yellow-400',
  protest:   'text-pink-400',
  default:   'text-slate-400',
}

function SimilarityBar({ score }) {
  const pct = Math.round((score || 0) * 100)
  const color = pct >= 75 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-slate-500'
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <div className="h-1.5 w-24 rounded-full bg-slate-700">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span>{pct}% match</span>
    </div>
  )
}

function ResultCard({ event }) {
  const typeColor = EVENT_TYPE_COLORS[event.event_type] || EVENT_TYPE_COLORS.default
  const locations = Array.isArray(event.locations) ? event.locations : []
  const keywords  = Array.isArray(event.keywords)  ? event.keywords  : []

  return (
    <Link
      to={`/events/${event._id}`}
      className="block rounded-lg border border-slate-700 bg-slate-800 p-5 hover:border-slate-500 hover:bg-slate-750 transition-colors"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className={`text-xs font-bold uppercase ${typeColor}`}>
              {event.event_type || 'unknown'}
            </span>
            <span className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${SEVERITY_STYLES[event.severity] || SEVERITY_STYLES.low}`}>
              {event.severity}
            </span>
            {locations[0] && (
              <span className="text-xs text-slate-400">📍 {locations[0]}</span>
            )}
          </div>
          <p className="text-sm text-slate-200 leading-relaxed line-clamp-3">
            {event.summary || 'No summary available.'}
          </p>
          {keywords.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {keywords.slice(0, 5).map(kw => (
                <span key={kw} className="rounded bg-slate-700 px-2 py-0.5 text-[11px] text-slate-400">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <SimilarityBar score={event.$similarity} />
          <span className="text-xs text-slate-500">
            {event.created_at ? new Date(event.created_at).toLocaleDateString('en-IN') : ''}
          </span>
        </div>
      </div>
    </Link>
  )
}

function EmptyState({ query, loading }) {
  if (loading) return null
  if (!query) return (
    <div className="text-center py-24 text-slate-500">
      <div className="text-4xl mb-3">🔍</div>
      <p className="text-lg font-medium text-slate-400">Search the Jaipur intelligence corpus</p>
      <p className="text-sm mt-1">Try: "fire accident", "police arrest", "road accident Tonk Road", "आग"</p>
    </div>
  )
  return (
    <div className="text-center py-24 text-slate-500">
      <div className="text-4xl mb-3">🕵️</div>
      <p className="text-lg font-medium text-slate-400">No results for "{query}"</p>
      <p className="text-sm mt-1">Try broader terms or search in Hindi</p>
    </div>
  )
}

const DEBOUNCE_MS = 400

export default function SearchPage() {
  const [query,      setQuery]   = useState('')
  const [severity,   setSeverity] = useState('')
  const [results,    setResults]  = useState([])
  const [loading,    setLoading]  = useState(false)
  const [error,      setError]    = useState('')
  const [lastQuery,  setLastQuery] = useState('')
  const controllerRef = useRef(null)
  const timerRef      = useRef(null)

  const doSearch = useCallback((q, sev) => {
    if (!q.trim()) {
      setResults([])
      setLoading(false)
      return
    }
    if (controllerRef.current) controllerRef.current.abort()
    controllerRef.current = new AbortController()
    setLoading(true)
    setError('')
    setLastQuery(q)

    const params = { q, limit: 30 }
    if (sev) params.severity = sev

    searchEvents(params, { signal: controllerRef.current.signal })
      .then(r => {
        setResults(r.data.results || [])
      })
      .catch(err => {
        if (!isCanceled(err)) setError('Search failed — is the backend running?')
      })
      .finally(() => setLoading(false))
  }, [])

  // Debounce query changes
  useEffect(() => {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => doSearch(query, severity), DEBOUNCE_MS)
    return () => clearTimeout(timerRef.current)
  }, [query, severity, doSearch])

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Semantic Search</h1>
        <p className="mt-1 text-sm text-slate-400">
          Natural-language search across all Jaipur intelligence events — English or Hindi.
        </p>
      </div>

      {/* Search bar */}
      <div className="flex gap-3 mb-4">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">🔍</span>
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder='Try: "building fire Vaishali Nagar" or "आग"'
            className="w-full rounded-lg border border-slate-600 bg-slate-800 pl-10 pr-4 py-3
                       text-sm text-white placeholder-slate-500 outline-none
                       focus:border-orange-500 focus:ring-1 focus:ring-orange-500"
            autoFocus
          />
          {loading && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs">
              searching…
            </span>
          )}
        </div>
        <select
          value={severity}
          onChange={e => setSeverity(e.target.value)}
          className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-3 text-sm text-slate-200
                     outline-none focus:border-orange-500"
        >
          <option value="">All severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {/* Result count */}
      {results.length > 0 && !loading && (
        <p className="text-xs text-slate-500 mb-4">
          {results.length} results for "{lastQuery}"
          {severity && ` · severity: ${severity}`}
        </p>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300 mb-4">
          {error}
        </div>
      )}

      {/* Results */}
      {results.length > 0 ? (
        <div className="space-y-3">
          {results.map(ev => <ResultCard key={ev._id} event={ev} />)}
        </div>
      ) : (
        <EmptyState query={query} loading={loading} />
      )}
    </div>
  )
}
