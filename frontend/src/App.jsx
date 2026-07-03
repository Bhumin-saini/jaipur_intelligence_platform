import React, { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'

import Dashboard       from './pages/Dashboard'
import MapDashboard    from './pages/MapDashboard'
import EntityView      from './pages/EntityView'
import GraphView       from './pages/GraphView'
import EventDetail     from './pages/EventDetail'
import SearchPage      from './pages/SearchPage'
import BriefsPage      from './pages/BriefsPage'
import TimelinePage    from './pages/TimelinePage'
import CasesPage       from './pages/CasesPage'
import WatchlistPage   from './pages/WatchlistPage'
import HypothesisPage  from './pages/HypothesisPage'
import PredictionsPage from './pages/PredictionsPage'
import CopilotPage     from './pages/CopilotPage'
import InsightsPage   from './pages/InsightsPage'

import { getStats, triggerScrape, isCanceled } from './api'

// ── Navbar ────────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { to: '/',           label: 'Dashboard',    exact: true },
  { to: '/map',        label: 'Map'       },
  { to: '/timeline',   label: 'Timeline'  },
  { to: '/search',     label: 'Search'    },
  { to: '/predict',    label: 'Predict'   },
  { to: '/briefs',     label: 'Briefs'    },
  { to: '/cases',      label: 'Cases'     },
  { to: '/watchlist',  label: 'Watchlist' },
  { to: '/hypotheses', label: 'Hypotheses'},
  { to: '/entities',   label: 'Entities'  },
  { to: '/graph',      label: 'Graph'     },
  { to: '/insights',   label: '💡 Insights'},
  { to: '/copilot',    label: '🧠 Copilot'},
]

function Navbar() {
  const [scraping, setScraping] = useState(false)
  const [flashMsg, setFlashMsg] = useState('')

  const handleScrape = async () => {
    setScraping(true)
    setFlashMsg('')
    try {
      const res = await triggerScrape()
      setFlashMsg(res.data?.status || 'Scrape queued')
    } catch {
      setFlashMsg('Scrape failed')
    } finally {
      setScraping(false)
      setTimeout(() => setFlashMsg(''), 4000)
    }
  }

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-950/95 backdrop-blur-sm">
      <div className="flex h-16 items-center justify-between px-4 lg:px-6">
        {/* Logo */}
        <NavLink to="/" className="flex items-center gap-2.5 shrink-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-orange-500 text-white font-black text-sm select-none">
            G
          </div>
          <div>
            <div className="text-sm font-bold text-white leading-none">GARUDA</div>
            <div className="text-xs text-slate-500 leading-none">Intelligence Platform</div>
          </div>
        </NavLink>

        {/* Nav links */}
        <nav className="hidden md:flex items-center gap-1">
          {NAV_ITEMS.map(({ to, label, exact }) => (
            <NavLink
              key={to}
              to={to}
              end={exact}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-orange-500/15 text-orange-400'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Right side */}
        <div className="flex items-center gap-3">
          {flashMsg && (
            <span className="text-xs text-green-400 bg-green-500/10 border border-green-500/30 px-3 py-1 rounded-full">
              {flashMsg}
            </span>
          )}
          <button
            onClick={handleScrape}
            disabled={scraping}
            className="flex items-center gap-2 rounded-lg bg-orange-500 px-3 py-1.5 text-sm
                       font-semibold text-white transition-all hover:bg-orange-600 disabled:opacity-50"
          >
            {scraping ? (
              <span className="animate-spin">⟳</span>
            ) : (
              <span>⟳</span>
            )}
            <span className="hidden sm:inline">{scraping ? 'Scraping…' : 'Scrape Now'}</span>
          </button>
        </div>
      </div>

      {/* Mobile nav */}
      <div className="flex md:hidden items-center gap-1 px-4 pb-2 overflow-x-auto">
        {NAV_ITEMS.map(({ to, label, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={({ isActive }) =>
              `px-3 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                isActive
                  ? 'bg-orange-500/15 text-orange-400'
                  : 'text-slate-400 hover:text-white'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </header>
  )
}

// ── Status bar ────────────────────────────────────────────────────────────────
function StatusBar() {
  const [stats, setStats] = useState(null)

  const load = useCallback((signal) => {
    getStats({ signal })
      .then(r => setStats(r.data))
      .catch(err => { if (!isCanceled(err)) setStats(null) })
  }, [])

  useEffect(() => {
    const c = new AbortController()
    load(c.signal)
    const t = setInterval(() => {
      const c2 = new AbortController()
      load(c2.signal)
    }, 30000)
    return () => { c.abort(); clearInterval(t) }
  }, [load])

  if (!stats) return null

  const scrape = stats.scrape || {}

  return (
    <div className="flex items-center gap-4 border-b border-slate-800/60 bg-slate-950 px-4 py-1.5 text-xs text-slate-500 overflow-x-auto">
      <span className="flex items-center gap-1.5 shrink-0">
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${scrape.running ? 'bg-orange-400 animate-pulse' : 'bg-green-500'}`} />
        {scrape.running ? 'Scraping…' : 'Idle'}
      </span>
      {stats.total_events !== undefined && (
        <span className="shrink-0">
          <span className="text-white font-semibold">{stats.total_events}</span> events
        </span>
      )}
      {stats.total_entities !== undefined && (
        <span className="shrink-0">
          <span className="text-white font-semibold">{stats.total_entities}</span> entities
        </span>
      )}
      {scrape.last_finished_at && (
        <span className="shrink-0">
          Last scrape: {new Date(scrape.last_finished_at).toLocaleTimeString('en-IN')}
        </span>
      )}
      {scrape.last_new_articles !== undefined && scrape.last_new_articles > 0 && (
        <span className="text-green-400 font-medium shrink-0">
          +{scrape.last_new_articles} new articles
        </span>
      )}
      <span className="ml-auto shrink-0 text-slate-600">Garuda v3 · AstraDB · Knowledge Graph</span>
    </div>
  )
}

// ── App shell ─────────────────────────────────────────────────────────────────
function AppShell() {
  const location = useLocation()
  const isMap = location.pathname === '/map'

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <Navbar />
      <StatusBar />
      <main className={isMap ? '' : 'min-h-[calc(100vh-104px)]'}>
        <Routes>
          <Route path="/"           element={<Dashboard />}       />
          <Route path="/map"        element={<MapDashboard />}    />
          <Route path="/timeline"   element={<TimelinePage />}    />
          <Route path="/search"     element={<SearchPage />}      />
          <Route path="/briefs"     element={<BriefsPage />}      />
          <Route path="/entities"   element={<EntityView />}      />
          <Route path="/entities/:id" element={<EntityView />}    />
          <Route path="/graph"      element={<GraphView />}       />
          <Route path="/events/:id" element={<EventDetail />}     />
          <Route path="/cases"      element={<CasesPage />}       />
          <Route path="/watchlist"  element={<WatchlistPage />}   />
          <Route path="/hypotheses" element={<HypothesisPage />}  />
          <Route path="/predict"    element={<PredictionsPage />} />
          <Route path="/insights"   element={<InsightsPage />}    />
          <Route path="/copilot"    element={<CopilotPage />}     />
          <Route path="*"          element={
            <div className="flex h-96 items-center justify-center text-slate-400">
              Page not found.
            </div>
          } />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  )
}
