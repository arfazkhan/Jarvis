import React, { useEffect, useState, useCallback } from 'react'
import { api } from './api'

const STATUS_TONE = { done: 'tone-green', in_progress: 'tone-blue', blocked: 'tone-red', pending: '' }
const TABS = ['plan', 'inbox', 'promises', 'approvals', 'brain', 'activity']
const today = () => new Date().toISOString().slice(0, 10)
const daysOver = (due) => (due ? Math.floor((new Date(today()) - new Date(due)) / 86400000) : 0)

export default function App() {
  const [projects, setProjects] = useState([])
  const [sel, setSel] = useState(null)
  const [tab, setTab] = useState('plan')
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
        <div className="brand-sub">AI Manager</div>
        <NewProject onCreated={refresh} />
        <div className="proj-list">
          {projects.map((p) => (
            <button key={p.id} className={`proj ${p.id === sel ? 'active' : ''}`} onClick={() => setSel(p.id)}>
              <div className="proj-name">{p.name}</div>
              <div className="proj-sub">{p.tasks_done}/{p.tasks_total} tasks · {p.pct}%</div>
              {!p.group_jid && <div className="warn-dot">no group linked</div>}
            </button>
          ))}
        </div>
      </aside>
      <main>
        {err && <div className="error">{err}</div>}
        {project && (
          <>
            <header>
              <div>
                <h1>{project.name}</h1>
                <div className="sub">{project.phase} · starts {project.start_date}</div>
              </div>
              <nav>
                {TABS.map((t) => (
                  <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
                ))}
              </nav>
            </header>
            {tab === 'plan' && <Plan pid={project.id} groupJid={project.group_jid} onLink={refresh} />}
            {tab === 'inbox' && <Inbox pid={project.id} />}
            {tab === 'promises' && <Promises pid={project.id} />}
            {tab === 'approvals' && <Approvals pid={project.id} name={project.name} />}
            {tab === 'brain' && <Brain pid={project.id} />}
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
  const [start, setStart] = useState(today())
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

// F11 — plan view + edit; group link; end-of-day
function Plan({ pid, groupJid, onLink }) {
  const [plan, setPlan] = useState(null)
  const [gj, setGj] = useState(groupJid || '')
  const [busy, setBusy] = useState('')
  const load = useCallback(() => api.plan(pid).then(setPlan).catch(() => {}), [pid])
  useEffect(() => { setGj(groupJid || ''); load() }, [load, groupJid])

  const edit = async (tid, patch) => { await api.editTask(pid, tid, patch); load() }
  if (!plan) return <div className="empty">Loading…</div>
  const t0 = today()
  return (
    <div>
      <div className="linkbar">
        <input placeholder="WhatsApp group JID (…@g.us)" value={gj} onChange={(e) => setGj(e.target.value)} />
        <button onClick={async () => { await api.linkGroup(pid, gj.trim()); onLink() }}>Link group</button>
        <div className="spacer" />
        <button disabled={!!busy} onClick={async () => {
          setBusy('day'); try { await api.closeDay(pid) } finally { setBusy('') }
        }}>{busy === 'day' ? 'Sending…' : 'Send end-of-day brief'}</button>
      </div>
      <table>
        <thead>
          <tr><th>Task</th><th>Owner</th><th>Days</th><th>Start → End</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {plan.tasks.map((t) => (
            <tr key={t.task_id} className={t.status !== 'done' && t.end < t0 ? 'overdue' : ''}>
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

// Lane-B inbox — what the group hasn't answered yet
function Inbox({ pid }) {
  const [items, setItems] = useState([])
  const load = useCallback(() => api.pending(pid).then((r) => setItems(r.pending)).catch(() => {}), [pid])
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])
  const decide = async (eid, status) => { await api.decide(eid, status); load() }
  if (!items.length) return <div className="empty">No pending confirmations. ✅</div>
  return (
    <div className="cards">
      {items.map((e) => (
        <div key={e.id} className="card">
          <div className="card-head">
            <span className="pill tone-amber">{e.type}</span>
            <span className="sub">confidence {Math.round((e.confidence || 0) * 100)}% · {e.created_at}</span>
          </div>
          <div className="card-body">
            {e.payload.task_hint}
            {e.payload.task_id && <span className="sub"> → {e.payload.task_id}</span>}
            {e.payload.due && <span className="sub"> · due {e.payload.due}</span>}
          </div>
          <div className="row">
            <button className="btn-primary auto" onClick={() => decide(e.id, 'confirmed')}>Confirm</button>
            <button onClick={() => decide(e.id, 'declined')}>Decline</button>
          </div>
        </div>
      ))}
    </div>
  )
}

// The promise ledger — who owes what, and how late
function Promises({ pid }) {
  const [cs, setCs] = useState([])
  useEffect(() => { api.commitments(pid).then((r) => setCs(r.commitments)).catch(() => {}) }, [pid])
  if (!cs.length) return <div className="empty">No open promises. 👌</div>
  return (
    <table>
      <thead><tr><th>Who</th><th>Promised</th><th>Made on</th><th>Due</th><th>Status</th><th>Nudges</th></tr></thead>
      <tbody>
        {cs.map((c) => {
          const over = daysOver(c.due_date)
          return (
            <tr key={c.id} className={over > 0 ? 'overdue' : ''}>
              <td><strong>{c.owner_name}</strong></td>
              <td>{c.text}</td>
              <td className="dates">{c.promised_on}</td>
              <td className="dates">{c.due_date}</td>
              <td>
                {over > 3 && <span className="pill tone-red">chronic · {over}d</span>}
                {over > 0 && over <= 3 && <span className="pill tone-amber">{over}d overdue</span>}
                {over === 0 && <span className="pill tone-blue">due today</span>}
                {over < 0 && <span className="pill">on track</span>}
              </td>
              <td className="sub">{c.nudges || 0}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// The evidence trail — the artefact you show an angry client
function Approvals({ pid, name }) {
  const [aps, setAps] = useState([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.approvals(pid).then((r) => setAps(r.approvals)).catch(() => {}) }, [pid])
  return (
    <div>
      <div className="linkbar">
        <div className="note">Every approval is kept with the message that proves it.</div>
        <div className="spacer" />
        <button className="btn-primary auto" disabled={busy} onClick={async () => {
          setBusy(true); try { await api.evidencePack(pid, name) } finally { setBusy(false) }
        }}>{busy ? 'Building…' : '⬇ Evidence pack (PDF)'}</button>
      </div>
      {!aps.length && <div className="empty">No approvals recorded yet.</div>}
      {!!aps.length && (
        <table>
          <thead><tr><th>#</th><th>When</th><th>Approved by</th><th>What was approved</th></tr></thead>
          <tbody>
            {aps.map((a) => (
              <tr key={a.id}>
                <td className="sub">#{a.id}</td>
                <td className="dates">{a.approved_on?.slice(0, 16)}</td>
                <td><strong>{a.approver_name}</strong></td>
                <td>“{a.text}”</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// The brain — what the project remembers, and search over everything ever said
function Brain({ pid }) {
  const [mems, setMems] = useState([])
  const [q, setQ] = useState('')
  const [ans, setAns] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const load = useCallback(() => api.memories(pid).then((r) => setMems(r.memories)).catch(() => {}), [pid])
  useEffect(() => { load() }, [load])

  const ask = async () => {
    if (!q.trim()) return
    setBusy(true)
    try { setAns(await api.recall(pid, q.trim())) } catch (e) { setAns({ answer: e.message, hits: [] }) }
    finally { setBusy(false) }
  }
  return (
    <div>
      <div className="linkbar">
        <input placeholder="Ask what the project remembers — “what did we say about the countertop?”"
          value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && ask()} />
        <button className="btn-primary auto" disabled={busy} onClick={ask}>{busy ? 'Thinking…' : 'Recall'}</button>
      </div>
      {ans && (
        <div className="card recall">
          <div className="card-body">{ans.answer}</div>
          {!!ans.hits?.length && (
            <div className="hits">
              {ans.hits.map((h, i) => (
                <div key={i} className="hit">
                  <span className="sub">[{(h.ts || '').slice(0, 10)}] {h.who || '?'}
                    {h.kind === 'memory' ? ' · memory' : ''}</span> {h.text}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="linkbar mt">
        <input placeholder="Teach it something — stored forever" value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={async (e) => {
            if (e.key === 'Enter' && note.trim()) { await api.addMemory(pid, note.trim()); setNote(''); load() }
          }} />
        <button onClick={async () => { if (note.trim()) { await api.addMemory(pid, note.trim()); setNote(''); load() } }}>
          Remember
        </button>
      </div>

      {!mems.length && <div className="empty">Nothing remembered yet.</div>}
      {!!mems.length && (
        <table>
          <thead><tr><th>When</th><th>Source</th><th>Memory</th><th>From</th></tr></thead>
          <tbody>
            {mems.map((m) => (
              <tr key={m.id}>
                <td className="dates">{(m.ref_date || m.ts || '').slice(0, 10)}</td>
                <td><span className="pill">{m.source}</span></td>
                <td className="pre">{m.text}</td>
                <td className="sub">{m.sender}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// F12 — every agent write, with lane + actor
function Activity({ pid }) {
  const [acts, setActs] = useState([])
  useEffect(() => { api.activity(pid).then((r) => setActs(r.activity)).catch(() => {}) }, [pid])
  if (!acts.length) return <div className="empty">Nothing yet.</div>
  return (
    <table>
      <thead><tr><th>When</th><th>Action</th><th>Detail</th><th>By</th><th>Lane</th></tr></thead>
      <tbody>
        {acts.map((a) => (
          <tr key={a.id}>
            <td className="dates">{a.ts?.slice(0, 16)}</td>
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
