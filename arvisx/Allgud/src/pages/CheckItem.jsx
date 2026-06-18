import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Building2,
  HelpCircle,
  Flag,
  Camera,
  TrendingUp,
  Gauge,
  Grid3x3,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  Check,
  AlertTriangle,
  TriangleAlert,
  Mic,
  PenLine,
  ImagePlus,
  ScanLine,
  ClipboardList,
  MapPin,
  Box,
  Repeat,
  Clock,
  Sparkles,
  Info,
  CheckCircle2,
} from 'lucide-react'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

export default function CheckItem() {
  const { rid, itemIndex } = useParams()
  const navigate = useNavigate()
  const { current, building } = useBuilding()
  const idx = Number(itemIndex)

  const runView = useAsync(() => api.getRun(rid), [rid])
  const readings = useAsync(() => api.get('/analyzers/readings', { building }), [building])

  const flat = useMemo(() => flattenItems(runView.data?.template), [runView.data])
  const item = flat[idx]
  const prevItem = flat[idx - 1]
  const nextItem = flat[idx + 1]
  const total = flat.length
  const entries = runView.data?.entries || {}
  const existing = item ? entries[item.item_id] : null
  const prevEntry = prevItem ? entries[prevItem.item_id] : null

  const [value, setValue] = useState('')
  const [note, setNote] = useState('')
  const [showNote, setShowNote] = useState(false)
  const [roundCtxOpen, setRoundCtxOpen] = useState(true)
  const [scanState, setScanState] = useState(null) // {available, extracted, suggestion_id} | 'loading'
  const fileRef = useRef(null)
  const scanRef = useRef(null)

  useEffect(() => {
    setValue(existing?.value || '')
    setNote(existing?.note || '')
    setScanState(null)
    setShowNote(false)
  }, [idx, existing?.value, existing?.note])

  if (runView.loading) return <div className="px-10 py-16 text-text-faint text-sm">Loading…</div>
  if (!item) return <div className="px-10 py-16 text-text-faint text-sm">Check not found.</div>

  const band = readings.data?.anomalies?.find((a) => a.item_id === item.item_id)
  const isReading = item.kind === 'reading'

  async function save(status, val, extraNote) {
    try {
      await api.entry(rid, { item_id: item.item_id, value: val ?? value, status: status ?? '', note: extraNote ?? note })
    } catch (e) {
      console.error(e)
    }
  }

  function goNext() {
    if (idx + 1 < total) navigate(`/operations/round/${rid}/check/${idx + 1}`)
    else navigate(`/operations/round/${rid}`)
  }

  function goPrev() {
    if (idx > 0) navigate(`/operations/round/${rid}/check/${idx - 1}`)
  }

  async function pickQualitative(label) {
    const status = label === 'Issue' ? 'issue' : 'ok'
    const noteVal = label === 'Attention' ? 'ATTENTION' : label === 'Issue' ? 'ISSUE' : 'NORMAL'
    setValue(noteVal)
    await save(status, noteVal)
  }

  async function pickOption(opt) {
    setValue(opt)
    await save(item.alert_states?.includes(opt) ? 'issue' : 'ok', opt)
  }

  async function submitReading() {
    await save('ok', value)
  }

  async function saveNote() {
    await save(undefined, value, note)
    setShowNote(false)
  }

  async function uploadPhoto(file) {
    try {
      await api.entryPhoto(rid, { item_id: item.item_id, filename: file.name, building }, file, file.type)
    } catch (e) {
      console.error(e)
    }
  }

  async function scanGauge(file) {
    setScanState('loading')
    try {
      const res = await api.visionExtract({ kind: 'gauge', run_id: rid, item_id: item.item_id, filename: file.name, building }, file, file.type)
      setScanState(res)
    } catch (e) {
      setScanState({ available: false, reason: e.message })
    }
  }

  async function confirmScan() {
    if (!scanState?.suggestion_id) return
    const reading = scanState.extracted?.readings && Object.values(scanState.extracted.readings)[0]
    const val = reading != null ? String(reading) : value
    await api.confirmSuggestion(scanState.suggestion_id, { value: val, run_id: rid, item_id: item.item_id })
    setValue(val)
    setScanState(null)
    runView.data && (await save('ok', val))
  }

  async function addIssueManually() {
    const detail = window.prompt(`Log an issue for ${item.label}`)
    if (detail === null) return
    await api.createIssue({
      building,
      title: item.label,
      detail,
      asset: item.asset,
      severity: 'issue',
      by: runView.data?.run?.technician,
    })
  }

  return (
    <div className="flex h-full">
      {/* left: round progress */}
      <div className="w-[260px] shrink-0 border-r border-border px-6 py-6 flex flex-col">
        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Round Progress</div>
        <div className="h-1.5 rounded-full bg-surface-2 mb-2 overflow-hidden">
          <div className="h-full bg-amber" style={{ width: `${(Object.keys(entries).length / total) * 100}%` }} />
        </div>
        <div className="text-sm text-text-dim mb-6">
          {Object.keys(entries).length} of {total} checks{' '}
          <span className="text-text-faint">{Math.round((Object.keys(entries).length / total) * 100)}%</span>
        </div>

        <div className="text-xs uppercase tracking-wide text-text-faint mb-2">Sections</div>
        <div className="flex flex-col gap-3 mb-8">
          {sectionsSummary(runView.data?.template, entries).map((s, i) => (
            <div key={i} className="flex items-center justify-between text-sm">
              <span className="text-text-dim">{s.name}</span>
              <span className="text-text-faint">
                {s.done} / {s.total}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-auto bg-surface border border-border rounded-xl p-3">
          <div className="text-sm text-text">{runView.data?.template?.name}</div>
          <div className="text-xs text-text-faint">{current?.name}</div>
          <div className="text-xs text-text-faint mt-1">{runView.data?.run?.shift_date}</div>
          <div className="flex items-center gap-2 mt-2">
            <div className="w-7 h-7 rounded-full bg-surface-2 border border-border flex items-center justify-center text-[10px] text-gold-soft">
              {(runView.data?.run?.technician || '?').slice(0, 2).toUpperCase()}
            </div>
            <div className="text-xs text-text-dim">{runView.data?.run?.technician}</div>
          </div>
        </div>
        <button onClick={() => navigate(`/operations/round/${rid}`)} className="flex items-center gap-2 text-sm text-text-faint mt-4 text-left">
          <LogOut className="w-4 h-4" /> Exit Round
        </button>
      </div>

      {/* center: the check itself */}
      <div className="flex-1 overflow-y-auto flex flex-col">
        <div className="flex items-center justify-between px-10 pt-6">
          <button onClick={() => navigate(`/operations/round/${rid}`)} className="text-sm text-text-dim flex items-center gap-2">
            <ChevronLeft className="w-4 h-4" /> Back to Round
          </button>
          <div className="text-center">
            <div className="flex items-center justify-center gap-2 text-lg text-text">
              <Building2 className="w-4 h-4" /> {item.asset || item.section}
            </div>
            <div className="text-xs text-text-faint">
              {runView.data?.template?.name} · Assigned to {runView.data?.run?.technician}
            </div>
          </div>
          <button className="text-sm text-text-dim flex items-center gap-2">
            <HelpCircle className="w-4 h-4" /> Help
          </button>
        </div>

        <div className="flex justify-end px-10 pt-2">
          <button className="text-xs border border-amber/30 text-amber rounded-lg px-3 py-1.5 flex items-center gap-1">
            <Flag className="w-3.5 h-3.5" /> Flag for Review
          </button>
        </div>

        <div className="px-10 pt-10 max-w-2xl mx-auto text-center flex-1">
          <div className="text-xs text-text-faint border border-border rounded-full inline-block px-3 py-1 mb-6">
            Check {idx + 1} of {total} {isReading ? '· Reading' : '· ' + (item.category || 'Mechanical')}
          </div>
          <div className="font-serif text-3xl text-text mb-8">{item.label}</div>

          {!isReading ? (
            <>
              <div className="text-sm text-text-dim mb-4">What do you observe?</div>
              <div className="grid grid-cols-3 gap-4 mb-8">
                {(item.options?.length ? item.options : ['Normal', 'Attention', 'Issue']).map((opt) => {
                  const isSelected = value === opt || (opt === 'Normal' && value === 'NORMAL')
                  const tone =
                    opt === 'Issue' || item.alert_states?.includes(opt)
                      ? 'red'
                      : opt === 'Attention'
                      ? 'amber'
                      : 'green'
                  return (
                    <button
                      key={opt}
                      onClick={() => (item.options?.length ? pickOption(opt) : pickQualitative(opt))}
                      className={`flex flex-col items-center gap-1 rounded-xl border px-4 py-5 transition-colors ${
                        isSelected ? TONE_SELECTED[tone] : 'border-border bg-surface text-text-dim hover:border-border'
                      }`}
                    >
                      <ToneIcon tone={tone} className="w-5 h-5" />
                      <span className="text-sm font-medium">{opt}</span>
                      <span className="text-xs opacity-70">{TONE_SUB[tone]}</span>
                    </button>
                  )
                })}
              </div>

              <div className="text-sm text-text-dim mb-3">Add Evidence (optional)</div>
              <div className="grid grid-cols-3 gap-4 mb-10">
                <EvidenceButton icon={Camera} label="Photo" onClick={() => fileRef.current?.click()} />
                <EvidenceButton icon={Mic} label="Voice Note" disabled title="Not available in pilot" />
                <EvidenceButton icon={PenLine} label="Note" onClick={() => setShowNote((s) => !s)} />
              </div>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && uploadPhoto(e.target.files[0])}
              />
              {showNote && (
                <div className="mb-10 text-left">
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                    className="w-full bg-surface border border-border rounded-xl p-3 text-sm text-text outline-none focus:border-gold/50"
                    placeholder="Add a note about this check…"
                  />
                  <button onClick={saveNote} className="text-sm text-gold mt-2">
                    Save Note
                  </button>
                </div>
              )}

              {band && (
                <>
                  <div className="flex items-center justify-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
                    <Sparkles className="w-4 h-4 text-purple" /> AI Context
                  </div>
                  <div className="grid grid-cols-2 gap-4 mb-3 text-left">
                    <div className="border border-border rounded-2xl p-5">
                      <div className="flex items-center justify-between text-xs text-text-faint mb-2">
                        Historical Range
                        <TrendingUp className="w-4 h-4 text-amber" />
                      </div>
                      <div className="font-serif text-2xl text-text">
                        {band.low} – {band.high} {item.unit}
                      </div>
                      <div className="text-xs text-text-faint mt-1">Based on last 30 days</div>
                    </div>
                    <div className="border border-border rounded-2xl p-5">
                      <div className="flex items-center justify-between text-xs text-text-faint mb-2">
                        Last Recorded
                        <Gauge className="w-4 h-4 text-amber" />
                      </div>
                      <div className="font-serif text-2xl text-text">
                        {band.latest} {item.unit}
                      </div>
                      <div className="text-xs text-text-faint mt-1">Most recent reading</div>
                    </div>
                  </div>
                  <div className="flex items-center justify-center gap-1 text-xs text-text-faint mb-2">
                    <Info className="w-3.5 h-3.5" /> Context is AI-generated. Verify in the field.
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              <div className="text-sm text-text-dim mb-3">Enter Reading</div>
              <div className="flex items-center justify-center gap-3 mb-6">
                <input
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="font-serif text-5xl text-text bg-transparent border border-gold/40 rounded-2xl px-8 py-4 w-64 text-center outline-none focus:border-gold"
                />
                <div className="border border-border rounded-2xl px-5 py-4 text-text-dim">{item.unit}</div>
              </div>

              <button
                onClick={() => scanRef.current?.click()}
                className="flex items-center justify-center gap-2 w-full border border-border rounded-xl py-3 mb-3 text-sm text-text-dim"
              >
                <Camera className="w-4 h-4" /> Scan Gauge
                <span className="text-[10px] uppercase tracking-wide border border-border rounded px-1.5 py-0.5 text-text-faint">Beta</span>
                <span className="text-text-faint">Use camera to read the gauge</span>
              </button>
              <input
                ref={scanRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && scanGauge(e.target.files[0])}
              />

              {scanState === 'loading' && <div className="text-xs text-text-faint mb-6">Scanning…</div>}
              {scanState && scanState !== 'loading' && (
                <div className="border border-border rounded-xl p-4 mb-6 text-left text-sm">
                  {scanState.available ? (
                    <>
                      <div className="text-text mb-2">Extracted: {JSON.stringify(scanState.extracted?.readings)}</div>
                      <button onClick={confirmScan} className="text-gold text-sm">
                        Confirm & fill reading
                      </button>
                    </>
                  ) : (
                    <div className="text-text-faint">Vision model not configured — {scanState.reason || 'enter manually'}.</div>
                  )}
                </div>
              )}

              {band && (
                <div className="border border-border rounded-2xl p-6 text-left mb-2">
                  <div className="text-xs uppercase tracking-wide text-text-faint mb-3 flex items-center gap-1">
                    <TrendingUp className="w-4 h-4" /> Historical Range (30 days)
                  </div>
                  <div className="text-2xl text-text mb-3">
                    {band.low} – {band.high} {item.unit}
                  </div>
                  <RangeBar low={band.low} high={band.high} value={band.latest} />
                  <div className="flex justify-between text-xs text-text-faint mt-2">
                    <span>{band.low} Min</span>
                    <span>Typical Range</span>
                    <span>{band.high} Max</span>
                  </div>
                </div>
              )}

              <button onClick={submitReading} className="text-sm text-gold mt-4">
                Save Reading
              </button>
            </>
          )}
        </div>

        <div className="sticky bottom-0 mt-10 border-t border-border bg-bg/95 backdrop-blur px-10 py-4 flex items-center justify-between">
          <button onClick={goPrev} disabled={idx === 0} className="flex items-center gap-1 text-sm text-text-dim disabled:opacity-30">
            <ChevronLeft className="w-4 h-4" />
            <div className="text-left">
              Previous
              <div className="text-xs text-text-faint">{idx > 0 ? `Check ${idx} of ${total}` : ''}</div>
            </div>
          </button>
          <div className="flex items-center gap-2 text-sm text-text-dim text-center">
            <Grid3x3 className="w-4 h-4" />
            <div>
              {idx + 1} of {total}
              <div className="text-xs text-text-faint">{item.label}</div>
            </div>
          </div>
          <button onClick={goNext} className="flex items-center gap-1 text-sm text-gold">
            <div className="text-right">
              Next
              <div className="text-xs text-text-faint">{nextItem?.label || 'Finish'}</div>
            </div>
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* right: context panel — differs by item kind, per mockups */}
      <div className="w-[320px] shrink-0 border-l border-border px-6 py-6 overflow-y-auto">
        {!isReading ? (
          <>
            <button
              onClick={() => setRoundCtxOpen((o) => !o)}
              className="flex items-center justify-between w-full text-xs uppercase tracking-wide text-text-faint mb-4"
            >
              Round Context
              {roundCtxOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {roundCtxOpen && (
              <div className="flex flex-col gap-4 mb-8">
                <ContextRow icon={ClipboardList} label="Template" value={runView.data?.template?.name} />
                <ContextRow icon={MapPin} label="Area" value={item.section} />
                <ContextRow icon={Box} label="Asset" value={item.asset} />
                <ContextRow icon={Repeat} label="Frequency" value={runView.data?.template?.cadence} />
                <ContextRow icon={Clock} label="Started" value={fmtTime(runView.data?.run?.started_at)} />
              </div>
            )}

            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Previous Check</div>
            {prevItem ? (
              <button
                onClick={goPrev}
                className="w-full flex items-center justify-between border border-border rounded-xl p-4 mb-6 text-left"
              >
                <div>
                  <div className="text-sm text-text">{prevItem.label}</div>
                  <div className={`text-sm ${prevEntry?.is_issue ? 'text-red' : 'text-green'}`}>
                    {prevEntry ? prevEntry.value : '—'}
                  </div>
                  <div className="text-xs text-text-faint">{fmtTime(prevEntry?.ts)}</div>
                </div>
                <ChevronRight className="w-4 h-4 text-text-faint" />
              </button>
            ) : (
              <div className="text-xs text-text-faint mb-6">First check in this round.</div>
            )}

            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Next Check</div>
            {nextItem ? (
              <div className="border border-border rounded-xl p-4 mb-8">
                <div className="text-sm text-text">{nextItem.label}</div>
                <div className="text-sm text-text-faint">Upcoming</div>
              </div>
            ) : (
              <div className="text-xs text-text-faint mb-8">Last check in this round.</div>
            )}

            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Quick Actions</div>
            <div className="flex flex-col gap-3">
              <QuickAction icon={ScanLine} label="Scan Gauge" badge="Beta" onClick={() => fileRef.current?.click()} />
              <QuickAction icon={TriangleAlert} label="Add Issue Manually" onClick={addIssueManually} />
            </div>
          </>
        ) : (
          <>
            <div className="text-xs uppercase tracking-wide text-text-faint mb-4">Item Context</div>
            <div className="flex flex-col gap-4 mb-8">
              <ContextRow icon={ClipboardList} label="Template" value={runView.data?.template?.name} />
              <ContextRow icon={MapPin} label="Area" value={item.section} />
              <ContextRow icon={Box} label="Asset" value={item.asset} />
              <ContextRow icon={Repeat} label="Frequency" value={runView.data?.template?.cadence} />
            </div>

            {band && (
              <>
                <div className="text-xs uppercase tracking-wide text-text-faint mb-3">AI Insight</div>
                <div className="border border-amber/30 bg-amber-bg rounded-xl p-4 mb-8">
                  <div className="flex items-center gap-2 text-amber text-sm mb-1">
                    <TriangleAlert className="w-4 h-4" />
                    {band.direction === 'below' ? 'Below typical range' : 'Above typical range'}
                  </div>
                  <div className="text-xs text-text-dim mb-2">
                    Current reading is {band.direction} the historical band.
                  </div>
                  <button className="text-xs text-blue">View Details</button>
                </div>
              </>
            )}

            <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Quick Actions</div>
            <div className="flex flex-col gap-3">
              <QuickAction icon={ImagePlus} label="Add Photo" onClick={() => fileRef.current?.click()} />
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && uploadPhoto(e.target.files[0])}
              />
              <QuickAction icon={Mic} label="Add Voice Note" disabled />
              <QuickAction icon={PenLine} label="Add Note" onClick={() => setShowNote((s) => !s)} />
            </div>
            {showNote && (
              <div className="mt-4 text-left">
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                  className="w-full bg-surface border border-border rounded-xl p-3 text-sm text-text outline-none focus:border-gold/50"
                  placeholder="Add a note about this reading…"
                />
                <button onClick={saveNote} className="text-sm text-gold mt-2">
                  Save Note
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const TONE_SELECTED = {
  green: 'border-green bg-green-bg text-green',
  amber: 'border-amber bg-amber-bg text-amber',
  red: 'border-red bg-red-bg text-red',
}
const TONE_SUB = { green: 'Operating as expected', amber: 'Needs monitoring', red: 'Requires action' }

function ToneIcon({ tone, className }) {
  if (tone === 'red') return <TriangleAlert className={className} />
  if (tone === 'amber') return <AlertTriangle className={className} />
  return <Check className={className} />
}

function EvidenceButton({ icon: Icon, label, onClick, disabled, title }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="flex flex-col items-center gap-2 rounded-xl border border-border bg-surface px-4 py-5 text-text-dim disabled:opacity-40 hover:border-gold/30"
    >
      <Icon className="w-5 h-5" />
      <span className="text-sm">{label}</span>
    </button>
  )
}

function ContextRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <Icon className="w-4 h-4 text-text-faint mt-0.5" />
      <div>
        <div className="text-xs text-text-faint">{label}</div>
        <div className="text-sm text-text">{value ?? '—'}</div>
      </div>
    </div>
  )
}

function QuickAction({ icon: Icon, label, badge, onClick, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-between border border-border rounded-xl px-4 py-3 text-sm text-text-dim disabled:opacity-40 hover:border-gold/30"
    >
      <span className="flex items-center gap-2">
        <Icon className="w-4 h-4" /> {label}
        {badge && <span className="text-xs border border-border rounded px-1.5 py-0.5 text-text-faint">{badge}</span>}
      </span>
      <ChevronRight className="w-4 h-4 text-text-faint" />
    </button>
  )
}

function RangeBar({ low, high, value }) {
  const range = high - low || 1
  const pct = Math.min(100, Math.max(0, ((value - low) / range) * 100))
  return (
    <div className="relative h-2 rounded-full bg-surface-2">
      <div className="absolute inset-y-0 left-[10%] right-[10%] bg-green rounded-full" />
      <div className="absolute -top-1 w-3 h-3 rounded-full bg-amber border-2 border-bg" style={{ left: `calc(${pct}% - 6px)` }} />
    </div>
  )
}

function fmtTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function flattenItems(template) {
  if (!template?.sections) return []
  const out = []
  template.sections.forEach((sec) => {
    sec.items.forEach((it) => out.push({ ...it, section: sec.name }))
  })
  return out
}

function sectionsSummary(template, entries) {
  if (!template?.sections) return []
  return template.sections.map((sec) => ({
    name: sec.name,
    total: sec.items.length,
    done: sec.items.filter((it) => entries?.[it.item_id]).length,
  }))
}
