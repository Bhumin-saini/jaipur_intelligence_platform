import React, { useState, useEffect, useCallback } from 'react'
import {
  getWatchlist, createWatchlist, updateWatchlistItem, deleteWatchlistItem,
  getAlerts, getUnreadCount, markAlertRead, markAllAlertsRead,
  triggerAlertCheck, isCanceled,
} from '../api'

const SEV_COLORS = {
  high:   'text-red-400 bg-red-500/10 border-red-500/30',
  medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  low:    'text-green-400 bg-green-500/10 border-green-500/30',
}

function Spinner() {
  return <div className="h-5 w-5 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

function Badge({ label, className }) {
  return <span className={`px-2 py-0.5 rounded text-xs font-medium border ${className}`}>{label}</span>
}

// ── Create Watchlist Modal ────────────────────────────────────────────────────
function CreateWatchlistModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '', description: '', watch_type: 'keyword',
    keywords: '', locations: '', event_types: '', min_severity: 'medium',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!form.name.trim()) { setErr('Name is required'); return }
    setSaving(true)
    try {
      const toList = s => s.split(',').map(x => x.trim()).filter(Boolean)
      await createWatchlist({
        ...form,
        keywords:    toList(form.keywords),
        locations:   toList(form.locations),
        event_types: toList(form.event_types),
      })
      onCreated()
    } catch { setErr('Failed to create watchlist item') }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg p-6 shadow-xl">
        <h2 className="text-lg font-bold text-white mb-4">New Watchlist Item</h2>
        {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
        <div className="space-y-3">
          <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            placeholder="Watch name *" className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
          <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Description" rows={2}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 resize-none" />
          <div className="grid grid-cols-2 gap-3">
            <select value={form.watch_type} onChange={e => setForm(f => ({ ...f, watch_type: e.target.value }))}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
              {['keyword','entity','location','topic','composite'].map(t => <option key={t}>{t}</option>)}
            </select>
            <select value={form.min_severity} onChange={e => setForm(f => ({ ...f, min_severity: e.target.value }))}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
              {['low','medium','high'].map(s => <option key={s}>{s}</option>)}
            </select>
          </div>
          <input value={form.keywords} onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))}
            placeholder="Keywords (comma-separated): metro, JDA, flood…"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
          <input value={form.locations} onChange={e => setForm(f => ({ ...f, locations: e.target.value }))}
            placeholder="Locations (comma-separated): Mansarovar, Vaishali Nagar…"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
          <input value={form.event_types} onChange={e => setForm(f => ({ ...f, event_types: e.target.value }))}
            placeholder="Event types (comma-separated): crime, infrastructure…"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="px-4 py-2 text-sm bg-orange-500 hover:bg-orange-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Watchlist Item Card ───────────────────────────────────────────────────────
function WatchlistCard({ item, onToggle, onDelete }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-white">{item.name}</h3>
            <Badge label={item.watch_type} className="text-slate-400 bg-slate-700/50 border-slate-700" />
            <Badge label={`min: ${item.min_severity}`} className={SEV_COLORS[item.min_severity] || ''} />
          </div>
          {item.description && <p className="text-slate-500 text-xs mt-1">{item.description}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className={`w-2 h-2 rounded-full ${item.active ? 'bg-green-400' : 'bg-slate-600'}`} />
          <button onClick={() => onToggle(item)} className="text-xs text-slate-500 hover:text-white">
            {item.active ? 'Pause' : 'Activate'}
          </button>
          <button onClick={() => onDelete(item._id)} className="text-xs text-slate-600 hover:text-red-400">✕</button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs text-slate-500">
        {item.keywords?.length > 0 && (
          <div>
            <div className="text-slate-600 mb-1">Keywords</div>
            <div className="flex flex-wrap gap-1">
              {item.keywords.slice(0, 4).map(k => (
                <span key={k} className="bg-slate-800 rounded px-1.5 py-0.5 text-slate-400">{k}</span>
              ))}
            </div>
          </div>
        )}
        {item.locations?.length > 0 && (
          <div>
            <div className="text-slate-600 mb-1">Locations</div>
            <div className="flex flex-wrap gap-1">
              {item.locations.slice(0, 3).map(l => (
                <span key={l} className="bg-slate-800 rounded px-1.5 py-0.5 text-orange-400/80">{l}</span>
              ))}
            </div>
          </div>
        )}
        {item.event_types?.length > 0 && (
          <div>
            <div className="text-slate-600 mb-1">Types</div>
            <div className="flex flex-wrap gap-1">
              {item.event_types.slice(0, 3).map(t => (
                <span key={t} className="bg-slate-800 rounded px-1.5 py-0.5 text-blue-400/80">{t}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs text-slate-600">
        <span>🔔 {item.alert_count || 0} alerts</span>
        {item.last_alert && <span>Last alert: {item.last_alert.slice(0, 10)}</span>}
        {item.last_checked && <span>Checked: {item.last_checked.slice(0, 16).replace('T', ' ')}</span>}
      </div>
    </div>
  )
}

// ── Alert Card ────────────────────────────────────────────────────────────────
function AlertCard({ alert, onRead }) {
  return (
    <div className={`bg-slate-900 border rounded-xl p-4 transition-all ${
      alert.read ? 'border-slate-800 opacity-60' : 'border-orange-500/30 bg-orange-500/5'
    }`}>
      <div className="flex items-start gap-3">
        <div className={`w-2 h-2 mt-1.5 rounded-full shrink-0 ${alert.read ? 'bg-slate-700' : 'bg-orange-400'}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-orange-300">{alert.watchlist_name}</span>
            <Badge label={alert.severity} className={SEV_COLORS[alert.severity] || ''} />
            <span className="text-xs text-slate-500">{(alert.created_at || '').slice(0, 16).replace('T', ' ')}</span>
          </div>
          <p className="text-slate-300 text-sm">{alert.event_summary}</p>
          <p className="text-slate-500 text-xs mt-1">Reason: {alert.reason}</p>
        </div>
        {!alert.read && (
          <button onClick={() => onRead(alert._id)} className="text-xs text-slate-500 hover:text-white shrink-0">Mark read</button>
        )}
      </div>
    </div>
  )
}

// ── Main WatchlistPage ────────────────────────────────────────────────────────
export default function WatchlistPage() {
  const [tab, setTab] = useState('watchlist')
  const [items, setItems] = useState([])
  const [alerts, setAlerts] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [checking, setChecking] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(false)

  const loadWatchlist = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getWatchlist({ active_only: false })
      setItems(r.data?.items || [])
    } catch {}
    setLoading(false)
  }, [])

  const loadAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const params = unreadOnly ? { unread_only: true } : {}
      const [ar, cr] = await Promise.all([getAlerts(params), getUnreadCount()])
      setAlerts(ar.data?.alerts || [])
      setUnreadCount(cr.data?.count || 0)
    } catch {}
    setLoading(false)
  }, [unreadOnly])

  useEffect(() => {
    if (tab === 'watchlist') loadWatchlist()
    else loadAlerts()
  }, [tab, loadWatchlist, loadAlerts])

  const handleToggle = async (item) => {
    try {
      await updateWatchlistItem(item._id, { active: !item.active })
      loadWatchlist()
    } catch {}
  }

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this watchlist item?')) return
    try { await deleteWatchlistItem(id); loadWatchlist() } catch {}
  }

  const handleCheck = async () => {
    setChecking(true)
    try { await triggerAlertCheck() } catch {}
    setTimeout(() => { setChecking(false); if (tab === 'alerts') loadAlerts() }, 1500)
  }

  const handleRead = async (id) => {
    try { await markAlertRead(id); loadAlerts() } catch {}
  }

  const handleReadAll = async () => {
    try { await markAllAlertsRead(); loadAlerts() } catch {}
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {showCreate && (
        <CreateWatchlistModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); loadWatchlist() }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Watchlist & Alerts</h1>
          <p className="text-slate-400 text-sm">Continuous monitoring for topics, entities, and locations</p>
        </div>
        <div className="flex gap-2">
          <button onClick={handleCheck} disabled={checking}
            className="px-3 py-2 text-sm bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 disabled:opacity-50">
            {checking ? '⟳ Checking…' : '⟳ Check Now'}
          </button>
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold rounded-lg">
            + New Monitor
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800">
        {[['watchlist','Monitors'],['alerts','Alerts']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors flex items-center gap-2 ${
              tab === k ? 'text-orange-400 border-orange-500' : 'text-slate-400 border-transparent hover:text-white'
            }`}>
            {l}
            {k === 'alerts' && unreadCount > 0 && (
              <span className="bg-orange-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[1.25rem] text-center">
                {unreadCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : tab === 'watchlist' ? (
        items.length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <div className="text-4xl mb-3">👁</div>
            <p>No monitors configured.</p>
            <button onClick={() => setShowCreate(true)} className="mt-3 text-orange-400 text-sm hover:underline">
              Add your first monitor →
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map(item => (
              <WatchlistCard key={item._id} item={item} onToggle={handleToggle} onDelete={handleDelete} />
            ))}
          </div>
        )
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <button onClick={() => setUnreadOnly(!unreadOnly)}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                unreadOnly ? 'bg-orange-500/20 text-orange-400 border-orange-500/30' : 'bg-slate-800 text-slate-400 border-slate-700'
              }`}>
              {unreadOnly ? 'Unread only' : 'All alerts'}
            </button>
            {unreadCount > 0 && (
              <button onClick={handleReadAll} className="text-sm text-slate-400 hover:text-white">
                Mark all read
              </button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <div className="text-4xl mb-3">🔔</div>
              <p>No alerts yet.</p>
            </div>
          ) : alerts.map(alert => (
            <AlertCard key={alert._id} alert={alert} onRead={handleRead} />
          ))}
        </div>
      )}
    </div>
  )
}
