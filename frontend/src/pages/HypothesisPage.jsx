import React, { useState, useEffect, useCallback } from 'react'
import {
  getHypotheses, createHypothesis, deleteHypothesis,
  getEvidence, addEvidence, removeEvidence,
  evaluateHypothesis, searchEvidence, autoGatherEvidence,
  isCanceled,
} from '../api'

const STANCE_COLORS = {
  supporting:    'text-green-400 bg-green-500/10 border-green-500/30',
  contradicting: 'text-red-400 bg-red-500/10 border-red-500/30',
  neutral:       'text-slate-400 bg-slate-700/50 border-slate-700',
}
const VERDICT_COLORS = {
  confirmed:           'text-green-400',
  rejected:            'text-red-400',
  inconclusive:        'text-yellow-400',
  needs_more_evidence: 'text-blue-400',
  open:                'text-slate-400',
}

function Spinner() {
  return <div className="h-5 w-5 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

function ConfidenceBar({ value }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 40 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-800 rounded-full h-2">
        <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-sm font-bold text-white w-10 text-right">{pct}%</span>
    </div>
  )
}

// ── Create Hypothesis Modal ───────────────────────────────────────────────────
function CreateHypothesisModal({ onClose, onCreated }) {
  const [statement, setStatement] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!statement.trim()) { setErr('Statement is required'); return }
    setSaving(true)
    try {
      await createHypothesis({ statement, initial_confidence: 0.5 })
      onCreated()
    } catch { setErr('Failed to create hypothesis') }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg p-6 shadow-xl">
        <h2 className="text-lg font-bold text-white mb-2">New Hypothesis</h2>
        <p className="text-slate-500 text-sm mb-4">State the claim to be tested. Be specific.</p>
        {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
        <textarea value={statement} onChange={e => setStatement(e.target.value)}
          rows={3} placeholder="e.g. Illegal mining activity is causing road damage in Chaksu region…"
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 resize-none" />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={submit} disabled={saving}
            className="px-4 py-2 text-sm bg-orange-500 hover:bg-orange-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Creating…' : 'Create Hypothesis'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Hypothesis Detail View ────────────────────────────────────────────────────
function HypothesisDetail({ hyp, onBack, onUpdated }) {
  const [evidence, setEvidence] = useState([])
  const [candidates, setCandidates] = useState([])
  const [evaluation, setEvaluation] = useState(null)
  const [tab, setTab] = useState('evidence')
  const [addStance, setAddStance] = useState('supporting')
  const [addText, setAddText] = useState('')
  const [loading, setLoading] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [gathering, setGathering] = useState(false)
  const [searching, setSearching] = useState(false)

  const loadEvidence = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getEvidence(hyp._id)
      setEvidence(r.data?.evidence || [])
    } catch {}
    setLoading(false)
  }, [hyp._id])

  useEffect(() => { loadEvidence() }, [loadEvidence])

  const submitEvidence = async () => {
    if (!addText.trim()) return
    try {
      await addEvidence(hyp._id, { text: addText, stance: addStance, strength: 0.5 })
      setAddText('')
      loadEvidence()
    } catch {}
  }

  const removeEv = async (id) => {
    try { await removeEvidence(id); loadEvidence() } catch {}
  }

  const handleEvaluate = async () => {
    setEvaluating(true)
    try {
      const r = await evaluateHypothesis(hyp._id)
      setEvaluation(r.data)
    } catch {}
    setEvaluating(false)
  }

  const handleAutoGather = async () => {
    setGathering(true)
    try {
      await autoGatherEvidence(hyp._id, { limit: 10, lookback_days: 90 })
      loadEvidence()
    } catch {}
    setGathering(false)
  }

  const handleSearch = async () => {
    setSearching(true)
    try {
      const r = await searchEvidence(hyp._id, { limit: 10 })
      setCandidates(r.data?.candidates || [])
      setTab('search')
    } catch {}
    setSearching(false)
  }

  const addCandidate = async (c) => {
    try {
      await addEvidence(hyp._id, {
        event_id: c.event_id, text: c.summary,
        stance: c.suggested_stance, strength: c.similarity,
      })
      loadEvidence()
      setTab('evidence')
    } catch {}
  }

  const statusLabel = hyp.status || 'open'
  const confColor = VERDICT_COLORS[statusLabel] || 'text-slate-400'

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-white text-sm">← Back</button>
        <div className="flex-1" />
        <span className={`text-sm font-bold uppercase ${confColor}`}>{statusLabel}</span>
      </div>

      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
        <p className="text-white text-sm font-medium leading-relaxed">{hyp.statement}</p>
        <div className="mt-3 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Confidence</span>
            <span>{Math.round((hyp.confidence || 0) * 100)}%</span>
          </div>
          <ConfidenceBar value={hyp.confidence || 0} />
        </div>
        <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
          <span className="text-green-400">✓ {hyp.supporting_count || 0} supporting</span>
          <span className="text-red-400">✗ {hyp.contradicting_count || 0} contradicting</span>
          <span className="text-slate-400">~ {hyp.neutral_count || 0} neutral</span>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button onClick={handleEvaluate} disabled={evaluating}
          className="px-3 py-1.5 text-sm bg-orange-500 hover:bg-orange-600 text-white rounded-lg disabled:opacity-50">
          {evaluating ? 'Evaluating…' : '🧠 Evaluate with AI'}
        </button>
        <button onClick={handleAutoGather} disabled={gathering}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg disabled:opacity-50">
          {gathering ? 'Gathering…' : '⟳ Auto-gather Evidence'}
        </button>
        <button onClick={handleSearch} disabled={searching}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg disabled:opacity-50">
          {searching ? 'Searching…' : '🔍 Search Evidence'}
        </button>
      </div>

      {/* Evaluation result */}
      {evaluation && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-white">AI Evaluation</span>
            <span className={`text-sm font-bold uppercase ${VERDICT_COLORS[evaluation.verdict] || ''}`}>
              {evaluation.verdict}
            </span>
            <ConfidenceBar value={evaluation.confidence} />
          </div>
          <p className="text-slate-300 text-sm leading-relaxed">{evaluation.reasoning}</p>
          {evaluation.key_gaps && <p className="text-slate-400 text-xs">Gaps: {evaluation.key_gaps}</p>}
          {evaluation.recommended_actions?.length > 0 && (
            <div>
              <div className="text-xs text-slate-500 mb-1">Recommended Actions</div>
              <ul className="space-y-1">
                {evaluation.recommended_actions.map((a, i) => (
                  <li key={i} className="text-slate-400 text-xs">→ {a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800">
        {[['evidence','Evidence'],['search','Search Results']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === k ? 'text-orange-400 border-orange-500' : 'text-slate-400 border-transparent hover:text-white'
            }`}>{l}</button>
        ))}
      </div>

      {loading ? <div className="flex justify-center py-8"><Spinner /></div> :
      tab === 'evidence' ? (
        <div className="space-y-3">
          {/* Add evidence */}
          <div className="flex gap-2">
            <select value={addStance} onChange={e => setAddStance(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
              {['supporting','contradicting','neutral'].map(s => <option key={s}>{s}</option>)}
            </select>
            <input value={addText} onChange={e => setAddText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submitEvidence()}
              placeholder="Add evidence text…"
              className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500" />
            <button onClick={submitEvidence} className="px-3 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm rounded-lg">Add</button>
          </div>

          {evidence.length === 0 ? (
            <p className="text-center text-slate-500 text-sm py-6">No evidence added yet. Use auto-gather or add manually.</p>
          ) : evidence.map(ev => (
            <div key={ev._id} className="flex items-start gap-3 bg-slate-800/50 border border-slate-700/50 rounded-lg p-3">
              <span className={`px-2 py-0.5 rounded text-xs font-medium border shrink-0 ${STANCE_COLORS[ev.stance] || ''}`}>{ev.stance}</span>
              <div className="flex-1 min-w-0">
                <p className="text-slate-300 text-sm">{ev.text}</p>
                <div className="flex gap-2 mt-1 text-xs text-slate-600">
                  <span>strength: {(ev.strength * 100).toFixed(0)}%</span>
                  {ev.source && <span>{ev.source}</span>}
                </div>
              </div>
              <button onClick={() => removeEv(ev._id)} className="text-slate-600 hover:text-red-400 text-xs shrink-0">✕</button>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {candidates.length === 0 ? (
            <p className="text-center text-slate-500 text-sm py-6">No candidates found. Try a different hypothesis or longer lookback.</p>
          ) : candidates.map(c => (
            <div key={c.event_id} className="flex items-start gap-3 bg-slate-800/50 border border-slate-700/50 rounded-lg p-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium border ${STANCE_COLORS[c.suggested_stance] || ''}`}>
                    {c.suggested_stance}
                  </span>
                  <span className="text-xs text-slate-500">sim: {(c.similarity * 100).toFixed(0)}%</span>
                  <span className="text-xs text-slate-600">{(c.created_at || '').slice(0, 10)}</span>
                </div>
                <p className="text-slate-300 text-sm">{c.summary}</p>
              </div>
              <button onClick={() => addCandidate(c)} className="px-2 py-1 text-xs bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded-lg hover:bg-orange-500/30 shrink-0">
                Add
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main HypothesisPage ───────────────────────────────────────────────────────
export default function HypothesisPage() {
  const [hypotheses, setHypotheses] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [selected, setSelected] = useState(null)
  const [filterStatus, setFilterStatus] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = filterStatus ? { status: filterStatus } : {}
      const r = await getHypotheses(params)
      setHypotheses(r.data?.hypotheses || [])
    } catch {}
    setLoading(false)
  }, [filterStatus])

  useEffect(() => { load() }, [load])

  const handleDelete = async (id, e) => {
    e.stopPropagation()
    if (!window.confirm('Delete this hypothesis?')) return
    try { await deleteHypothesis(id); load() } catch {}
  }

  if (selected) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-6">
        <HypothesisDetail hyp={selected} onBack={() => { setSelected(null); load() }} onUpdated={load} />
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {showCreate && (
        <CreateHypothesisModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load() }}
        />
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Hypothesis Testing</h1>
          <p className="text-slate-400 text-sm">Form claims, gather evidence, compute confidence with AI</p>
        </div>
        <button onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold rounded-lg">
          + New Hypothesis
        </button>
      </div>

      {/* Status filter */}
      <div className="flex gap-2">
        {[['','All'],['open','Open'],['confirmed','Confirmed'],['rejected','Rejected'],['inconclusive','Inconclusive']].map(([val, label]) => (
          <button key={val} onClick={() => setFilterStatus(val)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filterStatus === val ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' : 'bg-slate-800 text-slate-400 border border-transparent hover:text-white'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : hypotheses.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <div className="text-4xl mb-3">🔬</div>
          <p>No hypotheses yet.</p>
          <button onClick={() => setShowCreate(true)} className="mt-3 text-orange-400 text-sm hover:underline">
            Create your first hypothesis →
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {hypotheses.map(hyp => (
            <div key={hyp._id} onClick={() => setSelected(hyp)}
              className="bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-xl p-4 cursor-pointer transition-all hover:bg-slate-800/50 group">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`text-xs font-bold uppercase ${VERDICT_COLORS[hyp.status] || ''}`}>{hyp.status || 'open'}</span>
                    <span className="text-xs text-slate-500">{(hyp.updated_at || '').slice(0, 10)}</span>
                  </div>
                  <p className="text-sm text-white group-hover:text-orange-300 leading-relaxed">{hyp.statement}</p>
                  <div className="mt-3 flex items-center gap-2">
                    <div className="flex-1 bg-slate-800 rounded-full h-1.5">
                      <div className="h-1.5 rounded-full bg-orange-400" style={{ width: `${(hyp.confidence || 0) * 100}%` }} />
                    </div>
                    <span className="text-xs text-slate-400 w-8 text-right">{Math.round((hyp.confidence || 0) * 100)}%</span>
                  </div>
                  <div className="flex gap-3 mt-2 text-xs text-slate-500">
                    <span className="text-green-400">✓ {hyp.supporting_count || 0}</span>
                    <span className="text-red-400">✗ {hyp.contradicting_count || 0}</span>
                    <span>~ {hyp.neutral_count || 0}</span>
                  </div>
                </div>
                <button onClick={e => handleDelete(hyp._id, e)}
                  className="text-slate-700 hover:text-red-400 text-xs shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
