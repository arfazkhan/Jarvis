import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Info, Sparkles, ArrowRight, BatteryWarning, Flame, Droplets, Waves, Box } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Card, IconCircle } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

const BAND_TONE = { Healthy: 'green', 'Attention Required': 'amber', Critical: 'red' }
const CONCERN_TONE = { high: 'red', elevated: 'amber', watch: 'amber', low: 'green' }

export default function Overview() {
  const navigate = useNavigate()
  const { building } = useBuilding()
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(false)

  const readiness = useAsync(() => api.readiness(building), [building])
  const health = useAsync(() => api.health(building), [building])
  const watchlist = useAsync(() => api.watchlist(building), [building])
  const today = useAsync(() => api.today(building), [building])
  const ppm = useAsync(() => api.ppmSchedule(building), [building])

  const r = readiness.data
  const band = r?.band || 'Attention Required'
  const tone = BAND_TONE[band] || 'amber'

  const whyCards = useMemo(() => buildWhyCards(health.data, today.data, ppm.data), [health.data, today.data, ppm.data])
  const watch = watchlist.data?.watchlist || []

  async function submitAsk(e) {
    e.preventDefault()
    if (!q.trim()) return
    setAsking(true)
    try {
      const res = await api.ask(q, building)
      setAnswer(res.text)
    } catch (err) {
      setAnswer(`Error: ${err.message}`)
    } finally {
      setAsking(false)
    }
  }

  return (
    <div>
      <PageHeader />

      <div className="px-10 pt-8 pb-10 grid grid-cols-[1fr_420px] gap-10">
        <div>
          <div className="flex items-center gap-2 text-3xl font-serif text-text">
            Maintenance Readiness
            <Info
              className="w-4 h-4 text-text-faint cursor-help"
              title="Maintenance/inspection readiness from checklist data — not live equipment condition. Sensors upgrade this score in Phase 1."
            />
          </div>
          <div className="text-sm text-text-faint mt-1">Current state of building operations</div>

          <div className="flex items-end gap-8 mt-8">
            <div className="font-serif text-[6.5rem] leading-none text-gold-soft">
              {readiness.loading ? '--' : r?.readiness ?? '--'}
            </div>
            <div className="h-20 w-px bg-border" />
            <div>
              <div className={`text-xl font-medium ${TEXT_TONE[tone]}`}>{band}</div>
              <div className="text-sm text-text-faint mt-1 max-w-[260px]">
                {tone === 'red'
                  ? 'Critical areas need urgent action.'
                  : tone === 'green'
                  ? 'Building operations are in good shape.'
                  : 'Some critical areas need immediate attention.'}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="px-10">
        <div className="text-sm text-text-dim mb-4">Why this score?</div>
        <div className="grid grid-cols-3 gap-6 pb-10 border-b border-border-soft">
          {whyCards.map((c, i) => (
            <div key={i} className="flex items-start gap-4">
              <IconCircle tone={c.tone}>
                <AssetIcon name={c.title} className="w-5 h-5" />
              </IconCircle>
              <div>
                <div className="text-text text-base">{c.title}</div>
                <div className={`text-sm font-medium ${TEXT_TONE[c.tone]}`}>{c.value}</div>
                <div className="text-xs text-text-faint mt-0.5">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="px-10 pt-8">
        <div className="flex items-center justify-between mb-4">
          <div className="text-sm text-text-dim">Watchlist</div>
          <button onClick={() => navigate('/assets')} className="text-sm text-gold hover:underline flex items-center gap-1">
            View all assets <ArrowRight className="w-4 h-4" />
          </button>
        </div>
        <div className="grid grid-cols-4 gap-4">
          {watch.slice(0, 4).map((w, i) => {
            const wTone = CONCERN_TONE[w.concern] || 'amber'
            return (
              <Card key={i} className="p-4">
                <div className="flex items-center gap-2">
                  <AssetIcon name={w.asset} className={`w-4 h-4 ${TEXT_TONE[wTone]}`} />
                  <span className="text-sm text-text">{w.asset}</span>
                </div>
                <div className={`text-sm mt-2 font-medium ${TEXT_TONE[wTone]}`}>
                  {w.concern ? w.concern[0].toUpperCase() + w.concern.slice(1) + ' concern' : w.signals?.[0]}
                </div>
              </Card>
            )
          })}
          {watch.length === 0 && !watchlist.loading && (
            <div className="col-span-4 text-sm text-text-faint">No watchlist items — all assets nominal.</div>
          )}
        </div>
      </div>

      <div className="px-10 py-10">
        <form onSubmit={submitAsk} className="relative">
          <Sparkles className="w-4 h-4 text-purple absolute left-5 top-1/2 -translate-y-1/2" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Ask Arvis anything about your building..."
            className="w-full bg-surface border border-border rounded-2xl py-4 pl-12 pr-16 text-sm text-text placeholder:text-text-faint outline-none focus:border-gold/50"
          />
          <kbd className="absolute right-5 top-1/2 -translate-y-1/2 text-xs text-text-faint border border-border rounded px-1.5 py-0.5">
            {asking ? '...' : '⌘ K'}
          </kbd>
        </form>
        {answer && (
          <div className="mt-3 text-sm text-text-dim bg-surface border border-border rounded-xl p-4 whitespace-pre-line">
            {answer}
          </div>
        )}
      </div>
    </div>
  )
}

function buildWhyCards(health, today, ppm) {
  const cards = []
  const riskAsset = health?.assets?.find((a) => a.band === 'risk') || health?.assets?.[0]
  if (riskAsset) {
    cards.push({
      title: riskAsset.asset,
      tone: riskAsset.band === 'risk' ? 'red' : riskAsset.band === 'watch' ? 'amber' : 'green',
      value: riskAsset.band === 'risk' ? 'Risk' : riskAsset.band === 'watch' ? 'Watch' : 'Good',
      detail: riskAsset.reasons?.[0] || `${riskAsset.score}/100`,
    })
  }
  const run = today?.runs?.find((r) => r.status !== 'submitted') || today?.runs?.[0]
  if (run) {
    cards.push({
      title: run.name,
      tone: run.completion_pct >= 80 ? 'green' : 'amber',
      value: `${run.completion_pct}% complete`,
      detail: `${run.issues?.length || 0} issue(s) · ${run.status}`,
    })
  }
  const overdue = ppm?.schedules?.find((p) => p.overdue) || ppm?.schedules?.[0]
  if (overdue) {
    cards.push({
      title: `${overdue.asset} PPM`,
      tone: overdue.overdue ? 'purple' : 'green',
      value: overdue.overdue ? `Overdue by ${Math.abs(overdue.days_remaining)} days` : overdue.status,
      detail: overdue.overdue ? 'Maintenance is overdue' : `Due ${overdue.due_date}`,
    })
  }
  while (cards.length < 3) cards.push({ title: '—', tone: 'neutral', value: '—', detail: '' })
  return cards
}

const TEXT_TONE = {
  red: 'text-red',
  amber: 'text-amber',
  green: 'text-green',
  blue: 'text-blue',
  purple: 'text-purple',
  neutral: 'text-text-dim',
}

function AssetIcon({ name = '', className }) {
  const n = name.toLowerCase()
  if (n.includes('dg') || n.includes('generator') || n.includes('battery')) return <BatteryWarning className={className} />
  if (n.includes('fire')) return <Flame className={className} />
  if (n.includes('tank') || n.includes('oh ') || n.includes('water')) return <Waves className={className} />
  if (n.includes('wtp') || n.includes('treatment')) return <Droplets className={className} />
  return <Box className={className} />
}
