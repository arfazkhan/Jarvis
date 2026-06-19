import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, CalendarDays, ClipboardList, Wrench } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Spinner } from '../components/ui'
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
