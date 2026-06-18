import { useNavigate } from 'react-router-dom'
import { ClipboardList, ChevronRight, CheckCircle2, Loader2, Monitor, CalendarX } from 'lucide-react'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

// Technician home: the rounds to do today. Tap one to enter the runner. (The WhatsApp link
// usually jumps straight to /field/run/:rid, skipping this.)
export default function FieldHome() {
  const navigate = useNavigate()
  const { building, current } = useBuilding()
  const today = useAsync(() => api.today(building), [building])

  const runs = today.data?.runs || []
  const open = runs.filter((r) => r.status === 'open')
  const doneRuns = runs.filter((r) => r.status === 'submitted')
  const lapsed = runs.filter((r) => r.status === 'lapsed')   // missed — can't be filled anymore

  return (
    <div className="h-screen w-full bg-bg flex justify-center">
      <div className="w-full max-w-md flex flex-col h-full">
        <div className="px-5 pt-5 pb-3 border-b border-border">
          <div className="font-serif text-xl text-text">My rounds</div>
          <div className="text-sm text-text-faint">{current?.name || building} · today</div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {today.loading && <div className="flex justify-center py-12 text-text-faint"><Loader2 className="animate-spin" /></div>}
          {today.error && <div className="text-red text-sm py-8 text-center">{today.error.message}</div>}
          {!today.loading && !open.length && !doneRuns.length && !lapsed.length && (
            <div className="text-text-faint text-sm py-12 text-center">No rounds assigned today.</div>
          )}

          {open.map((r) => (
            <button key={r.run_id} onClick={() => navigate(`/field/run/${r.run_id}`)}
              className="w-full bg-surface border border-border rounded-2xl p-4 mb-3 flex items-center gap-3 text-left">
              <div className="w-11 h-11 rounded-full bg-surface-2 flex items-center justify-center text-gold">
                <ClipboardList size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-base font-medium text-text truncate">{r.name}</div>
                <div className="text-xs text-text-faint">{Math.round(r.completion_pct)}% done{r.assignee ? ` · ${r.assignee}` : ''}</div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-surface-2 overflow-hidden">
                  <div className="h-full rounded-full bg-gold" style={{ width: `${r.completion_pct}%` }} />
                </div>
              </div>
              <ChevronRight size={20} className="text-text-faint" />
            </button>
          ))}

          {/* Missed rounds — a prior round lapsed before it was submitted. Read-only,
              never tappable: it can't be filled now, but the tech should see it happened. */}
          {lapsed.map((r) => (
            <div key={r.run_id} className="w-full bg-surface border border-amber/40 rounded-2xl p-4 mb-3 flex items-center gap-3">
              <div className="w-11 h-11 rounded-full bg-amber-bg flex items-center justify-center text-amber">
                <CalendarX size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-base font-medium text-text truncate">{r.name}</div>
                <div className="text-xs text-amber">Missed — not submitted in time ({Math.round(r.completion_pct)}% done)</div>
              </div>
            </div>
          ))}

          {doneRuns.map((r) => (
            <div key={r.run_id} className="w-full bg-surface border border-border-soft rounded-2xl p-4 mb-3 flex items-center gap-3 opacity-70">
              <div className="w-11 h-11 rounded-full bg-green-bg flex items-center justify-center text-green">
                <CheckCircle2 size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-base font-medium text-text truncate">{r.name}</div>
                <div className="text-xs text-text-faint">Submitted</div>
              </div>
            </div>
          ))}
        </div>

        <div className="px-4 py-3 border-t border-border">
          <button onClick={() => navigate('/')} className="w-full flex items-center justify-center gap-2 py-2.5 text-sm text-text-faint">
            <Monitor size={16} /> Open manager console
          </button>
        </div>
      </div>
    </div>
  )
}
