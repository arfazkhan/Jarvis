import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Check, TriangleAlert, Camera, ChevronLeft, ChevronRight, X, CheckCircle2, Loader2,
  CloudOff, CalendarX, Circle, Droplets, Flame, Box, Zap, Wind,
} from 'lucide-react'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'
import { useAuth } from '../lib/AuthContext'
import { enqueue, flush, subscribe, isNetworkError } from '../lib/fieldQueue'

// Field round-runner, area-first: open a round → grid of AREAS (sections) → tap one →
// fill ALL its checks at once → Save → the area shows done (green) / issue (amber) →
// move to the next. Phone-first, offline-tolerant. Opened from the WhatsApp link.

const SECTION_ICONS = [Droplets, Flame, Box, Zap, Wind]
function secIcon(i) { return SECTION_ICONS[i % SECTION_ICONS.length] }

function sectionStatus(sec, entries) {
  const items = sec.items || []
  const ans = items.filter((it) => { const e = entries[it.item_id]; return e && (e.value || e.status) })
  const issue = items.some((it) => entries[it.item_id]?.is_issue || entries[it.item_id]?.status === 'issue')
  const done = items.length > 0 && ans.length === items.length
  return { done: ans.length, total: items.length, tone: issue ? 'issue' : done ? 'done' : 'todo' }
}

export default function FieldRound() {
  const { rid } = useParams()
  const navigate = useNavigate()
  const { building } = useBuilding()
  const { username, role } = useAuth()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('grid')   // 'grid' | section index (number)
  const [done, setDone] = useState(false)
  const [saving, setSaving] = useState(false)
  const [queued, setQueued] = useState(0)

  useEffect(() => subscribe(setQueued), [])

  function load() {
    setLoading(true)
    api.getRun(rid)
      .then((r) => { setRun(r); setErr(null); setLoading(false) })
      .catch((e) => { setErr(e); setLoading(false) })
  }
  useEffect(() => { load() }, [rid])

  const sections = run?.template?.sections || []
  const entries = run?.entries || {}
  const total = sections.reduce((n, s) => n + (s.items?.length || 0), 0)
  const doneCount = sections.reduce((n, s) => n + sectionStatus(s, entries).done, 0)

  // optimistic + offline-tolerant single-entry save
  async function saveEntry(item_id, body) {
    setRun((r) => ({ ...r, entries: { ...(r.entries || {}), [item_id]: { ...body, is_issue: body.status === 'issue' } } }))
    try { await api.entry(rid, { item_id, ...body }); setErr(null) }
    catch (e) { if (isNetworkError(e)) { enqueue(rid, { item_id, ...body }); setErr(null) } else { setErr(e) } }
  }

  async function submitRound() {
    setSaving(true)
    try {
      const drained = await flush()
      if (!drained) { setErr(new Error('Some entries are still syncing — reconnect, then submit.')); setSaving(false); return }
      await api.submit(rid); setDone(true)
    } catch (e) { setErr(e) }
    setSaving(false)
  }

  if (loading) return <FieldShell><Center><Loader2 className="animate-spin text-text-faint" /></Center></FieldShell>
  if (err && !run) return <FieldShell><Center><div className="text-center px-6"><div className="text-red text-sm mb-2">{err.message}</div><button onClick={load} className="text-sm text-gold">Retry</button></div></Center></FieldShell>
  if (done) return (
    <FieldShell><Center><div className="text-center px-6 flex flex-col items-center gap-4">
      <CheckCircle2 size={56} className="text-green" />
      <div className="font-serif text-2xl text-text">Round submitted</div>
      <button onClick={() => navigate('/field')} className="text-sm text-gold">Back to my rounds</button>
    </div></Center></FieldShell>
  )
  // Locked: a technician opening a round assigned to someone else (e.g. an old link
  // after reassignment). Managers/owner preview are exempt.
  if (run && role === 'technician' && run.run?.assignee && run.run.assignee !== username) return (
    <FieldShell><Center><div className="text-center px-6 flex flex-col items-center gap-4">
      <X size={56} className="text-red" />
      <div className="font-serif text-2xl text-text">Not your round</div>
      <div className="text-sm text-text-faint">This round is now assigned to {run.run.assignee}.</div>
      <button onClick={() => navigate('/field')} className="text-sm text-gold">Back to my rounds</button>
    </div></Center></FieldShell>
  )
  if (run?.run?.status === 'lapsed') return (
    <FieldShell><Center><div className="text-center px-6 flex flex-col items-center gap-4">
      <CalendarX size={56} className="text-amber" />
      <div className="font-serif text-2xl text-text">Round missed</div>
      <div className="text-sm text-text-faint">This round lapsed and can no longer be filled.</div>
      <button onClick={() => navigate('/field')} className="text-sm text-gold">Back to my rounds</button>
    </div></Center></FieldShell>
  )

  // ── AREA detail ──
  if (typeof view === 'number') {
    const sec = sections[view]
    return (
      <FieldShell>
        <TopBar title={sec.name} onBack={() => setView('grid')} queued={queued} />
        <AreaForm key={sec.name} section={sec} entries={entries} building={building} rid={rid}
          onSave={saveEntry} onDone={() => setView('grid')} setRun={setRun} />
      </FieldShell>
    )
  }

  // ── AREA grid ──
  return (
    <FieldShell>
      <div className="px-4 pt-4 pb-3 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium text-text truncate">{run.template?.name}</div>
          <button onClick={() => navigate('/field')} className="text-text-faint p-1"><X size={20} /></button>
        </div>
        <div className="h-2 w-full rounded-full bg-surface-2 overflow-hidden">
          <div className="h-full rounded-full bg-gold" style={{ width: `${total ? (doneCount / total) * 100 : 0}%` }} />
        </div>
        <div className="mt-1.5 text-xs text-text-faint">{doneCount} / {total} checks done · pick an area</div>
        {queued > 0 && <div className="mt-2 flex items-center gap-1.5 text-xs text-amber"><CloudOff size={13} /> {queued} saved offline — will sync</div>}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
        {sections.map((s, i) => {
          const st = sectionStatus(s, entries)
          const Icon = secIcon(i)
          return (
            <button key={i} onClick={() => setView(i)}
              className="w-full bg-surface border border-border rounded-2xl p-4 flex items-center gap-3 text-left">
              <div className="w-11 h-11 rounded-full bg-surface-2 flex items-center justify-center text-gold"><Icon size={20} /></div>
              <div className="flex-1 min-w-0">
                <div className="text-base font-medium text-text truncate">{s.name}</div>
                <div className="text-xs text-text-faint">{st.done} / {st.total} done</div>
              </div>
              <StatusBadge tone={st.tone} />
              <ChevronRight size={18} className="text-text-faint" />
            </button>
          )
        })}
      </div>

      <div className="px-4 py-3 border-t border-border">
        <button onClick={submitRound} disabled={saving}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-white font-medium disabled:opacity-50">
          {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />} Submit round
        </button>
        {doneCount < total && <div className="text-center text-xs text-text-faint mt-2">{total - doneCount} check(s) still pending</div>}
        {err && <div className="text-center text-xs text-red mt-2">{err.message}</div>}
      </div>
    </FieldShell>
  )
}

function StatusBadge({ tone }) {
  if (tone === 'done') return <span className="flex items-center gap-1 text-xs text-green"><CheckCircle2 size={16} /></span>
  if (tone === 'issue') return <span className="flex items-center gap-1 text-xs text-amber"><TriangleAlert size={16} /></span>
  return <Circle size={16} className="text-text-faint" />
}

// ── Area form: ALL checks in the area at once ──
function AreaForm({ section, entries, building, rid, onSave, onDone, setRun }) {
  const items = section.items || []
  const [draft, setDraft] = useState(() => {
    const d = {}
    for (const it of items) { const e = entries[it.item_id] || {}; d[it.item_id] = { value: e.value || '', status: e.status || '', note: e.note || '' } }
    return d
  })
  const [savingAll, setSavingAll] = useState(false)
  const set = (id, patch) => setDraft((p) => ({ ...p, [id]: { ...p[id], ...patch } }))

  async function saveAll() {
    setSavingAll(true)
    for (const it of items) {
      const d = draft[it.item_id]
      if (d && (d.value || d.status)) await onSave(it.item_id, d)
    }
    setSavingAll(false)
    onDone()
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {items.map((it) => (
          <ItemCard key={it.item_id} item={it} draft={draft[it.item_id]} set={(patch) => set(it.item_id, patch)}
            rid={rid} building={building} setRun={setRun} hasPhoto={!!entries[it.item_id]?.photo} />
        ))}
      </div>
      <div className="px-4 py-3 border-t border-border">
        <button onClick={saveAll} disabled={savingAll}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-white font-medium disabled:opacity-50">
          {savingAll ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />} Save area
        </button>
      </div>
    </>
  )
}

function ItemCard({ item, draft, set, rid, building, setRun, hasPhoto }) {
  const fileRef = useRef(null)
  const [photo, setPhoto] = useState(hasPhoto)
  async function uploadPhoto(file) {
    if (!file) return
    try {
      await api.entryPhoto(rid, { item_id: item.item_id, filename: file.name || 'photo.jpg', building }, file, file.type || 'image/jpeg')
      setPhoto(true)
    } catch (e) { /* best-effort */ }
  }
  return (
    <div className="bg-surface border border-border rounded-2xl p-4">
      <div className="text-sm font-medium text-text mb-3">{item.label}{item.unit ? ` (${item.unit})` : ''}</div>

      {item.kind === 'tick' && (
        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => set({ status: 'ok', value: 'OK' })}
            className={`py-3 rounded-xl border flex items-center justify-center gap-1.5 ${draft.status === 'ok' ? 'bg-green-bg border-green text-green' : 'bg-bg border-border text-text'}`}>
            <Check size={18} /> OK
          </button>
          <button onClick={() => set({ status: 'issue', value: 'ISSUE' })}
            className={`py-3 rounded-xl border flex items-center justify-center gap-1.5 ${draft.status === 'issue' ? 'bg-red-bg border-red text-red' : 'bg-bg border-border text-text'}`}>
            <TriangleAlert size={18} /> Issue
          </button>
        </div>
      )}

      {item.kind === 'reading' && (
        <input type="number" inputMode="decimal" value={draft.value} onChange={(e) => set({ value: e.target.value, status: 'ok' })}
          placeholder="0"
          className="w-full bg-bg border border-border rounded-xl px-4 py-3 text-2xl font-serif text-text outline-none focus:border-gold/50 [appearance:none] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
      )}

      {item.kind === 'state' && (
        <div className="flex flex-col gap-2">
          {(item.options || []).map((opt) => {
            const isIssue = (item.alert_states || []).includes(opt)
            const sel = draft.value === opt
            return (
              <button key={opt} onClick={() => set({ value: opt, status: isIssue ? 'issue' : 'ok' })}
                className={`py-3 rounded-xl border text-base ${sel ? (isIssue ? 'bg-red-bg border-red text-red' : 'bg-green-bg border-green text-green') : 'bg-bg border-border text-text'}`}>
                {opt}
              </button>
            )
          })}
        </div>
      )}

      {item.kind === 'note' && (
        <textarea value={draft.value} onChange={(e) => set({ value: e.target.value, status: 'ok' })} rows={3}
          placeholder="Type…" className="w-full bg-bg border border-border rounded-xl p-3 text-base text-text outline-none focus:border-gold/50" />
      )}

      <div className="mt-3 flex items-center gap-3">
        <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
          onChange={(e) => uploadPhoto(e.target.files?.[0])} />
        <button onClick={() => fileRef.current?.click()} className="flex items-center gap-1.5 text-xs text-text-dim">
          <Camera size={15} /> {photo ? 'Photo added — retake' : 'Add photo'}
        </button>
        {item.kind !== 'note' && (
          <input value={draft.note} onChange={(e) => set({ note: e.target.value })} placeholder="note (optional)"
            className="flex-1 bg-bg border border-border rounded-lg px-2 py-1.5 text-xs text-text outline-none focus:border-gold/40" />
        )}
      </div>
    </div>
  )
}

function TopBar({ title, onBack, queued }) {
  return (
    <div className="px-4 pt-4 pb-3 border-b border-border">
      <div className="flex items-center gap-2">
        <button onClick={onBack} className="text-text-faint p-1"><ChevronLeft size={20} /></button>
        <div className="text-base font-medium text-text truncate flex-1">{title}</div>
      </div>
      {queued > 0 && <div className="mt-2 flex items-center gap-1.5 text-xs text-amber"><CloudOff size={13} /> {queued} saved offline — will sync</div>}
    </div>
  )
}

function Center({ children }) {
  return <div className="flex-1 flex items-center justify-center">{children}</div>
}

function FieldShell({ children }) {
  return (
    <div className="h-screen w-full bg-bg flex justify-center">
      <div className="w-full max-w-md flex flex-col h-full">{children}</div>
    </div>
  )
}
