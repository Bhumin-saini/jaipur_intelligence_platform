import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getGraphData, getMetrics, isCanceled } from '../api'

const SEV_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' }
const TYPE_COLOR = { person: '#3b82f6', organization: '#a855f7', location: '#f97316' }
const PIE_COLORS = ['#f97316', '#3b82f6', '#22c55e', '#ef4444', '#a855f7', '#14b8a6', '#f59e0b', '#94a3b8']

const tabs = [
  { id: 'graph', label: 'Graph' },
  { id: 'types', label: 'Types' },
  { id: 'severity', label: 'Severity' },
  { id: 'entities', label: 'Top Entities' },
]

function isGraphNode(id) {
  return id.startsWith('event-') || id.startsWith('entity-')
}

function buildSeveritySeries(rows = []) {
  const byDay = new Map(rows.map(row => [row.day, row]))
  const series = []
  for (let offset = 29; offset >= 0; offset -= 1) {
    const date = new Date()
    date.setDate(date.getDate() - offset)
    const day = date.toISOString().slice(0, 10)
    const row = byDay.get(day) || {}
    series.push({
      day,
      label: day.slice(5),
      high: row.high || 0,
      medium: row.medium || 0,
      low: row.low || 0,
      total: row.total || 0,
    })
  }
  return series
}

function polarToCartesian(cx, cy, radius, angle) {
  const radians = ((angle - 90) * Math.PI) / 180
  return {
    x: cx + radius * Math.cos(radians),
    y: cy + radius * Math.sin(radians),
  }
}

function pieSlicePath(cx, cy, radius, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, radius, endAngle)
  const end = polarToCartesian(cx, cy, radius, startAngle)
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1
  return `M ${cx} ${cy} L ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 0 ${end.x} ${end.y} Z`
}

function ChartShell({ title, subtitle, children }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <p className="text-sm text-slate-400">{subtitle}</p>
      </div>
      {children}
    </div>
  )
}

function EmptyChart({ message }) {
  return (
    <div className="flex h-80 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-sm text-slate-500">
      {message}
    </div>
  )
}

function EventTypePieChart({ data }) {
  const total = data.reduce((sum, row) => sum + row.count, 0)
  let angle = 0

  if (!total) return <EmptyChart message="No event type data yet." />

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <svg viewBox="0 0 260 260" className="mx-auto h-80 w-80 max-w-full">
        {data.map((row, index) => {
          const sweep = (row.count / total) * 360
          if (sweep >= 359.999) {
            angle += sweep
            return <circle key={row.name} cx="130" cy="130" r="108" fill={PIE_COLORS[index % PIE_COLORS.length]} />
          }
          const path = pieSlicePath(130, 130, 108, angle, angle + sweep)
          angle += sweep
          return <path key={row.name} d={path} fill={PIE_COLORS[index % PIE_COLORS.length]} stroke="#0f172a" strokeWidth="2" />
        })}
        <circle cx="130" cy="130" r="58" fill="#1e293b" />
        <text x="130" y="126" textAnchor="middle" className="fill-white text-2xl font-bold">{total}</text>
        <text x="130" y="148" textAnchor="middle" className="fill-slate-400 text-xs">events</text>
      </svg>

      <div className="space-y-2 self-center">
        {data.map((row, index) => {
          const pct = Math.round((row.count / total) * 100)
          return (
            <div key={row.name} className="flex items-center gap-3 rounded-lg bg-slate-900 px-3 py-2">
              <span className="h-3 w-3 rounded-full" style={{ background: PIE_COLORS[index % PIE_COLORS.length] }} />
              <span className="flex-1 capitalize text-slate-200">{row.name}</span>
              <span className="text-sm font-semibold text-white">{row.count}</span>
              <span className="w-10 text-right text-xs text-slate-500">{pct}%</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SeverityAreaChart({ data }) {
  const width = 900
  const height = 320
  const padX = 32
  const padY = 26
  const chartW = width - padX * 2
  const chartH = height - padY * 2
  const maxTotal = Math.max(...data.map(row => row.total), 1)

  const point = (row, index, key) => {
    const x = padX + (index / Math.max(data.length - 1, 1)) * chartW
    const y = height - padY - ((row[key] || 0) / maxTotal) * chartH
    return `${x},${y}`
  }

  const polygon = key => {
    const points = data.map((row, index) => point(row, index, key)).join(' ')
    return `${padX},${height - padY} ${points} ${width - padX},${height - padY}`
  }

  const line = key => data.map((row, index) => point(row, index, key)).join(' ')

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="min-w-[720px]">
        {[0, 0.25, 0.5, 0.75, 1].map(tick => {
          const y = height - padY - tick * chartH
          return <line key={tick} x1={padX} x2={width - padX} y1={y} y2={y} stroke="#1e293b" />
        })}
        <polygon points={polygon('low')} fill="#22c55e33" />
        <polygon points={polygon('medium')} fill="#f59e0b33" />
        <polygon points={polygon('high')} fill="#ef444433" />
        <polyline points={line('low')} fill="none" stroke={SEV_COLOR.low} strokeWidth="3" />
        <polyline points={line('medium')} fill="none" stroke={SEV_COLOR.medium} strokeWidth="3" />
        <polyline points={line('high')} fill="none" stroke={SEV_COLOR.high} strokeWidth="3" />
        {data.filter((_, index) => index % 5 === 0 || index === data.length - 1).map((row, index) => {
          const originalIndex = data.findIndex(item => item.day === row.day)
          const x = padX + (originalIndex / Math.max(data.length - 1, 1)) * chartW
          return <text key={`${row.day}-${index}`} x={x} y={height - 4} textAnchor="middle" className="fill-slate-500 text-[10px]">{row.label}</text>
        })}
      </svg>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-300">
        {Object.entries(SEV_COLOR).map(([key, color]) => (
          <span key={key} className="inline-flex items-center gap-2 capitalize">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
            {key}
          </span>
        ))}
      </div>
    </div>
  )
}

function TopEntityBarChart({ data }) {
  const max = Math.max(...data.map(entity => entity.mention_count), 1)

  if (!data.length) return <EmptyChart message="No entity data yet." />

  return (
    <div className="space-y-3">
      {data.map(entity => {
        const width = Math.max(8, Math.round((entity.mention_count / max) * 100))
        return (
          <div key={entity.id} className="grid grid-cols-[150px_1fr_44px] items-center gap-3 text-sm">
            <span className="truncate text-slate-300" title={entity.name}>{entity.name}</span>
            <div className="h-8 rounded bg-slate-900">
              <div className="flex h-8 items-center justify-end rounded bg-orange-500 px-3 text-xs font-bold text-white" style={{ width: `${width}%` }}>
                {width > 22 ? entity.type : ''}
              </div>
            </div>
            <span className="text-right font-semibold text-white">{entity.mention_count}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function GraphView() {
  const containerRef = useRef(null)
  const cyRef = useRef(null)
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('graph')
  const [loading, setLoading] = useState(true)
  const [info, setInfo] = useState('')
  const [limit, setLimit] = useState(25)
  const [focusMode, setFocusMode] = useState(false)
  const [metrics, setMetrics] = useState(null)
  const [metricsError, setMetricsError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getMetrics({ signal: controller.signal })
      .then(({ data }) => setMetrics(data))
      .catch(error => {
        if (!isCanceled(error)) setMetricsError('Could not load chart metrics.')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (activeTab !== 'graph') return undefined

    let cancelled = false
    const controller = new AbortController()
    setLoading(true)
    setInfo('')

    getGraphData({ limit }, { signal: controller.signal })
      .then(async ({ data }) => {
        if (cancelled || !containerRef.current) return
        const cytoscape = (await import('cytoscape')).default
        if (cancelled || !containerRef.current) return

        const elements = [
          ...data.nodes.map(node => ({
            data: {
              id: node.id,
              label: node.label?.substring(0, 60) || node.id,
              group: node.group,
              color: node.group === 'event'
                ? (SEV_COLOR[node.severity] || '#f97316')
                : (TYPE_COLOR[node.group] || '#94a3b8'),
            },
          })),
          ...data.links.map(link => ({
            data: { source: link.source, target: link.target, role: link.role || '' },
          })),
        ]

        if (cyRef.current) {
          cyRef.current.destroy()
          cyRef.current = null
        }

        const cy = cytoscape({
          container: containerRef.current,
          elements,
          style: [
            {
              selector: 'node',
              style: {
                'background-color': 'data(color)',
                label: 'data(label)',
                color: '#e2e8f0',
                'font-size': 10,
                'text-valign': 'bottom',
                'text-margin-y': 6,
                'text-wrap': 'ellipsis',
                'text-max-width': 90,
                width: 22,
                height: 22,
                'border-width': 2,
                'border-color': '#0f172a',
              },
            },
            { selector: 'node[group="event"]', style: { shape: 'ellipse', width: 28, height: 28 } },
            { selector: 'node[group="person"]', style: { shape: 'round-rectangle' } },
            { selector: 'node[group="location"]', style: { shape: 'diamond' } },
            { selector: 'node[group="organization"]', style: { shape: 'hexagon' } },
            {
              selector: 'edge',
              style: {
                width: 1,
                'line-color': '#334155',
                'target-arrow-color': '#334155',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
              },
            },
            { selector: ':selected', style: { 'border-width': 4, 'border-color': '#f97316' } },
            { selector: '.hidden', style: { display: 'none' } },
          ],
          layout: {
            name: 'cose',
            animate: true,
            animationDuration: 600,
            nodeRepulsion: 6000,
            idealEdgeLength: 80,
            fit: true,
            padding: 30,
          },
        })

        const focusNode = node => {
          const oneHop = node.closedNeighborhood()
          const twoHop = oneHop.nodes().closedNeighborhood()
          const visible = oneHop.union(twoHop).union(twoHop.connectedEdges())
          cy.elements().addClass('hidden')
          visible.removeClass('hidden')
          cy.fit(visible, 40)
        }

        cy.on('tap', 'node', event => {
          const id = event.target.id()
          if (!isGraphNode(id)) return
          if (focusMode) {
            focusNode(event.target)
            return
          }
          if (id.startsWith('event-')) navigate(`/events/${id.replace('event-', '')}`)
          if (id.startsWith('entity-')) navigate(`/entities/${id.replace('entity-', '')}`)
        })
        cy.on('tap', event => {
          if (focusMode && event.target === cy) {
            cy.elements().removeClass('hidden')
            cy.fit(undefined, 30)
          }
        })
        cy.on('mouseover', 'node', event => event.target.style({ 'border-color': '#f97316', 'border-width': 3 }))
        cy.on('mouseout', 'node', event => event.target.style({ 'border-color': '#0f172a', 'border-width': 2 }))

        cyRef.current = cy
        setInfo(`${data.nodes.length} nodes / ${data.links.length} edges`)
        setLoading(false)
      })
      .catch(error => {
        if (!isCanceled(error)) {
          setInfo('Error loading graph - is the backend running?')
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
      controller.abort()
      if (cyRef.current) {
        cyRef.current.destroy()
        cyRef.current = null
      }
    }
  }, [activeTab, limit, focusMode, navigate])

  const eventTypeData = useMemo(
    () => (metrics?.event_type_distribution || []).map(row => ({
      name: row.event_type,
      count: row.count,
    })),
    [metrics],
  )
  const severitySeries = useMemo(
    () => buildSeveritySeries(metrics?.severity_by_day || []),
    [metrics],
  )
  const entityData = useMemo(
    () => (metrics?.top_entities || []),
    [metrics],
  )

  return (
    <div style={{ position: 'relative', minHeight: 'calc(100vh - 64px)', background: '#020617' }}>
      <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, background: 'rgba(15,23,42,0.94)',
        border: '1px solid #334155', borderRadius: 14, padding: 14, minWidth: 250 }}>
        <div style={{ color: 'white', fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Graph View</div>
        {activeTab === 'graph' && info && <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 10 }}>{info}</div>}

        <div className="mb-3 grid grid-cols-2 gap-2">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                activeTab === tab.id ? 'bg-orange-500 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'graph' && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <label style={{ color: '#64748b', fontSize: 12 }}>Events:</label>
              <select value={limit} onChange={event => setLimit(Number(event.target.value))}
                style={{ background: '#334155', border: 'none', color: 'white', borderRadius: 6, padding: '3px 6px', fontSize: 12 }}>
                {[25, 50, 100, 200].map(value => <option key={value} value={value}>{value}</option>)}
              </select>
            </div>
            <button
              onClick={() => setFocusMode(value => !value)}
              style={{
                width: '100%',
                marginBottom: 12,
                padding: '6px 8px',
                background: focusMode ? '#f97316' : '#334155',
                color: 'white',
                border: 'none',
                borderRadius: 8,
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {focusMode ? 'Focus mode on' : 'Focus mode off'}
            </button>
            {[
              ['Event by severity', '#f97316'],
              ['Person', '#3b82f6'],
              ['Organization', '#a855f7'],
              ['Location', '#f97316'],
            ].map(([label, color]) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: '#cbd5e1', marginBottom: 4 }}>
                <span style={{ width: 10, height: 10, borderRadius: 10, background: color, display: 'inline-block' }} />
                <span>{label}</span>
              </div>
            ))}
          </>
        )}
      </div>

      {activeTab === 'graph' ? (
        <>
          {loading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9 }}>
              <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: '12px 20px', color: '#94a3b8', fontSize: 14 }}>
                Building graph...
              </div>
            </div>
          )}
          <div ref={containerRef} style={{ width: '100%', height: 'calc(100vh - 64px)' }} />
        </>
      ) : (
        <div className="mx-auto max-w-6xl px-4 pb-10 pt-36">
          {metricsError && (
            <div className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {metricsError}
            </div>
          )}

          {activeTab === 'types' && (
            <ChartShell title="Event Type Distribution" subtitle="Share of extracted events by classification.">
              <EventTypePieChart data={eventTypeData} />
            </ChartShell>
          )}

          {activeTab === 'severity' && (
            <ChartShell title="Severity Over Last 30 Days" subtitle="Daily event volume grouped by extracted severity.">
              <SeverityAreaChart data={severitySeries} />
            </ChartShell>
          )}

          {activeTab === 'entities' && (
            <ChartShell title="Top Entities By Mentions" subtitle="Ten most frequently mapped people, organizations, and locations.">
              <TopEntityBarChart data={entityData} />
            </ChartShell>
          )}
        </div>
      )}
    </div>
  )
}
