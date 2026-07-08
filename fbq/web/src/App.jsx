import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api'

const STATUS_TONE = { done: 'tone-green', in_progress: 'tone-blue', blocked: 'tone-red', pending: '' }

export default function App() {
  const [projects, setProjects] = useState([])
  const [sel, setSel] = useState(null)          // selected project id
  const [tab, setTab] = useState('plan')        // plan | inbox | activity
  const [err, setErr] = useState('')

  const refresh = useCallback(() => {
    api.projects().then((r) => {
      setProjects(r.projects)
      if (r.projects.length && sel === null) setSel(r.projects[0].id)
    }).catch((e) => setErr(e.message))
  }, [sel])
  useEffect(() => { refresh() }, [refresh])

  const project = projects.find((p) => p.id === sel)
  return (
    <div className="shell">
      <aside>
        <div className="brand">firstbriq</div>
        <NewProject onCreated={refresh} />
        <div className="proj-list">
          {projects.map((p) => (
            <button key={p.id} className={`proj ${p.id === sel ? 'active' : ''}`} onClick={() => setSel(p.id)}>
              <div className="proj-name">{p.name}</div>
              <div className="proj-sub">{p.tasks_done}/{p.tasks_total} tasks · {p.pct}%</div>
            </button>
          ))}
        </div>
      </aside>
      <main>
        {err && <div className="error">{err}</div>}
        {project && (
          <>
            <header>
              <h1>{project.name}</h1>
              <nav>
                {['plan', 'inbox', 'activity'].map((t) => (
                  <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
                ))}
              </nav>
            </header>
            {tab === 'plan' && <Plan pid={project.id} groupJid={project.group_jid} onLink={refresh} />}
            {tab === 'inbox' && <Inbox pid={project.id} />}
            {tab === 'activity' && <Activity pid={project.id} />}
          </>
        )}
        {!project && <div className="empty">Create a project to start.</div>}
      </main>
    </div>
  )
}

function NewProject({ onCreated }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [start, setStart] = useState(new Date().toISOString().slice(0, 10))
  const create = async () => {
    if (!name.trim()) return
    await api.createProject({ name: name.trim(), template_id: 'P3-MANUF-EXEC', start_date: start })
    setName(''); setOpen(false); onCreated()
  }
  if (!open) return <button className="btn-primary" onClick={() => setOpen(true)}>+ New project</button>
  return (
    <div className="new-proj">
      <input placeholder="Client / project name" value={name} onChange={(e) => setName(e.target.value)} />
      <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      <div className="row">
        <button className="btn-primary" onClick={create}>Create</button>
        <button onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  )
}

// F11 — plan view + edit (status / duration / owner); group link
function Plan({ pid, groupJid, onLink }) {
  const [plan, setPlan] = useState(null)
  const [gj, setGj] = useState(groupJid || '')
  const load = useCallback(() => api.plan(pid).then(setPlan).catch(() => {}), [pid])
  useEffect(() => { load() }, [load])

  const edit = async (tid, patch) => { await api.editTask(pid, tid, patch); load() }
  if (!plan) return <div className="empty">Loading…</div>
  const today = new Date().toISOString().slice(0, 10)
  return (
    <div>
      <div className="linkbar">
        <input placeholder="WhatsApp group JID (…@g.us)" value={gj} onChange={(e) => setGj(e.target.value)} />
        <button onClick={async () => { await api.linkGroup(pid, gj.trim()); onLink() }}>Link group</button>
      </div>
      <table>
        <thead>
          <tr><th>Task</th><th>Owner</th><th>Days</th><th>Start → End</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {plan.tasks.map((t) => (
            <tr key={t.task_id} className={t.status !== 'done' && t.end < today ? 'overdue' : ''}>
              <td>
                <div>{t.name}</div>
                <div className="sub">{t.milestone}{t.client_owned ? ' · client' : ''}</div>
              </td>
              <td>
                <input className="cell" defaultValue={t.owner_role}
                  onBlur={(e) => e.target.value !== t.owner_role && edit(t.task_id, { owner_role: e.target.value })} />
              </td>
              <td>
                <input className="cell num" type="number" min="1" defaultValue={t.duration_days}
                  onBlur={(e) => Number(e.target.value) !== t.duration_days && edit(t.task_id, { duration_days: Number(e.target.value) })} />
              </td>
              <td className="dates">{t.start} → {t.end}{t.actual_end ? ` (done ${t.actual_end})` : ''}</td>
              <td><span className={`pill ${STATUS_TONE[t.status] || ''}`}>{t.status}</span></td>
              <td>
                {t.status !== 'done' && (
                  <button className="btn-small" onClick={() => edit(t.task_id, { status: 'done' })}>done</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Lane-B inbox — pending confirms the group hasn't answered
function Inbox({ pid }) {
  const [items, setItems] = useState([])
  const load = useCallback(() => api.pending(pid).then((r) => setItems(r.pending)).catch(() => {}), [pid])
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])
  const decide = async (eid, status) => { await api.decide(eid, status); load() }
  if (!items.length) return <div className="empty">No pending confirmations. ✅</div>
  return (
    <div className="inbox">
      {items.map((e) => (
        <div key={e.id} className="card">
          <div className="card-head"><span className={`pill tone-amber`}>{e.type}</span>
            <span className="sub">conf {Math.round((e.confidence || 0) * 100)}% · {e.created_at}</span></div>
          <div className="card-body">
            {e.payload.task_hint}
            {e.payload.task_id && <span className="sub"> → task: {e.payload.task_id}</span>}
            {e.payload.due && <span className="sub"> · due {e.payload.due}</span>}
          </div>
          <div className="row">
            <button className="btn-primary" onClick={() => decide(e.id, 'confirmed')}>Confirm</button>
            <button onClick={() => decide(e.id, 'declined')}>Decline</button>
          </div>
        </div>
      ))}
    </div>
  )
}

// F12 — every agent write, with lane + actor + source
function Activity({ pid }) {
  const [acts, setActs] = useState([])
  useEffect(() => { api.activity(pid).then((r) => setActs(r.activity)).catch(() => {}) }, [pid])
  return (
    <table>
      <thead><tr><th>When</th><th>Action</th><th>Detail</th><th>By</th><th>Lane</th></tr></thead>
      <tbody>
        {acts.map((a) => (
          <tr key={a.id}>
            <td className="dates">{a.ts}</td>
            <td>{a.action}</td>
            <td>{a.detail}</td>
            <td>{a.actor}</td>
            <td>{a.lane && <span className={`pill ${a.lane === 'A' ? 'tone-green' : 'tone-amber'}`}>{a.lane}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
