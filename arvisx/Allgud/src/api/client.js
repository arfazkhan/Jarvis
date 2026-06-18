const BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8091/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

let currentBuilding = ''

export function setCurrentBuilding(id) {
  currentBuilding = id
}

function qs(params = {}) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, v)
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function request(path, { method = 'GET', body, params, headers, raw } = {}) {
  const building = params?.building ?? currentBuilding
  const url = `${BASE}${path}${qs({ ...params, building })}`
  const h = { ...(headers || {}) }
  if (!raw) h['Content-Type'] = 'application/json'
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
  return res.json()
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body, params) => request(path, { method: 'POST', body, params }),
  del: (path, params) => request(path, { method: 'DELETE', params }),

  seeds: () => api.get('/forms/seeds'),
  seedBuilding: (body) => api.post('/forms/seed', body),

  readiness: (building) => api.get('/analyzers/readiness', { building }),
  health: (building) => api.get('/analyzers/health', { building }),
  watchlist: (building) => api.get('/analyzers/watchlist', { building }),
  compliance: (building) => api.get('/analyzers/compliance', { building }),
  vendors: (building) => api.get('/analyzers/vendors', { building }),

  today: (building, date) => api.get('/forms/today', { building, date }),
  digest: (building, date) => api.get('/forms/digest', { building, date }),
  templates: (building) => api.get('/forms/templates', { building }),
  template: (id, building) => api.get(`/forms/template/${id}`, { building }),
  startRun: (body) => api.post('/forms/run', body),
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

  // sweeps
  runEscalations: (building) => api.post('/escalations/run', undefined, { building }),
  runReminders: (building) => api.post('/forms/reminders/run', undefined, { building }),

  // agents
  rca: (asset, building) => api.get('/agents/rca', { asset, building }),
  workOrder: (issue_id, building) => api.get('/agents/work-order', { issue_id, building }),
}
