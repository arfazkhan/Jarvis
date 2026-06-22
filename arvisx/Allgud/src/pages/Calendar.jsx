import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, CalendarDays, ClipboardList, Wrench, Clock, Plus, Play, X } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Spinner, Pill } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

// Simple month calendar — PPM due dates across the month + today's rounds.
// (Per-day round history isn't fetched in bulk; today's runs are marked on today.)
export default function Calendar() {
  const navigate = useNavigate()
  const { building } = useBuilding()
  const [cursor, setCursor] = useState(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() } })

  const ppm = useAsync(() => api.ppmSchedule(building), [building])
  const today = useAsync(() => api.today(building), [building])

  const todayStr = new Date().toISOString().slice(0, 10)
  const ppmByDate = useMemo(() => {
    const map = {}
    for (const p of ppm.data?.schedules || []) {
      if (p.due_date) (map[p.due_date] ||= []).push(p)
    }
    return map
  }, [ppm.data])

  const cells = useMemo(() => buildMonth(cursor.y, cursor.m), [cursor])
  const monthLabel = new Date(cursor.y, cursor.m, 1).toLocaleString('en-US', { month: 'long', year: 'numeric' })
  const move = (d) => setCursor((c) => {
    const nm = c.m + d
    return { y: c.y + Math.floor(nm / 12), m: ((nm % 12) + 12) % 12 }
  })
  const runs = today.data?.runs || []

  return (
    <div>
      <PageHeader subtitle="Rounds & preventive maintenance schedule" />
      <div className="px-10 pt-6">
        <div className="flex items-center justify-between mb-5">
          <div className="text-2xl font-serif text-text flex items-center gap-2"><CalendarDays className="w-5 h-5 text-gold-soft" /> {monthLabel}</div>
          <div className="flex gap-2">
            <button onClick={() => move(-1)} className="p-2 rounded-lg border border-border text-text-dim hover:border-gold/40"><ChevronLeft className="w-4 h-4" /></button>
            <button onClick={() => setCursor(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() } })} className="px-3 rounded-lg border border-border text-sm text-text-dim hover:border-gold/40">Today</button>
            <button onClick={() => move(1)} className="p-2 rounded-lg border border-border text-text-dim hover:border-gold/40"><ChevronRight className="w-4 h-4" /></button>
          </div>
        </div>

        {ppm.loading ? <Spinner /> : (
          <div className="grid grid-cols-7 gap-px bg-border rounded-xl overflow-hidden border border-border">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => (
              <div key={d} className="bg-surface px-2 py-2 text-xs text-text-faint text-center">{d}</div>
            ))}
            {cells.map((cell, i) => {
              if (!cell) return <div key={i} className="bg-bg min-h-[96px]" />
              const isToday = cell.date === todayStr
              const due = ppmByDate[cell.date] || []
              return (
                <div key={i} className={`bg-bg min-h-[96px] p-2 ${isToday ? 'ring-1 ring-gold/50' : ''}`}>
                  <div className={`text-xs mb-1 ${isToday ? 'text-gold-soft font-medium' : 'text-text-faint'}`}>{cell.day}</div>
                  {isToday && runs.map((r) => (
                    <button key={r.run_id} onClick={() => navigate(`/operations/round/${r.run_id}`)}
                      className="w-full flex items-center gap-1 text-[11px] text-text bg-surface rounded px-1.5 py-1 mb-1 truncate hover:bg-surface-2">
                      <ClipboardList className="w-3 h-3 text-gold-soft shrink-0" /> <span className="truncate">{r.name?.split('—')[0] || r.name}</span>
                    </button>
                  ))}
                  {due.map((p, j) => (
                    <div key={j} className={`flex items-center gap-1 text-[11px] rounded px-1.5 py-1 mb-1 truncate ${p.overdue ? 'bg-red-bg text-red' : 'bg-amber-bg text-amber'}`}>
                      <Wrench className="w-3 h-3 shrink-0" /> <span className="truncate">{p.asset} PPM</span>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        )}
        <div className="flex items-center gap-4 text-xs text-text-faint mt-3">
          <span className="flex items-center gap-1"><ClipboardList className="w-3 h-3 text-gold-soft" /> Round (today)</span>
          <span className="flex items-center gap-1"><Wrench className="w-3 h-3 text-amber" /> PPM due</span>
          <span className="flex items-center gap-1"><Wrench className="w-3 h-3 text-red" /> PPM overdue</span>
        </div>

        <SchedulePanel building={building} />
      </div>
    </div>
  )
}

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']   // index → weekday() value

function SchedulePanel({ building }) {
  const [key, setKey] = useState(0)
  const refresh = () => setKey((k) => k + 1)
  const scheds = useAsync(() => api.schedules(building), [building, key])
  const templates = useAsync(() => api.templates(building), [building])
  const techs = useAsync(() => api.technicians(building), [building])
  const [open, setOpen] = useState(false)

  function describe(s) {
    const at = s.run_time || '09:00'
    if (s.mode === 'once') return `Once · ${s.run_date} ${at}`
    if (s.recur === 'weekly') return `Every ${DOW[s.dow] || '?'} · ${at}`
    if (s.recur === 'monthly') return `Monthly · day ${s.dom} · ${at}`
    return `Daily · ${at}`
  }

  return (
    <div className="mt-10 border-t border-border-soft pt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="text-lg font-serif text-text flex items-center gap-2"><Clock className="w-4 h-4 text-gold-soft" /> Scheduled checklists</div>
        <button onClick={() => setOpen((o) => !o)} className="text-sm text-gold hover:underline flex items-center gap-1">
          <Plus className="w-4 h-4" /> New schedule
        </button>
      </div>

      {open && <ScheduleForm building={building} templates={templates.data?.templates || []}
        techs={techs.data?.technicians || []} onDone={() => { setOpen(false); refresh() }} />}

      {scheds.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(scheds.data?.schedules || []).map((s) => (
            <div key={s.id} className="flex items-center gap-3 bg-surface border border-border rounded-lg px-4 py-2.5">
              <ClipboardList className="w-4 h-4 text-gold-soft shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-text truncate">{s.label || s.template_name}</div>
                <div className="text-xs text-text-faint">{describe(s)}{s.assignee ? ` · ${s.assignee}` : ' · unassigned'}</div>
              </div>
              {s.last_fired && <Pill tone="neutral">last {s.last_fired}</Pill>}
              <button onClick={async () => { await api.runScheduleNow(s.id); refresh() }}
                className="text-xs text-text-dim hover:text-green flex items-center gap-1" title="Run now">
                <Play className="w-3.5 h-3.5" /> run
              </button>
              <button onClick={async () => { await api.deactivateSchedule(s.id); refresh() }}
                className="text-xs text-text-faint hover:text-red" title="Remove"><X className="w-4 h-4" /></button>
            </div>
          ))}
          {!scheds.data?.schedules?.length && <div className="text-sm text-text-faint">No scheduled checklists — add one to auto-open a checklist at a set date & time.</div>}
        </div>
      )}
    </div>
  )
}

function ScheduleForm({ building, templates, techs, onDone }) {
  const [f, setF] = useState({
    template_id: templates[0]?.template_id || '', label: '', mode: 'once',
    date: new Date().toISOString().slice(0, 10), time: '09:00',
    recur: 'weekly', dow: 0, dom: 1, assignee: '',
  })
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }))

  async function save() {
    if (!f.template_id) return
    setBusy(true)
    try {
      await api.addSchedule({
        building, template_id: f.template_id, label: f.label.trim(), mode: f.mode,
        date: f.date, time: f.time, recur: f.mode === 'recurring' ? f.recur : '',
        dow: f.recur === 'weekly' ? Number(f.dow) : '', dom: f.recur === 'monthly' ? Number(f.dom) : '',
        assignee: f.assignee,
      })
      onDone()
    } catch (e) { alert(e.message) } finally { setBusy(false) }
  }

  const inp = 'bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50'
  return (
    <div className="bg-surface-2 border border-border rounded-xl p-4 mb-4 grid grid-cols-2 gap-3">
      <label className="text-xs text-text-dim flex flex-col gap-1">Checklist
        <select className={inp} value={f.template_id} onChange={(e) => set('template_id', e.target.value)}>
          {templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
        </select>
      </label>
      <label className="text-xs text-text-dim flex flex-col gap-1">Label (optional)
        <input className={inp} value={f.label} onChange={(e) => set('label', e.target.value)} placeholder="e.g. Quarterly fire drill" />
      </label>
      <label className="text-xs text-text-dim flex flex-col gap-1">When
        <select className={inp} value={f.mode} onChange={(e) => set('mode', e.target.value)}>
          <option value="once">Once (specific date)</option>
          <option value="recurring">Recurring</option>
        </select>
      </label>
      <label className="text-xs text-text-dim flex flex-col gap-1">Time
        <input type="time" className={inp} value={f.time} onChange={(e) => set('time', e.target.value)} />
      </label>
      {f.mode === 'once' ? (
        <label className="text-xs text-text-dim flex flex-col gap-1">Date
          <input type="date" className={inp} value={f.date} onChange={(e) => set('date', e.target.value)} />
        </label>
      ) : (
        <label className="text-xs text-text-dim flex flex-col gap-1">Repeat
          <select className={inp} value={f.recur} onChange={(e) => set('recur', e.target.value)}>
            <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
          </select>
        </label>
      )}
      {f.mode === 'recurring' && f.recur === 'weekly' && (
        <label className="text-xs text-text-dim flex flex-col gap-1">Weekday
          <select className={inp} value={f.dow} onChange={(e) => set('dow', e.target.value)}>
            {DOW.map((d, i) => <option key={i} value={i}>{d}</option>)}
          </select>
        </label>
      )}
      {f.mode === 'recurring' && f.recur === 'monthly' && (
        <label className="text-xs text-text-dim flex flex-col gap-1">Day of month
          <input type="number" min="1" max="31" className={inp} value={f.dom} onChange={(e) => set('dom', e.target.value)} />
        </label>
      )}
      <label className="text-xs text-text-dim flex flex-col gap-1">Assign to (optional)
        <select className={inp} value={f.assignee} onChange={(e) => set('assignee', e.target.value)}>
          <option value="">Unassigned</option>
          {techs.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
        </select>
      </label>
      <div className="col-span-2 flex justify-end gap-2">
        <button onClick={onDone} className="px-3 py-2 text-sm text-text-dim">Cancel</button>
        <button onClick={save} disabled={busy} className="px-4 py-2 text-sm rounded-lg bg-gold text-bg disabled:opacity-50">{busy ? 'Saving…' : 'Add schedule'}</button>
      </div>
    </div>
  )
}

function buildMonth(y, m) {
  const first = new Date(y, m, 1)
  const startDow = (first.getDay() + 6) % 7 // Mon=0
  const daysInMonth = new Date(y, m + 1, 0).getDate()
  const cells = []
  for (let i = 0; i < startDow; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) {
    const date = `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({ day: d, date })
  }
  return cells
}
