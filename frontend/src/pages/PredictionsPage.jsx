import React, { useState, useEffect, useCallback } from 'react'
import { getPredictions, getHotspots, getForecast, generatePredictions, isCanceled } from '../api'

const RISK_COLORS = {
  high:   { text: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/30' },
  medium: { text: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
  low:    { text: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/30' },
}
const TREND_ICONS = { rising: '↑', falling: '↓', stable: '→' }
const TREND_COLORS = { rising: 'text-red-400', falling: 'text-green-400', stable: 'text-slate-400' }
const EVENT_TYPES = ['crime','accident','infrastructure','politics','health','weather','business']

function Spinner() {
  return <div className="h-5 w-5 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

function RiskBadge({ level }) {
  const c = RISK_COLORS[level] || RISK_COLORS.low
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase border ${c.text} ${c.bg} ${c.border}`}>
      {level}
    </span>
  )
}

// ── Forecast Chart (pure CSS bar chart) ──────────────────────────────────────
function ForecastBars({ history, forecast }) {
  const allDays = [...(history || []).slice(-14), ...(forecast || [])]
  if (!allDays.length) return null
  const maxVal = Math.max(...allDays.map(d => d.expected_count ?? d.count ?? 0), 1)

  return (
    <div className="flex items-end gap-0.5 h-28 mt-2">
      {allDays.map((d, i) => {
        const isFC = i >= (history || []).slice(-14).length
        const val = d.expected_count ?? d.count ?? 0
        const height = `${Math.max(4, (val / maxVal) * 100)}%`
        const label = (d.date || '').slice(5)
        return (
          <div key={i} className="flex-1 flex flex-col items-center gap-0.5 group relative">
            <div className={`w-full rounded-t-sm transition-all ${isFC ? 'bg-orange-500/60 border-t border-orange-400' : 'bg-blue-500/40'}`}
              style={{ height }} />
            <div className="absolute bottom-full mb-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-10">
              {label}: {val.toFixed ? val.toFixed(1) : val}
              {isFC && d.lower !== undefined && ` (${d.lower}–${d.upper})`}
            </div>
            {(i === 0 || i === 6 || i === 13 || i === allDays.length - 1) && (
              <div className="text-[9px] text-slate-600">{label}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Forecast Panel ────────────────────────────────────────────────────────────
function ForecastPanel({ eventType }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    setData(null)
    getForecast(eventType, { lookback_days: 30, forecast_days: 7 })
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [eventType])

  if (loading) return <div className="flex justify-center py-8"><Spinner /></div>
  if (!data) return <p className="text-slate-500 text-sm text-center py-4">No forecast data available.</p>

  const rc = RISK_COLORS[data.risk_level] || RISK_COLORS.low

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div>
          <div className="text-2xl font-black text-white capitalize">{data.event_type}</div>
          <div className="flex items-center gap-2 mt-1">
            <RiskBadge level={data.risk_level} />
            <span className={`text-sm font-bold ${TREND_COLORS[data.trend]}`}>
              {TREND_ICONS[data.trend]} {data.trend}
            </span>
            <span className="text-sm text-slate-500">~{data.recent_avg}/day avg</span>
          </div>
        </div>
      </div>

      <ForecastBars history={data.daily_history} forecast={data.forecast} />

      <div className="grid grid-cols-2 gap-2">
        {(data.forecast || []).slice(0, 4).map(f => (
          <div key={f.date} className={`rounded-lg p-3 border ${rc.bg} ${rc.border}`}>
            <div className="text-xs text-slate-500">{f.date}</div>
            <div className="text-lg font-bold text-white">{f.expected_count}</div>
            <div className="text-xs text-slate-500">{f.lower}–{f.upper} expected</div>
          </div>
        ))}
      </div>

      {data.insights?.length > 0 && (
        <div className="space-y-1">
          {data.insights.map((ins, i) => (
            <div key={i} className="flex items-start gap-2 text-sm text-slate-300">
              <span className="text-orange-400 shrink-0">→</span>
              <span>{ins}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Hotspots Panel ────────────────────────────────────────────────────────────
function HotspotsPanel({ days }) {
  const [hotspots, setHotspots] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getHotspots({ days, top_n: 10 })
      .then(r => setHotspots(r.data?.hotspots || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="flex justify-center py-8"><Spinner /></div>

  const maxRisk = Math.max(...hotspots.map(h => h.risk_score), 0.01)

  return (
    <div className="space-y-2">
      {hotspots.length === 0 ? (
        <p className="text-center text-slate-500 text-sm py-6">No hotspot data available.</p>
      ) : hotspots.map((h, i) => {
        const rPct = (h.risk_score / maxRisk) * 100
        const rc = h.risk_score >= 0.6 ? RISK_COLORS.high : h.risk_score >= 0.3 ? RISK_COLORS.medium : RISK_COLORS.low
        return (
          <div key={h.location} className={`flex items-center gap-3 p-3 rounded-lg border ${rc.bg} ${rc.border}`}>
            <div className="text-lg font-black text-slate-500 w-6 shrink-0">{i + 1}</div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-semibold text-white">{h.location}</span>
                <span className={`text-xs font-bold ${TREND_COLORS[h.trend]}`}>
                  {TREND_ICONS[h.trend]} {h.trend}
                </span>
                <RiskBadge level={h.risk_score >= 0.6 ? 'high' : h.risk_score >= 0.3 ? 'medium' : 'low'} />
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5">
                <div className={`h-1.5 rounded-full ${rc.text.replace('text-', 'bg-')}`} style={{ width: `${rPct}%` }} />
              </div>
              <div className="flex gap-3 mt-1 text-xs text-slate-500">
                <span>{h.event_count} events</span>
                <span>×{h.trend_ratio} vs baseline</span>
                {h.top_event_types?.map(t => (
                  <span key={t} className="text-slate-600">{t}</span>
                ))}
              </div>
            </div>
            <div className={`text-lg font-black ${rc.text} shrink-0`}>
              {(h.risk_score * 100).toFixed(0)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Main PredictionsPage ──────────────────────────────────────────────────────
export default function PredictionsPage() {
  const [tab, setTab] = useState('forecast')
  const [selectedType, setSelectedType] = useState('crime')
  const [hotspotDays, setHotspotDays] = useState(7)
  const [generating, setGenerating] = useState(false)

  const handleGenerate = async () => {
    setGenerating(true)
    try { await generatePredictions() } catch {}
    setTimeout(() => setGenerating(false), 2000)
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Predictive Intelligence</h1>
          <p className="text-slate-400 text-sm">7-day event forecasts and geographic hotspot analysis</p>
        </div>
        <button onClick={handleGenerate} disabled={generating}
          className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold rounded-lg disabled:opacity-50">
          {generating ? '⟳ Generating…' : '⟳ Run Predictions'}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800">
        {[['forecast','Event Forecasts'],['hotspots','Geographic Hotspots']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === k ? 'text-orange-400 border-orange-500' : 'text-slate-400 border-transparent hover:text-white'
            }`}>{l}</button>
        ))}
      </div>

      {tab === 'forecast' ? (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {/* Type selector */}
          <div className="lg:col-span-1 space-y-1">
            {EVENT_TYPES.map(et => (
              <button key={et} onClick={() => setSelectedType(et)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm capitalize transition-colors ${
                  selectedType === et
                    ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`}>
                {et}
              </button>
            ))}
          </div>
          {/* Forecast panel */}
          <div className="lg:col-span-3 bg-slate-900 border border-slate-800 rounded-xl p-5">
            <ForecastPanel key={selectedType} eventType={selectedType} />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-400">Lookback:</span>
            {[7, 14, 30].map(d => (
              <button key={d} onClick={() => setHotspotDays(d)}
                className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                  hotspotDays === d ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' : 'bg-slate-800 text-slate-400 border-slate-700'
                }`}>
                {d} days
              </button>
            ))}
          </div>
          <HotspotsPanel key={hotspotDays} days={hotspotDays} />
        </div>
      )}
    </div>
  )
}
