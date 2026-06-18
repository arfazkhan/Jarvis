import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Check, TriangleAlert, Camera, ChevronLeft, ChevronRight, X, CheckCircle2, Loader2, CloudOff, CalendarX } from 'lucide-react'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'
import { enqueue, flush, subscribe, isNetworkError } from '../lib/fieldQueue'

// Field round-runner: the technician's ENTIRE world. Phone-first, one check at a time,
// big touch targets, auto-advance, minimal chrome. Opened straight from the WhatsApp link
// (/field/run/:rid). Must feel faster than paper.

function flatten(t) {
  const out = []
  ;(t?.sections || []).forEach((s) => (s.items || []).forEach((it) => out.push({ ...it, section: s.name })))
  return out
}

export default function FieldRound() {
  const { rid } = useParams()
  const navigate = useNavigate()
  const { building } = useBuilding()

  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [idx, setIdx] = useState(0)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [queued, setQueued] = useState(0)
  const fileRef = useRef(null)

  // surface how many taps are waiting on a reconnect
  useEffect(() => subscribe(setQueued), [])

  const items = useMemo(() => flatten(run?.template), [run])
  const entries = run?.entries || {}
  const item = items[idx]
  const total = items.length
  const doneCount = items.filter((it) => entries[it.item_id]?.value || entries[it.item_id]?.status).length

  function load(startAtFirstUnfilled) {
    setLoading(true)
    api.getRun(rid)
      .then((r) => {
        setRun(r)
        if (startAtFirstUnfilled) {
          const its = flatten(r.template)
          const e = r.entries || {}
          const first = its.findIndex((it) => !(e[it.item_id]?.value || e[it.item_id]?.status))
          setIdx(first === -1 ? 0 : first)
        }
        setErr(null)
        setLoading(false)
      })
      .catch((e) => { setErr(e); setLoading(false) })
  }

  useEffect(() => { load(true) }, [rid])

  async function record({ status = '', value = '', note = '' }) {
    setSaving(true)
    const body = { item_id: item.item_id, value: String(value), status, note }
    // Optimistic local update first — progress + resume stay correct whether or
    // not the network is up. The tech never waits on a round-trip.
    setRun((r) => ({ ...r, entries: { ...(r.entries || {}), [item.item_id]: { value: String(value), status, note } } }))
    try {
      await api.entry(rid, body)
      setErr(null)
    } catch (e) {
      if (isNetworkError(e)) {
        enqueue(rid, body)   // offline — stash and replay on reconnect
        setErr(null)
      } else {
        setErr(e)            // a real rejection (auth/validation) — show it
      }
    }
    setSaving(false)
  }

  function next() {
    if (idx + 1 < total) setIdx(idx + 1)
  }
  function prev() {
    if (idx > 0) setIdx(idx - 1)
  }

  async function pickTick(isIssue) {
    await record({ status: isIssue ? 'issue' : 'ok', value: isIssue ? 'ISSUE' : 'OK' })
    if (!isIssue) setTimeout(next, 200)   // auto-advance on OK; pause on Issue
  }
  async function pickState(opt) {
    const isIssue = (item.alert_states || []).includes(opt)
    await record({ status: isIssue ? 'issue' : 'ok', value: opt })
    if (!isIssue) setTimeout(next, 200)
  }

  async function uploadPhoto(file) {
    if (!file) return
    setSaving(true)
    try {
      await api.entryPhoto(rid, { item_id: item.item_id, filename: file.name || 'photo.jpg', building }, file, file.type || 'image/jpeg')
    } catch (e) { setErr(e) }
    setSaving(false)
  }

  async function submitRound() {
    setSaving(true)
    try {
      const drained = await flush()      // land any offline entries before closing the round
      if (!drained) {
        setErr(new Error('Some entries are still waiting to sync — reconnect, then submit.'))
        setSaving(false)
        return
      }
      await api.submit(rid)
      setDone(true)
    } catch (e) { setErr(e) }
    setSaving(false)
  }

  if (loading) return <FieldShell><div className="flex-1 flex items-center justify-center text-text-faint"><Loader2 className="animate-spin" /></div></FieldShell>
  if (err) return <FieldShell><div className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center"><div className="text-red text-sm">{err.message}</div><button onClick={() => load(true)} className="text-sm text-gold">Retry</button></div></FieldShell>
  if (done) return (
    <FieldShell>
      <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center">
        <CheckCircle2 size={56} className="text-green" />
        <div className="font-serif text-2xl text-text">Round submitted</div>
        <div className="text-sm text-text-faint">{run.run.template_id} · {run.run.shift_date}</div>
      </div>
    </FieldShell>
  )

  // A round opened via an old link may already be closed (submitted) or have lapsed
  // (missed its window). Entries are rejected server-side once a run isn't 'open', so
  // show a clear read-only state instead of letting taps fail.
  const runStatus = run.run?.status
  if (runStatus && runStatus !== 'open') {
    const lapsedRun = runStatus === 'lapsed'
    return (
      <FieldShell>
        <div className="px-4 pt-4 pb-3 border-b border-border flex items-center justify-between">
          <div className="text-sm font-medium text-text truncate">{run.template?.name}</div>
          <button onClick={() => navigate('/field')} className="text-text-faint p-1"><X size={20} /></button>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center">
          {lapsedRun ? <CalendarX size={56} className="text-amber" /> : <CheckCircle2 size={56} className="text-green" />}
          <div className="font-serif text-2xl text-text">{lapsedRun ? 'Round missed' : 'Already submitted'}</div>
          <div className="text-sm text-text-faint">
            {lapsedRun
              ? 'This round lapsed before it was submitted and can no longer be filled.'
              : 'This round has been submitted. Nothing left to do here.'}
          </div>
          <button onClick={() => navigate('/field')} className="mt-2 text-sm text-gold">Back to my rounds</button>
        </div>
      </FieldShell>
    )
  }

  const e = entries[item.item_id] || {}
  const hasPhoto = !!e.photo

  return (
    <FieldShell>
      {/* top bar */}
      <div className="px-4 pt-4 pb-3 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium text-text truncate">{run.template?.name}</div>
          <button onClick={() => navigate('/field')} className="text-text-faint p-1"><X size={20} /></button>
        </div>
        <div className="h-2 w-full rounded-full bg-surface-2 overflow-hidden">
          <div className="h-full rounded-full bg-gold" style={{ width: `${total ? (doneCount / total) * 100 : 0}%` }} />
        </div>
        <div className="mt-1.5 flex justify-between text-xs text-text-faint">
          <span>{item.section}</span>
          <span>{doneCount} / {total} done</span>
        </div>
        {queued > 0 && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-amber">
            <CloudOff size={13} /> {queued} saved on this phone — will sync when back online
          </div>
        )}
      </div>

      {/* the one check */}
      <div className="flex-1 overflow-y-auto px-5 py-6">
        <div className="text-xs text-text-faint mb-1">Check {idx + 1} of {total}</div>
        <div className="font-serif text-2xl text-text mb-6">{item.label}</div>

        {item.kind === 'reading' && (
          <ReadingInput key={item.item_id} unit={item.unit} value={e.value || ''} onSave={(v) => record({ status: 'ok', value: v })} saving={saving} />
        )}

        {item.kind === 'state' && (
          <div className="flex flex-col gap-3">
            {(item.options || []).map((opt) => {
              const isIssue = (item.alert_states || []).includes(opt)
              const sel = e.value === opt
              return (
                <button key={opt} onClick={() => pickState(opt)}
                  className={`w-full py-4 rounded-xl border text-lg font-medium ${sel ? (isIssue ? 'bg-red-bg border-red text-red' : 'bg-green-bg border-green text-green') : 'bg-surface border-border text-text'}`}>
                  {opt}
                </button>
              )
            })}
          </div>
        )}

        {item.kind === 'tick' && (
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => pickTick(false)}
              className={`py-6 rounded-xl border flex flex-col items-center gap-2 ${e.status === 'ok' ? 'bg-green-bg border-green text-green' : 'bg-surface border-border text-text'}`}>
              <Check size={28} /> <span className="text-base font-medium">OK</span>
            </button>
            <button onClick={() => pickTick(true)}
              className={`py-6 rounded-xl border flex flex-col items-center gap-2 ${e.status === 'issue' ? 'bg-red-bg border-red text-red' : 'bg-surface border-border text-text'}`}>
              <TriangleAlert size={28} /> <span className="text-base font-medium">Issue</span>
            </button>
          </div>
        )}

        {item.kind === 'note' && (
          <textarea defaultValue={e.value || ''} onBlur={(ev) => record({ status: 'ok', value: ev.target.value })}
            rows={4} placeholder="Type your note…"
            className="w-full bg-surface border border-border rounded-xl p-3 text-base text-text outline-none focus:border-gold/50" />
        )}

        {/* photo evidence — camera on mobile */}
        <div className="mt-5">
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={(ev) => uploadPhoto(ev.target.files?.[0])} />
          <button onClick={() => fileRef.current?.click()}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border border-border text-text-dim text-sm">
            <Camera size={18} /> {hasPhoto ? 'Photo added — retake' : 'Add photo'}
          </button>
        </div>
      </div>

      {/* bottom nav */}
      <div className="px-4 py-3 border-t border-border flex items-center gap-3">
        <button onClick={prev} disabled={idx === 0}
          className="flex items-center gap-1 px-4 py-3 rounded-xl border border-border text-text disabled:opacity-40">
          <ChevronLeft size={18} /> Back
        </button>
        {idx + 1 < total ? (
          <button onClick={next} className="flex-1 flex items-center justify-center gap-1 px-4 py-3 rounded-xl bg-surface-2 text-text font-medium">
            Next <ChevronRight size={18} />
          </button>
        ) : (
          <button onClick={submitRound} disabled={saving}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-primary text-white font-medium disabled:opacity-50">
            {saving ? <Loader2 size={18} className="animate-spin" /> : <Check size={18} />} Submit round
          </button>
        )}
      </div>
    </FieldShell>
  )
}

function ReadingInput({ unit, value, onSave, saving }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  return (
    <div>
      <div className="flex items-center gap-3">
        <input
          type="number" inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)}
          placeholder="0"
          className="flex-1 bg-surface border border-border rounded-xl px-4 py-5 text-4xl font-serif text-text outline-none focus:border-gold/50"
        />
        {unit && <div className="text-xl text-text-faint w-16 text-center">{unit}</div>}
      </div>
      <button onClick={() => onSave(v)} disabled={saving || v === ''}
        className="mt-4 w-full py-3 rounded-xl bg-surface-2 text-text font-medium disabled:opacity-50">
        Save reading
      </button>
    </div>
  )
}

function FieldShell({ children }) {
  return (
    <div className="h-screen w-full bg-bg flex justify-center">
      <div className="w-full max-w-md flex flex-col h-full">{children}</div>
    </div>
  )
}
