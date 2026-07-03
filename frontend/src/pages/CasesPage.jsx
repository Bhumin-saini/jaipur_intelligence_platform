import React, { useState, useEffect, useCallback } from 'react'
import {
  getCases, createCase, updateCase, deleteCase, closeCase,
  getCaseEvents, getCaseAnnotations, addAnnotation, deleteAnnotation,
  getCaseRisk, addCaseEvent, removeCaseEvent, isCanceled,
} from '../api'

const PRIORITY_COLORS = {
  critical: 'text-red-400 bg-red-500/10 border-red-500/30',
  high:     'text-orange-400 bg-orange-500/10 border-orange-500/30',
  medium:   'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  low:      'text-green-400 bg-green-500/10 border-green-500/30',
}
const STATUS_COLORS = {
  open:   'text-blue-400 bg-blue-500/10',
  closed: 'text-slate-400 bg-slate-500/10',
}
const RISK_COLORS = {
  critical: 'text-red-400',
  high:     'text-orange-400',
  medium:   'text-yellow-400',
  low:      'text-green-400',
  unknown:  'text-slate-400',
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function Badge({ label, className }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${className}`}>
      {label}
    </span>
  )
}

function Spinner() {
  return <div className="h-5 w-5 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

// ── Create Case Modal ─────────────────────────────────────────────────────────
function CreateCaseModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    title: '', description: '', category: 'general', priority: 'medium', tags: '',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!form.title.trim()) { setErr('Title is required'); return }
    setSaving(true)
    try {
      const tags = form.tags.split(',').map(t => t.trim()).filter(Boolean)
      await createCase({ ...form, tags })
      onCreated()
    } catch {
      setErr('Failed to create case')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg p-6 shadow-xl">
        <h2 className="text-lg font-bold text-white mb-4">New Case</h2>
        {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
        <div className="space-y-3">
          <input value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
            placeholder="Case title *" className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
          <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Description" rows={2}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 resize-none" />
          <div className="grid grid-cols-2 gap-3">
            <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500">
              {['general','crime','infrastructure','political','health'].map(c => <option key={c}>{c}</option>)}
            </select>
            <select value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-orange-500">
              {['low','medium','high','critical'].map(p => <option key={p}>{p}</option>)}
            </select>
          </div>
          <input value={form.tags} onChange={e => setForm(f => ({ ...f, tags: e.target.value }))}
            placeholder="Tags (comma-separated)" className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="px-4 py-2 text-sm bg-orange-500 hover:bg-orange-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Creating…' : 'Create Case'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Case Detail Panel ─────────────────────────────────────────────────────────
function CaseDetailPanel({ caseDoc, onBack, onUpdated }) {
  const [tab, setTab] = useState('events')
  const [events, setEvents] = useState([])
  const [annotations, setAnnotations] = useState([])
  const [risk, setRisk] = useState(null)
  const [noteText, setNoteText] = useState('')
  const [noteType, setNoteType] = useState('note')
  const [loading, setLoading] = useState(false)

  const loadTab = useCallback(async () => {
    setLoading(true)
    try {
      if (tab === 'events') {
        const r = await getCaseEvents(caseDoc._id)
        setEvents(r.data?.events || [])
      } else if (tab === 'annotations') {
        const r = await getCaseAnnotations(caseDoc._id)
        setAnnotations(r.data?.annotations || [])
      } else if (tab === 'risk') {
        const r = await getCaseRisk(caseDoc._id)
        setRisk(r.data)
      }
    } catch {}
    setLoading(false)
  }, [tab, caseDoc._id])

  useEffect(() => { loadTab() }, [loadTab])

  const submitNote = async () => {
    if (!noteText.trim()) return
    try {
      await addAnnotation(caseDoc._id, { text: noteText, annotation_type: noteType })
      setNoteText('')
      loadTab()
    } catch {}
  }

  const removeEvent = async (eventId) => {
    try { await removeCaseEvent(caseDoc._id, eventId); loadTab() } catch {}
  }

  const removeNote = async (annId) => {
    try {
      const { deleteAnnotation: del } = await import('../api')
      await del(annId); loadTab()
    } catch {}
  }

  const handleClose = async () => {
    if (!window.confirm('Close this case?')) return
    try { await closeCase(caseDoc._id, {}); onUpdated() } catch {}
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-white text-sm">← Back</button>
        <div className="flex-1">
          <h2 className="text-lg font-bold text-white">{caseDoc.title}</h2>
          <p className="text-slate-400 text-sm">{caseDoc.description}</p>
        </div>
        <Badge label={caseDoc.priority} className={PRIORITY_COLORS[caseDoc.priority] || ''} />
        <Badge label={caseDoc.status} className={STATUS_COLORS[caseDoc.status] || ''} />
        {caseDoc.status === 'open' && (
          <button onClick={handleClose} className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg">
            Close Case
          </button>
        )}
      </div>

      {/* Tags */}
      {caseDoc.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {caseDoc.tags.map(tag => (
            <span key={tag} className="px-2 py-0.5 bg-slate-800 text-slate-400 rounded text-xs">{tag}</span>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800 pb-0">
        {[['events','Events'],['annotations','Notes'],['risk','Risk']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === k ? 'text-orange-400 border-orange-500' : 'text-slate-400 border-transparent hover:text-white'
            }`}>
            {l} {k === 'events' ? `(${caseDoc.event_count || 0})` : ''}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-8"><Spinner /></div>
      ) : tab === 'events' ? (
        <div className="space-y-2">
          {events.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">No events added yet.</p>
          ) : events.map(ev => (
            <div key={ev._id} className="flex items-start gap-3 bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-bold uppercase ${ev.severity === 'high' ? 'text-red-400' : ev.severity === 'medium' ? 'text-yellow-400' : 'text-green-400'}`}>
                    {ev.severity}
                  </span>
                  <span className="text-slate-500 text-xs">{ev.event_type}</span>
                  <span className="text-slate-600 text-xs">{(ev.created_at || '').slice(0, 10)}</span>
                </div>
                <p className="text-slate-300 text-sm">{ev.summary}</p>
              </div>
              <button onClick={() => removeEvent(ev._id)} className="text-slate-600 hover:text-red-400 text-xs shrink-0">✕</button>
            </div>
          ))}
        </div>
      ) : tab === 'annotations' ? (
        <div className="space-y-3">
          <div className="flex gap-2">
            <select value={noteType} onChange={e => setNoteType(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
              {['note','hypothesis','finding','question','action'].map(t => <option key={t}>{t}</option>)}
            </select>
            <input value={noteText} onChange={e => setNoteText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submitNote()}
              placeholder="Add annotation…"
              className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
            <button onClick={submitNote} className="px-3 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm rounded-lg">Add</button>
          </div>
          {annotations.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-6">No annotations yet.</p>
          ) : annotations.map(ann => (
            <div key={ann._id} className="flex items-start gap-3 bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs text-orange-400 font-medium uppercase">{ann.annotation_type}</span>
                  <span className="text-slate-600 text-xs">{(ann.created_at || '').slice(0, 16).replace('T', ' ')}</span>
                </div>
                <p className="text-slate-300 text-sm">{ann.text}</p>
              </div>
              <button onClick={() => removeNote(ann._id)} className="text-slate-600 hover:text-red-400 text-xs shrink-0">✕</button>
            </div>
          ))}
        </div>
      ) : tab === 'risk' && risk ? (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-5 space-y-4">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-3xl font-black text-white">{(risk.risk_score * 100).toFixed(0)}</div>
              <div className="text-xs text-slate-500 uppercase tracking-widest">Risk Score</div>
            </div>
            <div>
              <div className={`text-xl font-bold uppercase ${RISK_COLORS[risk.risk_label]}`}>{risk.risk_label}</div>
              <div className="text-xs text-slate-500">Risk Level</div>
            </div>
          </div>
          {risk.breakdown && (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-3">
                {Object.entries(risk.breakdown.severity_distribution || {}).map(([sev, cnt]) => (
                  <div key={sev} className="bg-slate-900/60 rounded-lg p-3 text-center">
                    <div className="text-lg font-bold text-white">{cnt}</div>
                    <div className="text-xs text-slate-500 capitalize">{sev} severity</div>
                  </div>
                ))}
              </div>
              <div className="flex gap-4 text-sm text-slate-400">
                <span>{risk.breakdown.total_events} events</span>
                <span>{risk.breakdown.unique_entities} entities</span>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}

// ── Main CasesPage ────────────────────────────────────────────────────────────
export default function CasesPage() {
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [selected, setSelected] = useState(null)
  const [filterStatus, setFilterStatus] = useState('')

  const load = useCallback(async (signal) => {
    setLoading(true)
    try {
      const params = {}
      if (filterStatus) params.status = filterStatus
      const r = await getCases(params, { signal })
      setCases(r.data?.cases || [])
    } catch (e) { if (!isCanceled(e)) setCases([]) }
    setLoading(false)
  }, [filterStatus])

  useEffect(() => {
    const c = new AbortController()
    load(c.signal)
    return () => c.abort()
  }, [load])

  if (selected) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-6">
        <CaseDetailPanel
          caseDoc={selected}
          onBack={() => setSelected(null)}
          onUpdated={() => { setSelected(null); load() }}
        />
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {showCreate && (
        <CreateCaseModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load() }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Case Management</h1>
          <p className="text-slate-400 text-sm">Investigation files bundling events, entities, and analyst notes</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold rounded-lg">
          + New Case
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {[['', 'All'], ['open', 'Open'], ['closed', 'Closed']].map(([val, label]) => (
          <button key={val} onClick={() => setFilterStatus(val)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filterStatus === val ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' : 'bg-slate-800 text-slate-400 hover:text-white border border-transparent'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* Cases */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : cases.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <div className="text-4xl mb-3">📁</div>
          <p>No cases found.</p>
          <button onClick={() => setShowCreate(true)} className="mt-3 text-orange-400 text-sm hover:underline">Create your first case →</button>
        </div>
      ) : (
        <div className="space-y-2">
          {cases.map(c => (
            <div key={c._id} onClick={() => setSelected(c)}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-xl p-4 cursor-pointer transition-all hover:bg-slate-800/50 group">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-semibold text-white group-hover:text-orange-300 truncate">{c.title}</h3>
                    <Badge label={c.priority} className={PRIORITY_COLORS[c.priority] || ''} />
                    <Badge label={c.status} className={STATUS_COLORS[c.status] || ''} />
                  </div>
                  {c.description && <p className="text-slate-400 text-xs truncate">{c.description}</p>}
                  <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                    <span>📋 {c.event_count || 0} events</span>
                    <span className="capitalize">🏷 {c.category}</span>
                    {c.risk_label && c.risk_label !== 'unknown' && (
                      <span className={RISK_COLORS[c.risk_label]}>⚠ {c.risk_label} risk</span>
                    )}
                    <span>{(c.updated_at || '').slice(0, 10)}</span>
                  </div>
                </div>
                {c.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1 shrink-0">
                    {c.tags.slice(0, 3).map(tag => (
                      <span key={tag} className="px-1.5 py-0.5 bg-slate-800 text-slate-500 rounded text-xs">{tag}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
