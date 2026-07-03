import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getEntities, getEntity, getEntityNetwork, isCanceled } from '../api'

const TYPE_STYLE = {
  person:       { pill: 'border-blue-500/40 text-blue-300 bg-blue-500/10',   marker: 'bg-blue-500/20 text-blue-300',   label: 'P',   icon: '👤' },
  organization: { pill: 'border-purple-500/40 text-purple-300 bg-purple-500/10', marker: 'bg-purple-500/20 text-purple-300', label: 'O', icon: '🏛' },
  location:     { pill: 'border-orange-500/40 text-orange-300 bg-orange-500/10', marker: 'bg-orange-500/20 text-orange-300', label: 'L', icon: '📍' },
}
const SEV_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' }
const SEV_CLS   = { high: 'text-red-400', medium: 'text-amber-400', low: 'text-green-400' }
const SEV_BG    = { high: 'bg-red-500/20 text-red-400 border-red-500/40', medium: 'bg-amber-500/20 text-amber-400 border-amber-500/40', low: 'bg-green-500/20 text-green-400 border-green-500/40' }

// ── Entity List ───────────────────────────────────────────────────────────────
function EntityCard({ entity }) {
  const style = TYPE_STYLE[entity.type] || TYPE_STYLE.person
  const status = (() => {
    if (!entity.last_seen_at) return 'unknown'
    const days = (Date.now() - new Date(entity.last_seen_at)) / 86400000
    return days < 7 ? 'active' : days < 30 ? 'recent' : 'dormant'
  })()

  return (
    <Link to={`/entities/${entity._id || entity.id}`}
      className="block rounded-xl border border-slate-700 bg-slate-800 p-4 transition-all hover:border-slate-500 hover:bg-slate-750 group">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`inline-flex h-10 w-10 items-center justify-center rounded-lg text-lg ${style.marker}`}>
            {style.icon}
          </span>
          <div>
            <div className="font-semibold text-white group-hover:text-orange-300 transition-colors">{entity.name}</div>
            <div className="flex items-center gap-2 mt-1">
              <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${style.pill}`}>{entity.type}</span>
              <span className={`text-xs font-medium ${status === 'active' ? 'text-green-400' : status === 'recent' ? 'text-amber-400' : 'text-slate-500'}`}>
                ● {status}
              </span>
            </div>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-xl font-bold text-orange-400">{entity.mention_count}</div>
          <div className="text-xs text-slate-500">mentions</div>
        </div>
      </div>
    </Link>
  )
}

function EntityList() {
  const [entities, setEntities] = useState([])
  const [filter, setFilter]     = useState('')
  const [search, setSearch]     = useState('')
  const [loading, setLoading]   = useState(true)

  const load = useCallback((signal) => {
    setLoading(true)
    const params = { limit: 200 }
    if (filter) params.type = filter
    return getEntities(params, { signal })
      .then(r => setEntities(r.data))
      .catch(err => { if (!isCanceled(err)) setEntities([]) })
      .finally(() => { if (!signal.aborted) setLoading(false) })
  }, [filter])

  useEffect(() => {
    const c = new AbortController()
    load(c.signal)
    return () => c.abort()
  }, [load])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return entities.filter(e => !q || e.name.toLowerCase().includes(q))
  }, [entities, search])

  const counts = useMemo(
    () => entities.reduce((acc, e) => ({ ...acc, [e.type]: (acc[e.type] || 0) + 1 }), {}),
    [entities]
  )

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Entity Explorer</h1>
        <p className="mt-1 text-sm text-slate-400">People, organizations and locations extracted from Jaipur news.</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <input type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search entities…"
          className="w-64 rounded-lg border border-slate-600 bg-slate-800 px-4 py-2 text-sm text-white
                     placeholder-slate-500 focus:border-orange-500 focus:outline-none" />
        {['', 'person', 'organization', 'location'].map(type => (
          <button key={type || 'all'} onClick={() => setFilter(type)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              filter === type
                ? 'bg-orange-500 text-white'
                : 'border border-slate-700 bg-slate-800 text-slate-300 hover:border-slate-500'
            }`}>
            {type ? `${TYPE_STYLE[type]?.icon} ${type} (${counts[type] || 0})` : `All (${entities.length})`}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="py-20 text-center text-slate-400">Loading entities…</div>
      ) : filtered.length === 0 ? (
        <div className="py-20 text-center text-slate-500">No entities found.</div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map(e => <EntityCard key={e._id || e.id} entity={e} />)}
        </div>
      )}
    </div>
  )
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = ['Overview', 'Timeline', 'Network']

function TabBar({ active, onChange }) {
  return (
    <div className="flex border-b border-slate-700">
      {TABS.map(tab => (
        <button key={tab} onClick={() => onChange(tab)}
          className={`px-5 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
            active === tab
              ? 'border-orange-500 text-orange-400'
              : 'border-transparent text-slate-400 hover:text-white'
          }`}>
          {tab}
        </button>
      ))}
    </div>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
function OverviewTab({ data }) {
  const style = TYPE_STYLE[data.type] || TYPE_STYLE.person
  const status = (() => {
    if (!data.last_seen_at) return 'unknown'
    const days = (Date.now() - new Date(data.last_seen_at)) / 86400000
    return days < 7 ? 'active' : days < 30 ? 'recent' : 'dormant'
  })()

  return (
    <div className="space-y-5 pt-4">
      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Mentions',    value: data.mention_count, color: 'text-orange-400' },
          { label: 'Events',      value: data.timeline?.length || 0, color: 'text-blue-400' },
          { label: 'Related',     value: data.related_entities?.length || 0, color: 'text-purple-400' },
          { label: 'Status',      value: status, color: status === 'active' ? 'text-green-400' : 'text-slate-400' },
        ].map(s => (
          <div key={s.label} className="bg-slate-700/50 rounded-xl p-4 text-center">
            <div className={`text-xl font-bold capitalize ${s.color}`}>{s.value}</div>
            <div className="text-xs text-slate-500 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Dates */}
      <div className="grid grid-cols-2 gap-3">
        {data.first_seen_at && (
          <div className="bg-slate-700/50 rounded-xl p-4">
            <div className="text-xs text-slate-500 uppercase mb-1 font-semibold">First seen</div>
            <div className="text-sm text-white">{new Date(data.first_seen_at).toLocaleDateString('en-IN', { day:'numeric', month:'short', year:'numeric' })}</div>
          </div>
        )}
        {data.last_seen_at && (
          <div className="bg-slate-700/50 rounded-xl p-4">
            <div className="text-xs text-slate-500 uppercase mb-1 font-semibold">Last seen</div>
            <div className="text-sm text-white">{new Date(data.last_seen_at).toLocaleDateString('en-IN', { day:'numeric', month:'short', year:'numeric' })}</div>
          </div>
        )}
      </div>

      {/* Related entities */}
      {data.related_entities?.length > 0 && (
        <div className="bg-slate-700/50 rounded-xl p-5">
          <h3 className="text-xs font-bold uppercase text-slate-400 mb-3 tracking-wider">Co-occurring Entities</h3>
          <div className="flex flex-wrap gap-2">
            {data.related_entities.map(en => {
              const s = TYPE_STYLE[en.type] || TYPE_STYLE.person
              return (
                <Link key={en._id || en.id} to={`/entities/${en._id || en.id}`}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm hover:opacity-80 transition-opacity ${s.pill}`}>
                  <span>{s.icon}</span>
                  <span>{en.name}</span>
                  <span className="text-xs opacity-50">{en.mention_count}</span>
                </Link>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────
function TimelineTab({ events }) {
  return (
    <div className="pt-4">
      {!events?.length ? (
        <p className="text-slate-500 text-sm py-8 text-center">No events found for this entity.</p>
      ) : (
        <div className="relative">
          <div className="absolute bottom-0 left-4 top-0 w-px bg-slate-700" />
          <div className="space-y-4 pl-10">
            {events.map(ev => (
              <div key={ev._id || ev.id} className="relative">
                <div className="absolute -left-6 top-1.5 h-3 w-3 rounded-full border-2 border-slate-600"
                     style={{ background: SEV_COLOR[ev.severity] || SEV_COLOR.low }} />
                <Link to={`/events/${ev._id || ev.id}`}
                  className="block rounded-xl bg-slate-700/50 border border-slate-700 p-4
                             hover:bg-slate-700 hover:border-slate-600 transition-colors group">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-0.5 rounded border text-xs font-bold uppercase ${SEV_BG[ev.severity] || SEV_BG.low}`}>
                      {ev.severity}
                    </span>
                    <span className="text-xs capitalize text-slate-400">{ev.event_type}</span>
                    <span className="ml-auto text-xs text-slate-500">
                      {ev.created_at ? new Date(ev.created_at).toLocaleDateString('en-IN') : ''}
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-white group-hover:text-orange-300 transition-colors">
                    {ev.article_title}
                  </p>
                  {ev.summary && (
                    <p className="mt-1 text-xs text-slate-400 line-clamp-2">{ev.summary}</p>
                  )}
                  {ev.role && (
                    <span className="mt-2 inline-block px-2 py-0.5 bg-slate-600 text-slate-300 text-xs rounded-full capitalize">
                      Role: {ev.role}
                    </span>
                  )}
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Network Tab ───────────────────────────────────────────────────────────────
function NetworkTab({ entityId }) {
  const [network, setNetwork] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const c = new AbortController()
    getEntityNetwork(entityId, { depth: 1 }, { signal: c.signal })
      .then(r => setNetwork(r.data))
      .catch(err => { if (!isCanceled(err)) setNetwork(null) })
      .finally(() => setLoading(false))
    return () => c.abort()
  }, [entityId])

  if (loading) return <div className="py-12 text-center text-slate-400">Loading network…</div>
  if (!network) return <div className="py-12 text-center text-slate-500">Network data unavailable.</div>

  const { nodes = [], edges = [] } = network

  return (
    <div className="pt-4 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-slate-700/50 rounded-xl p-4 text-center">
          <div className="text-2xl font-bold text-orange-400">{nodes.length}</div>
          <div className="text-xs text-slate-500 mt-1">Connected nodes</div>
        </div>
        <div className="bg-slate-700/50 rounded-xl p-4 text-center">
          <div className="text-2xl font-bold text-blue-400">{edges.length}</div>
          <div className="text-xs text-slate-500 mt-1">Relationships</div>
        </div>
      </div>
      <div className="bg-slate-700/50 rounded-xl p-5">
        <h3 className="text-xs font-bold uppercase text-slate-400 mb-3 tracking-wider">Connected Entities</h3>
        <div className="space-y-2">
          {nodes.filter(n => n.id !== entityId).slice(0, 20).map(n => {
            const s = TYPE_STYLE[n.type] || TYPE_STYLE.person
            const edgeCount = edges.filter(e => e.source === n.id || e.target === n.id).length
            return (
              <Link key={n.id} to={`/entities/${n.id}`}
                className="flex items-center justify-between rounded-lg bg-slate-700 border border-slate-600
                           px-4 py-3 hover:border-slate-500 transition-colors">
                <div className="flex items-center gap-3">
                  <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg text-sm ${s.marker}`}>
                    {s.icon}
                  </span>
                  <div>
                    <div className="text-sm font-medium text-white">{n.label || n.name}</div>
                    <div className="text-xs text-slate-500 capitalize">{n.type}</div>
                  </div>
                </div>
                <span className="text-xs text-slate-400">{edgeCount} shared events</span>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Entity Detail ─────────────────────────────────────────────────────────────
function EntityDetail({ id }) {
  const navigate = useNavigate()
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab]       = useState('Overview')

  useEffect(() => {
    const c = new AbortController()
    setLoading(true)
    getEntity(id, { signal: c.signal })
      .then(r => setData(r.data))
      .catch(err => { if (!isCanceled(err)) setData(null) })
      .finally(() => { if (!c.signal.aborted) setLoading(false) })
    return () => c.abort()
  }, [id])

  if (loading) return <div className="flex h-96 items-center justify-center text-slate-400">Loading…</div>
  if (!data)   return <div className="flex h-96 items-center justify-center text-slate-400">Entity not found.</div>

  const style = TYPE_STYLE[data.type] || TYPE_STYLE.person
  const status = (() => {
    if (!data.last_seen_at) return 'unknown'
    const days = (Date.now() - new Date(data.last_seen_at)) / 86400000
    return days < 7 ? 'active' : days < 30 ? 'recent' : 'dormant'
  })()

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-5">
      <button onClick={() => navigate(-1)} className="text-sm text-slate-400 hover:text-white flex items-center gap-1">
        ← Back
      </button>

      {/* Entity header */}
      <div className="rounded-xl border border-slate-700 bg-slate-800 p-6">
        <div className="flex items-start gap-4">
          <span className={`inline-flex h-14 w-14 items-center justify-center rounded-xl text-2xl ${style.marker} shrink-0`}>
            {style.icon}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl font-bold text-white">{data.name}</h1>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                status === 'active' ? 'bg-green-500/20 text-green-400' :
                status === 'recent' ? 'bg-amber-500/20 text-amber-400' :
                'bg-slate-600/40 text-slate-400'
              }`}>
                ● {status}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-400">
              <span className={`px-2 py-0.5 rounded border text-xs capitalize ${style.pill}`}>{data.type}</span>
              <span className="font-semibold text-orange-400">{data.mention_count} mentions</span>
            </div>
          </div>
        </div>

        {/* Tab navigation */}
        <div className="mt-5 border-t border-slate-700 -mx-6 px-6">
          <TabBar active={tab} onChange={setTab} />
        </div>
      </div>

      {/* Tab content */}
      {tab === 'Overview'  && <OverviewTab data={data} />}
      {tab === 'Timeline'  && <TimelineTab events={data.timeline} />}
      {tab === 'Network'   && <NetworkTab entityId={id} />}
    </div>
  )
}

export default function EntityView() {
  const { id } = useParams()
  return id ? <EntityDetail id={id} /> : <EntityList />
}
