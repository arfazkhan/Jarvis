const BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const KEY = import.meta.env.VITE_API_KEY || ''

async function req(path, { method = 'GET', body } = {}) {
  const h = { 'Content-Type': 'application/json' }
  if (KEY) h['X-API-Key'] = KEY
  const res = await fetch(`${BASE}${path}`, {
    method, headers: h, body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let d = res.statusText
    try { d = (await res.json()).detail || d } catch { /* noop */ }
    throw new Error(`${res.status}: ${d}`)
  }
  return res.json()
}

export const api = {
  templates: () => req('/templates'),
  projects: () => req('/projects'),
  createProject: (body) => req('/projects', { method: 'POST', body }),
  plan: (pid) => req(`/projects/${pid}/plan`),
  editTask: (pid, tid, body) => req(`/projects/${pid}/tasks/${tid}`, { method: 'POST', body }),
  pending: (pid) => req(`/projects/${pid}/pending`),
  decide: (eid, status) => req(`/pending/${eid}/decide`, { method: 'POST', body: { status, by: 'web' } }),
  activity: (pid) => req(`/projects/${pid}/activity`),
  digest: (pid) => req(`/projects/${pid}/digest`),
  linkGroup: (pid, group_jid) => req(`/projects/${pid}/link-group`, { method: 'POST', body: { group_jid } }),
  people: (pid) => req(`/projects/${pid}/people`),
}
