import { useState, useEffect } from 'react'
import {
  Sparkles,
  Send,
  ClipboardCheck,
  ShieldAlert,
  Radio,
  RefreshCw,
  Gauge,
  Settings2,
  Play,
  QrCode,
  CheckCircle2,
  Loader2,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Card, Pill, Spinner, Empty, SourceBadge } from '../components/ui'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'
import { useAuth } from '../lib/AuthContext'

const READINESS_BAND = { Healthy: 'green', 'Attention Required': 'amber', Critical: 'red' }
const CONCERN_TONE = { high: 'red', elevated: 'amber', watch: 'amber', low: 'green' }
const TEXT_TONE = { green: 'text-green', amber: 'text-amber', red: 'text-red', neutral: 'text-text-dim' }

export default function Intelligence() {
  const { building } = useBuilding()
  const { role } = useAuth()
  const canPair = role === 'owner' || role === 'fm' || role === 'system'
  const [refreshKey, setRefreshKey] = useState(0)
  const refresh = () => setRefreshKey((k) => k + 1)

  const readiness = useAsync(() => api.readiness(building), [building, refreshKey])
  const compliance = useAsync(() => api.compliance(building), [building, refreshKey])
  const watchlist = useAsync(() => api.watchlist(building), [building, refreshKey])
  const handover = useAsync(() => api.handover(building), [building, refreshKey])

  return (
    <div>
      <PageHeader subtitle="AI intelligence, compliance & escalation" />

      <div className="px-10 pt-6 grid grid-cols-[1fr_360px] gap-8 pb-10">
        <div className="flex flex-col gap-8">
          <AskBuilding building={building} />

          <ReadinessCard data={readiness.data} loading={readiness.loading} />

          <div className="grid grid-cols-2 gap-6">
            <ComplianceCard data={compliance.data} loading={compliance.loading} />
            <WatchlistCard data={watchlist.data} loading={watchlist.loading} />
          </div>
        </div>

        <div className="flex flex-col gap-8">
          {canPair && <WhatsAppCard />}
          <HandoverCard data={handover.data} loading={handover.loading} />
          <SweepsCard building={building} onRun={refresh} />
          <SlaCard building={building} />
        </div>
      </div>
    </div>
  )
}

function AskBuilding({ building }) {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState(null)
  const [busy, setBusy] = useState(false)

  async function ask(e) {
    e.preventDefault()
    if (!q.trim()) return
    setBusy(true)
    try {
      const res = await api.ask(q, building)
      setAnswer(res)
    } catch (err) {
      setAnswer({ text: `Error: ${err.message}`, source: '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
        <Sparkles className="w-4 h-4 text-purple" /> Ask the Building
      </div>
      <form onSubmit={ask} className="relative">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. what is the riskiest system?"
          className="w-full bg-bg border border-border rounded-xl py-3 pl-4 pr-12 text-sm text-text placeholder:text-text-faint outline-none focus:border-gold/50"
        />
        <button type="submit" disabled={busy} className="absolute right-3 top-1/2 -translate-y-1/2 text-gold disabled:opacity-50">
          <Send className="w-4 h-4" />
        </button>
      </form>
      {answer && (
        <div className="mt-3 text-sm text-text-dim whitespace-pre-line border-t border-border-soft pt-3">
          {answer.text}
          {answer.source && (
            <div className="mt-2">
              <SourceBadge source={answer.source} />
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

function ReadinessCard({ data, loading }) {
  if (loading) return <Card className="p-5"><Spinner /></Card>
  if (!data) return null
  const tone = READINESS_BAND[data.band] || 'amber'
  const c = data.components || {}
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
        <Gauge className="w-4 h-4" /> {data.label}
      </div>
      <div className="flex items-end gap-4 mb-4">
        <div className={`font-serif text-5xl ${TEXT_TONE[tone]}`}>{data.readiness}</div>
        <Pill tone={tone}>{data.band}</Pill>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <Metric label="Asset health avg" value={c.asset_health_avg} />
        <Metric label="Rounds completion" value={`${c.rounds_completion_avg}%`} />
        <Metric label="Overdue PPM" value={c.overdue_ppm} />
        <Metric label="Compliance penalty" value={c.compliance_penalty} />
      </div>
      {data.contributors?.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border-soft text-xs text-text-faint">
          {data.contributors.map((x, i) => (
            <div key={i}>• {x}</div>
          ))}
        </div>
      )}
    </Card>
  )
}

function ComplianceCard({ data, loading }) {
  if (loading) return <Card className="p-5"><Spinner /></Card>
  if (!data) return null
  const tone = data.compliance_risk === 'high' ? 'red' : data.compliance_risk === 'medium' ? 'amber' : 'green'
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint">
          <ClipboardCheck className="w-4 h-4" /> Compliance
        </div>
        <Pill tone={tone}>{data.compliance_risk} risk</Pill>
      </div>
      <Group label="Overdue PPM">
        {(data.overdue_ppm || []).map((p, i) => (
          <Row key={i} text={p.asset} sub={`${p.days_overdue}d overdue`} tone="red" />
        ))}
        {!data.overdue_ppm?.length && <Empty>None</Empty>}
      </Group>
      <Group label="Due soon">
        <div className="text-sm text-text-dim">{(data.due_soon_ppm || []).join(', ') || '—'}</div>
      </Group>
      <Group label="Stale assets">
        {(data.stale_assets || []).map((s, i) => (
          <Row key={i} text={s.asset} sub={`${s.days_since_check}d since check`} tone="amber" />
        ))}
        {!data.stale_assets?.length && <Empty>None</Empty>}
      </Group>
    </Card>
  )
}

function WatchlistCard({ data, loading }) {
  if (loading) return <Card className="p-5"><Spinner /></Card>
  const watch = data?.watchlist || []
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
        <Radio className="w-4 h-4" /> Failure Watchlist
      </div>
      {watch.length === 0 ? (
        <Empty>All assets nominal.</Empty>
      ) : (
        <div className="flex flex-col gap-3">
          {watch.map((w, i) => {
            const tone = CONCERN_TONE[w.concern] || 'amber'
            return (
              <div key={i} className="border-b border-border-soft pb-3 last:border-0">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-text">{w.asset}</span>
                  <Pill tone={tone}>{w.concern}</Pill>
                </div>
                <ul className="text-xs text-text-faint mt-1">
                  {(w.signals || []).map((s, j) => (
                    <li key={j}>• {s}</li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

// WhatsApp bot pairing — the owner links the bot without SSH. The bot pushes its
// QR + status to the API; we poll and render the QR until it's connected.
const BRIDGE_TONE = { connected: 'green', waiting_scan: 'amber', disconnected: 'red', unknown: 'neutral' }
const BRIDGE_LABEL = {
  connected: 'Connected',
  waiting_scan: 'Waiting for scan',
  disconnected: 'Disconnected',
  unknown: 'Not reporting yet',
}

function WhatsAppCard() {
  const [state, setState] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const tick = () =>
      api
        .bridgeState()
        .then((d) => { if (alive) { setState(d); setErr(null) } })
        .catch((e) => { if (alive) setErr(e) })
    tick()
    const id = setInterval(tick, 3000)   // QR rotates; poll keeps it fresh
    return () => { alive = false; clearInterval(id) }
  }, [])

  const status = state?.status || 'unknown'
  const tone = BRIDGE_TONE[status] || 'neutral'

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint">
          <QrCode className="w-4 h-4" /> WhatsApp Bot
        </div>
        <Pill tone={tone}>{BRIDGE_LABEL[status] || status}</Pill>
      </div>

      {err && <div className="text-sm text-red">Couldn't reach the bot bridge.</div>}

      {status === 'connected' && (
        <div className="flex items-center gap-2 text-sm text-green">
          <CheckCircle2 className="w-4 h-4" /> Bot is linked and delivering messages.
        </div>
      )}

      {status === 'waiting_scan' && state?.qr && (
        <div className="flex flex-col items-center gap-3">
          <img src={state.qr} alt="WhatsApp pairing QR" className="w-48 h-48 rounded-lg border border-border bg-white p-2" />
          <div className="text-xs text-text-faint text-center">
            On the bot's phone: WhatsApp → <span className="text-text-dim">Linked devices → Link a device</span> → scan this.
          </div>
        </div>
      )}

      {status === 'waiting_scan' && !state?.qr && (
        <div className="flex items-center gap-2 text-sm text-text-faint">
          <Loader2 className="w-4 h-4 animate-spin" /> Generating pairing code…
        </div>
      )}

      {(status === 'disconnected' || status === 'unknown') && (
        <div className="text-sm text-text-faint">
          {status === 'disconnected'
            ? 'Bot lost its WhatsApp link — it will show a new QR to re-pair.'
            : 'Waiting for the bot to report in. Make sure the bot service is running.'}
        </div>
      )}
    </Card>
  )
}

function HandoverCard({ data, loading }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint">
          <ShieldAlert className="w-4 h-4" /> Shift Handover
        </div>
        {data?.priority && <Pill tone={data.priority === 'High' ? 'red' : 'amber'}>{data.priority}</Pill>}
      </div>
      {loading ? (
        <Spinner />
      ) : (
        <div className="text-sm text-text-dim whitespace-pre-line">{data?.text || '—'}</div>
      )}
      {data?.source && (
        <div className="mt-3">
          <SourceBadge source={data.source} />
        </div>
      )}
    </Card>
  )
}

function SweepsCard({ building, onRun }) {
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(false)

  async function run(which) {
    setBusy(true)
    try {
      const res = which === 'esc' ? await api.runEscalations(building) : await api.runReminders(building)
      setOut(res)
      onRun?.()
    } catch (e) {
      setOut({ error: e.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
        <RefreshCw className="w-4 h-4" /> Escalation Sweeps
      </div>
      <div className="flex gap-2 mb-3">
        <button
          disabled={busy}
          onClick={() => run('esc')}
          className="flex-1 flex items-center justify-center gap-2 text-sm border border-border rounded-lg py-2 text-text-dim hover:border-gold/40 disabled:opacity-50"
        >
          <Play className="w-4 h-4" /> Issue SLA
        </button>
        <button
          disabled={busy}
          onClick={() => run('rem')}
          className="flex-1 flex items-center justify-center gap-2 text-sm border border-border rounded-lg py-2 text-text-dim hover:border-gold/40 disabled:opacity-50"
        >
          <Play className="w-4 h-4" /> Round sweep
        </button>
      </div>
      {out && (
        <pre className="text-xs text-text-faint bg-bg border border-border rounded-lg p-3 overflow-x-auto">
          {JSON.stringify(out, null, 2)}
        </pre>
      )}
    </Card>
  )
}

function SlaCard({ building }) {
  const [refreshKey, setRefreshKey] = useState(0)
  const cfg = useAsync(() => api.slaConfig(building), [building, refreshKey])
  const [edit, setEdit] = useState(null)

  const sla = cfg.data?.sla || {}

  async function save(priority, response_hours, resolution_hours) {
    await api.setSlaConfig({ priority, response_hours: Number(response_hours), resolution_hours: Number(resolution_hours), building })
    setEdit(null)
    setRefreshKey((k) => k + 1)
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3">
        <Settings2 className="w-4 h-4" /> SLA Targets (hours)
      </div>
      {cfg.loading ? (
        <Spinner />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-text-faint">
              <th className="text-left font-normal py-1">Priority</th>
              <th className="text-right font-normal">Response</th>
              <th className="text-right font-normal">Resolution</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {Object.entries(sla).map(([priority, v]) =>
              edit === priority ? (
                <EditRow key={priority} priority={priority} v={v} onSave={save} onCancel={() => setEdit(null)} />
              ) : (
                <tr key={priority} className="border-t border-border-soft">
                  <td className="py-2 capitalize text-text">{priority}</td>
                  <td className="text-right text-text-dim">{v.response_hours}</td>
                  <td className="text-right text-text-dim">{v.resolution_hours}</td>
                  <td className="text-right">
                    <button onClick={() => setEdit(priority)} className="text-xs text-gold">
                      edit
                    </button>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      )}
    </Card>
  )
}

function EditRow({ priority, v, onSave, onCancel }) {
  const [resp, setResp] = useState(v.response_hours)
  const [reso, setReso] = useState(v.resolution_hours)
  return (
    <tr className="border-t border-border-soft">
      <td className="py-2 capitalize text-text">{priority}</td>
      <td className="text-right">
        <input
          value={resp}
          onChange={(e) => setResp(e.target.value)}
          className="w-14 bg-bg border border-border rounded px-1 text-right text-text"
        />
      </td>
      <td className="text-right">
        <input
          value={reso}
          onChange={(e) => setReso(e.target.value)}
          className="w-14 bg-bg border border-border rounded px-1 text-right text-text"
        />
      </td>
      <td className="text-right">
        <button onClick={() => onSave(priority, resp, reso)} className="text-xs text-green mr-1">
          save
        </button>
        <button onClick={onCancel} className="text-xs text-text-faint">
          x
        </button>
      </td>
    </tr>
  )
}

function Metric({ label, value }) {
  return (
    <div>
      <div className="text-xs text-text-faint">{label}</div>
      <div className="text-text">{value ?? '—'}</div>
    </div>
  )
}

function Group({ label, children }) {
  return (
    <div className="mb-3">
      <div className="text-xs text-text-faint mb-1">{label}</div>
      {children}
    </div>
  )
}

function Row({ text, sub, tone }) {
  return (
    <div className="flex items-center justify-between text-sm py-1">
      <span className="text-text-dim">{text}</span>
      <span className={`text-xs ${TEXT_TONE[tone] || 'text-text-faint'}`}>{sub}</span>
    </div>
  )
}
