import { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Building2,
  CalendarDays,
  User,
  Clock,
  Droplets,
  Zap,
  ShieldCheck,
  Flame,
  Wind,
  ClipboardList,
  Repeat,
  Sparkles,
  CheckCircle2,
  TriangleAlert,
  TrendingUp,
  Radio,
  Shield,
  PlayCircle,
  FileText,
  ChevronRight,
} from 'lucide-react'
import { Card, Pill } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

export default function RoundDetail() {
  const { rid } = useParams()
  const navigate = useNavigate()
  const { current, building } = useBuilding()
  const runView = useAsync(() => api.getRun(rid), [rid])
  const review = useAsync(() => api.review(rid), [rid])
  const watchlist = useAsync(() => api.watchlist(building), [building])
  const ppm = useAsync(() => api.ppmSchedule(building), [building])

  const run = runView.data?.run
  const template = runView.data?.template
  const summary = runView.data?.summary
  const signoffs = runView.data?.signoffs || []

  const sections = useMemo(() => buildSections(template, runView.data?.entries), [template, runView.data])
  const attention = useMemo(() => buildAttention(review.data, summary), [review.data, summary])

  if (runView.loading) return <div className="px-10 py-16 text-text-faint text-sm">Loading round…</div>
  if (!run) return <div className="px-10 py-16 text-text-faint text-sm">Round not found.</div>

  const overdue = ppm.data?.schedules?.find((p) => p.overdue)
  const watch = watchlist.data?.watchlist?.[0]

  return (
    <div>
      <div className="px-10 pt-6 flex items-center justify-between">
        <div className="text-sm text-text-faint">
          Operations / Rounds / <span className="text-text-dim">#{rid}</span>
        </div>
        <button className="text-sm border border-border rounded-lg px-3 py-1.5 text-text-dim">Run #{rid}</button>
      </div>

      <div className="px-10 pt-2 grid grid-cols-[1fr_320px] gap-10">
        <div>
          <div className="text-3xl font-serif text-text">{template?.name}</div>
          <div className="flex items-center gap-2 text-sm text-text-faint mt-2">
            <Building2 className="w-4 h-4" /> {current?.name}
            <CalendarDays className="w-4 h-4 ml-2" /> {run.shift_date}
          </div>

          <div className="grid grid-cols-2 gap-10 mt-8 pb-8 border-b border-border-soft">
            <div>
              <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Status</div>
              <div className="text-2xl text-amber font-medium mb-1">{statusLabel(run.status)}</div>
              <div className="font-serif text-5xl text-text">
                {summary?.completion_pct}
                <span className="text-2xl text-text-faint"> % Complete</span>
              </div>
              <div className="flex flex-col gap-1 mt-4 text-sm text-text-dim">
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4" /> Assigned → <span className="text-text">{run.assignee}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4" /> Started → <span className="text-text">{fmtTime(run.started_at)}</span>
                </div>
              </div>
            </div>

            <div>
              <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Round Progress</div>
              <Timeline run={run} summary={summary} signoffs={signoffs} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-10 mt-8">
            <div>
              <div className="flex items-center justify-between mb-3 text-xs uppercase tracking-wide text-text-faint">
                Areas in this round
              </div>
              <div className="flex flex-col gap-1">
                {sections.map((s, i) => {
                  const Icon = s.icon
                  return (
                    <div key={i} className="flex items-center justify-between py-3 border-b border-border-soft">
                      <div className="flex items-center gap-3">
                        <Icon className="w-4 h-4 text-text-dim" />
                        <div>
                          <div className="text-sm text-text">{s.name}</div>
                          <div className="text-xs text-text-faint">{s.total} checks</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 text-sm text-text-dim">
                        {s.done} / {s.total} <ChevronRight className="w-4 h-4" />
                      </div>
                    </div>
                  )
                })}
              </div>
              <button className="flex items-center gap-1 text-sm text-gold mt-3">
                View all checks <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-wide text-text-faint">
                Attention Required
                <span className="bg-red text-bg text-[11px] font-semibold rounded-full px-2 py-0.5">
                  {attention.length}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                {attention.map((a, i) => {
                  const Icon = a.icon
                  return (
                    <div key={i} className="flex items-center justify-between py-3 border-b border-border-soft">
                      <div className="flex items-center gap-3">
                        <span className={`w-9 h-9 rounded-full flex items-center justify-center ${a.bg} ${a.text}`}>
                          <Icon className="w-4 h-4" />
                        </span>
                        <div>
                          <div className="text-sm text-text">{a.title}</div>
                          <div className="text-xs text-text-faint">{a.detail}</div>
                        </div>
                      </div>
                      <Pill tone={a.tone}>{a.badge}</Pill>
                    </div>
                  )
                })}
                {attention.length === 0 && <div className="text-sm text-text-faint py-3">All clear.</div>}
              </div>
              <button className="flex items-center gap-1 text-sm text-gold mt-3">
                View all issues <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <Card className="p-4">
            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Today's Context</div>
            {watch && (
              <ContextEntry icon={Radio} title={`${watch.asset} on watchlist`} sub={`${watch.concern} concern`} tone="red" />
            )}
            {attention.length > 0 && (
              <ContextEntry icon={Shield} title={`${attention.length} unresolved issue(s)`} sub="Need action" tone="amber" />
            )}
            {overdue && (
              <ContextEntry
                icon={CalendarDays}
                title="1 overdue PPM"
                sub={`${overdue.asset} · ${Math.abs(overdue.days_remaining)} days overdue`}
                tone="purple"
              />
            )}
          </Card>

          <Card className="p-4">
            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Round Details</div>
            <DetailRow icon={ClipboardList} label="Template" value={template?.name} />
            <DetailRow icon={Repeat} label="Cadence" value={template?.cadence} />
            <DetailRow icon={Clock} label="Started" value={fmtTime(run.started_at)} />
            <DetailRow icon={Sparkles} label="Total Checks" value={summary?.total} />
            <DetailRow icon={CheckCircle2} label="Completed" value={summary?.done} />
            <DetailRow icon={TriangleAlert} label="Issues Raised" value={summary?.issues?.length || 0} />
            <div className="mt-2">
              <div className="text-xs text-text-faint mb-2">
                Signoffs <span className="text-text">{signoffs.length} / {template?.signoff_roles?.length}</span>
              </div>
              <div className="flex gap-1">
                {template?.signoff_roles?.map((role) => (
                  <span
                    key={role}
                    className={`w-7 h-7 rounded-full text-[10px] flex items-center justify-center border ${
                      signoffs.find((s) => s.role === role)
                        ? 'bg-green-bg text-green border-green/30'
                        : 'border-border text-text-faint'
                    }`}
                  >
                    {role.slice(0, 2).toUpperCase()}
                  </span>
                ))}
              </div>
            </div>
          </Card>
        </div>
      </div>

      <div className="sticky bottom-0 mt-10 border-t border-border bg-bg/95 backdrop-blur px-10 py-4 grid grid-cols-3 gap-4">
        <button
          onClick={() => navigate(`/operations/round/${rid}/check/0`)}
          className="flex items-center gap-3 bg-amber-bg border border-amber/30 rounded-xl px-4 py-3 text-left"
        >
          <PlayCircle className="w-5 h-5 text-amber" />
          <div>
            <div className="text-sm text-amber">Resume Inspection</div>
            <div className="text-xs text-text-faint">Continue where you left off</div>
          </div>
        </button>
        <button className="flex items-center gap-3 bg-surface border border-border rounded-xl px-4 py-3 text-left">
          <FileText className="w-5 h-5 text-text-dim" />
          <div>
            <div className="text-sm text-text">Review Entries</div>
            <div className="text-xs text-text-faint">See all recorded checks</div>
          </div>
        </button>
        <button className="flex items-center gap-3 bg-surface border border-border rounded-xl px-4 py-3 text-left">
          <TriangleAlert className="w-5 h-5 text-text-dim" />
          <div>
            <div className="text-sm text-text">View Issues</div>
            <div className="text-xs text-text-faint">{attention.length} issues need attention</div>
          </div>
        </button>
      </div>
    </div>
  )
}

function Timeline({ run, summary, signoffs }) {
  const steps = [
    { label: 'Started', sub: `${fmtTime(run.started_at)} by ${run.technician}`, done: true },
    { label: `${summary?.done ?? 0} Checks Complete`, sub: 'In progress', done: (summary?.done ?? 0) > 0 },
    { label: `${summary?.issues?.length ?? 0} Issues Raised`, sub: 'Requires attention', done: (summary?.issues?.length ?? 0) > 0 },
    { label: 'Supervisor Review', sub: 'Pending', done: signoffs.find((s) => s.role === 'supervisor') },
    { label: 'Signoff', sub: 'Pending', done: run.status === 'submitted' },
  ]
  return (
    <div className="relative pl-5">
      <div className="absolute left-[3px] top-2 bottom-2 w-px bg-border" />
      <div className="flex flex-col gap-5">
        {steps.map((s, i) => (
          <div key={i} className="relative">
            <span
              className={`absolute -left-5 top-1 w-2 h-2 rounded-full ${s.done ? 'bg-amber' : 'bg-border'}`}
            />
            <div className={`text-sm ${s.done ? 'text-text' : 'text-text-faint'}`}>{s.label}</div>
            <div className="text-xs text-text-faint">{s.sub}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ContextEntry({ icon: Icon, title, sub, tone }) {
  const text = { red: 'text-red', amber: 'text-amber', purple: 'text-purple' }[tone]
  return (
    <div className="flex items-center gap-3 py-2">
      <Icon className={`w-5 h-5 ${text}`} />
      <div>
        <div className="text-sm text-text">{title}</div>
        <div className={`text-xs ${text}`}>{sub}</div>
      </div>
    </div>
  )
}

function DetailRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="flex items-center gap-2 text-text-faint">
        <Icon className="w-4 h-4" /> {label}
      </span>
      <span className="text-text">{value ?? '—'}</span>
    </div>
  )
}

function statusLabel(status) {
  return { open: 'In Progress', submitted: 'Submitted', lapsed: 'Lapsed' }[status] || status
}

function fmtTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

const SECTION_ICONS = [Droplets, Zap, ShieldCheck, Flame, Wind]

function buildSections(template, entries) {
  if (!template?.sections) return []
  return template.sections.map((sec, i) => {
    const total = sec.items.length
    const done = sec.items.filter((it) => entries?.[it.item_id]).length
    return { name: sec.name, total, done, icon: SECTION_ICONS[i % SECTION_ICONS.length] }
  })
}

function buildAttention(review, summary) {
  const out = []
  for (const m of review?.missing || []) {
    out.push({ icon: Clock, text: 'text-blue', bg: 'bg-blue-bg', tone: 'blue', title: m.label, detail: 'Not inspected yet', badge: 'Pending' })
  }
  for (const f of review?.flagged_issues || summary?.issues || []) {
    out.push({ icon: TriangleAlert, text: 'text-red', bg: 'bg-red-bg', tone: 'red', title: f.label, detail: `Value: ${f.value}`, badge: f.value })
  }
  for (const a of review?.anomalies || []) {
    out.push({
      icon: TrendingUp,
      text: 'text-amber',
      bg: 'bg-amber-bg',
      tone: 'amber',
      title: a.label,
      detail: `Outside historical range (${a.low} – ${a.high})`,
      badge: `${a.latest}${a.unit || ''}`,
    })
  }
  return out
}
