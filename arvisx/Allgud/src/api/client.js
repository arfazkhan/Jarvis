const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8091/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

let currentBuilding = ''

export function setCurrentBuilding(id) {
  currentBuilding = id
}

// ── auth token (user login) ───────────────────────────────────────────────
const TOKEN_KEY = 'allgud.token'
let authToken = localStorage.getItem(TOKEN_KEY) || ''

export function setToken(t) {
  authToken = t || ''
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export function getToken() {
  return authToken
}

// Deep-link auth: a WhatsApp assignment link can carry a pre-minted technician
// token as ?t=<token> so tapping it drops the tech straight into the round, no
// login wall. Consume it once on load and scrub it from the URL (don't leave a
// bearer token sitting in the address bar / history / referrer).
function consumeDeepLinkToken() {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  const t = url.searchParams.get('t')
  if (!t) return
  setToken(t)
  url.searchParams.delete('t')
  window.history.replaceState({}, '', url.pathname + url.search + url.hash)
}
consumeDeepLinkToken()

function qs(params = {}) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, v)
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function request(path, { method = 'GET', body, params, headers, raw, blob } = {}) {
  const building = params?.building ?? currentBuilding
  const url = `${BASE}${path}${qs({ ...params, building })}`
  const h = { ...(headers || {}) }
  if (!raw) h['Content-Type'] = 'application/json'
  if (authToken) h['Authorization'] = `Bearer ${authToken}`
  if (API_KEY) h['X-API-Key'] = API_KEY

  const res = await fetch(url, {
    method,
    headers: h,
    body: raw ? body : body ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail || detail
    } catch {}
    throw new Error(`${res.status}: ${detail}`)
  }
  if (res.status === 204) return null
  if (blob) return res.blob()
  return res.json()
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body, params) => request(path, { method: 'POST', body, params }),
  del: (path, params) => request(path, { method: 'DELETE', params }),

  // auth
  login: (username, password) => api.post('/auth/login', { username, password }),
  me: () => api.get('/auth/me'),
  createUser: (body) => api.post('/auth/users', body),

  // field access (technicians): PIN now, deep-link token later — same primitive.
  fieldLogin: (building, pin) => api.post('/auth/field-login', { building, pin }),
  setTechPin: (id, pin) => api.post(`/technicians/${id}/pin`, { pin }),
  fieldToken: (building, technician) => api.post('/auth/field-token', { building, technician }),

  seeds: () => api.get('/forms/seeds'),
  seedBuilding: (body) => api.post('/forms/seed', body),

  readiness: (building) => api.get('/analyzers/readiness', { building }),
  health: (building) => api.get('/analyzers/health', { building }),
  watchlist: (building) => api.get('/analyzers/watchlist', { building }),
  compliance: (building) => api.get('/analyzers/compliance', { building }),
  vendors: (building) => api.get('/analyzers/vendors', { building }),

  today: (building, date) => api.get('/forms/today', { building, date }),
  digest: (building, date) => api.get('/forms/digest', { building, date }),
  activity: (building, date) => api.get('/forms/activity', { building, date }),
  trend: (building, days) => api.get('/forms/trend', { building, days }),
  templates: (building) => api.get('/forms/templates', { building }),
  template: (id, building) => api.get(`/forms/template/${id}`, { building }),
  saveTemplate: (body) => api.post('/forms/templates', body),
  deleteTemplate: (id, building) => api.del(`/forms/template/${id}`, { building }),
  startRun: (body) => api.post('/forms/run', body),
  openToday: (building) => api.post('/forms/open-today', undefined, { building }),
  getRun: (rid) => api.get(`/forms/run/${rid}`),
  entry: (rid, body) => api.post(`/forms/run/${rid}/entry`, body),
  assign: (rid, body) => api.post(`/forms/run/${rid}/assign`, body),
  signoff: (rid, body) => api.post(`/forms/run/${rid}/signoff`, body),
  submit: (rid) => api.post(`/forms/run/${rid}/submit`),
  review: (rid) => api.get(`/forms/run/${rid}/review`),

  issues: (building, status) => api.get('/issues', { building, status }),
  issue: (id) => api.get(`/issues/${id}`),
  transitionIssue: (id, body) => api.post(`/issues/${id}/transition`, body),

  ppmSchedule: (building) => api.get('/ppm/schedule', { building }),
  assets: (building) => api.get('/assets', { building }),
  assetHistory: (asset, building) => api.get(`/assets/${asset}/history`, { building }),
  assetsRegistry: (building) => api.get('/assets/registry', { building }),
  addAsset: (body) => api.post('/assets', body),
  deactivateAsset: (id) => api.post(`/assets/${id}/deactivate`),

  // B1: equipment manual attach / view
  uploadAssetManual: (id, blob, contentType, filename) =>
    request(`/assets/${id}/manual`, {
      method: 'POST', params: { filename }, raw: true, body: blob,
      headers: { 'Content-Type': contentType || 'application/octet-stream' },
    }),
  clearAssetManual: (id) => api.post(`/assets/${id}/manual/clear`),
  openAssetManual: async (name) => {
    const b = await request(`/assets/manual/${name}`, { blob: true })
    window.open(URL.createObjectURL(b), '_blank')
  },
  // C1: distil manual → skills + read stored knowledge
  extractAssetSkills: (id) => api.post(`/assets/${id}/extract-skills`),
  assetKnowledge: (id) => api.get(`/assets/${id}/knowledge`),
  // C2: building memory — recurring issues
  buildingMemory: (building, days) => api.get('/building/memory', { building, days }),

  ask: (q, building) => api.get('/agents/ask', { q, building }),
  handover: (building) => api.get('/agents/handover', { building }),

  entryPhoto: (rid, { item_id, filename, building }, blob, contentType) =>
    request(`/forms/run/${rid}/photo`, {
      method: 'POST',
      params: { item_id, filename, building },
      raw: true,
      body: blob,
      headers: { 'Content-Type': contentType },
    }),

  visionExtract: (params, blob, contentType) =>
    request('/vision/extract', { method: 'POST', params, raw: true, body: blob, headers: { 'Content-Type': contentType } }),
  visionSuggestions: (building, status) => api.get('/vision/suggestions', { building, status }),
  confirmSuggestion: (id, body) => api.post(`/vision/suggestion/${id}/confirm`, body),
  rejectSuggestion: (id) => api.post(`/vision/suggestion/${id}/reject`),

  createIssue: (body) => api.post('/issues', body),
  issueSla: (id) => api.get(`/issues/${id}/sla`),
  issueVisited: (id, body) => api.post(`/issues/${id}/visited`, body),

  // technicians
  technicians: (building, all) => api.get('/technicians', { building, all }),
  addTechnician: (body) => api.post('/technicians', body),
  deactivateTechnician: (id) => api.post(`/technicians/${id}/deactivate`),

  // residents (A3 — pre-registered, may raise common-area tickets via WhatsApp)
  residents: (building, all) => api.get('/residents', { building, all }),
  addResident: (body) => api.post('/residents', body),
  deactivateResident: (id) => api.post(`/residents/${id}/deactivate`),

  // scheduled checklists (B2 — date+time triggers)
  schedules: (building, all) => api.get('/schedules', { building, all }),
  addSchedule: (body) => api.post('/schedules', body),
  deactivateSchedule: (id) => api.post(`/schedules/${id}/deactivate`),
  runScheduleNow: (id) => api.post(`/schedules/${id}/run-now`),

  // vendors
  vendorsList: (building, all) => api.get('/vendors', { building, all }),
  addVendor: (body) => api.post('/vendors', body),
  deactivateVendor: (id) => api.post(`/vendors/${id}/deactivate`),

  // ppm
  setPpm: (body) => api.post('/ppm/schedule', body),
  ppmDone: (asset, body) => api.post(`/ppm/${asset}/done`, body),

  // sla
  slaConfig: (building) => api.get('/sla/config', { building }),
  setSlaConfig: (body) => api.post('/sla/config', body),

  // admin panel (operator) — bot pairing + building analytics
  adminBridge: () => api.get('/admin/bridge/state'),
  resetBot: () => api.post('/admin/bot/reset'),
  adminAnalytics: (building, days) => api.get('/admin/analytics', { building, days }),
  adminUsage: (building, days) => api.get('/admin/usage', { building, days }),
  sendSummary: (building, period) => api.post('/admin/send-summary', undefined, { building, period }),

  // sweeps
  runEscalations: (building) => api.post('/escalations/run', undefined, { building }),
  runReminders: (building) => api.post('/forms/reminders/run', undefined, { building }),

  // agents
  rca: (asset, building) => api.get('/agents/rca', { asset, building }),
  workOrder: (issue_id, building) => api.get('/agents/work-order', { issue_id, building }),
}
