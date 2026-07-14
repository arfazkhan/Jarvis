const BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const KEY = import.meta.env.VITE_API_KEY || ''

async function req(path, { method = 'GET', body, blob } = {}) {
  const h = {}
  if (!blob) h['Content-Type'] = 'application/json'
  if (KEY) h['X-API-Key'] = KEY
  const res = await fetch(`${BASE}${path}`, {
    method, headers: h, body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let d = res.statusText
    try { d = (await res.json()).detail || d } catch { /* noop */ }
    throw new Error(`${res.status}: ${d}`)
  }
  return blob ? res.blob() : res.json()
}

export const api = {
  templates: () => req('/templates'),
  projects: () => req('/projects'),
  createProject: (body) => req('/projects', { method: 'POST', body }),
  plan: (pid) => req(`/projects/${pid}/plan`),
  editTask: (pid, tid, body) => req(`/projects/${pid}/tasks/${tid}`, { method: 'POST', body }),

  // Lane B
  pending: (pid) => req(`/projects/${pid}/pending`),
  decide: (eid, status) => req(`/pending/${eid}/decide`, { method: 'POST', body: { status, by: 'web' } }),

  // the chase
  commitments: (pid) => req(`/projects/${pid}/commitments`),
  approvals: (pid) => req(`/projects/${pid}/approvals`),

  // the brain
  memories: (pid) => req(`/projects/${pid}/memories`),
  addMemory: (pid, text) => req(`/projects/${pid}/memories`, { method: 'POST', body: { text, by: 'web' } }),
  recall: (pid, q) => req(`/projects/${pid}/recall?q=${encodeURIComponent(q)}`),
  media: (pid) => req(`/projects/${pid}/media`),

  activity: (pid) => req(`/projects/${pid}/activity`),
  digest: (pid) => req(`/projects/${pid}/digest`),
  closeDay: (pid) => req(`/projects/${pid}/close-day`, { method: 'POST', body: {} }),
  linkGroup: (pid, group_jid) => req(`/projects/${pid}/link-group`, { method: 'POST', body: { group_jid } }),
  people: (pid) => req(`/projects/${pid}/people`),

  // the moat — dispute-proof export
  evidencePack: async (pid, name) => {
    const b = await req(`/projects/${pid}/evidence.pdf`, { blob: true })
    const url = URL.createObjectURL(b)
    const a = document.createElement('a')
    a.href = url
    a.download = `evidence-${(name || 'project').replace(/\s+/g, '_')}.pdf`
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  },
}
