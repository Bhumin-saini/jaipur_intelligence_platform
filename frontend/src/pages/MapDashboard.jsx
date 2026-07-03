import React, { useEffect, useState, useCallback, useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet'
import { useNavigate } from 'react-router-dom'
import { getEvents, getHeatmap, isCanceled } from '../api'

const SEV_COLOR  = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' }
const SEV_RADIUS = { high: 14, medium: 10, low: 7 }
const TYPE_ICONS = {
  crime:'🚨', politics:'🏛', accident:'💥', infrastructure:'🏗',
  cultural:'🎭', weather:'🌧', business:'💼', health:'🏥', other:'📌',
}

// ── Heatmap layer using canvas ────────────────────────────────────────────────
function HeatmapLayer({ points }) {
  const map = useMap()
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!points?.length) return

    // Remove existing canvas
    if (canvasRef.current) {
      canvasRef.current.remove()
      canvasRef.current = null
    }

    const canvas = document.createElement('canvas')
    canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:400;opacity:0.65;'
    const container = map.getContainer()
    container.appendChild(canvas)
    canvasRef.current = canvas

    const draw = () => {
      const size = container.getBoundingClientRect()
      canvas.width  = size.width
      canvas.height = size.height
      const ctx = canvas.getContext('2d')
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      points.forEach(pt => {
        const latlng = window.L?.latLng(pt.lat, pt.lng) || { lat: pt.lat, lng: pt.lng }
        try {
          const pos = map.latLngToContainerPoint([pt.lat, pt.lng])
          const radius = pt.weight ? 40 + pt.weight * 10 : 40
          const grad = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, radius)
          const col = pt.severity === 'high' ? '239,68,68'
                    : pt.severity === 'medium' ? '245,158,11'
                    : '34,197,94'
          grad.addColorStop(0,   `rgba(${col},0.8)`)
          grad.addColorStop(0.4, `rgba(${col},0.4)`)
          grad.addColorStop(1,   `rgba(${col},0)`)
          ctx.beginPath()
          ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2)
          ctx.fillStyle = grad
          ctx.fill()
        } catch {}
      })
    }

    draw()
    map.on('move zoom', draw)
    return () => {
      map.off('move zoom', draw)
      if (canvasRef.current) { canvasRef.current.remove(); canvasRef.current = null }
    }
  }, [map, points])

  return null
}

// ── Side panel ────────────────────────────────────────────────────────────────
function SidePanel({ event, onClose }) {
  const navigate = useNavigate()
  if (!event) return null
  const locs   = Array.isArray(event.locations)    ? event.locations    : []
  const people = Array.isArray(event.people)        ? event.people        : []
  const orgs   = Array.isArray(event.organizations) ? event.organizations : []

  const sCol = SEV_COLOR[event.severity] || SEV_COLOR.low

  return (
    <div style={{
      position:'absolute', top:16, right:16, width:340,
      background:'#1e293b', border:'1px solid #475569',
      borderRadius:16, zIndex:1000, padding:20,
      boxShadow:'0 25px 50px rgba(0,0,0,0.5)', maxHeight:'calc(100% - 100px)',
      overflowY:'auto',
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:12 }}>
        <div style={{ display:'flex', gap:8, alignItems:'center', flexWrap:'wrap' }}>
          <span style={{ fontSize:22 }}>{TYPE_ICONS[event.event_type] || '📌'}</span>
          <span style={{
            padding:'2px 8px', borderRadius:6, fontSize:11, fontWeight:700, textTransform:'uppercase',
            background:`${sCol}22`, color: sCol, border:`1px solid ${sCol}66`,
          }}>{event.severity}</span>
          <span style={{ color:'#94a3b8', fontSize:12, textTransform:'capitalize' }}>{event.event_type}</span>
        </div>
        <button onClick={onClose} style={{ color:'#64748b', background:'none', border:'none', cursor:'pointer', fontSize:22 }}>×</button>
      </div>

      <h3 style={{ color:'white', fontSize:14, fontWeight:600, marginBottom:8, lineHeight:1.4 }}>
        {event.article_title}
      </h3>
      <p style={{ color:'#cbd5e1', fontSize:12, lineHeight:1.6, marginBottom:12 }}>{event.summary}</p>

      {[...people.slice(0,3), ...orgs.slice(0,2), ...locs.slice(0,2)].length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginBottom:12 }}>
          {people.slice(0,3).map((p,i) => (
            <span key={i} style={{ padding:'2px 8px', borderRadius:20, fontSize:11, border:'1px solid #3b82f666', color:'#93c5fd', background:'#3b82f615' }}>👤 {p}</span>
          ))}
          {orgs.slice(0,2).map((o,i) => (
            <span key={i} style={{ padding:'2px 8px', borderRadius:20, fontSize:11, border:'1px solid #a855f766', color:'#d8b4fe', background:'#a855f715' }}>🏛 {o}</span>
          ))}
          {locs.slice(0,2).map((l,i) => (
            <span key={i} style={{ padding:'2px 8px', borderRadius:20, fontSize:11, border:'1px solid #f9731666', color:'#fdba74', background:'#f9731615' }}>📍 {l}</span>
          ))}
        </div>
      )}

      {event.source && (
        <div style={{ fontSize:11, color:'#64748b', marginBottom:12 }}>
          📰 {event.source} · {event.created_at ? new Date(event.created_at).toLocaleDateString('en-IN') : ''}
        </div>
      )}

      <div style={{ display:'flex', gap:8 }}>
        <button onClick={() => navigate(`/events/${event._id || event.id}`)}
          style={{ flex:1, padding:'8px 0', background:'#f97316', color:'white',
            border:'none', borderRadius:8, cursor:'pointer', fontSize:12, fontWeight:600 }}>
          Full Detail →
        </button>
        {event.article_url && (
          <a href={event.article_url} target="_blank" rel="noopener noreferrer"
            style={{ padding:'8px 12px', border:'1px solid #475569', borderRadius:8,
              color:'#94a3b8', fontSize:12, textDecoration:'none', display:'flex', alignItems:'center' }}>
            Source ↗
          </a>
        )}
      </div>
    </div>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────
function FilterBar({ severity, setSeverity, eventType, setEventType, heatmap, setHeatmap, eventCount }) {
  const sev   = ['all','high','medium','low']
  const types = ['all','crime','politics','accident','infrastructure','cultural','weather','business','health','other']

  const btn = (val, cur, set, small) => (
    <button key={val} onClick={() => set(val === 'all' ? '' : val)} style={{
      padding: small ? '3px 8px' : '4px 10px',
      borderRadius:8, fontSize:11, fontWeight:500, cursor:'pointer', border:'none',
      background: (val === 'all' ? !cur : cur === val) ? '#f97316' : '#334155',
      color:      (val === 'all' ? !cur : cur === val) ? 'white' : '#94a3b8',
      margin:2, textTransform:'capitalize',
    }}>{val}</button>
  )

  return (
    <div style={{
      position:'absolute', top:16, left:16, zIndex:1000,
      background:'rgba(15,23,42,0.94)', border:'1px solid #334155',
      borderRadius:14, padding:14, maxWidth:280,
    }}>
      <div style={{ fontSize:10, color:'#64748b', fontWeight:700, textTransform:'uppercase', marginBottom:6 }}>Severity</div>
      <div style={{ display:'flex', flexWrap:'wrap' }}>{sev.map(v => btn(v, severity, setSeverity, false))}</div>

      <div style={{ fontSize:10, color:'#64748b', fontWeight:700, textTransform:'uppercase', margin:'10px 0 6px' }}>Event Type</div>
      <div style={{ display:'flex', flexWrap:'wrap' }}>{types.map(v => btn(v, eventType, setEventType, true))}</div>

      <div style={{ borderTop:'1px solid #334155', marginTop:10, paddingTop:10 }}>
        <button onClick={() => setHeatmap(h => !h)} style={{
          width:'100%', padding:'6px 0', borderRadius:8, fontSize:12, fontWeight:600, cursor:'pointer', border:'none',
          background: heatmap ? '#7c3aed' : '#1e40af',
          color:'white', display:'flex', alignItems:'center', justifyContent:'center', gap:6,
        }}>
          {heatmap ? '🔵 Heatmap ON' : '⚪ Show Heatmap'}
        </button>
        <div style={{ fontSize:10, color:'#475569', textAlign:'center', marginTop:6 }}>
          {eventCount} events
        </div>
      </div>
    </div>
  )
}

export default function MapDashboard() {
  const [events, setEvents]       = useState([])
  const [heatPoints, setHeatPoints] = useState([])
  const [selected, setSelected]   = useState(null)
  const [severity, setSeverity]   = useState('')
  const [eventType, setEventType] = useState('')
  const [heatmap, setHeatmap]     = useState(false)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')

  // Load event markers
  const loadEvents = useCallback((signal) => {
    setLoading(true)
    setError('')
    const params = {}
    if (severity)  params.severity   = severity
    if (eventType) params.event_type = eventType
    getEvents(params, { signal })
      .then(r => setEvents(r.data))
      .catch(e => { if (!isCanceled(e)) setError('Could not load events.') })
      .finally(() => { if (!signal.aborted) setLoading(false) })
  }, [severity, eventType])

  // Load heatmap points
  const loadHeatmap = useCallback((signal) => {
    if (!heatmap) return
    getHeatmap({ severity, event_type: eventType, days: 30 }, { signal })
      .then(r => setHeatPoints(r.data?.points || []))
      .catch(() => setHeatPoints([]))
  }, [heatmap, severity, eventType])

  useEffect(() => {
    const c = new AbortController()
    loadEvents(c.signal)
    loadHeatmap(c.signal)
    return () => c.abort()
  }, [loadEvents, loadHeatmap])

  return (
    <div style={{ position:'relative', height:'calc(100vh - 64px)' }}>
      <FilterBar
        severity={severity} setSeverity={setSeverity}
        eventType={eventType} setEventType={setEventType}
        heatmap={heatmap} setHeatmap={setHeatmap}
        eventCount={events.length}
      />

      {error && (
        <div style={{
          position:'absolute', top:'50%', left:'50%', transform:'translate(-50%,-50%)',
          background:'#1e293b', border:'1px solid #ef4444', borderRadius:12,
          padding:'16px 24px', color:'#f87171', zIndex:1000, textAlign:'center', fontSize:14,
        }}>⚠ {error}</div>
      )}

      {loading && !error && (
        <div style={{
          position:'absolute', top:16, left:'50%', transform:'translateX(-50%)',
          background:'#1e293b', border:'1px solid #334155', borderRadius:10,
          padding:'8px 16px', color:'#94a3b8', zIndex:1000, fontSize:13,
        }}>Loading events…</div>
      )}

      <MapContainer center={[26.9124, 75.7873]} zoom={12}
        style={{ width:'100%', height:'100%' }} zoomControl={true}>
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='© <a href="https://openstreetmap.org">OSM</a> © <a href="https://carto.com">CARTO</a>'
        />

        {/* Heatmap layer */}
        {heatmap && heatPoints.length > 0 && <HeatmapLayer points={heatPoints} />}

        {/* Point markers (always shown) */}
        {events.map(ev => (
          <CircleMarker
            key={ev._id || ev.id}
            center={[ev.lat || 26.9124, ev.lng || 75.7873]}
            radius={SEV_RADIUS[ev.severity] || 7}
            pathOptions={{
              color: SEV_COLOR[ev.severity] || '#22c55e',
              fillColor: SEV_COLOR[ev.severity] || '#22c55e',
              fillOpacity: heatmap ? 0.4 : 0.75,
              weight: 2,
            }}
            eventHandlers={{ click: () => setSelected(ev) }}
          >
            <Popup>
              <div style={{ fontSize:12, fontWeight:600, maxWidth:200 }}>{ev.article_title}</div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      <SidePanel event={selected} onClose={() => setSelected(null)} />

      {/* Legend */}
      <div style={{
        position:'absolute', bottom:24, right:16, zIndex:1000,
        background:'rgba(15,23,42,0.92)', border:'1px solid #334155',
        borderRadius:12, padding:'10px 14px',
      }}>
        {Object.entries(SEV_COLOR).map(([sev, col]) => (
          <div key={sev} style={{ display:'flex', alignItems:'center', gap:8, fontSize:12, color:'#cbd5e1', marginBottom:4 }}>
            <span style={{ width:12, height:12, borderRadius:'50%', background:col, display:'block' }} />
            <span style={{ textTransform:'capitalize' }}>{sev}</span>
          </div>
        ))}
        {heatmap && (
          <div style={{ fontSize:11, color:'#7c3aed', marginTop:6, fontWeight:600 }}>🔵 Heatmap active</div>
        )}
      </div>
    </div>
  )
}
