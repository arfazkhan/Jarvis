import { useMemo, useState } from 'react'
import {
  Box,
  X,
  Activity,
  CalendarCheck,
  TriangleAlert,
  History,
  Sparkles,
  ChevronRight,
  CheckCircle2,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, Drawer, Empty, Spinner, ProgressBar, SourceBadge, ConfidenceBadge } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

const BAND_TONE = { good: 'green', watch: 'amber', risk: 'red' }
const TEXT_TONE = { green: 'text-green', amber: 'text-amber', red: 'text-red', neutral: 'text-text-dim' }

export default function Assets() {
  const { building } = useBuilding()
  const [selected, setSelected] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const health = useAsync(() => api.health(building), [building, refreshKey])
  const ppm = useAsync(() => api.ppmSchedule(building), [building, refreshKey])

  const assets = health.data?.assets || []
  const ppmByAsset = useMemo(() => {
    const m = {}
    for (const p of ppm.data?.schedules || []) m[p.asset] = p
    return m
  }, [ppm.data])

  return (
    <div>
      <PageHeader subtitle="Asset health, history & preventive maintenance" />

      <div className="px-10 pt-6">
        <div className="text-2xl font-serif text-text">{assets.length} Assets</div>
        <div className="text-sm text-text-faint mb-5">
          Assets are defined by tagging checklist items with an asset (Setup → Checklists)
          and by PPM schedules (Setup → PPM). This page shows their health, history & maintenance.
        </div>
      </div>

      <div className="px-10 pb-10">
        {health.loading ? (
          <Spinner />
        ) : assets.length === 0 ? (
          <Empty>No assets found.</Empty>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {assets.map((a) => {
              const tone = BAND_TONE[a.band] || 'neutral'
              const p = ppmByAsset[a.asset]
              return (
                <button
                  key={a.asset}
                  onClick={() => setSelected(a)}
                  className="border border-border rounded-2xl p-5 text-left hover:border-gold/30"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Box className="w-4 h-4 text-text-dim" />
                      <span className="text-sm text-text">{a.asset}</span>
                    </div>
                    <Pill tone={tone}>{a.band}</Pill>
                  </div>
                  <div className="flex items-end gap-2 mb-3">
                    <div className={`font-serif text-3xl ${TEXT_TONE[tone]}`}>{a.score}</div>
                    <div className="text-xs text-text-faint mb-1">/ 100</div>
                  </div>
                  <ProgressBar pct={a.score} tone={tone} className="mb-3" />
                  <div className="text-xs text-text-faint">
                    {a.open_issues > 0 && `${a.open_issues} open issue(s)`}
                    {a.open_issues > 0 && (a.overdue_ppm || p?.overdue) && ' · '}
                    {(a.overdue_ppm || p?.overdue) && 'PPM overdue'}
                    {!a.open_issues && !a.overdue_ppm && !p?.overdue && 'Nominal'}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      <AssetDrawer
        asset={selected}
        ppm={selected ? ppmByAsset[selected.asset] : null}
        building={building}
        onClose={() => setSelected(null)}
        onChanged={() => setRefreshKey((k) => k + 1)}
      />
    </div>
  )
}

function AssetDrawer({ asset, ppm, building, onClose, onChanged }) {
  const hist = useAsync(() => (asset ? api.assetHistory(asset.asset, building) : Promise.resolve(null)), [asset?.asset])
  const rca = useAsync(() => (asset ? api.rca(asset.asset, building) : Promise.resolve(null)), [asset?.asset])
  const [busy, setBusy] = useState(false)

  if (!asset) return null
  const tone = BAND_TONE[asset.band] || 'neutral'

  async function markDone() {
    setBusy(true)
    try {
      await api.ppmDone(asset.asset, { date: new Date().toISOString().slice(0, 10), building })
      onChanged()
      onClose()
    } catch (e) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Drawer open={!!asset} onClose={onClose} width={500}>
      <div className="p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <Box className="w-5 h-5 text-text-dim" />
            <span className="font-serif text-2xl text-text">{asset.asset}</span>
          </div>
          <button onClick={onClose} className="text-text-faint">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex items-center gap-3 mb-6">
          <div className={`font-serif text-4xl ${TEXT_TONE[tone]}`}>{asset.score}</div>
          <div>
            <Pill tone={tone}>{asset.band}</Pill>
            <div className="text-xs text-text-faint mt-1">{asset.reasons?.join(' · ') || 'No concerns'}</div>
          </div>
        </div>

        {ppm && (
          <div className="border border-border rounded-xl p-4 mb-6">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs uppercase tracking-wide text-text-faint flex items-center gap-2">
                <CalendarCheck className="w-4 h-4" /> Preventive Maintenance
              </div>
              <Pill tone={ppm.overdue ? 'red' : ppm.status === 'due_soon' ? 'amber' : 'green'}>{ppm.status}</Pill>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm mb-3">
              <Field label="Last done" value={ppm.last_done} />
              <Field label="Due date" value={ppm.due_date} />
              <Field label="Interval" value={`${ppm.interval_days} days`} />
              <Field
                label="Days remaining"
                value={ppm.days_remaining}
                tone={ppm.overdue ? 'red' : undefined}
              />
            </div>
            <button
              disabled={busy}
              onClick={markDone}
              className="flex items-center gap-2 text-sm border border-border rounded-lg px-3 py-2 text-text-dim hover:border-gold/40 disabled:opacity-50"
            >
              <CheckCircle2 className="w-4 h-4" /> Mark PPM done today
            </button>
          </div>
        )}

        {rca.data && (
          <div className="border border-border rounded-xl p-4 mb-6">
            <div className="text-xs uppercase tracking-wide text-text-faint mb-2 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-purple" /> Root-Cause Analysis
              <span className="ml-auto">
                <SourceBadge source={rca.data.source} />
              </span>
            </div>
            {rca.data.probable_cause ? (
              <>
                <div className="text-sm text-text mb-2">{rca.data.probable_cause}</div>
                <ConfidenceBadge confidence={rca.data.confidence} />
              </>
            ) : (
              <div className="text-sm text-text-dim whitespace-pre-line">{rca.data.text}</div>
            )}
            <div className="text-xs text-text-faint mt-2">Arvis suggests — review before acting.</div>
          </div>
        )}

        {hist.data?.issues?.length > 0 && (
          <>
            <div className="text-xs uppercase tracking-wide text-text-faint mb-2 flex items-center gap-2">
              <TriangleAlert className="w-4 h-4" /> Issues
            </div>
            <div className="flex flex-col gap-2 mb-6">
              {hist.data.issues.map((iss) => (
                <div key={iss.id} className="flex items-center justify-between text-sm border border-border-soft rounded-lg px-3 py-2">
                  <span className="text-text-dim">{iss.title}</span>
                  <Pill tone={iss.status === 'resolved' ? 'green' : 'amber'}>{iss.status}</Pill>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="text-xs uppercase tracking-wide text-text-faint mb-2 flex items-center gap-2">
          <History className="w-4 h-4" /> Recent Readings
        </div>
        {hist.loading ? (
          <Spinner />
        ) : hist.data?.entries?.length ? (
          <div className="flex flex-col gap-1">
            {hist.data.entries.slice(0, 15).map((e, i) => (
              <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-border-soft">
                <div>
                  <div className="text-text-dim">{e.item_id}</div>
                  <div className="text-xs text-text-faint">{fmt(e.ts)}</div>
                </div>
                <div className={`text-sm ${e.is_issue ? 'text-red' : 'text-text'}`}>{e.value}</div>
              </div>
            ))}
          </div>
        ) : (
          <Empty>No readings recorded.</Empty>
        )}
      </div>
    </Drawer>
  )
}

function Field({ label, value, tone }) {
  return (
    <div>
      <div className="text-xs text-text-faint">{label}</div>
      <div className={`text-sm ${tone ? TEXT_TONE[tone] : 'text-text'}`}>{value ?? '—'}</div>
    </div>
  )
}

function fmt(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}
