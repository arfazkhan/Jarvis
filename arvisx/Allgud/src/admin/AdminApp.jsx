import { useState, useEffect, useCallback } from 'react'
import {
  QrCode, BarChart3, LogIn, LogOut, Lock, User, Loader2, CheckCircle2,
  RefreshCw, ClipboardList, TriangleAlert, CalendarCheck, Users,
} from 'lucide-react'
import { AllGudLogo } from '../components/Logo'
import { Card, Pill, Spinner } from '../components/ui'
import { api, setToken } from '../api/client'

// AllGud operator admin panel — SEPARATE from the building console (own subdomain).
// Only the `admin` role gets in. Bot pairing (QR) + building performance analytics.
export default function AdminApp() {
  const [status, setStatus] = useState('checking') // checking | login | authed
  const [me, setMe] = useState(null)
  const [tab, setTab] = useState('analytics')

  const check = useCallback(() => {
    setStatus('checking')
    api.me()
      .then((r) => (r && r.role === 'admin' ? (setMe(r), setStatus('authed')) : setStatus('login')))
      .catch(() => setStatus('login'))
  }, [])
  useEffect(() => check(), [check])

  if (status === 'checking') return <Center><Loader2 className="animate-spin text-text-faint" /></Center>
  if (status === 'login') return <AdminLogin onAuthed={check} />

  return (
    <div className="min-h-screen bg-bg text-text font-sans">
      <header className="flex items-center justify-between px-8 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <AllGudLogo textClass="text-xl" markClass="w-6 h-6" />
          <span className="text-xs uppercase tracking-wide text-text-faint border border-border rounded px-2 py-0.5">Admin</span>
        </div>
        <div className="flex items-center gap-4 text-sm text-text-faint">
          <span>{me?.username} · operator</span>
          <button onClick={() => { setToken(''); check() }} className="flex items-center gap-1 hover:text-text"><LogOut className="w-4 h-4" /> Sign out</button>
        </div>
      </header>

      <nav className="flex gap-1 px-8 pt-4">
        <Tab active={tab === 'analytics'} onClick={() => setTab('analytics')} icon={BarChart3}>Analytics</Tab>
        <Tab active={tab === 'bot'} onClick={() => setTab('bot')} icon={QrCode}>WhatsApp Bot</Tab>
      </nav>

      <main className="px-8 py-6">
        {tab === 'analytics' ? <Analytics /> : <BotPairing />}
      </main>
    </div>
  )
}

function Center({ children }) {
  return <div className="min-h-screen bg-bg flex items-center justify-center">{children}</div>
}
function Tab({ active, onClick, icon: Icon, children }) {
  return (
    <button onClick={onClick} className={`flex items-center gap-2 px-4 py-2 text-sm rounded-t-lg border-b-2 ${
      active ? 'border-gold text-text' : 'border-transparent text-text-faint hover:text-text'}`}>
      <Icon className="w-4 h-4" /> {children}
    </button>
  )
}

function AdminLogin({ onAuthed }) {
  const [u, setU] = useState(''); const [p, setP] = useState('')
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(null)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      const res = await api.login(u.trim(), p)
      if (res.role !== 'admin') { setToken(''); setErr('Not an operator account.'); setBusy(false); return }
      setToken(res.token)          // persist the token, else /auth/me 401s
      onAuthed()
    } catch (e2) {
      setErr(String(e2.message).startsWith('401') ? 'Wrong username or password.' : e2.message); setBusy(false)
    }
  }
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm">
        <div className="mb-8 flex justify-center"><AllGudLogo textClass="text-2xl" /></div>
        <div className="bg-surface border border-border rounded-2xl p-6">
          <div className="font-serif text-xl text-text mb-1">Operator sign-in</div>
          <div className="text-sm text-text-faint mb-5">AllGud admin panel</div>
          <label className="block text-xs text-text-faint mb-1">Username</label>
          <div className="flex items-center gap-2 bg-bg border border-border rounded-xl px-3 mb-4 focus-within:border-gold/50">
            <User size={16} className="text-text-faint" />
            <input autoFocus value={u} onChange={(e) => setU(e.target.value)} className="flex-1 bg-transparent py-3 text-sm text-text outline-none" />
          </div>
          <label className="block text-xs text-text-faint mb-1">Password</label>
          <div className="flex items-center gap-2 bg-bg border border-border rounded-xl px-3 mb-5 focus-within:border-gold/50">
            <Lock size={16} className="text-text-faint" />
            <input type="password" value={p} onChange={(e) => setP(e.target.value)} className="flex-1 bg-transparent py-3 text-sm text-text outline-none" />
          </div>
          {err && <div className="text-sm text-red bg-red-bg rounded-lg px-3 py-2 mb-4">{err}</div>}
          <button type="submit" disabled={busy || !u || !p} className="w-full flex items-center justify-center gap-2 bg-primary text-white rounded-xl py-3 text-sm font-medium disabled:opacity-50">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />} Sign in
          </button>
        </div>
      </form>
    </div>
  )
}

// ── Analytics ────────────────────────────────────────────────────────────────
function Analytics() {
  const [building, setBuilding] = useState('one-anthem')
  const [days, setDays] = useState(7)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    api.adminAnalytics(building, days)
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(e))
      .finally(() => setLoading(false))
  }, [building, days])
  useEffect(() => load(), [load])

  if (loading) return <Spinner />
  if (err) return <div className="text-red text-sm">{err.message}</div>
  if (!data) return null
  const { rounds, issues, ppm, technicians } = data

  return (
    <div className="max-w-5xl">
      <div className="flex items-center gap-3 mb-5">
        <input value={building} onChange={(e) => setBuilding(e.target.value)} className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text" />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text">
          {[7, 14, 30].map((d) => <option key={d} value={d}>last {d} days</option>)}
        </select>
        <button onClick={load} className="flex items-center gap-1 text-sm text-gold"><RefreshCw className="w-4 h-4" /> Refresh</button>
        <div className="flex-1" />
        <SendSummary building={building} />
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <Stat icon={ClipboardList} label="Round submit rate" value={`${rounds.submit_rate_pct}%`} sub={`${rounds.submitted}/${rounds.total} submitted · ${rounds.lapsed} lapsed`} tone={tone(rounds.submit_rate_pct)} />
        <Stat icon={CheckCircle2} label="Avg completion" value={`${rounds.avg_completion_pct}%`} sub={`${rounds.open} still open`} tone={tone(rounds.avg_completion_pct)} />
        <Stat icon={TriangleAlert} label="Issue action rate" value={issues.action_rate_pct == null ? '—' : `${issues.action_rate_pct}%`} sub={`${issues.resolved}/${issues.raised} resolved · ${issues.open} open`} tone={tone(issues.action_rate_pct ?? 0)} />
        <Stat icon={CalendarCheck} label="PPM overdue" value={ppm.overdue} sub={`${ppm.due_soon} due soon · ${ppm.scheduled} scheduled`} tone={ppm.overdue > 0 ? 'red' : 'green'} />
      </div>

      <TrendCard trend={data.trend} avg={rounds.avg_completion_pct} />

      <Card className="p-5 mb-6">
        <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Issue SLA</div>
        <div className="grid grid-cols-4 gap-4">
          <Mini label="SLA breached" value={issues.sla_breached ?? 0} tone={issues.sla_breached ? 'red' : 'green'} />
          <Mini label="At risk" value={issues.sla_at_risk ?? 0} tone={issues.sla_at_risk ? 'amber' : 'green'} />
          <Mini label="Open" value={issues.open} />
          <Mini label="Avg resolution" value={issues.avg_resolution_hrs == null ? '—' : `${issues.avg_resolution_hrs}h`} />
        </div>
      </Card>

      <Card className="p-5">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3"><Users className="w-4 h-4" /> Technician performance</div>
        <table className="w-full text-sm">
          <thead><tr className="text-xs text-text-faint text-left"><th className="py-1 font-normal">Technician</th><th className="font-normal">Assigned</th><th className="font-normal">Submitted</th><th className="font-normal">Completion</th></tr></thead>
          <tbody>
            {technicians.map((t) => (
              <tr key={t.name} className="border-t border-border-soft">
                <td className="py-2 text-text">{t.name}</td>
                <td className="text-text-dim">{t.assigned}</td>
                <td className="text-text-dim">{t.submitted}</td>
                <td><Pill tone={tone(t.completion_pct)}>{t.completion_pct}%</Pill></td>
              </tr>
            ))}
            {!technicians.length && <tr><td colSpan={4} className="py-3 text-text-faint">No technicians.</td></tr>}
          </tbody>
        </table>
      </Card>
      <div className="text-xs text-text-faint mt-4">Real counts from checklist data over the window — not estimates.</div>
    </div>
  )
}
function tone(pct) { return pct >= 80 ? 'green' : pct >= 50 ? 'amber' : 'red' }

function SendSummary({ building }) {
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  async function send(period) {
    setBusy(period); setMsg('')
    try {
      const r = await api.sendSummary(building, period)
      setMsg(r.sent_to_owner ? `${period === 'month' ? 'Monthly' : 'Weekly'} summary sent to owner` : 'No owner number set')
    } catch (e) { setMsg(e.message) } finally { setBusy('') }
  }
  return (
    <div className="flex items-center gap-2">
      {msg && <span className="text-xs text-green">{msg}</span>}
      <button disabled={busy === 'week'} onClick={() => send('week')}
        className="text-xs border border-border rounded-lg px-3 py-1.5 text-text-dim hover:border-gold/40 disabled:opacity-50">Send weekly</button>
      <button disabled={busy === 'month'} onClick={() => send('month')}
        className="text-xs border border-border rounded-lg px-3 py-1.5 text-text-dim hover:border-gold/40 disabled:opacity-50">Send monthly</button>
    </div>
  )
}

function TrendCard({ trend, avg }) {
  const data = trend || []
  if (!data.length) return null
  const today = data[data.length - 1]
  const barTone = { green: 'bg-green', amber: 'bg-amber', red: 'bg-red' }
  return (
    <Card className="p-5 mb-6">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-wide text-text-faint">Completion trend (daily)</div>
        <div className="text-xs text-text-faint">
          today <span className={tone(today.completion_pct) === 'red' ? 'text-red' : tone(today.completion_pct) === 'amber' ? 'text-amber' : 'text-green'}>{today.completion_pct}%</span>
          {' · '}avg <span className="text-text">{avg}%</span>
        </div>
      </div>
      <div className="flex items-end gap-[3px] h-28">
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex flex-col justify-end group relative" title={`${d.date}: ${d.completion_pct}% · ${d.runs} round(s) · ${d.issues_opened} issue(s)`}>
            <div className={`${barTone[tone(d.completion_pct)] || 'bg-surface-2'} rounded-t`} style={{ height: `${Math.max(2, d.completion_pct)}%` }} />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-text-faint mt-1">
        <span>{data[0]?.date?.slice(5)}</span>
        <span>{today.date?.slice(5)}</span>
      </div>
      <div className="text-xs text-text-faint mt-2">A low day inside a healthy average is normal — watch the trend, not one bar.</div>
    </Card>
  )
}
function Mini({ label, value, tone }) {
  const tt = { green: 'text-green', amber: 'text-amber', red: 'text-red' }[tone] || 'text-text'
  return (
    <div>
      <div className="text-xs text-text-faint">{label}</div>
      <div className={`text-2xl font-serif ${tt}`}>{value}</div>
    </div>
  )
}
function Stat({ icon: Icon, label, value, sub, tone }) {
  const tt = { green: 'text-green', amber: 'text-amber', red: 'text-red' }[tone] || 'text-text'
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs text-text-faint mb-2"><Icon className="w-4 h-4" /> {label}</div>
      <div className={`font-serif text-3xl ${tt}`}>{value}</div>
      <div className="text-xs text-text-faint mt-1">{sub}</div>
    </Card>
  )
}

// ── Bot pairing ──────────────────────────────────────────────────────────────
const B_TONE = { connected: 'green', waiting_scan: 'amber', disconnected: 'red', unknown: 'neutral' }
const B_LABEL = { connected: 'Connected', waiting_scan: 'Waiting for scan', disconnected: 'Disconnected', unknown: 'Not reporting yet' }
function BotPairing() {
  const [s, setS] = useState(null); const [err, setErr] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = () => api.adminBridge().then((d) => alive && (setS(d), setErr(null))).catch((e) => alive && setErr(e))
    tick(); const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  const status = s?.status || 'unknown'
  return (
    <div className="max-w-md">
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint"><QrCode className="w-4 h-4" /> WhatsApp Bot</div>
          <Pill tone={B_TONE[status]}>{B_LABEL[status] || status}</Pill>
        </div>
        {err && <div className="text-sm text-red">Couldn't reach the bot bridge.</div>}
        {status === 'connected' && <div className="flex items-center gap-2 text-sm text-green"><CheckCircle2 className="w-4 h-4" /> Bot is linked and delivering messages.</div>}
        {status === 'waiting_scan' && s?.qr && (
          <div className="flex flex-col items-center gap-3">
            <img src={s.qr} alt="WhatsApp pairing QR" className="w-56 h-56 rounded-lg border border-border bg-white p-2" />
            <div className="text-xs text-text-faint text-center">On the bot's phone: WhatsApp → <span className="text-text-dim">Linked devices → Link a device</span> → scan this.</div>
          </div>
        )}
        {status === 'waiting_scan' && !s?.qr && <div className="flex items-center gap-2 text-sm text-text-faint"><Loader2 className="w-4 h-4 animate-spin" /> Generating pairing code…</div>}
        {(status === 'disconnected' || status === 'unknown') && (
          <div className="text-sm text-text-faint">{status === 'disconnected' ? 'Bot lost its WhatsApp link — a new QR will appear to re-pair.' : 'Waiting for the bot to report in. Make sure the bot service is running.'}</div>
        )}
      </Card>
      <div className="text-xs text-text-faint mt-3">Use a dedicated, building-owned number. One number = one bot.</div>
    </div>
  )
}
