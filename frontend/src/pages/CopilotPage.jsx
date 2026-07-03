import React, { useState, useEffect, useRef, useCallback } from 'react'
import { queryCopilot, getCopilotHistory, clearCopilotHistory, isCanceled } from '../api'

function Spinner() {
  return <div className="h-4 w-4 rounded-full border-2 border-orange-400 border-t-transparent animate-spin" />
}

function MessageBubble({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 ${
        isUser
          ? 'bg-orange-500 text-white rounded-br-sm'
          : 'bg-slate-800 border border-slate-700 text-slate-200 rounded-bl-sm'
      }`}>
        {!isUser && (
          <div className="flex items-center gap-1.5 mb-2">
            <div className="flex h-5 w-5 items-center justify-center rounded bg-orange-500 text-white text-xs font-black">G</div>
            <span className="text-xs text-orange-400 font-semibold">GARUDA</span>
          </div>
        )}
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.text}</p>
        {msg.sources?.length > 0 && (
          <div className="mt-2 flex gap-1 flex-wrap">
            {msg.sources.map(s => (
              <span key={s} className="text-[10px] bg-orange-500/20 text-orange-300 rounded px-1.5 py-0.5">{s}</span>
            ))}
          </div>
        )}
        <div className="mt-1 text-[10px] opacity-50">{msg.time}</div>
      </div>
    </div>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex justify-start">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-2">
        <Spinner />
        <span className="text-xs text-slate-400">Analyzing intelligence database…</span>
      </div>
    </div>
  )
}

// ── Suggested queries ─────────────────────────────────────────────────────────
const SUGGESTED = [
  "What are the most significant events in Jaipur this week?",
  "Show infrastructure incidents involving JDA in the last 30 days",
  "Who are the key political figures mentioned in recent events?",
  "What crime patterns are emerging in Mansarovar?",
  "Summarize recent health-related events in Jaipur",
  "What organizations appear most frequently in high-severity events?",
]

// ── Main CopilotPage ──────────────────────────────────────────────────────────
export default function CopilotPage() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [includeContext, setIncludeContext] = useState(true)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  // Restore session from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('garuda_copilot_session')
    if (saved) {
      setSessionId(saved)
      // Load history
      getCopilotHistory(saved, { limit: 20 })
        .then(r => {
          const history = r.data?.history || []
          const msgs = []
          history.forEach(turn => {
            msgs.push({ role: 'user', text: turn.query, time: (turn.created_at || '').slice(11, 16) })
            msgs.push({ role: 'assistant', text: turn.response, time: (turn.created_at || '').slice(11, 16) })
          })
          if (msgs.length) setMessages(msgs)
        })
        .catch(() => {})
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, thinking])

  const send = useCallback(async (text) => {
    const q = text || input.trim()
    if (!q || thinking) return
    setInput('')

    const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
    setMessages(prev => [...prev, { role: 'user', text: q, time: now }])
    setThinking(true)

    try {
      const r = await queryCopilot({
        query: q,
        session_id: sessionId,
        include_context: includeContext,
      })
      const data = r.data
      if (data.session_id && !sessionId) {
        setSessionId(data.session_id)
        localStorage.setItem('garuda_copilot_session', data.session_id)
      }
      const respTime = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: data.response || 'No response received.',
        sources: data.sources || [],
        time: respTime,
      }])
    } catch (e) {
      if (!isCanceled(e)) {
        setMessages(prev => [...prev, {
          role: 'assistant',
          text: 'Failed to connect to the intelligence backend. Please check the API is running.',
          time: new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
        }])
      }
    } finally {
      setThinking(false)
      inputRef.current?.focus()
    }
  }, [input, thinking, sessionId, includeContext])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const handleClear = async () => {
    if (!window.confirm('Clear conversation history?')) return
    if (sessionId) {
      try { await clearCopilotHistory(sessionId) } catch {}
    }
    setMessages([])
    setSessionId(null)
    localStorage.removeItem('garuda_copilot_session')
  }

  const isEmpty = messages.length === 0 && !thinking

  return (
    <div className="flex flex-col h-[calc(100vh-104px)]">
      {/* Header */}
      <div className="border-b border-slate-800 px-4 py-3 flex items-center gap-3 bg-slate-950 shrink-0">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-500 text-white font-black text-sm select-none">G</div>
        <div className="flex-1">
          <div className="text-sm font-bold text-white">GARUDA Analyst Copilot</div>
          <div className="text-xs text-slate-500">Intelligence assistant for Jaipur · GraphRAG-powered</div>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
          <div className={`relative w-8 h-4 rounded-full transition-colors cursor-pointer ${includeContext ? 'bg-orange-500' : 'bg-slate-700'}`}
            onClick={() => setIncludeContext(!includeContext)}>
            <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${includeContext ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </div>
          Context
        </label>
        {messages.length > 0 && (
          <button onClick={handleClear} className="text-xs text-slate-600 hover:text-slate-400">Clear</button>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div>
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-orange-500/20 border border-orange-500/30 mx-auto mb-4">
                <span className="text-3xl">🧠</span>
              </div>
              <h2 className="text-white font-bold text-lg">GARUDA Intelligence Copilot</h2>
              <p className="text-slate-400 text-sm mt-1 max-w-md">
                Query the live Jaipur intelligence database in natural language.
                Grounded in real events, entities, and trends.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-2xl">
              {SUGGESTED.map(q => (
                <button key={q} onClick={() => send(q)}
                  className="text-left px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-sm text-slate-300 hover:border-orange-500/40 hover:bg-slate-800 transition-all">
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
            {thinking && <ThinkingBubble />}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-800 px-4 py-3 bg-slate-950 shrink-0">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about Jaipur events, entities, trends, patterns…"
            rows={1}
            className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-orange-500 resize-none max-h-32 overflow-y-auto"
            style={{ minHeight: '44px' }}
          />
          <button
            onClick={() => send()}
            disabled={!input.trim() || thinking}
            className="h-11 w-11 rounded-xl bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center text-white transition-colors shrink-0"
          >
            {thinking ? <Spinner /> : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            )}
          </button>
        </div>
        <div className="text-center mt-2">
          <span className="text-xs text-slate-600">Enter to send · Shift+Enter for new line</span>
        </div>
      </div>
    </div>
  )
}
