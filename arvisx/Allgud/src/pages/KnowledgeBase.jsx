import { useState, useRef, useEffect } from 'react'
import {
  BookOpen, Brain, FileText, FileUp, Sparkles, Loader2, CheckCircle2,
  AlertTriangle, RotateCcw, Wrench, Gauge, ListChecks, Plus, X, Save, Pencil, ArrowLeft, CalendarCheck,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Card, Spinner, Empty } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

const STEPS = ['Reading the manual…', 'Extracting specs & intervals…', 'Distilling troubleshooting…', 'Almost there…']
function useCycling(active, ms = 2200) {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (!active) { setI(0); return }
    const t = setInterval(() => setI((x) => Math.min(x + 1, STEPS.length - 1)), ms)
    return () => clearInterval(t)
  }, [active, ms])
  return STEPS[i]
}

export default function KnowledgeBase() {
  const { building } = useBuilding()
  const [key, setKey] = useState(0)
  const [openAsset, setOpenAsset] = useState(null)
  const [memKey, setMemKey] = useState(0)
  const assets = useAsync(() => api.assetsRegistry(building), [building, key])
  const memory = useAsync(() => api.buildingMemory(building, 90), [building, memKey])
  const refreshMem = () => setMemKey((k) => k + 1)
  const list = (assets.data?.assets || []).filter((a) => a.id)
  const refresh = () => setKey((k) => k + 1)

  return (
    <div>
      <PageHeader subtitle="Equipment manuals, distilled skills & building memory" />

      <div className="px-10 pt-8">
        <div className="flex items-center gap-2 text-2xl font-serif text-text mb-1"><BookOpen className="w-5 h-5 text-purple" /> Equipment knowledge</div>
        <div className="text-sm text-text-dim mb-5">Click an asset to view, edit, or add specs · PPM intervals · troubleshooting. Distil a manual or curate by hand.</div>
        {assets.loading ? <Spinner /> : (
          <div className="grid grid-cols-3 gap-4 pb-4">
            {list.map((a) => <AssetTile key={a.id} asset={a} onOpen={() => setOpenAsset(a)} />)}
            {!list.length && <Empty>No registered assets yet — add them in Setup → Assets, then attach manuals here.</Empty>}
          </div>
        )}
      </div>

      <div className="px-10 pt-10 pb-14">
        <div className="flex items-center gap-2 text-2xl font-serif text-text mb-1"><Brain className="w-5 h-5 text-purple" /> Building memory</div>
        <div className="text-sm text-text-dim mb-5">Approve what AllGud learns before it's trusted. Confirmed lessons + raw recurring patterns.</div>
        <MemorySection data={memory.data} loading={memory.loading} building={building} onChange={refreshMem} />
      </div>

      {openAsset && <KnowledgeEditor asset={openAsset} onClose={() => { setOpenAsset(null); refresh() }} onManualChange={refresh} />}
    </div>
  )
}

// Compact grid tile — shows manual status + knowledge counts; click to open the editor.
function AssetTile({ asset, onOpen }) {
  const know = useAsync(() => (asset.manual_path ? api.assetKnowledge(asset.id) : Promise.resolve(null)), [asset.id, asset.manual_path])
  const k = know.data || {}
  const n = (k.specs?.length || 0) + (k.ppm?.length || 0) + (k.troubleshooting?.length || 0)
  return (
    <button onClick={onOpen} className="text-left">
      <Card className="p-4 hover:border-purple/50 transition-colors h-full">
        <div className="flex items-center justify-between">
          <div className="text-sm text-text truncate">{asset.name}</div>
          {asset.manual_path
            ? <span className="text-[10px] uppercase tracking-wide text-gold flex items-center gap-1"><FileText className="w-3 h-3" /> manual</span>
            : <span className="text-[10px] uppercase tracking-wide text-text-faint">no manual</span>}
        </div>
        <div className="text-xs text-text-faint mt-0.5 truncate">{[asset.kind, asset.location].filter(Boolean).join(' · ') || '—'}</div>
        <div className="mt-3 text-xs">
          {n > 0
            ? <span className="text-purple flex items-center gap-1"><Sparkles className="w-3.5 h-3.5" /> {k.specs?.length || 0} specs · {k.ppm?.length || 0} PPM · {k.troubleshooting?.length || 0} fixes</span>
            : <span className="text-text-faint">{asset.manual_path ? 'not distilled yet' : 'open to add knowledge'}</span>}
        </div>
      </Card>
    </button>
  )
}

const empty = { specs: [], ppm: [], troubleshooting: [] }

function KnowledgeEditor({ asset, onClose, onManualChange }) {
  const fileRef = useRef(null)
  const [k, setK] = useState(empty)
  const [loaded, setLoaded] = useState(false)
  const [mode, setMode] = useState('view')     // view (preview) | edit
  const [phase, setPhase] = useState('idle')   // idle | uploading | distilling | saving | error
  const [note, setNote] = useState('')
  const [manual, setManual] = useState(asset.manual_path)
  const distilMsg = useCycling(phase === 'distilling')
  const hasKnow = (k.specs?.length || 0) + (k.ppm?.length || 0) + (k.troubleshooting?.length || 0) > 0

  useEffect(() => {
    let on = true
    if (asset.manual_path) api.assetKnowledge(asset.id).then((d) => on && (setK({ specs: d.specs || [], ppm: d.ppm || [], troubleshooting: d.troubleshooting || [] }), setLoaded(true)))
    else setLoaded(true)
    return () => { on = false }
  }, [asset.id])

  const dirty = useRef(false)
  function edit(section, idx, field, val) { dirty.current = true; setK((x) => ({ ...x, [section]: x[section].map((it, i) => i === idx ? { ...it, [field]: val } : it) })) }
  function add(section, blank) { dirty.current = true; setK((x) => ({ ...x, [section]: [...x[section], blank] })) }
  function remove(section, idx) { dirty.current = true; setK((x) => ({ ...x, [section]: x[section].filter((_, i) => i !== idx) })) }

  async function save() {
    setPhase('saving'); setNote('')
    try { await api.saveAssetKnowledge(asset.id, k); dirty.current = false; setPhase('idle'); setMode('view'); setNote('Saved ✓'); setTimeout(() => setNote(''), 2500) }
    catch (e) { setPhase('error'); setNote(e.message || 'Save failed') }
  }
  async function upload(file) {
    if (!file) return
    setPhase('uploading'); setNote('')
    try { await api.uploadAssetManual(asset.id, file, file.type, file.name); setManual(file.name); onManualChange(); setPhase('idle') }
    catch (e) { setPhase('error'); setNote(e.message || 'Upload failed') }
  }
  async function distil() {
    setPhase('distilling'); setNote('')
    try {
      const r = await api.extractAssetSkills(asset.id)
      if (r.extracted) { const d = r.knowledge || await api.assetKnowledge(asset.id); setK({ specs: d.specs || [], ppm: d.ppm || [], troubleshooting: d.troubleshooting || [] }); setPhase('idle'); setMode('edit'); setNote('Distilled — review & save') }
      else { setPhase('error'); setNote(r.note || 'This manual looks scanned — upload a digital PDF.') }
    } catch (e) { setPhase('error'); setNote(e.message || 'Distil failed') }
  }
  async function applyPpm() {
    setPhase('saving'); setNote('')
    try { const r = await api.applyAssetPpm(asset.id); setPhase('idle'); setNote(`PPM schedule set — service every ${r.interval_days}d (from "${r.task || 'manual'}")`); setTimeout(() => setNote(''), 4000) }
    catch (e) { setPhase('error'); setNote(e.message || 'Could not apply PPM') }
  }
  const ppmDated = (k.ppm || []).some((p) => p.interval_days > 0)

  const busy = phase === 'uploading' || phase === 'distilling' || phase === 'saving'

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-2xl max-w-2xl w-full max-h-[88vh] overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
        {/* header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            {mode === 'edit' && <button onClick={() => setMode('view')} className="text-text-faint hover:text-text" title="Back to preview"><ArrowLeft className="w-5 h-5" /></button>}
            <div>
              <div className="text-xl font-serif text-text flex items-center gap-2"><BookOpen className="w-5 h-5 text-purple" /> {asset.name}{mode === 'edit' && <span className="text-xs text-purple uppercase tracking-wide">editing</span>}</div>
              <div className="text-xs text-text-faint mt-0.5">{[asset.kind, asset.location].filter(Boolean).join(' · ') || 'equipment knowledge'}</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {mode === 'view' && <button onClick={() => setMode('edit')} className="flex items-center gap-1 text-xs border border-border rounded-lg px-2.5 py-1.5 text-text-dim hover:border-purple/40 hover:text-text" title="Edit knowledge"><Pencil className="w-3.5 h-3.5" /> edit</button>}
            <button onClick={onClose} className="text-text-faint hover:text-text"><X className="w-5 h-5" /></button>
          </div>
        </div>

        {/* manual actions */}
        <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,image/*" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <div className="flex items-center gap-3 mb-4 text-xs">
          {manual
            ? <>
                <button onClick={() => api.openAssetManual(manual === asset.manual_path ? asset.manual_path : asset.manual_path)} className="text-gold hover:underline flex items-center gap-1"><FileText className="w-3.5 h-3.5" /> view manual</button>
                <button onClick={distil} disabled={busy} className="text-purple hover:underline flex items-center gap-1 disabled:opacity-50"><Sparkles className="w-3.5 h-3.5" /> distil from manual</button>
                <button onClick={() => fileRef.current?.click()} disabled={busy} className="text-text-faint hover:text-text flex items-center gap-1 disabled:opacity-50"><FileUp className="w-3.5 h-3.5" /> replace</button>
              </>
            : <button onClick={() => fileRef.current?.click()} disabled={busy} className="text-text-dim hover:text-text flex items-center gap-1"><FileUp className="w-3.5 h-3.5" /> upload manual to auto-distil</button>}
          {ppmDated && <button onClick={applyPpm} disabled={busy} className="text-green hover:underline flex items-center gap-1 disabled:opacity-50" title="Create the PPM schedule from the manual's intervals"><CalendarCheck className="w-3.5 h-3.5" /> apply to PPM</button>}
        </div>

        {/* processing / feedback */}
        {(phase === 'distilling' || phase === 'uploading' || phase === 'saving') && (
          <div className="mb-4">
            <div className={`flex items-center gap-1.5 text-xs ${phase === 'distilling' ? 'text-purple' : 'text-gold'}`}>
              {phase === 'distilling' ? <Sparkles className="w-3.5 h-3.5 animate-pulse" /> : <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {phase === 'distilling' ? distilMsg : phase === 'saving' ? 'Saving…' : 'Uploading…'}
            </div>
            <div className="w-full h-1 mt-1.5 rounded-full bg-surface-2 overflow-hidden"><div className={`h-full w-1/3 rounded-full ${phase === 'distilling' ? 'bg-purple' : 'bg-gold'}`} style={{ animation: 'shimmer 1.2s ease-in-out infinite' }} /></div>
          </div>
        )}
        {phase === 'error' && <div className="mb-4 flex items-start gap-1.5 text-xs text-amber"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" /> {note}</div>}

        {!loaded ? <Spinner /> : mode === 'view' ? (
          // ── PREVIEW (read-only) ──
          !hasKnow ? (
            <div className="text-sm text-text-faint py-4">No knowledge yet. {manual ? <>Click <span className="text-purple">distil from manual</span> above, or</> : <>Upload a manual, or</>} click <span className="text-text-dim">edit</span> to add specs, PPM intervals & troubleshooting by hand.</div>
          ) : (
            <div className="flex flex-col gap-5">
              {!!k.specs.length && <ViewSection icon={Gauge} tone="text-blue" title="Specifications">
                {k.specs.map((s, i) => <div key={i} className="flex justify-between gap-3 text-sm py-1 border-b border-border-soft"><span className="text-text-dim">{s.name}</span><span className="text-text text-right">{s.value}</span></div>)}
              </ViewSection>}
              {!!k.ppm.length && <ViewSection icon={ListChecks} tone="text-gold-soft" title="PPM intervals">
                {k.ppm.map((p, i) => <div key={i} className="text-sm py-1 border-b border-border-soft text-text">{p.task} <span className="text-gold-soft">· {p.interval_text || (p.interval_days ? p.interval_days + 'd' : '—')}</span></div>)}
              </ViewSection>}
              {!!k.troubleshooting.length && <ViewSection icon={Wrench} tone="text-amber" title="Troubleshooting">
                {k.troubleshooting.map((t, i) => <div key={i} className="text-sm py-1 border-b border-border-soft"><span className="text-amber">{t.symptom}</span> <span className="text-text-faint">→</span> <span className="text-text-dim">{t.action}</span></div>)}
              </ViewSection>}
            </div>
          )
        ) : (
          // ── EDIT ──
          <div className="flex flex-col gap-5">
            <EditSection icon={Gauge} tone="text-blue" title="Specifications" rows={k.specs}
              cols={[['name', 'Name'], ['value', 'Value']]}
              onEdit={(i, f, v) => edit('specs', i, f, v)} onRemove={(i) => remove('specs', i)} onAdd={() => add('specs', { name: '', value: '' })} />
            <EditSection icon={ListChecks} tone="text-gold-soft" title="PPM intervals" rows={k.ppm}
              cols={[['task', 'Task'], ['interval_text', 'Interval (e.g. every 3 months)']]}
              onEdit={(i, f, v) => edit('ppm', i, f, v)} onRemove={(i) => remove('ppm', i)} onAdd={() => add('ppm', { task: '', interval_text: '', interval_days: null })} />
            <EditSection icon={Wrench} tone="text-amber" title="Troubleshooting" rows={k.troubleshooting}
              cols={[['symptom', 'Symptom'], ['action', 'Action']]}
              onEdit={(i, f, v) => edit('troubleshooting', i, f, v)} onRemove={(i) => remove('troubleshooting', i)} onAdd={() => add('troubleshooting', { symptom: '', action: '' })} />
          </div>
        )}

        <div className="flex items-center justify-between mt-6 pt-4 border-t border-border-soft">
          <div className="text-xs text-green">{note && phase === 'idle' ? note : ''}</div>
          <div className="flex items-center gap-3">
            <button onClick={onClose} className="text-sm text-text-faint hover:text-text">Close</button>
            {mode === 'edit'
              ? <button onClick={save} disabled={busy} className="flex items-center gap-1.5 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50"><Save className="w-4 h-4" /> Save knowledge</button>
              : <button onClick={() => setMode('edit')} className="flex items-center gap-1.5 text-sm border border-border rounded-lg px-4 py-2 text-text-dim hover:text-text hover:border-purple/40"><Pencil className="w-4 h-4" /> Edit</button>}
          </div>
        </div>
        <div className="text-xs text-text-faint mt-3">The bot recalls this knowledge in Ask Arvis answers + root-cause. Distil drafts it; the pencil lets you curate — add, edit, or remove.</div>
      </div>
    </div>
  )
}

function ViewSection({ icon: Icon, tone, title, children }) {
  return (
    <div>
      <div className={`flex items-center gap-1.5 text-xs uppercase tracking-wide ${tone} mb-1`}><Icon className="w-3.5 h-3.5" /> {title}</div>
      {children}
    </div>
  )
}

function EditSection({ icon: Icon, tone, title, rows, cols, onEdit, onRemove, onAdd }) {
  return (
    <div>
      <div className={`flex items-center justify-between mb-2`}>
        <div className={`flex items-center gap-1.5 text-xs uppercase tracking-wide ${tone}`}><Icon className="w-3.5 h-3.5" /> {title} <span className="text-text-faint">({rows.length})</span></div>
        <button onClick={onAdd} className="text-xs text-text-dim hover:text-text flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> add</button>
      </div>
      {rows.length === 0 && <div className="text-xs text-text-faint mb-1">None yet — click add, or distil from the manual.</div>}
      <div className="flex flex-col gap-1.5">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2">
            {cols.map(([field, ph]) => (
              <input key={field} value={r[field] ?? ''} placeholder={ph} onChange={(e) => onEdit(i, field, e.target.value)}
                className="flex-1 bg-bg border border-border rounded-lg px-2.5 py-1.5 text-sm text-text placeholder:text-text-faint outline-none focus:border-purple/50" />
            ))}
            <button onClick={() => onRemove(i)} className="text-text-faint hover:text-red p-1" title="Remove"><X className="w-4 h-4" /></button>
          </div>
        ))}
      </div>
    </div>
  )
}

function MemorySection({ data, loading, building, onChange }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  if (loading) return <Spinner />
  const pending = data?.pending || [], lessons = data?.lessons || [], recurring = data?.recurring || []
  async function decide(id, status) { setBusy(true); try { await api.decideMemory(id, status, 'manager'); onChange() } finally { setBusy(false) } }
  async function add() { if (!text.trim()) return; setBusy(true); try { await api.addMemory({ building, title: text.trim() }); setText(''); onChange() } finally { setBusy(false) } }

  return (
    <div className="flex flex-col gap-8">
      {pending.length > 0 && (
        <div>
          <div className="text-sm text-text-dim mb-3 flex items-center gap-2"><Sparkles className="w-4 h-4 text-purple" /> Pending learnings — approve to remember <span className="text-xs bg-purple/15 text-purple rounded-full px-2 py-0.5">{pending.length}</span></div>
          <div className="flex flex-col gap-2">
            {pending.map((c) => (
              <Card key={c.id} className="p-4 flex items-start justify-between gap-4 border-purple/30">
                <div className="min-w-0"><div className="text-sm text-text">{c.title}</div><div className="text-xs text-text-faint mt-0.5">{c.detail}</div></div>
                <div className="flex items-center gap-2 shrink-0">
                  <button onClick={() => decide(c.id, 'approved')} disabled={busy} className="text-xs flex items-center gap-1 text-green border border-green/40 rounded-lg px-2.5 py-1.5 hover:bg-green/10 disabled:opacity-50"><CheckCircle2 className="w-3.5 h-3.5" /> approve</button>
                  <button onClick={() => decide(c.id, 'rejected')} disabled={busy} className="text-xs flex items-center gap-1 text-text-faint border border-border rounded-lg px-2.5 py-1.5 hover:text-red hover:border-red/40 disabled:opacity-50"><X className="w-3.5 h-3.5" /> reject</button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-sm text-text-dim mb-3 flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-green" /> Confirmed memory</div>
        <div className="flex gap-2 mb-3">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder="Add a lesson by hand — e.g. 'Lift B resets on power dip → check UPS first'"
            className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text placeholder:text-text-faint outline-none focus:border-purple/50" />
          <button onClick={add} disabled={busy || !text.trim()} className="text-sm bg-primary text-white rounded-lg px-4 disabled:opacity-50 flex items-center gap-1"><Plus className="w-4 h-4" /> add</button>
        </div>
        {lessons.length === 0 ? <div className="text-xs text-text-faint">No confirmed lessons yet — approve a pending learning, or add one above.</div> : (
          <div className="flex flex-col gap-1.5">
            {lessons.map((L) => (
              <Card key={L.id} className="p-3 flex items-start justify-between gap-3">
                <div className="min-w-0"><div className="text-sm text-text">{L.title}</div>{L.detail && <div className="text-xs text-text-faint mt-0.5">{L.detail}</div>}</div>
                <button onClick={() => decide(L.id, 'rejected')} disabled={busy} className="text-text-faint hover:text-red p-1 shrink-0" title="Remove from memory"><X className="w-4 h-4" /></button>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="text-sm text-text-dim mb-3 flex items-center gap-2"><RotateCcw className="w-4 h-4 text-text-faint" /> Recurring patterns (last 90 days)</div>
        {recurring.length === 0 ? <div className="text-xs text-text-faint">No recurring problems yet — nothing has come back ≥2× in 90 days.</div> : (
          <div className="grid grid-cols-3 gap-4">
            {recurring.map((m, i) => (
              <Card key={i} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-text truncate"><RotateCcw className="w-4 h-4 text-purple" /> {m.asset || m.example}</div>
                  <span className="text-xs font-medium text-purple">{m.count}×</span>
                </div>
                <div className="text-xs text-text-faint mt-1 truncate" title={m.example}>{m.example}</div>
                <div className="text-xs mt-1">{m.open > 0 ? <span className="text-amber">{m.open} still open</span> : <span className="text-green">all resolved</span>} <span className="text-text-faint">· last {m.last_seen}</span></div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
