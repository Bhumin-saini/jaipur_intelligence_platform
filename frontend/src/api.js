import axios from 'axios'

const api = axios.create({ baseURL: '/api' })
const scrapeApiKey = import.meta.env.VITE_SCRAPE_API_KEY || ''

const mergeConfig = (config = {}, extra = {}) => ({
  ...config, ...extra,
  headers: { ...(config.headers || {}), ...(extra.headers || {}) },
})

export const isCanceled = error =>
  error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError'

// ── Core endpoints ────────────────────────────────────────────────────────────
export const getEvents    = (params = {}, config = {}) => api.get('/events',       mergeConfig(config, { params }))
export const getEvent     = (id, config = {})           => api.get(`/events/${id}`, config)
export const getEntities  = (params = {}, config = {}) => api.get('/entities',     mergeConfig(config, { params }))
export const getEntity    = (id, config = {})           => api.get(`/entities/${id}`, config)
export const getGraphData = (params = {}, config = {}) => api.get('/graph-data',   mergeConfig(config, { params }))
export const getStats     = (config = {})               => api.get('/stats',        config)
export const getMetrics   = (config = {})               => api.get('/metrics',      config)
export const getHealth    = (config = {})               => api.get('/health',       config)

export const triggerScrape = (config = {}) =>
  api.post('/scrape', null, mergeConfig(config, {
    headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {},
  }))

// ── v2: Semantic search ───────────────────────────────────────────────────────
export const searchEvents = (params = {}, config = {}) =>
  api.get('/search', mergeConfig(config, { params }))

// ── v2: Intelligence briefs ───────────────────────────────────────────────────
export const getBriefs = (params = {}, config = {}) => api.get('/briefs',          mergeConfig(config, { params }))
export const getBrief  = (id, config = {})           => api.get(`/briefs/${id}`,    config)
export const genBrief  = (body, config = {}) =>
  api.post('/briefs/generate', body,
    mergeConfig(config, { headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {} }))

// ── v2: Trends, anomalies, heatmap ───────────────────────────────────────────
export const getTrends    = (params = {}, config = {}) => api.get('/trends',    mergeConfig(config, { params }))
export const getAnomalies = (params = {}, config = {}) => api.get('/anomalies', mergeConfig(config, { params }))
export const getHeatmap   = (params = {}, config = {}) => api.get('/heatmap',   mergeConfig(config, { params }))

// ── v2: Entity network graph ──────────────────────────────────────────────────
export const getEntityNetwork = (id, params = {}, config = {}) =>
  api.get(`/entities/${id}/network`, mergeConfig(config, { params }))

// ── Phase 1: Timeline & similar events ───────────────────────────────────────
export const getTimeline     = (params = {}, config = {}) => api.get('/timeline',               mergeConfig(config, { params }))
export const getSimilarEvents = (id, params = {}, config = {}) => api.get(`/events/${id}/similar`, mergeConfig(config, { params }))

// ══ v3: Knowledge Graph ───────────────────────────────────────────────────────
export const getGraphNodes      = (params = {}, config = {}) => api.get('/graph/nodes',               mergeConfig(config, { params }))
export const getGraphNodeDetail = (id, params = {}, config = {}) => api.get(`/graph/nodes/${id}`,     mergeConfig(config, { params }))
export const getGraphEdges      = (params = {}, config = {}) => api.get('/graph/edges',               mergeConfig(config, { params }))
export const getGraphCommunities = (config = {})              => api.get('/graph/communities',         config)
export const getGraphStats      = (config = {})               => api.get('/graph/stats',               config)
export const buildGraph         = (body, config = {})         => api.post('/graph/build', body,        mergeConfig(config, { headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {} }))
export const getEventLinks      = (id, config = {})           => api.get(`/graph/event-links/${id}`,   config)
export const getEventChain      = (id, params = {}, config = {}) => api.get(`/graph/event-chain/${id}`, mergeConfig(config, { params }))

// ══ v3: Cases ────────────────────────────────────────────────────────────────
export const getCases         = (params = {}, config = {}) => api.get('/cases',              mergeConfig(config, { params }))
export const createCase       = (body, config = {})        => api.post('/cases', body,        config)
export const getCase          = (id, config = {})          => api.get(`/cases/${id}`,         config)
export const updateCase       = (id, body, config = {})    => api.put(`/cases/${id}`, body,   config)
export const deleteCase       = (id, config = {})          => api.delete(`/cases/${id}`,      config)
export const closeCase        = (id, body, config = {})    => api.post(`/cases/${id}/close`, body, config)
export const getCaseEvents    = (id, params = {}, config = {}) => api.get(`/cases/${id}/events`, mergeConfig(config, { params }))
export const addCaseEvent     = (id, body, config = {})    => api.post(`/cases/${id}/events`, body, config)
export const removeCaseEvent  = (caseId, eventId, config = {}) => api.delete(`/cases/${caseId}/events/${eventId}`, config)
export const getCaseAnnotations = (id, params = {}, config = {}) => api.get(`/cases/${id}/annotations`, mergeConfig(config, { params }))
export const addAnnotation    = (id, body, config = {})    => api.post(`/cases/${id}/annotations`, body, config)
export const deleteAnnotation = (id, config = {})          => api.delete(`/annotations/${id}`, config)
export const getCaseRisk      = (id, config = {})          => api.get(`/cases/${id}/risk`,    config)
export const exportCase       = (id, config = {})          => api.get(`/cases/${id}/export`,  config)

// ══ v3: Watchlist ─────────────────────────────────────────────────────────────
export const getWatchlist       = (params = {}, config = {}) => api.get('/watchlist',             mergeConfig(config, { params }))
export const createWatchlist    = (body, config = {})        => api.post('/watchlist', body,       config)
export const getWatchlistItem   = (id, config = {})          => api.get(`/watchlist/${id}`,        config)
export const updateWatchlistItem = (id, body, config = {})   => api.put(`/watchlist/${id}`, body,  config)
export const deleteWatchlistItem = (id, config = {})         => api.delete(`/watchlist/${id}`,     config)
export const getAlerts          = (params = {}, config = {}) => api.get('/alerts',                 mergeConfig(config, { params }))
export const getUnreadCount     = (config = {})              => api.get('/alerts/unread-count',     config)
export const triggerAlertCheck  = (config = {}) => api.post('/alerts/check', null, mergeConfig(config, { headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {} }))
export const markAlertRead      = (id, config = {})          => api.post(`/alerts/${id}/read`, null, config)
export const markAllAlertsRead  = (config = {})              => api.post('/alerts/read-all', null,  config)

// ══ v3: Hypotheses ───────────────────────────────────────────────────────────
export const getHypotheses      = (params = {}, config = {}) => api.get('/hypotheses',             mergeConfig(config, { params }))
export const createHypothesis   = (body, config = {})        => api.post('/hypotheses', body,       config)
export const getHypothesis      = (id, config = {})          => api.get(`/hypotheses/${id}`,        config)
export const updateHypothesis   = (id, body, config = {})    => api.put(`/hypotheses/${id}`, body,  config)
export const deleteHypothesis   = (id, config = {})          => api.delete(`/hypotheses/${id}`,     config)
export const getEvidence        = (id, params = {}, config = {}) => api.get(`/hypotheses/${id}/evidence`, mergeConfig(config, { params }))
export const addEvidence        = (id, body, config = {})    => api.post(`/hypotheses/${id}/evidence`, body, config)
export const removeEvidence     = (id, config = {})          => api.delete(`/evidence/${id}`,       config)
export const evaluateHypothesis = (id, config = {})          => api.post(`/hypotheses/${id}/evaluate`, null, config)
export const searchEvidence     = (id, params = {}, config = {}) => api.get(`/hypotheses/${id}/search-evidence`, mergeConfig(config, { params }))
export const autoGatherEvidence = (id, body, config = {})    => api.post(`/hypotheses/${id}/auto-evidence`, body, config)

// ══ v3: Predictions ──────────────────────────────────────────────────────────
export const getPredictions     = (params = {}, config = {}) => api.get('/predict',               mergeConfig(config, { params }))
export const getHotspots        = (params = {}, config = {}) => api.get('/predict/hotspots',       mergeConfig(config, { params }))
export const getForecast        = (eventType, params = {}, config = {}) => api.get(`/predict/${eventType}`, mergeConfig(config, { params }))
export const generatePredictions = (config = {}) => api.post('/predict/generate', null, mergeConfig(config, { headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {} }))

// ══ v3: Sources ──────────────────────────────────────────────────────────────
export const getSources         = (params = {}, config = {}) => api.get('/sources',               mergeConfig(config, { params }))

// ══ v3: Copilot ──────────────────────────────────────────────────────────────
export const queryCopilot       = (body, config = {})        => api.post('/copilot', body,         config)
export const getCopilotSessions = (config = {})              => api.get('/copilot/sessions',        config)
export const getCopilotHistory  = (sessionId, params = {}, config = {}) => api.get(`/copilot/history/${sessionId}`, mergeConfig(config, { params }))
export const clearCopilotHistory = (sessionId, config = {}) => api.delete(`/copilot/history/${sessionId}`, config)

// ══ v3: Insights ──────────────────────────────────────────────────────────────
export const getInsights         = (params = {}, config = {}) => api.get('/insights',              mergeConfig(config, { params }))
export const getInsightStats     = (config = {})              => api.get('/insights/stats',         config)
export const getInsightUnread    = (config = {})              => api.get('/insights/unread-count',  config)
export const getInsight          = (id, config = {})          => api.get(`/insights/${id}`,         config)
export const markInsightRead     = (id, config = {})          => api.post(`/insights/${id}/read`, null, config)
export const generateInsights    = (body, config = {}) => api.post('/insights/generate', body, mergeConfig(config, { headers: scrapeApiKey ? { 'X-API-Key': scrapeApiKey } : {} }))
