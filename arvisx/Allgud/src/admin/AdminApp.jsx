import { useState, useEffect, useCallback } from 'react'
import {
  QrCode, BarChart3, LogIn, LogOut, Lock, User, Loader2, CheckCircle2,
  RefreshCw, ClipboardList, TriangleAlert, CalendarCheck, Users,
  DollarSign, MessageSquare, Cpu, ArrowDownLeft, ArrowUpRight,
  UserPlus, Activity, Plus, Power, AlertTriangle,
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
        <Tab active={tab === 'usage'} onClick={() => setTab('usage')} icon={DollarSign}>Usage & Cost</Tab>
        <Tab active={tab === 'team'} onClick={() => setTab('team')} icon={Users}>Team</Tab>
        <Tab active={tab === 'llm'} onClick={() => setTab('llm')} icon={Activity}>LLM</Tab>
        <Tab active={tab === 'bot'} onClick={() => setTab('bot')} icon={QrCode}>WhatsApp Bot</Tab>
      </nav>

      <main className="px-8 py-6">
        {tab === 'analytics' && <Analytics />}
        {tab === 'usage' && <Usage />}
        {tab === 'team' && <Team />}
        {tab === 'llm' && <div className="space-y-8"><LlmConfig /><EmbedConfig /><SttConfig /><LlmTest /></div>}
        {tab === 'bot' && <BotPairing />}
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

// ── Usage & Cost (WhatsApp + LLM) ─────────────────────────────────────────────
function Usage() {
  const [building, setBuilding] = useState('one-anthem')
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    api.adminUsage(building, days)
      .then((d) => { setData(d); setErr(null) })
      .catch((e) => setErr(e))
      .finally(() => setLoading(false))
  }, [building, days])
  useEffect(() => load(), [load])

  if (loading) return <Spinner />
  if (err) return <div className="text-red text-sm">{err.message}</div>
  if (!data) return null
  const { summary, daily, currency } = data
  const wa = summary.whatsapp, llm = summary.llm, emb = summary.embed || { calls: 0, tokens: 0, cost: 0 }
  const money = (n) => `${currency} ${Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}`
  const num = (n) => Number(n || 0).toLocaleString()

  return (
    <div className="max-w-5xl">
      <div className="flex items-center gap-3 mb-5">
        <input value={building} onChange={(e) => setBuilding(e.target.value)} className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text" />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text">
          {[7, 14, 30, 90].map((d) => <option key={d} value={d}>last {d} days</option>)}
        </select>
        <button onClick={load} className="flex items-center gap-1 text-sm text-gold"><RefreshCw className="w-4 h-4" /> Refresh</button>
      </div>

      <div className="grid grid-cols-5 gap-4 mb-6">
        <Stat icon={MessageSquare} label="WhatsApp messages" value={num(wa.total)} sub={`${num(wa.in)} in · ${num(wa.out)} out`} tone="green" />
        <Stat icon={Cpu} label="LLM calls" value={num(llm.calls)} sub={`${num(llm.total_tokens)} tokens · avg ctx ${num(llm.avg_context)}`} tone="green" />
        <Stat icon={DollarSign} label="LLM cost" value={money(llm.cost)} sub={`${num(llm.prompt_tokens)} in / ${num(llm.completion_tokens)} out`} tone="amber" />
        <Stat icon={DollarSign} label="Embedding cost" value={money(emb.cost)} sub={`${num(emb.calls)} calls · ${num(emb.tokens)} tokens`} tone="amber" />
        <Stat icon={DollarSign} label="Total cost" value={money(summary.total_cost)} sub={`WA ${money(wa.cost)} + LLM ${money(llm.cost)} + Emb ${money(emb.cost)}`} tone="amber" />
      </div>

      <Card className="p-5 mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3"><MessageSquare className="w-4 h-4" /> WhatsApp messages (bot)</div>
        <div className="grid grid-cols-5 gap-4">
          <Mini label="Received (in)" value={num(wa.in)} />
          <Mini label="Sent (out)" value={num(wa.out)} />
          <Mini label="Billable (utility)" value={num(wa.billable)} tone="amber" />
          <Mini label="Free (service/reply)" value={num(wa.free)} tone="green" />
          <Mini label="Cost" value={money(wa.cost)} />
        </div>
        <div className="text-xs text-text-faint mt-3">Official API bills only business-initiated utility templates; inbound + replies are free.</div>
      </Card>

      <Card className="p-5 mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint mb-3"><Cpu className="w-4 h-4" /> LLM {llm.model ? `(${llm.model})` : ''}</div>
        <div className="grid grid-cols-4 gap-4 mb-4">
          <Mini label="Calls" value={num(llm.calls)} />
          <Mini label="Context (prompt) tokens" value={num(llm.prompt_tokens)} />
          <Mini label="Completion tokens" value={num(llm.completion_tokens)} />
          <Mini label="Avg context / call" value={num(llm.avg_context)} />
        </div>
        {Object.keys(llm.by_channel || {}).length > 0 && (
          <table className="w-full text-sm">
            <thead><tr className="text-xs text-text-faint text-left"><th className="py-1 font-normal">Channel</th><th className="font-normal">Calls</th><th className="font-normal">Prompt tok</th><th className="font-normal">Completion tok</th><th className="font-normal">Cost</th></tr></thead>
            <tbody>
              {Object.entries(llm.by_channel).map(([ch, v]) => (
                <tr key={ch} className="border-t border-border-soft">
                  <td className="py-2 text-text">{ch}</td>
                  <td className="text-text-dim">{num(v.calls)}</td>
                  <td className="text-text-dim">{num(v.prompt_tokens)}</td>
                  <td className="text-text-dim">{num(v.completion_tokens)}</td>
                  <td className="text-text-dim">{money(v.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <UsageTrend daily={daily} currency={currency} />
      <div className="text-xs text-text-faint mt-4">WhatsApp cost uses ARVISX_WA_MSG_COST (0 for Baileys — counts still tracked). LLM cost uses ARVISX_LLM_PRICE_IN / _OUT and embedding cost uses ARVISX_EMBED_PRICE, per 1M tokens. Set these in the deploy env to reflect real rates.</div>
    </div>
  )
}

function UsageTrend({ daily, currency }) {
  const data = daily || []
  if (!data.length) return <Card className="p-5 mb-6"><div className="text-sm text-text-faint">No usage recorded yet in this window.</div></Card>
  const max = Math.max(...data.map((d) => (d.wa_in + d.wa_out) || 0), 1)
  return (
    <Card className="p-5 mb-6">
      <div className="text-xs uppercase tracking-wide text-text-faint mb-3">Daily WhatsApp volume</div>
      <div className="flex items-end gap-[3px] h-24">
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex flex-col justify-end" title={`${d.date}: ${d.wa_in} in / ${d.wa_out} out · ${d.llm_calls} LLM calls · ${currency} ${d.cost}`}>
            <div className="bg-gold/70 rounded-t" style={{ height: `${Math.max(2, (d.wa_in + d.wa_out) / max * 100)}%` }} />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-text-faint mt-1">
        <span>{data[0]?.date?.slice(5)}</span><span>{data[data.length - 1]?.date?.slice(5)}</span>
      </div>
    </Card>
  )
}

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
// ── Team: owner / manager logins (+ WhatsApp number) ─────────────────────────
const ROLE_LABEL = { owner: 'Owner', fm: 'Manager', viewer: 'Viewer', system: 'System', admin: 'Operator' }
function Team() {
  const [users, setUsers] = useState(null); const [err, setErr] = useState(null)
  const [f, setF] = useState({ username: '', password: '', role: 'fm', phone: '' })
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState('')
  const load = useCallback(() => api.adminUsers().then((d) => setUsers(d.users || [])).catch(setErr), [])
  useEffect(() => { load() }, [load])
  async function add() {
    if (!f.username.trim() || !f.password) { setMsg('Username + password required'); return }
    setBusy(true); setMsg('')
    try { await api.adminAddUser({ username: f.username.trim(), password: f.password, role: f.role, phone: f.phone.trim() }); setF({ username: '', password: '', role: 'fm', phone: '' }); load(); setMsg('Added ✓'); setTimeout(() => setMsg(''), 2500) }
    catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="max-w-3xl">
      <div className="text-sm text-text-dim mb-4">Add owners and managers. A phone on an owner/manager also grants <b>WhatsApp privileges</b> — they get alerts and can run commands (assign, close, approve…).</div>
      <Card className="p-5 mb-6">
        <div className="grid grid-cols-[1fr_1fr_120px_1fr_auto] gap-3 items-end">
          <Field label="Username"><Inp value={f.username} onChange={(v) => setF({ ...f, username: v })} /></Field>
          <Field label="Password"><Inp type="password" value={f.password} onChange={(v) => setF({ ...f, password: v })} /></Field>
          <Field label="Role">
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} className="w-full bg-surface border border-border rounded-lg px-2 py-2 text-sm text-text">
              <option value="owner">Owner</option><option value="fm">Manager</option><option value="viewer">Viewer</option>
            </select>
          </Field>
          <Field label="WhatsApp (no +)"><Inp value={f.phone} onChange={(v) => setF({ ...f, phone: v.replace(/[^0-9]/g, '') })} /></Field>
          <button onClick={add} disabled={busy} className="flex items-center gap-1 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50 h-[38px]"><UserPlus className="w-4 h-4" /> Add</button>
        </div>
        {msg && <div className="text-xs text-green mt-2">{msg}</div>}
      </Card>
      {err && <div className="text-sm text-red">{err.message}</div>}
      {!users ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {users.map((u) => (
            <Card key={u.username} className="p-3 flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-surface-2 flex items-center justify-center text-xs text-text-dim">{(u.username || '?').slice(0, 2).toUpperCase()}</div>
              <div className="flex-1"><div className="text-sm text-text">{u.username}</div><div className="text-xs text-text-faint">{u.phone || 'no WhatsApp number'}</div></div>
              <Pill tone={u.role === 'owner' ? 'gold' : u.role === 'fm' ? 'green' : 'neutral'}>{ROLE_LABEL[u.role] || u.role}</Pill>
              {u.phone && (u.role === 'owner' || u.role === 'fm') && <span className="text-[10px] text-green flex items-center gap-1"><MessageSquare className="w-3 h-3" /> WhatsApp</span>}
              <Pill tone={u.active === 0 ? 'neutral' : 'green'}>{u.active === 0 ? 'inactive' : 'active'}</Pill>
              {u.active !== 0 && <button onClick={async () => { await api.adminDeactivateUser(u.username); load() }} className="text-text-faint hover:text-red p-1" title="Deactivate"><Power className="w-4 h-4" /></button>}
            </Card>
          ))}
          {!users.length && <div className="text-sm text-text-faint">No users yet — add the building owner + manager above.</div>}
        </div>
      )}
    </div>
  )
}
function Field({ label, children }) { return <label className="block"><div className="text-xs text-text-faint mb-1">{label}</div>{children}</label> }
function Inp({ value, onChange, type = 'text' }) { return <input type={type} value={value} onChange={(e) => onChange(e.target.value)} className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50" /> }

// ── LLM provider/model/key config ─────────────────────────────────────────────
function LlmConfig() {
  const [cfg, setCfg] = useState(null)
  const [form, setForm] = useState({ provider: '', model: '', api_key: '', base_url: '' })
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [err, setErr] = useState('')
  const load = () => api.adminLlmConfig().then((c) => {
    setCfg(c)
    setForm({ provider: c.provider || '', model: c.model || '', api_key: '', base_url: c.base_url || '' })
  }).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])

  const models = (cfg?.catalog && cfg.catalog[form.provider]) || []
  const def = (cfg?.defaults && cfg.defaults[form.provider]) || {}
  const setProvider = (p) => setForm((f) => ({ ...f, provider: p, model: (cfg?.catalog?.[p]?.[0]) || '' }))

  async function save() {
    if (!form.provider) { setErr('Pick a provider'); return }
    setBusy(true); setErr(''); setSaved(false)
    try {
      await api.adminSetLlmConfig({ provider: form.provider, model: form.model.trim(), api_key: form.api_key.trim(), base_url: form.base_url.trim() })
      setSaved(true); setTimeout(() => setSaved(false), 2500); load()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  if (!cfg) return <div className="text-sm text-text-faint">Loading LLM config…</div>
  return (
    <div className="max-w-xl">
      <div className="text-sm text-text-dim mb-1">LLM provider</div>
      <div className="text-xs text-text-faint mb-4">
        Pick a provider, model, and API key — powers Ask AllGud, reports, RCA, and the anomaly lessons.
        Overrides the deploy env. {cfg.provider ? <>Current: <b className="text-text-dim">{cfg.provider}/{cfg.model}</b>{cfg.api_key_set ? ` · key •••${cfg.api_key_last4}` : ' · no key'}</> : 'Not configured yet.'}
      </div>
      <Card className="p-6 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs text-text-faint">Provider
            <select value={form.provider} onChange={(e) => setProvider(e.target.value)}
              className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text">
              <option value="">Select…</option>
              {(cfg.providers || []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-text-faint">Model
            <input list="llm-models" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder={def.model || 'model id'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
            <datalist id="llm-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
          </label>
        </div>
        <label className="flex flex-col gap-1 text-xs text-text-faint">API key
          <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            placeholder={cfg.api_key_set ? `keep existing (•••${cfg.api_key_last4}) — type to change` : 'paste API key'}
            className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-faint">Base URL (optional — defaults to the provider's)
          <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            placeholder={def.base_url || 'https://…/v1'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        {err && <div className="text-xs text-red">{err}</div>}
        <button onClick={save} disabled={busy}
          className="flex items-center gap-2 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50">
          {saved ? <CheckCircle2 className="w-4 h-4" /> : null} {busy ? 'Saving…' : saved ? 'Saved — run the test below' : 'Save LLM config'}
        </button>
      </Card>
      <KeyPool cfg={cfg} reload={load} />
    </div>
  )
}

// ── API key pool: rotate off a rate-limited key instead of going dark ─────────
function KeyPool({ cfg, reload }) {
  const [newKey, setNewKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const keys = cfg?.keys || []
  const avail = cfg?.keys_available ?? 0

  async function add() {
    if (!newKey.trim()) return
    setBusy(true); setErr('')
    try { await api.adminAddLlmKey(newKey.trim()); setNewKey(''); reload() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  async function remove(last4) {
    setBusy(true); setErr('')
    try { await api.adminRemoveLlmKey(last4); reload() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const mins = (s) => (s >= 60 ? `${Math.ceil(s / 60)} min` : `${s}s`)

  return (
    <Card className="p-6 mt-4 space-y-4">
      <div>
        <div className="text-sm text-text-dim">API key pool</div>
        <div className="text-xs text-text-faint mt-1">
          Add more keys and AllGud rotates automatically: when the provider rate-limits one key it's
          parked until the provider says it's free, and the next key answers. The bot only shows the
          "busy" message once <b className="text-text-dim">every</b> key is exhausted.
        </div>
        {keys.length > 0 && (
          <div className="text-xs mt-2">
            <span className={avail > 0 ? 'text-green' : 'text-red'}>{avail} of {keys.length} available</span>
          </div>
        )}
      </div>

      {keys.length > 0 && (
        <div className="space-y-2">
          {keys.map((k) => (
            <div key={k.last4} className="flex items-center justify-between bg-bg border border-border rounded-lg px-3 py-2">
              <div className="flex items-center gap-3 text-sm">
                <span className="font-mono text-text-dim">•••• {k.last4}</span>
                {k.cooling
                  ? <span className="text-xs text-amber">rate-limited · frees up in {mins(k.cooldown_s)}</span>
                  : <span className="text-xs text-green">available</span>}
              </div>
              <button onClick={() => remove(k.last4)} disabled={busy}
                className="text-xs text-text-faint hover:text-red disabled:opacity-50">Remove</button>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input type="password" value={newKey} onChange={(e) => setNewKey(e.target.value)}
          placeholder="paste another API key" onKeyDown={(e) => e.key === 'Enter' && add()}
          className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        <button onClick={add} disabled={busy || !newKey.trim()}
          className="text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50">Add key</button>
      </div>
      {err && <div className="text-xs text-red">{err}</div>}
    </Card>
  )
}

// ── Embeddings config (semantic chat recall) ──────────────────────────────────
function EmbedConfig() {
  const [cfg, setCfg] = useState(null)
  const [form, setForm] = useState({ provider: '', model: '', api_key: '', base_url: '' })
  const [busy, setBusy] = useState(false); const [saved, setSaved] = useState(false); const [err, setErr] = useState('')
  const load = () => api.adminEmbedConfig().then((c) => {
    setCfg(c); setForm({ provider: c.provider || '', model: c.model || '', api_key: '', base_url: c.base_url || '' })
  }).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const models = (cfg?.catalog && cfg.catalog[form.provider]) || []
  const def = (cfg?.defaults && cfg.defaults[form.provider]) || {}
  const setProvider = (p) => setForm((f) => ({ ...f, provider: p, model: (cfg?.catalog?.[p]?.[0]) || '' }))
  async function save() {
    if (!form.provider) { setErr('Pick a provider'); return }
    setBusy(true); setErr(''); setSaved(false)
    try {
      await api.adminSetEmbedConfig({ provider: form.provider, model: form.model.trim(), api_key: form.api_key.trim(), base_url: form.base_url.trim() })
      setSaved(true); setTimeout(() => setSaved(false), 2500); load()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  if (!cfg) return null
  return (
    <div className="max-w-xl">
      <div className="text-sm text-text-dim mb-1">Embeddings (semantic recall)</div>
      <div className="text-xs text-text-faint mb-4">
        Powers "what did we discuss about X" over the full chat history. Without it, recall falls back to keyword match.
        {cfg.provider ? <> Current: <b className="text-text-dim">{cfg.provider}/{cfg.model}</b>{cfg.api_key_set ? ` · key •••${cfg.api_key_last4}` : ' · no key'}</> : ' Not configured — using keyword fallback.'}
      </div>
      <Card className="p-6 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs text-text-faint">Provider
            <select value={form.provider} onChange={(e) => setProvider(e.target.value)} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text">
              <option value="">Select…</option>
              {(cfg.providers || []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-text-faint">Model
            <input list="emb-models" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder={def.model || 'model id'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
            <datalist id="emb-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
          </label>
        </div>
        <label className="flex flex-col gap-1 text-xs text-text-faint">API key
          <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={cfg.api_key_set ? `keep existing (•••${cfg.api_key_last4})` : 'paste API key'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-faint">Base URL (optional)
          <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder={def.base_url || 'https://…/v1'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        {err && <div className="text-xs text-red">{err}</div>}
        <button onClick={save} disabled={busy} className="flex items-center gap-2 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50">
          {saved ? <CheckCircle2 className="w-4 h-4" /> : null} {busy ? 'Saving…' : saved ? 'Saved' : 'Save embeddings config'}
        </button>
      </Card>
    </div>
  )
}

// ── Speech-to-text (WhatsApp voice notes) ────────────────────────────────────
function SttConfig() {
  const [cfg, setCfg] = useState(null)
  const [form, setForm] = useState({ provider: '', model: '', api_key: '', base_url: '' })
  const [busy, setBusy] = useState(false); const [saved, setSaved] = useState(false); const [err, setErr] = useState('')
  const load = () => api.adminSttConfig().then((c) => {
    setCfg(c); setForm({ provider: c.provider || '', model: c.model || '', api_key: '', base_url: c.base_url || '' })
  }).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  const models = (cfg?.catalog && cfg.catalog[form.provider]) || []
  const def = (cfg?.defaults && cfg.defaults[form.provider]) || {}
  const setProvider = (p) => setForm((f) => ({ ...f, provider: p, model: (cfg?.catalog?.[p]?.[0]) || '' }))
  // Only whisper-large-v3 / whisper-1 can translate to English; the turbo + distil models
  // transcribe in the spoken language only. Warn instead of silently changing behaviour.
  const canTranslate = !form.model || (cfg?.translate_capable || []).some((m) => form.model.startsWith(m))
  async function save() {
    if (!form.provider) { setErr('Pick a provider'); return }
    setBusy(true); setErr(''); setSaved(false)
    try {
      await api.adminSetSttConfig({ provider: form.provider, model: form.model.trim(), api_key: form.api_key.trim(), base_url: form.base_url.trim() })
      setSaved(true); setTimeout(() => setSaved(false), 2500); load()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  if (!cfg) return null
  return (
    <div className="max-w-xl">
      <div className="text-sm text-text-dim mb-1">Voice notes (speech-to-text)</div>
      <div className="text-xs text-text-faint mb-4">
        Lets people send WhatsApp voice notes instead of typing. Audio is transcribed to English, then answered exactly like a typed message.
        {cfg.provider ? <> Current: <b className="text-text-dim">{cfg.provider}/{cfg.model}</b>{cfg.api_key_set ? ` · key •••${cfg.api_key_last4}` : ' · no key'}</> : ' Not configured — voice notes are ignored.'}
      </div>
      <Card className="p-6 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs text-text-faint">Provider
            <select value={form.provider} onChange={(e) => setProvider(e.target.value)} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text">
              <option value="">Select…</option>
              {(cfg.providers || []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-text-faint">Model
            <input list="stt-models" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder={def.model || 'model id'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
            <datalist id="stt-models">{models.map((m) => <option key={m} value={m} />)}</datalist>
          </label>
        </div>
        {!canTranslate && <div className="text-xs text-amber">This model transcribes in the language spoken — it can't translate to English. Use whisper-large-v3 for mixed Hindi/Kannada/English speech.</div>}
        <label className="flex flex-col gap-1 text-xs text-text-faint">API key
          <input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={cfg.api_key_set ? `keep existing (•••${cfg.api_key_last4})` : 'paste API key'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-text-faint">Base URL (optional)
          <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder={def.base_url || 'https://…/v1'} className="bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text" />
        </label>
        {err && <div className="text-xs text-red">{err}</div>}
        <button onClick={save} disabled={busy} className="flex items-center gap-2 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50">
          {saved ? <CheckCircle2 className="w-4 h-4" /> : null} {busy ? 'Saving…' : saved ? 'Saved' : 'Save voice config'}
        </button>
      </Card>
    </div>
  )
}

// ── LLM smoke test ───────────────────────────────────────────────────────────
function LlmTest() {
  const [r, setR] = useState(null); const [busy, setBusy] = useState(false)
  async function run() { setBusy(true); setR(null); try { setR(await api.adminLlmTest()) } catch (e) { setR({ ok: false, reason: e.message }) } finally { setBusy(false) } }
  return (
    <div className="max-w-xl">
      <div className="text-sm text-text-dim mb-4">A one-call round-trip to the configured LLM — confirms the Ask Arvis / RCA / distil brain is reachable.</div>
      <Card className="p-6">
        <button onClick={run} disabled={busy} className="flex items-center gap-2 text-sm bg-primary text-white rounded-lg px-4 py-2 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />} {busy ? 'Testing…' : 'Run LLM test'}
        </button>
        {r && (
          <div className="mt-5">
            <div className={`flex items-center gap-2 text-base ${r.ok ? 'text-green' : 'text-red'}`}>
              {r.ok ? <CheckCircle2 className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
              {r.ok ? 'LLM is working' : 'LLM not reachable'}
            </div>
            {r.reason && <div className="text-xs text-amber mt-1">{r.reason}</div>}
            <div className="grid grid-cols-2 gap-3 mt-4">
              <Mini label="Provider" value={r.provider || '—'} />
              <Mini label="Model" value={r.model || '—'} />
              <Mini label="Latency" value={r.latency_ms != null ? `${r.latency_ms} ms` : '—'} />
              <Mini label="Round-trip" value={r.pong ? 'JSON ✓' : (r.ok ? 'reached' : '—')} />
            </div>
            {r.reply && <pre className="mt-4 text-xs text-text-faint bg-bg border border-border rounded-lg p-3 overflow-auto">{JSON.stringify(r.reply, null, 2)}</pre>}
          </div>
        )}
      </Card>
    </div>
  )
}

function BotPairing() {
  const [s, setS] = useState(null); const [err, setErr] = useState(null)
  const [resetting, setResetting] = useState(false); const [msg, setMsg] = useState('')
  useEffect(() => {
    let alive = true
    const tick = () => api.adminBridge().then((d) => alive && (setS(d), setErr(null))).catch((e) => alive && setErr(e))
    tick(); const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])
  const status = s?.status || 'unknown'
  async function repair() {
    if (!window.confirm('Re-pair the bot? This clears the current WhatsApp link and shows a new QR to scan. Messaging is briefly offline until you scan.')) return
    setResetting(true); setMsg('')
    try { await api.resetBot(); setMsg('Reset sent — a new QR will appear below in a few seconds. Scan it from the bot phone.') }
    catch (e) { setMsg('Failed: ' + e.message) }
    finally { setResetting(false) }
  }
  return (
    <div className="max-w-md">
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-text-faint"><QrCode className="w-4 h-4" /> WhatsApp Bot</div>
          <div className="flex items-center gap-2">
            <Pill tone={B_TONE[status]}>{B_LABEL[status] || status}</Pill>
            <button onClick={repair} disabled={resetting}
              className="flex items-center gap-1 text-xs border border-border rounded-lg px-2 py-1 text-text-dim hover:border-gold/40 disabled:opacity-50">
              <RefreshCw className={`w-3 h-3 ${resetting ? 'animate-spin' : ''}`} /> Re-pair
            </button>
          </div>
        </div>
        {msg && <div className="text-xs text-amber mb-3">{msg}</div>}
        {(status !== 'connected' && status !== 'waiting_scan') && (
          <div className="mb-3 rounded-lg bg-red/10 border border-red/40 px-3 py-2 text-sm text-red">
            ⚠️ Bot is NOT delivering messages ({B_LABEL[status] || status}). Click <b>Re-pair</b> and scan the QR.
          </div>
        )}
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
