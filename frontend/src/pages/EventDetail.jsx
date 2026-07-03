import React, { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { getEvent, getSimilarEvents, isCanceled } from '../api'

const SEV_CLS = {
  high:   'bg-red-500/20 text-red-400 border-red-500/40',
  medium: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
  low:    'bg-green-500/20 text-green-400 border-green-500/40',
}
const ENTITY_CLS = {
  person:       'border-blue-500/40 text-blue-300 bg-blue-500/10',
  organization: 'border-purple-500/40 text-purple-300 bg-purple-500/10',
  location:     'border-orange-500/40 text-orange-300 bg-orange-500/10',
}
const ENTITY_ICON = { person: '👤', organization: '🏛', location: '📍' }
const TYPE_ICON   = {
  crime:'🚨', politics:'🏛', accident:'💥', infrastructure:'🏗',
  cultural:'🎭', weather:'🌧', business:'💼', health:'🏥', other:'📌',
}

function SimilarEvents({ eventId }) {
  const [similar, setSimilar] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const c = new AbortController()
    getSimilarEvents(eventId, { limit: 5 }, { signal: c.signal })
      .then(r => setSimilar(r.data || []))
      .catch(err => { if (!isCanceled(err)) setSimilar([]) })
      .finally(() => setLoading(false))
    return () => c.abort()
  }, [eventId])

  if (loading) return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
      <h2 className="text-sm font-semibold text-slate-400 uppercase mb-3">Similar Events</h2>
      <div className="text-slate-500 text-sm">Finding related events…</div>
    </div>
  )

  if (!similar.length) return null

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
      <h2 className="text-sm font-semibold text-slate-400 uppercase mb-3">
        Similar Events
        <span className="text-slate-600 font-normal ml-2 normal-case">via semantic search</span>
      </h2>
      <div className="space-y-2">
        {similar.map(ev => (
          <Link
            key={ev._id}
            to={`/events/${ev._id}`}
            className="flex items-start gap-3 p-3 rounded-lg bg-slate-700/50 hover:bg-slate-700
                       border border-transparent hover:border-slate-600 transition-colors group"
          >
            <span className="text-base shrink-0 mt-0.5">{TYPE_ICON[ev.event_type] || '📌'}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={`px-1.5 py-0.5 rounded border text-xs font-bold uppercase ${SEV_CLS[ev.severity] || SEV_CLS.low}`}>
                  {ev.severity}
                </span>
                <span className="text-xs text-slate-400 capitalize">{ev.event_type}</span>
                <span className="text-xs text-slate-500 ml-auto">
                  {ev.created_at ? new Date(ev.created_at).toLocaleDateString('en-IN') : ''}
                </span>
              </div>
              <p className="text-sm text-white group-hover:text-orange-300 transition-colors line-clamp-2">
                {ev.article_title || ev.summary}
              </p>
              {ev.$similarity && (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <div className="h-1 flex-1 bg-slate-600 rounded-full overflow-hidden">
                    <div className="h-full bg-orange-500 rounded-full"
                         style={{ width: `${Math.round(ev.$similarity * 100)}%` }} />
                  </div>
                  <span className="text-xs text-slate-500">{Math.round(ev.$similarity * 100)}% match</span>
                </div>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

function ActionBar({ event }) {
  const [bookmarked, setBookmarked] = useState(false)
  const [escalated, setEscalated]   = useState(false)
  const [copied, setCopied]         = useState(false)

  // Persist bookmarks in localStorage
  useEffect(() => {
    const saved = JSON.parse(localStorage.getItem('garuda_bookmarks') || '[]')
    setBookmarked(saved.includes(event._id))
  }, [event._id])

  const toggleBookmark = () => {
    const saved  = JSON.parse(localStorage.getItem('garuda_bookmarks') || '[]')
    const updated = bookmarked
      ? saved.filter(id => id !== event._id)
      : [...saved, event._id]
    localStorage.setItem('garuda_bookmarks', JSON.stringify(updated))
    setBookmarked(!bookmarked)
  }

  const copyLink = () => {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={toggleBookmark}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                    border transition-colors ${
                      bookmarked
                        ? 'bg-orange-500/20 border-orange-500/40 text-orange-300'
                        : 'bg-slate-700 border-slate-600 text-slate-300 hover:border-orange-500/40'
                    }`}
      >
        {bookmarked ? '🔖 Bookmarked' : '🔖 Bookmark'}
      </button>

      <button
        onClick={() => setEscalated(true)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                    border transition-colors ${
                      escalated
                        ? 'bg-red-500/20 border-red-500/40 text-red-300'
                        : 'bg-slate-700 border-slate-600 text-slate-300 hover:border-red-500/40'
                    }`}
      >
        {escalated ? '⚠ Escalated' : '⚠ Escalate'}
      </button>

      <button
        onClick={copyLink}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                   bg-slate-700 border border-slate-600 text-slate-300 hover:border-slate-400 transition-colors"
      >
        {copied ? '✓ Copied' : '🔗 Copy Link'}
      </button>

      {event.article_url && (
        <a href={event.article_url} target="_blank" rel="noopener noreferrer"
           className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                      bg-slate-700 border border-slate-600 text-orange-400 hover:border-orange-500/40 transition-colors">
          Read Source ↗
        </a>
      )}
    </div>
  )
}

export default function EventDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [event, setEvent]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const c = new AbortController()
    setLoading(true)
    getEvent(id, { signal: c.signal })
      .then(r => setEvent(r.data))
      .catch(err => { if (!isCanceled(err)) setEvent(null) })
      .finally(() => { if (!c.signal.aborted) setLoading(false) })
    return () => c.abort()
  }, [id])

  if (loading) return <div className="flex items-center justify-center h-96 text-slate-400">Loading…</div>
  if (!event)  return <div className="flex items-center justify-center h-96 text-slate-400">Event not found.</div>

  const arr = f => Array.isArray(event[f]) ? event[f] : (event[f] ? JSON.parse(event[f]) : [])
  const locations = arr('locations')
  const people    = arr('people')
  const orgs      = arr('organizations')

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-5">
      <button onClick={() => navigate(-1)} className="text-slate-400 hover:text-white text-sm flex items-center gap-1">
        ← Back
      </button>

      {/* Main card */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 space-y-4">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-2xl">{TYPE_ICON[event.event_type] || '📌'}</span>
          <span className={`px-3 py-1 rounded border text-xs font-bold uppercase ${SEV_CLS[event.severity] || SEV_CLS.low}`}>
            {event.severity}
          </span>
          <span className="capitalize text-slate-300 text-sm font-medium">{event.event_type}</span>
          <span className="text-slate-500 text-xs ml-auto">
            {event.created_at ? new Date(event.created_at).toLocaleString('en-IN') : ''}
          </span>
        </div>

        <h1 className="text-xl font-bold text-white leading-snug">{event.article_title}</h1>

        {/* Source + metadata row */}
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 border-t border-slate-700 pt-3">
          {event.source && (
            <span className="bg-slate-700 px-2 py-0.5 rounded text-slate-300">📰 {event.source}</span>
          )}
          {event.published_at && (
            <span>Published: {new Date(event.published_at).toLocaleDateString('en-IN')}</span>
          )}
          {event.lat && event.lng && (
            <span>📍 {event.lat.toFixed(4)}, {event.lng.toFixed(4)}</span>
          )}
        </div>

        {/* Summary */}
        <p className="text-slate-300 leading-relaxed text-sm">{event.summary}</p>

        {/* Keywords */}
        {arr('keywords').length > 0 && (
          <div className="flex flex-wrap gap-2">
            {arr('keywords').map((k, i) => (
              <span key={i} className="px-2 py-0.5 bg-slate-700 text-slate-300 text-xs rounded-full">{k}</span>
            ))}
          </div>
        )}

        {/* Action bar */}
        <div className="border-t border-slate-700 pt-4">
          <ActionBar event={event} />
        </div>
      </div>

      {/* Entities involved */}
      {event.entities?.length > 0 && (
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-400 uppercase mb-3 tracking-wider">Entities Involved</h2>
          <div className="flex flex-wrap gap-2">
            {event.entities.map(en => (
              <Link
                key={en._id || en.id}
                to={`/entities/${en._id || en.id}`}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm
                            hover:opacity-80 transition-opacity ${ENTITY_CLS[en.type] || ''}`}
              >
                <span>{ENTITY_ICON[en.type] || '•'}</span>
                <span>{en.name}</span>
                {en.mention_count > 1 && (
                  <span className="text-xs opacity-60 ml-0.5">{en.mention_count}</span>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Locations, People, Orgs */}
      {(locations.length > 0 || people.length > 0 || orgs.length > 0) && (
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 space-y-4">
          {locations.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2 tracking-wider">Locations</h3>
              <div className="flex flex-wrap gap-2">
                {locations.map((l, i) => (
                  <span key={i} className="px-2 py-0.5 bg-orange-500/10 border border-orange-500/30 text-orange-300 text-xs rounded-full">
                    📍 {l}
                  </span>
                ))}
              </div>
            </div>
          )}
          {people.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2 tracking-wider">People</h3>
              <div className="flex flex-wrap gap-2">
                {people.map((p, i) => (
                  <span key={i} className="px-2 py-0.5 bg-blue-500/10 border border-blue-500/30 text-blue-300 text-xs rounded-full">
                    👤 {p}
                  </span>
                ))}
              </div>
            </div>
          )}
          {orgs.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2 tracking-wider">Organizations</h3>
              <div className="flex flex-wrap gap-2">
                {orgs.map((o, i) => (
                  <span key={i} className="px-2 py-0.5 bg-purple-500/10 border border-purple-500/30 text-purple-300 text-xs rounded-full">
                    🏛 {o}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Similar events */}
      <SimilarEvents eventId={id} />
    </div>
  )
}
