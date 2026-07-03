import React, { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { getTimeline, isCanceled } from '../api'

const SEV_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' }
const SEV_BG    = { high: 'bg-red-500/20 text-red-400 border-red-500/40',
                    medium: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
                    low:    'bg-green-500/20 text-green-400 border-green-500/40' }
const TYPE_ICON = {
  crime:'🚨', politics:'🏛', accident:'💥', infrastructure:'🏗',
  cultural:'🎭', weather:'🌧', business:'💼', health:'🏥', other:'📌',
}

function DayRow({ entry, isExpanded, onToggle }) {
  const { day, high, medium, low, total, events } = entry
  const date = new Date(day + 'T12:00:00')
  const label = date.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })

  const dots = [
    ...Array(Math.min(high, 8)).fill('high'),
    ...Array(Math.min(medium, 8)).fill('medium'),
    ...Array(Math.min(low, 8)).fill('low'),
  ]

  return (
    <div className="border-b border-slate-800 last:border-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 px-4 py-3 hover:bg-slate-800/60 transition-colors text-left"
      >
        {/* Date */}
        <div className="w-28 shrink-0">
          <div className="text-sm font-semibold text-white">{label}</div>
          <div className="text-xs text-slate-500">{day}</div>
        </div>

        {/* Severity counts */}
        <div className="flex items-center gap-3 shrink-0 w-32">
          {high > 0   && <span className="text-xs font-bold text-red-400">  {high}H</span>}
          {medium > 0 && <span className="text-xs font-bold text-amber-400">{medium}M</span>}
          {low > 0    && <span className="text-xs font-bold text-green-400">{low}L</span>}
        </div>

        {/* Dot visualisation */}
        <div className="flex items-center gap-1 flex-1 flex-wrap">
          {dots.map((sev, i) => (
            <span
              key={i}
              title={sev}
              style={{ background: SEV_COLOR[sev] }}
              className="inline-block w-2.5 h-2.5 rounded-full opacity-80"
            />
          ))}
          {total > 24 && (
            <span className="text-xs text-slate-500 ml-1">+{total - 24} more</span>
          )}
        </div>

        {/* Total + chevron */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-sm font-bold text-orange-400">{total}</span>
          <span className="text-slate-500 text-xs">{isExpanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded events */}
      {isExpanded && events?.length > 0 && (
        <div className="px-4 pb-4 space-y-2 border-t border-slate-800/60 pt-3 bg-slate-900/40">
          {events.map(ev => (
            <Link
              key={ev._id}
              to={`/events/${ev._id}`}
              className="flex items-start gap-3 rounded-lg bg-slate-800 border border-slate-700
                         p-3 hover:border-slate-500 transition-colors group"
            >
              <span className="text-lg mt-0.5 shrink-0">{TYPE_ICON[ev.event_type] || '📌'}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className={`px-2 py-0.5 rounded border text-xs font-bold uppercase ${SEV_BG[ev.severity] || SEV_BG.low}`}>
                    {ev.severity}
                  </span>
                  <span className="text-xs text-slate-400 capitalize">{ev.event_type}</span>
                </div>
                <div className="text-sm font-medium text-white group-hover:text-orange-300 transition-colors truncate">
                  {ev.article_title || ev.summary}
                </div>
                {ev.summary && (
                  <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{ev.summary}</p>
                )}
              </div>
              <span className="text-orange-400 text-sm shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">→</span>
            </Link>
          ))}
          {total > events.length && (
            <Link
              to={`/map?from=${day}&to=${day}`}
              className="block text-center text-xs text-orange-400 hover:text-orange-300 py-2"
            >
              View all {total} events on map →
            </Link>
          )}
        </div>
      )}
    </div>
  )
}

function MiniCalendar({ data, activeDay, onSelect }) {
  const bySev = Object.fromEntries(data.map(d => [d.day, d]))
  const days  = data.map(d => d.day).sort()
  if (!days.length) return null

  const max = Math.max(...data.map(d => d.total), 1)

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <div className="text-xs font-bold uppercase text-slate-500 mb-3 tracking-wider">Activity Heatmap</div>
      <div className="flex flex-wrap gap-1">
        {days.map(day => {
          const d = bySev[day]
          const intensity = d ? d.total / max : 0
          const color = d?.high > 0 ? `rgba(239,68,68,${0.2 + intensity * 0.8})`
                      : d?.medium > 0 ? `rgba(245,158,11,${0.2 + intensity * 0.8})`
                      : `rgba(34,197,94,${0.2 + intensity * 0.8})`
          return (
            <button
              key={day}
              onClick={() => onSelect(day)}
              title={`${day}: ${d?.total || 0} events`}
              style={{ background: d ? color : 'transparent' }}
              className={`w-5 h-5 rounded-sm border transition-all ${
                activeDay === day ? 'border-white scale-125' : 'border-slate-700 hover:border-slate-400'
              }`}
            />
          )
        })}
      </div>
      <div className="flex items-center gap-2 mt-3 text-xs text-slate-500">
        <span className="inline-block w-3 h-3 rounded-sm bg-slate-700" /> None
        <span className="inline-block w-3 h-3 rounded-sm bg-green-500/40" /> Low
        <span className="inline-block w-3 h-3 rounded-sm bg-amber-500/60" /> Medium
        <span className="inline-block w-3 h-3 rounded-sm bg-red-500/80" />  High
      </div>
    </div>
  )
}

export default function TimelinePage() {
  const [data, setData]       = useState([])
  const [loading, setLoading] = useState(true)
  const [days, setDays]       = useState(30)
  const [expanded, setExpanded] = useState(new Set())
  const [filter, setFilter]   = useState('')   // 'high' | 'medium' | 'low' | ''
  const [typeFilter, setTypeFilter] = useState('')

  const load = useCallback((signal) => {
    setLoading(true)
    getTimeline({ days }, { signal })
      .then(r => {
        const sorted = [...(r.data || [])].reverse() // newest first
        setData(sorted)
        // Auto-expand last 3 days
        const top3 = sorted.slice(0, 3).map(d => d.day)
        setExpanded(new Set(top3))
      })
      .catch(err => { if (!isCanceled(err)) setData([]) })
      .finally(() => setLoading(false))
  }, [days])

  useEffect(() => {
    const c = new AbortController()
    load(c.signal)
    return () => c.abort()
  }, [load])

  const toggle = day => setExpanded(prev => {
    const next = new Set(prev)
    next.has(day) ? next.delete(day) : next.add(day)
    return next
  })

  const filtered = data.filter(d => {
    if (filter === 'high')   return d.high > 0
    if (filter === 'medium') return d.medium > 0
    if (filter === 'low')    return d.low > 0
    return true
  })

  const totalEvents   = data.reduce((s, d) => s + d.total, 0)
  const totalHigh     = data.reduce((s, d) => s + d.high, 0)
  const activeDay     = [...expanded].sort().reverse()[0] || null

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Intelligence Timeline</h1>
          <p className="text-sm text-slate-400 mt-1">
            Day-by-day event history for Jaipur — {totalEvents} events over {days} days
          </p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 14, 30, 60].map(d => (
            <button key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                days === d
                  ? 'bg-orange-500 text-white'
                  : 'bg-slate-800 border border-slate-700 text-slate-400 hover:border-slate-500'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Events', value: totalEvents, color: 'text-orange-400' },
          { label: 'High Severity', value: totalHigh, color: 'text-red-400' },
          { label: 'Active Days', value: data.filter(d => d.total > 0).length, color: 'text-blue-400' },
          { label: 'Daily Average', value: data.length ? (totalEvents / data.length).toFixed(1) : 0, color: 'text-green-400' },
        ].map(s => (
          <div key={s.label} className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-center">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-xs text-slate-500 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main timeline */}
        <div className="lg:col-span-2 space-y-4">
          {/* Filter bar */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-500 uppercase font-bold tracking-wider">Filter:</span>
            {[['', 'All'], ['high', '🔴 High'], ['medium', '🟡 Medium'], ['low', '🟢 Low']].map(([val, label]) => (
              <button key={val} onClick={() => setFilter(val)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  filter === val
                    ? 'bg-orange-500 text-white'
                    : 'bg-slate-800 border border-slate-700 text-slate-400 hover:border-slate-500'
                }`}
              >
                {label}
              </button>
            ))}
            <button onClick={() => setExpanded(new Set(filtered.map(d => d.day)))}
              className="ml-auto text-xs text-slate-500 hover:text-slate-300">Expand all</button>
            <button onClick={() => setExpanded(new Set())}
              className="text-xs text-slate-500 hover:text-slate-300">Collapse all</button>
          </div>

          <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
            {loading ? (
              <div className="py-20 text-center text-slate-400">Loading timeline…</div>
            ) : filtered.length === 0 ? (
              <div className="py-20 text-center text-slate-500">No events in this period.</div>
            ) : (
              filtered.map(entry => (
                <DayRow
                  key={entry.day}
                  entry={entry}
                  isExpanded={expanded.has(entry.day)}
                  onToggle={() => toggle(entry.day)}
                />
              ))
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <MiniCalendar
            data={[...data].reverse()}
            activeDay={activeDay}
            onSelect={day => {
              setExpanded(prev => {
                const next = new Set(prev)
                next.has(day) ? next.delete(day) : next.add(day)
                return next
              })
              // Scroll to that day
              setTimeout(() => {
                document.querySelector(`[data-day="${day}"]`)?.scrollIntoView({ behavior: 'smooth' })
              }, 100)
            }}
          />

          {/* Severity summary */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
            <div className="text-xs font-bold uppercase text-slate-500 tracking-wider">Severity Breakdown</div>
            {[
              { key: 'high',   label: 'High',   color: 'bg-red-500',    val: totalHigh },
              { key: 'medium', label: 'Medium', color: 'bg-amber-500',  val: data.reduce((s,d) => s+d.medium, 0) },
              { key: 'low',    label: 'Low',    color: 'bg-green-500',  val: data.reduce((s,d) => s+d.low, 0) },
            ].map(s => (
              <div key={s.key}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-300">{s.label}</span>
                  <span className="text-slate-400 font-semibold">{s.val}</span>
                </div>
                <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${s.color} rounded-full transition-all`}
                    style={{ width: totalEvents ? `${(s.val / totalEvents * 100).toFixed(1)}%` : '0%' }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
