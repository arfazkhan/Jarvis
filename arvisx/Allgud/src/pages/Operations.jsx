import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ClipboardList,
  CalendarDays,
  ShieldAlert,
  Clock,
  Sparkles,
  CircleDot,
  Timer,
  CheckCircle2,
  UserPlus,
  PlayCircle,
  TriangleAlert,
  PenLine,
  ChevronRight,
  X,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, ProgressBar, Avatar, Drawer, Spinner, Empty } from '../components/ui'
import { CreateIssueDrawer } from './Issues'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'
import { useAuth } from '../lib/AuthContext'

// PPM schedule statuses (date/condition based)
const PPM_STYLE = {
  overdue: { label: 'Overdue', tone: 'red' },
  due_soon: { label: 'Due Soon', tone: 'amber' },
  ok: { label: 'Scheduled', tone: 'blue' },
  unscheduled: { label: 'Unscheduled', tone: 'neutral' },
}

// Derive UI status from a run per §7:
// Scheduled=future date · Open=open/0 entries · In Progress=open/some ·
// Review=submitted, signoffs pending · Complete=submitted+signed.
function deriveRunStatus(run, today) {
  const isFuture = run.shift_date && run.shift_date > today
  if (run.status === 'lapsed') return { label: 'Lapsed', tone: 'red' }
  if (run.status === 'submitted') {
    return (run.signoffs?.length || 0) > 0
      ? { label: 'Complete', tone: 'green' }
      : { label: 'Review', tone: 'purple' }
  }
  // open
  if (isFuture) return { label: 'Scheduled', tone: 'blue' }
  if ((run.completion_pct || 0) === 0) return { label: 'Open', tone: 'amber' }
  return { label: 'In Progress', tone: 'blue' }
}

export default function Operations() {
  const navigate = useNavigate()
  const { building } = useBuilding()
  const [drawer, setDrawer] = useState(null) // assign | start | signoff | issue
  const [ppmRow, setPpmRow] = useState(null) // selected PPM schedule row
  const [refreshKey, setRefreshKey] = useState(0)
  const refresh = () => setRefreshKey((k) => k + 1)
  const today = useAsync(() => api.today(building), [building, refreshKey])
  const ppm = useAsync(() => api.ppmSchedule(building), [building, refreshKey])
  const issues = useAsync(() => api.issues(building, 'open'), [building, refreshKey])
  const techs = useAsync(() => api.technicians(building), [building, refreshKey])
  const techList = techs.data?.technicians || []

  const rows = useMemo(() => buildRows(today.data, ppm.data), [today.data, ppm.data])
  const openIssues = issues.data?.issues || []

  const counts = useMemo(() => {
    const total = rows.length
    const inProgress = rows.filter((r) => r.status === 'In Progress').length
    const review = rows.filter((r) => r.status === 'Review').length
    const completed = rows.filter((r) => r.status === 'Complete').length
    return { total, inProgress, review, completed }
  }, [rows])

  return (
    <div>
      <PageHeader subtitle="Real-time view of all building operations" />

      <div className="grid grid-cols-[1fr_340px]">
        <div className="px-10 pt-6">
          <div className="flex items-center justify-between mb-5">
            <div className="text-2xl font-serif text-text">{rows.length} Active Operations</div>
            <button
              onClick={async () => { try { await api.openToday(building); refresh() } catch (e) { alert(e.message) } }}
              className="flex items-center gap-2 text-sm border border-border rounded-lg px-3 py-2 text-text-dim hover:border-gold/40"
              title="Open today's recurring shifts (carries forward the usual technician)"
            >
              <CalendarDays className="w-4 h-4" /> Open today's rounds
            </button>
          </div>

          <table className="w-full text-left">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-text-faint border-b border-border-soft">
                <th className="py-3 font-normal">Operation</th>
                <th className="py-3 font-normal">Assignee</th>
                <th className="py-3 font-normal">Status</th>
                <th className="py-3 font-normal">Progress</th>
                <th className="py-3 font-normal">Updated</th>
                <th className="py-3 font-normal w-6" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={i}
                  onClick={() => (r.kind === 'ppm' ? setPpmRow(r) : r.runId && navigate(`/operations/round/${r.runId}`))}
                  className="border-b border-border-soft hover:bg-surface/60 cursor-pointer transition-colors"
                >
                  <td className="py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-surface-2 border border-border flex items-center justify-center text-gold-soft">
                        {r.kind === 'ppm' ? <CalendarDays className="w-4 h-4" /> : <ClipboardList className="w-4 h-4" />}
                      </div>
                      <div>
                        <div className="text-sm text-text">{r.name}</div>
                        <div className="text-xs text-text-faint">{r.subtitle}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-4">
                    {r.runId ? (
                      <AssigneeCell runId={r.runId} current={r.assignee} techs={techList} onChanged={refresh} />
                    ) : (
                      <div className="flex items-center gap-2">
                        <Avatar name={r.assignee} />
                        <div>
                          <div className="text-sm text-text">{r.assignee || '—'}</div>
                          <div className="text-xs text-text-faint">{r.role}</div>
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="py-4">
                    <Pill tone={r.statusTone}>{r.status}</Pill>
                  </td>
                  <td className="py-4 w-40">
                    {r.total ? (
                      <>
                        <div className="text-sm text-text mb-1">{r.pct}%</div>
                        <ProgressBar pct={r.pct} tone={r.statusTone} className="w-32" />
                        <div className="text-xs text-text-faint mt-1">
                          {r.done} / {r.total} items
                        </div>
                      </>
                    ) : (
                      <span className="text-text-faint text-sm">—</span>
                    )}
                  </td>
                  <td className="py-4 text-sm text-text-faint">{r.updated}</td>
                  <td className="py-4 text-text-faint">
                    <ChevronRight className="w-4 h-4" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="px-6 pt-6 border-l border-border-soft">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-4">
            Attention
            <span className="bg-red text-bg text-[11px] font-semibold rounded-full px-2 py-0.5">
              {openIssues.length}
            </span>
          </div>

          <div className="flex flex-col gap-4 mb-8">
            {rows
              .filter((r) => r.runId && r.pct < 100)
              .slice(0, 1)
              .map((r, i) => (
                <AttentionItem
                  key={'r' + i}
                  tone="amber"
                  icon={TriangleAlert}
                  title={`${r.name} incomplete`}
                  detail={`${r.total - r.done} items remaining`}
                  sub={r.assignee}
                  onClick={() => navigate(`/operations/round/${r.runId}`)}
                />
              ))}
            {openIssues.slice(0, 1).map((iss) => (
              <AttentionItem
                key={iss.id}
                tone="red"
                icon={ShieldAlert}
                title={`${iss.asset} issue open`}
                detail="SLA breached"
                sub={iss.assignee || iss.vendor || 'Unassigned'}
                onClick={() => navigate('/issues')}
              />
            ))}
            <AttentionItem
              tone="blue"
              icon={Clock}
              title="Sign-offs pending"
              detail="Supervisor approval"
              sub={rows.filter((r) => r.total && r.pct < 100).map((r) => r.shortName).join(', ') || '—'}
              onClick={() => setDrawer('signoff')}
            />
          </div>

          <div className="text-xs uppercase tracking-wide text-text-faint mb-4">Today's Context</div>
          <div className="flex flex-col gap-3 text-sm">
            <ContextRow icon={Sparkles} label="Total operations" value={counts.total} />
            <ContextRow icon={CircleDot} label="In progress" value={counts.inProgress} />
            <ContextRow icon={Timer} label="Awaiting review" value={counts.review} />
            <ContextRow icon={CheckCircle2} label="Completed" value={counts.completed} />
            <button onClick={() => navigate('/operations/calendar')} className="flex items-center justify-between text-gold mt-1">
              <span className="flex items-center gap-2">
                <CalendarDays className="w-4 h-4" /> View calendar
              </span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 mt-10 border-t border-border bg-bg/95 backdrop-blur px-10 py-4 grid grid-cols-5 gap-4">
        <ActionButton icon={UserPlus} title="Assign Round" sub="Assign to technician" onClick={() => setDrawer('assign')} />
        <ActionButton icon={PlayCircle} title="Start Inspection" sub="Begin a checklist" onClick={() => setDrawer('start')} />
        <ActionButton icon={TriangleAlert} title="Create Issue" sub="Log an observation" onClick={() => setDrawer('issue')} />
        <ActionButton icon={PenLine} title="Request Sign-off" sub="Approve a round" onClick={() => setDrawer('signoff')} />
        <ActionButton icon={Sparkles} title="Ask Arvis" sub="Get instant help" onClick={() => navigate('/intelligence')} />
      </div>

      <AssignRoundDrawer open={drawer === 'assign'} onClose={() => setDrawer(null)} building={building}
        onDone={() => { refresh(); setDrawer(null) }} />
      <StartInspectionDrawer open={drawer === 'start'} onClose={() => setDrawer(null)} building={building}
        onStarted={(rid) => { setDrawer(null); navigate(`/operations/round/${rid}`) }} />
      <CreateIssueDrawer open={drawer === 'issue'} onClose={() => setDrawer(null)} building={building}
        onCreated={() => { refresh(); setDrawer(null) }} />
      <SignoffDrawer open={drawer === 'signoff'} onClose={() => setDrawer(null)} building={building}
        onDone={() => { refresh(); setDrawer(null) }} />
      <PpmDrawer row={ppmRow} onClose={() => setPpmRow(null)} building={building}
        onAssigned={(rid) => { setPpmRow(null); navigate(`/operations/round/${rid}`) }}
        onLogged={() => { refresh(); setPpmRow(null) }} />
    </div>
  )
}

function PpmDrawer({ row, onClose, building, onAssigned, onLogged }) {
  const tpls = useTemplates(building)
  const techs = useAsync(() => api.technicians(building), [building])
  const [tid, setTid] = useState('')
  const [tech, setTech] = useState('')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [busy, setBusy] = useState(false)
  if (!row) return null
  const ppmTemplates = (tpls.data?.templates || []).filter((t) => t.cadence !== 'daily')
  const techlist = techs.data?.technicians || []

  async function assign() {
    if (!tid || !tech) return
    setBusy(true)
    try {
      const r = await api.startRun({ building, template_id: tid, asset: row.asset, technician: tech, assignee: tech })
      onAssigned(r.run.id)
    } catch (e) { alert(e.message) } finally { setBusy(false) }
  }
  async function logDone() {
    setBusy(true)
    try { await api.ppmDone(row.asset, { date, building }); onLogged() }
    catch (e) { alert(e.message) } finally { setBusy(false) }
  }

  return (
    <Drawer open={!!row} onClose={onClose} width={420}>
      <div className="p-6">
        <div className="flex items-center justify-between mb-1">
          <div className="font-serif text-xl text-text">{row.asset} — PPM</div>
          <button onClick={onClose} className="text-text-faint"><X className="w-5 h-5" /></button>
        </div>
        <div className="text-xs text-text-faint mb-6">{row.status} · due {row.updated}</div>

        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Assign as a maintenance round</div>
        <div className="flex flex-col gap-3 mb-3">
          <SelectField label="PPM checklist" value={tid} onChange={setTid}
            options={ppmTemplates.map((t) => ({ value: t.template_id, label: t.name }))} />
          <SelectField label="Technician" value={tech} onChange={setTech}
            options={techlist.map((t) => ({ value: t.name, label: t.phone ? `${t.name} (${t.phone})` : t.name }))} />
          <button disabled={busy || !tid || !tech} onClick={assign}
            className="bg-primary text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50">
            Assign + notify
          </button>
          <div className="text-xs text-text-faint">Submitting the round auto-marks this PPM done.</div>
        </div>

        <div className="border-t border-border-soft my-5" />
        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Or log external service done</div>
        <div className="flex items-end gap-2">
          <label className="flex-1 flex flex-col gap-1 text-xs text-text-faint">Service date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
              className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50" />
          </label>
          <button disabled={busy} onClick={logDone}
            className="border border-green/40 text-green rounded-lg px-3 py-2.5 text-sm disabled:opacity-50">Log done</button>
        </div>
      </div>
    </Drawer>
  )
}

function useTemplates(building) {
  return useAsync(() => api.templates(building), [building])
}

function AssignRoundDrawer({ open, onClose, building, onDone }) {
  const tpls = useTemplates(building)
  const techs = useAsync(() => api.technicians(building), [building])
  const [tid, setTid] = useState('')
  const [tech, setTech] = useState('')
  const [busy, setBusy] = useState(false)
  const tlist = tpls.data?.templates || []
  const techlist = techs.data?.technicians || []
  async function submit() {
    if (!tid || !tech) return
    setBusy(true)
    try { await api.startRun({ building, template_id: tid, technician: tech, assignee: tech }); onDone() }
    catch (e) { alert(e.message) } finally { setBusy(false) }
  }
  return (
    <FormDrawer open={open} onClose={onClose} title="Assign Round" busy={busy} onSubmit={submit} cta="Assign + notify">
      <SelectField label="Checklist" value={tid} onChange={setTid}
        options={tlist.map((t) => ({ value: t.template_id, label: t.name }))} />
      <SelectField label="Technician" value={tech} onChange={setTech}
        options={techlist.map((t) => ({ value: t.name, label: t.phone ? `${t.name} (${t.phone})` : t.name }))} />
      <div className="text-xs text-text-faint">Assigning sends the technician a WhatsApp link to the round.</div>
    </FormDrawer>
  )
}

function StartInspectionDrawer({ open, onClose, building, onStarted }) {
  const tpls = useTemplates(building)
  const [tid, setTid] = useState('')
  const [busy, setBusy] = useState(false)
  const tlist = tpls.data?.templates || []
  async function submit() {
    if (!tid) return
    setBusy(true)
    try { const r = await api.startRun({ building, template_id: tid }); onStarted(r.run.id) }
    catch (e) { alert(e.message) } finally { setBusy(false) }
  }
  return (
    <FormDrawer open={open} onClose={onClose} title="Start Inspection" busy={busy} onSubmit={submit} cta="Start">
      <SelectField label="Checklist" value={tid} onChange={setTid}
        options={tlist.map((t) => ({ value: t.template_id, label: t.name }))} />
    </FormDrawer>
  )
}

function SignoffDrawer({ open, onClose, building, onDone }) {
  const { username } = useAuth()
  const today = useAsync(() => (open ? api.today(building) : Promise.resolve(null)), [building, open])
  const [busy, setBusy] = useState('')
  const [role, setRole] = useState('supervisor')
  const runs = (today.data?.runs || []).filter((r) => r.status === 'submitted')
  async function sign(rid) {
    setBusy(rid)
    try { await api.signoff(rid, { role, by: username || 'manager' }); onDone() }
    catch (e) { alert(e.message) } finally { setBusy('') }
  }
  return (
    <Drawer open={open} onClose={onClose} width={420}>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="font-serif text-xl text-text">Sign off rounds</div>
          <button onClick={onClose} className="text-text-faint"><X className="w-5 h-5" /></button>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-faint mb-4">
          Signing as
          <select value={role} onChange={(e) => setRole(e.target.value)}
            className="bg-surface border border-border rounded-lg px-2 py-1.5 text-sm text-text outline-none focus:border-gold/50">
            <option value="supervisor">supervisor</option>
            <option value="technician">technician</option>
            <option value="manager">manager</option>
          </select>
          <span className="text-text">{username || 'manager'}</span>
        </label>
        {today.loading ? <Spinner /> : runs.length === 0 ? <Empty>No submitted rounds awaiting sign-off.</Empty> : (
          <div className="flex flex-col gap-2">
            {runs.map((r) => (
              <div key={r.run_id} className="flex items-center justify-between border border-border-soft rounded-xl px-4 py-3">
                <div>
                  <div className="text-sm text-text">{r.name}</div>
                  <div className="text-xs text-text-faint">{r.assignee || r.technician} · {r.signoffs?.length || 0} signoff(s)</div>
                </div>
                <button disabled={busy === r.run_id} onClick={() => sign(r.run_id)}
                  className="text-xs border border-green/40 text-green rounded-lg px-3 py-1.5 disabled:opacity-50">
                  Sign off
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </Drawer>
  )
}

function FormDrawer({ open, onClose, title, busy, onSubmit, cta, children }) {
  return (
    <Drawer open={open} onClose={onClose} width={420}>
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="font-serif text-xl text-text">{title}</div>
          <button onClick={onClose} className="text-text-faint"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex flex-col gap-4">
          {children}
          <button disabled={busy} onClick={onSubmit}
            className="bg-primary text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50">
            {cta}
          </button>
        </div>
      </div>
    </Drawer>
  )
}

function SelectField({ label, value, onChange, options }) {
  return (
    <label className="block">
      <div className="text-xs text-text-faint mb-1">{label}</div>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50">
        <option value="">Select…</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )
}

function buildRows(today, ppm) {
  const rows = []
  const todayStr = today?.date || new Date().toISOString().slice(0, 10)
  for (const r of today?.runs || []) {
    const st = deriveRunStatus(r, todayStr)
    rows.push({
      kind: 'round',
      runId: r.run_id,
      name: r.name,
      shortName: r.name?.split(' ')[0] + ' ' + (r.name?.split(' ')[1] || ''),
      subtitle: 'Daily Checklist · All Assets',
      assignee: r.assignee || r.technician,
      role: 'Technician',
      status: st.label,
      statusTone: st.tone,
      total: 1,
      done: r.completion_pct === 100 ? 1 : 0,
      pct: r.completion_pct,
      updated: 'today',
    })
  }
  for (const p of ppm?.schedules || []) {
    rows.push({
      kind: 'ppm',
      runId: null,
      asset: p.asset,
      name: `${p.asset} PPM`,
      subtitle: `PPM Schedule · ${p.asset}`,
      assignee: '',
      role: 'Vendor',
      status: PPM_STYLE[p.status]?.label || p.status,
      statusTone: PPM_STYLE[p.status]?.tone || 'neutral',
      total: 0,
      done: 0,
      pct: 0,
      updated: p.due_date || '—',
    })
  }
  return rows
}

function AssigneeCell({ runId, current, techs, onChanged }) {
  const [busy, setBusy] = useState(false)
  async function change(name) {
    setBusy(true)
    try { await api.assign(runId, { assignee: name }); onChanged() }
    catch (e) { alert(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
      <Avatar name={current} />
      <select
        value={current || ''} disabled={busy} onChange={(e) => change(e.target.value)}
        className="bg-surface border border-border rounded-lg px-2 py-1.5 text-sm text-text outline-none focus:border-gold/50 disabled:opacity-50"
        title="Reassign this round"
      >
        <option value="">Unassigned</option>
        {techs.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
      </select>
    </div>
  )
}

function AttentionItem({ tone, icon: Icon, title, detail, sub, onClick }) {
  const toneText = { amber: 'text-amber', red: 'text-red', blue: 'text-blue' }[tone]
  const toneBg = { amber: 'bg-amber-bg', red: 'bg-red-bg', blue: 'bg-blue-bg' }[tone]
  return (
    <button onClick={onClick} disabled={!onClick} className="flex items-start gap-3 text-left w-full disabled:cursor-default enabled:hover:opacity-80">
      <div className={`w-9 h-9 rounded-full flex items-center justify-center ${toneBg} ${toneText}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <div className="text-sm text-text">{title}</div>
        <div className={`text-xs ${toneText}`}>{detail}</div>
        <div className="text-xs text-text-faint">{sub}</div>
      </div>
    </button>
  )
}

function ContextRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center justify-between text-text-dim">
      <span className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-gold" />
        {label}
      </span>
      <span className="text-text">{value}</span>
    </div>
  )
}

function ActionButton({ icon: Icon, title, sub, onClick }) {
  return (
    <button onClick={onClick} className="flex items-center gap-3 bg-surface border border-border rounded-xl px-4 py-3 hover:border-gold/40 transition-colors text-left">
      <Icon className="w-5 h-5 text-gold" />
      <div>
        <div className="text-sm text-text">{title}</div>
        <div className="text-xs text-text-faint">{sub}</div>
      </div>
    </button>
  )
}
