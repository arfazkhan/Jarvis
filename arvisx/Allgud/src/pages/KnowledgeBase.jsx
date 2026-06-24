import { useState, useRef, useEffect } from 'react'
import {
  BookOpen, Brain, FileText, FileUp, Sparkles, Loader2, CheckCircle2,
  AlertTriangle, RotateCcw, Wrench, Gauge, ListChecks,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Card, Spinner, Empty } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

// Cycling "working" messages so the long LLM distil feels alive.
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
  const assets = useAsync(() => api.assetsRegistry(building), [building, key])
  const memory = useAsync(() => api.buildingMemory(building, 90), [building])
  const list = (assets.data?.assets || []).filter((a) => a.id)   // registered = can attach a manual
  const withManual = list.filter((a) => a.manual_path).length

  return (
    <div>
      <PageHeader subtitle="Equipment manuals, distilled skills & building memory" />

      <div className="px-10 pt-8">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2 text-2xl font-serif text-text"><BookOpen className="w-5 h-5 text-purple" /> Equipment knowledge</div>
          <div className="text-xs text-text-faint">{withManual} of {list.length} assets have a manual</div>
        </div>
        {assets.loading ? <Spinner /> : (
          <div className="grid grid-cols-2 gap-5 pb-4">
            {list.map((a) => <AssetCard key={a.id} asset={a} onChange={() => setKey((k) => k + 1)} />)}
            {!list.length && <Empty>No registered assets yet — add them in Setup → Assets, then attach equipment manuals here.</Empty>}
          </div>
        )}
        <div className="text-xs text-text-faint">Distilled from each asset's uploaded manual. The bot recalls this knowledge in Ask Arvis answers + root-cause. Scanned/photo PDFs read only their text layer — digital PDFs distil fully.</div>
      </div>

      <div className="px-10 pt-10 pb-14">
        <div className="flex items-center gap-2 text-2xl font-serif text-text mb-5"><Brain className="w-5 h-5 text-purple" /> Building memory</div>
        <div className="text-sm text-text-dim mb-4">Problems that have recurred (≥2×) over the last 90 days — the building's learned history.</div>
        <MemoryGrid data={memory.data} loading={memory.loading} />
      </div>
    </div>
  )
}

function AssetCard({ asset, onChange }) {
  const fileRef = useRef(null)
  const [phase, setPhase] = useState('idle')   // idle | uploading | distilling | error
  const [note, setNote] = useState('')
  const [kKey, setKKey] = useState(0)
  const know = useAsync(() => (asset.manual_path ? api.assetKnowledge(asset.id) : Promise.resolve(null)), [asset.id, asset.manual_path, kKey])
  const distilMsg = useCycling(phase === 'distilling')
  const k = know.data || {}
  const specs = k.specs || [], ppm = k.ppm || [], tr = k.troubleshooting || []
  const hasKnow = specs.length || ppm.length || tr.length

  async function upload(file) {
    if (!file) return
    setPhase('uploading'); setNote('')
    try { await api.uploadAssetManual(asset.id, file, file.type, file.name); onChange() }
    catch (e) { setPhase('error'); setNote(e.message || 'Upload failed'); return }
    setPhase('idle')
  }
  async function distil() {
    setPhase('distilling'); setNote('')
    try {
      const r = await api.extractAssetSkills(asset.id)
      if (r.extracted) { setKKey((x) => x + 1); setPhase('idle') }
      else { setPhase('error'); setNote(r.note || 'This manual looks scanned — upload a digital PDF.') }
    } catch (e) { setPhase('error'); setNote(e.message || 'Distil failed') }
  }

  return (
    <Card className="p-5 flex flex-col gap-3">
      <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,image/*" className="hidden"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />

      <div className="flex items-start justify-between">
        <div>
          <div className="text-base text-text">{asset.name}</div>
          <div className="text-xs text-text-faint">{[asset.kind, asset.location].filter(Boolean).join(' · ') || '—'}</div>
        </div>
        <div className="flex items-center gap-2">
          {asset.manual_path ? (
            <>
              <button onClick={() => api.openAssetManual(asset.manual_path)} className="text-xs text-gold hover:underline flex items-center gap-1" title={asset.manual_name}><FileText className="w-3.5 h-3.5" /> manual</button>
              <button onClick={distil} className="text-xs text-purple hover:underline flex items-center gap-1"><Sparkles className="w-3.5 h-3.5" /> {hasKnow ? 're-distil' : 'distil'}</button>
            </>
          ) : (
            <button onClick={() => fileRef.current?.click()} className="text-xs text-text-faint hover:text-text flex items-center gap-1"><FileUp className="w-3.5 h-3.5" /> upload manual</button>
          )}
        </div>
      </div>

      {/* processing / error states */}
      {(phase === 'uploading' || phase === 'distilling') && (
        <div>
          <div className={`flex items-center gap-1.5 text-xs ${phase === 'distilling' ? 'text-purple' : 'text-gold'}`}>
            {phase === 'distilling' ? <Sparkles className="w-3.5 h-3.5 animate-pulse" /> : <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {phase === 'distilling' ? distilMsg : 'Uploading…'}
          </div>
          <div className="w-full h-1 mt-1.5 rounded-full bg-surface-2 overflow-hidden">
            <div className={`h-full w-1/3 rounded-full ${phase === 'distilling' ? 'bg-purple' : 'bg-gold'}`} style={{ animation: 'shimmer 1.2s ease-in-out infinite' }} />
          </div>
        </div>
      )}
      {phase === 'error' && <div className="flex items-start gap-1.5 text-xs text-amber"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" /> {note}</div>}

      {/* knowledge */}
      {phase === 'idle' && (
        know.loading ? <div className="text-xs text-text-faint">Loading…</div>
        : !asset.manual_path ? <div className="text-xs text-text-faint">No manual attached. Upload one to distil specs, PPM intervals & troubleshooting.</div>
        : !hasKnow ? <div className="text-xs text-text-faint">Manual attached — click <span className="text-purple">distil</span> to extract knowledge.</div>
        : (
          <div className="flex flex-col gap-3">
            {!!specs.length && <KSection icon={Gauge} title="Specifications" tone="text-blue">
              {specs.slice(0, 8).map((s, i) => <div key={i} className="flex justify-between gap-3 text-sm py-0.5 border-b border-border-soft"><span className="text-text-dim shrink-0">{s.name}</span><span className="text-text text-right">{s.value}</span></div>)}
            </KSection>}
            {!!ppm.length && <KSection icon={ListChecks} title="PPM intervals" tone="text-gold-soft">
              {ppm.slice(0, 8).map((p, i) => <div key={i} className="text-sm py-0.5 border-b border-border-soft text-text">{p.task} <span className="text-gold-soft">· {p.interval_text || (p.interval_days ? p.interval_days + 'd' : '—')}</span></div>)}
            </KSection>}
            {!!tr.length && <KSection icon={Wrench} title="Troubleshooting" tone="text-amber">
              {tr.slice(0, 8).map((t, i) => <div key={i} className="text-sm py-0.5 border-b border-border-soft"><span className="text-amber">{t.symptom}</span> <span className="text-text-faint">→</span> <span className="text-text-dim">{t.action}</span></div>)}
            </KSection>}
          </div>
        )
      )}
    </Card>
  )
}

function KSection({ icon: Icon, title, tone, children }) {
  return (
    <div>
      <div className={`flex items-center gap-1.5 text-xs uppercase tracking-wide ${tone} mb-1`}><Icon className="w-3.5 h-3.5" /> {title}</div>
      {children}
    </div>
  )
}

function MemoryGrid({ data, loading }) {
  const items = data?.recurring || []
  if (loading) return <Spinner />
  if (!items.length) return <Empty>No recurring problems yet — nothing has come back ≥2× in 90 days. The bot learns as issues accrue.</Empty>
  return (
    <div className="grid grid-cols-3 gap-4">
      {items.map((m, i) => (
        <Card key={i} className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-text"><RotateCcw className="w-4 h-4 text-purple" /> {m.asset || m.example}</div>
            <span className="text-xs font-medium text-purple">{m.count}×</span>
          </div>
          <div className="text-xs text-text-faint mt-1 truncate" title={m.example}>{m.example}</div>
          <div className="text-xs mt-1">{m.open > 0 ? <span className="text-amber">{m.open} still open</span> : <span className="text-green">all resolved</span>} <span className="text-text-faint">· last {m.last_seen}</span></div>
        </Card>
      ))}
    </div>
  )
}
