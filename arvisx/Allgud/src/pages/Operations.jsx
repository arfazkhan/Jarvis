import { useMemo } from 'react'
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
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, ProgressBar, Avatar } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

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
  const today = useAsync(() => api.today(building), [building])
  const ppm = useAsync(() => api.ppmSchedule(building), [building])
  const issues = useAsync(() => api.issues(building, 'open'), [building])

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
          <div className="text-2xl font-serif text-text mb-5">{rows.length} Active Operations</div>

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
                  onClick={() => r.runId && navigate(`/operations/round/${r.runId}`)}
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
                    <div className="flex items-center gap-2">
                      <Avatar name={r.assignee} />
                      <div>
                        <div className="text-sm text-text">{r.assignee || '—'}</div>
                        <div className="text-xs text-text-faint">{r.role}</div>
                      </div>
                    </div>
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
              .filter((r) => r.total && r.pct < 100)
              .slice(0, 1)
              .map((r, i) => (
                <AttentionItem
                  key={'r' + i}
                  tone="amber"
                  icon={TriangleAlert}
                  title={`${r.name} incomplete`}
                  detail={`${r.total - r.done} items remaining`}
                  sub={r.assignee}
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
              />
            ))}
            <AttentionItem
              tone="blue"
              icon={Clock}
              title="Sign-offs pending"
              detail="Supervisor approval"
              sub={rows.filter((r) => r.total && r.pct < 100).map((r) => r.shortName).join(', ') || '—'}
            />
          </div>

          <div className="text-xs uppercase tracking-wide text-text-faint mb-4">Today's Context</div>
          <div className="flex flex-col gap-3 text-sm">
            <ContextRow icon={Sparkles} label="Total operations" value={counts.total} />
            <ContextRow icon={CircleDot} label="In progress" value={counts.inProgress} />
            <ContextRow icon={Timer} label="Awaiting review" value={counts.review} />
            <ContextRow icon={CheckCircle2} label="Completed" value={counts.completed} />
            <button className="flex items-center justify-between text-gold mt-1">
              <span className="flex items-center gap-2">
                <CalendarDays className="w-4 h-4" /> View calendar
              </span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 mt-10 border-t border-border bg-bg/95 backdrop-blur px-10 py-4 grid grid-cols-5 gap-4">
        <ActionButton icon={UserPlus} title="Assign Round" sub="Assign to technician" />
        <ActionButton icon={PlayCircle} title="Start Inspection" sub="Begin a checklist" />
        <ActionButton icon={TriangleAlert} title="Create Issue" sub="Log an observation" />
        <ActionButton icon={PenLine} title="Request Sign-off" sub="Ask for approval" />
        <ActionButton icon={Sparkles} title="Ask Arvis" sub="Get instant help" />
      </div>
    </div>
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

function AttentionItem({ tone, icon: Icon, title, detail, sub }) {
  const toneText = { amber: 'text-amber', red: 'text-red', blue: 'text-blue' }[tone]
  const toneBg = { amber: 'bg-amber-bg', red: 'bg-red-bg', blue: 'bg-blue-bg' }[tone]
  return (
    <div className="flex items-start gap-3">
      <div className={`w-9 h-9 rounded-full flex items-center justify-center ${toneBg} ${toneText}`}>
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <div className="text-sm text-text">{title}</div>
        <div className={`text-xs ${toneText}`}>{detail}</div>
        <div className="text-xs text-text-faint">{sub}</div>
      </div>
    </div>
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

function ActionButton({ icon: Icon, title, sub }) {
  return (
    <button className="flex items-center gap-3 bg-surface border border-border rounded-xl px-4 py-3 hover:border-gold/40 transition-colors text-left">
      <Icon className="w-5 h-5 text-gold" />
      <div>
        <div className="text-sm text-text">{title}</div>
        <div className="text-xs text-text-faint">{sub}</div>
      </div>
    </button>
  )
}
