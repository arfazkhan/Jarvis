import { useMemo, useState } from 'react'
import {
  TriangleAlert,
  ShieldAlert,
  Clock,
  ChevronRight,
  X,
  Plus,
  FileText,
  MapPin,
  User,
  Wrench,
  CircleDot,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, Drawer, Empty, Spinner } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

const STATUS_TONE = { open: 'amber', assigned: 'blue', in_progress: 'purple', resolved: 'green', lapsed: 'red' }
const SEV_TONE = { critical: 'red', issue: 'amber', warning: 'amber', info: 'neutral' }
const PRIORITY_TONE = { critical: 'red', high: 'amber', medium: 'blue', low: 'neutral' }
const FILTERS = ['all', 'open', 'assigned', 'in_progress', 'resolved']

const SEV_BG = {
  red: 'bg-red-bg text-red',
  amber: 'bg-amber-bg text-amber',
  neutral: 'bg-surface-2 text-text-dim',
}
const TEXT_TONE = { red: 'text-red', amber: 'text-amber', green: 'text-green', blue: 'text-blue', neutral: 'text-text-dim' }

export default function Issues() {
  const { building } = useBuilding()
  const [filter, setFilter] = useState('all')
  const [selected, setSelected] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [showCreate, setShowCreate] = useState(false)

  const issues = useAsync(
    () => api.issues(building, filter === 'all' ? '' : filter),
    [building, filter, refreshKey]
  )
  const list = issues.data?.issues || []

  const refresh = () => setRefreshKey((k) => k + 1)

  return (
    <div>
      <PageHeader subtitle="Tracked issues & SLA accountability" />

      <div className="px-10 pt-6 flex items-center justify-between">
        <div className="text-2xl font-serif text-text">{list.length} Issues</div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 text-sm bg-surface border border-border rounded-lg px-3 py-2 text-text-dim hover:border-gold/40"
        >
          <Plus className="w-4 h-4" /> Log Issue
        </button>
      </div>

      <div className="px-10 pt-4 flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1.5 rounded-lg border capitalize ${
              filter === f ? 'border-gold/40 text-gold-soft bg-surface-2' : 'border-border text-text-dim'
            }`}
          >
            {f.replace('_', ' ')}
          </button>
        ))}
      </div>

      <div className="px-10 pt-6">
        {issues.loading ? (
          <Spinner />
        ) : list.length === 0 ? (
          <Empty>No issues for this filter.</Empty>
        ) : (
          <div className="flex flex-col gap-2">
            {list.map((iss) => (
              <button
                key={iss.id}
                onClick={() => setSelected(iss)}
                className="flex items-center justify-between border border-border-soft rounded-xl px-4 py-4 hover:bg-surface/60 text-left"
              >
                <div className="flex items-center gap-4">
                  <span
                    className={`w-10 h-10 rounded-full flex items-center justify-center ${SEV_BG[SEV_TONE[iss.severity] || 'neutral']}`}
                  >
                    {iss.severity === 'critical' ? <ShieldAlert className="w-4 h-4" /> : <TriangleAlert className="w-4 h-4" />}
                  </span>
                  <div>
                    <div className="text-sm text-text">{iss.title}</div>
                    <div className="text-xs text-text-faint flex items-center gap-2 mt-0.5">
                      <MapPin className="w-3 h-3" /> {iss.asset || '—'}
                      {iss.assignee && (
                        <>
                          · <User className="w-3 h-3" /> {iss.assignee}
                        </>
                      )}
                      {iss.vendor && (
                        <>
                          · <Wrench className="w-3 h-3" /> {iss.vendor}
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {iss.priority && <Pill tone={PRIORITY_TONE[iss.priority]}>{iss.priority}</Pill>}
                  <Pill tone={STATUS_TONE[iss.status]}>{iss.status.replace('_', ' ')}</Pill>
                  <ChevronRight className="w-4 h-4 text-text-faint" />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <IssueDrawer issue={selected} onClose={() => setSelected(null)} building={building} onChanged={refresh} />
      <CreateIssueDrawer open={showCreate} onClose={() => setShowCreate(false)} building={building} onCreated={refresh} />
    </div>
  )
}

function IssueDrawer({ issue, onClose, building, onChanged }) {
  const sla = useAsync(() => (issue ? api.issueSla(issue.id) : Promise.resolve(null)), [issue?.id])
  const wo = useAsync(() => (issue ? api.workOrder(issue.id, building) : Promise.resolve(null)), [issue?.id])
  const [busy, setBusy] = useState(false)

  if (!issue) return null

  async function transition(status, extra = {}) {
    setBusy(true)
    try {
      await api.transitionIssue(issue.id, { status, by: 'Athul G', ...extra })
      onChanged()
      onClose()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  const s = sla.data

  return (
    <Drawer open={!!issue} onClose={onClose} width={480}>
      <div className="p-6">
        <div className="flex items-start justify-between mb-4">
          <Pill tone={STATUS_TONE[issue.status]}>{issue.status.replace('_', ' ')}</Pill>
          <button onClick={onClose} className="text-text-faint">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="font-serif text-2xl text-text mb-1">{issue.title}</div>
        <div className="text-xs text-text-faint mb-6 flex items-center gap-2">
          <MapPin className="w-3 h-3" /> {issue.asset || '—'} · raised by {issue.raised_by || '—'}
        </div>

        {issue.detail && <div className="text-sm text-text-dim mb-6">{issue.detail}</div>}

        {s && (
          <div className="border border-border rounded-xl p-4 mb-6">
            <div className="text-xs uppercase tracking-wide text-text-faint mb-3 flex items-center gap-2">
              <Clock className="w-4 h-4" /> SLA Status
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Field label="Priority" value={s.priority} />
              <Field label="Age" value={`${s.age_hours?.toFixed(1)} h`} />
              <Field label="Response SLA" value={`${s.response_hours} h`} />
              <Field label="Resolution SLA" value={`${s.resolution_hours} h`} />
              <Field
                label="Breached"
                value={s.breached_resolution ? 'Yes' : 'No'}
                tone={s.breached_resolution ? 'red' : 'green'}
              />
              <Field label="Escalation" value={`L${s.escalation_level} → ${s.target}`} />
            </div>
          </div>
        )}

        {wo.data && (
          <div className="border border-border rounded-xl p-4 mb-6">
            <div className="text-xs uppercase tracking-wide text-text-faint mb-2 flex items-center gap-2">
              <FileText className="w-4 h-4" /> Suggested Work Order
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm mb-2">
              <Field label="Category" value={wo.data.category} />
              <Field label="Team" value={wo.data.required_team} />
              <Field label="Priority" value={wo.data.priority} />
            </div>
            <div className="text-sm text-text-dim">{wo.data.suggested_action}</div>
            <div className="text-xs text-text-faint mt-2">Arvis suggests — you create the work order.</div>
          </div>
        )}

        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">History</div>
        <div className="flex flex-col gap-2 mb-6">
          {(issue.history || []).map((h, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <CircleDot className="w-3 h-3 text-text-faint mt-1" />
              <div>
                <span className="text-text">{h.action}</span>
                <span className="text-text-faint"> by {h.by} · {fmt(h.ts)}</span>
                {h.note && <div className="text-xs text-text-faint">{h.note}</div>}
              </div>
            </div>
          ))}
        </div>

        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Actions</div>
        <div className="grid grid-cols-2 gap-2">
          {issue.status === 'open' && (
            <ActBtn disabled={busy} onClick={() => transition('assigned', assignPrompt())}>
              Assign
            </ActBtn>
          )}
          {issue.status === 'assigned' && (
            <ActBtn disabled={busy} onClick={() => transition('in_progress')}>
              Start work
            </ActBtn>
          )}
          {issue.status !== 'resolved' && (
            <ActBtn disabled={busy} tone="green" onClick={() => transition('resolved', { note: 'resolved' })}>
              Resolve
            </ActBtn>
          )}
          {issue.status === 'resolved' && (
            <ActBtn disabled={busy} onClick={() => transition('open')}>
              Reopen
            </ActBtn>
          )}
          {(issue.vendor || issue.assignee) && issue.status !== 'resolved' && (
            <ActBtn
              disabled={busy}
              onClick={async () => {
                await api.issueVisited(issue.id, { by: issue.vendor || issue.assignee })
                onChanged()
                onClose()
              }}
            >
              Mark visited
            </ActBtn>
          )}
        </div>
      </div>
    </Drawer>
  )
}

function assignPrompt() {
  const assignee = window.prompt('Assign to (staff or vendor name):')
  if (!assignee) return {}
  const priority = window.prompt('Priority (critical/high/medium/low):', 'high') || undefined
  return { assignee, vendor: assignee, priority }
}

function CreateIssueDrawer({ open, onClose, building, onCreated }) {
  const [form, setForm] = useState({ title: '', detail: '', asset: '', severity: 'issue', priority: 'medium' })
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!form.title.trim()) return
    setBusy(true)
    try {
      await api.createIssue({ building, by: 'Athul G', ...form })
      onCreated()
      onClose()
      setForm({ title: '', detail: '', asset: '', severity: 'issue', priority: 'medium' })
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={open} onClose={onClose} width={420}>
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="font-serif text-xl text-text">Log Issue</div>
          <button onClick={onClose} className="text-text-faint">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex flex-col gap-4">
          <Input label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} />
          <Textarea label="Detail" value={form.detail} onChange={(v) => setForm({ ...form, detail: v })} />
          <Input label="Asset" value={form.asset} onChange={(v) => setForm({ ...form, asset: v })} />
          <Select
            label="Severity"
            value={form.severity}
            options={['issue', 'critical', 'warning', 'info']}
            onChange={(v) => setForm({ ...form, severity: v })}
          />
          <Select
            label="Priority"
            value={form.priority}
            options={['critical', 'high', 'medium', 'low']}
            onChange={(v) => setForm({ ...form, priority: v })}
          />
          <button
            disabled={busy}
            onClick={submit}
            className="bg-primary text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50"
          >
            Create Issue
          </button>
        </div>
      </div>
    </Drawer>
  )
}

function Field({ label, value, tone }) {
  return (
    <div>
      <div className="text-xs text-text-faint">{label}</div>
      <div className={`text-sm ${tone ? TEXT_TONE[tone] : 'text-text'} capitalize`}>{value ?? '—'}</div>
    </div>
  )
}

function ActBtn({ children, onClick, disabled, tone }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`text-sm rounded-lg py-2 border disabled:opacity-50 ${
        tone === 'green' ? 'border-green/40 text-green' : 'border-border text-text-dim hover:border-gold/40'
      }`}
    >
      {children}
    </button>
  )
}

export function Input({ label, value, onChange }) {
  return (
    <label className="block">
      <div className="text-xs text-text-faint mb-1">{label}</div>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50"
      />
    </label>
  )
}

export function Textarea({ label, value, onChange }) {
  return (
    <label className="block">
      <div className="text-xs text-text-faint mb-1">{label}</div>
      <textarea
        value={value}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50"
      />
    </label>
  )
}

export function Select({ label, value, options, onChange }) {
  return (
    <label className="block">
      <div className="text-xs text-text-faint mb-1">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50 capitalize"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  )
}

function fmt(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}
