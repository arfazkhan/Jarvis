import { useState, useRef } from 'react'
import { Users, Wrench, CalendarCheck, ShieldCheck, Plus, Power, KeyRound, Check, ChevronRight, ClipboardList, Trash2, Copy, Box, Home, FileText, FileUp } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, Spinner, Empty } from '../components/ui'
import { Input, Select } from './Issues'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'
import ChecklistBuilder from './ChecklistBuilder'

// Guided onboarding — do everything via the UI instead of the onboard.json/CLI:
// roster + field PINs, vendors, PPM schedules, manager logins. All backend endpoints
// already exist; this just chains them into one flow.
const STEPS = [
  { key: 'checklists', label: 'Checklists', icon: ClipboardList },
  { key: 'assets', label: 'Assets', icon: Box },
  { key: 'roster', label: 'Roster & PINs', icon: Users },
  { key: 'residents', label: 'Residents', icon: Home },
  { key: 'vendors', label: 'Vendors', icon: Wrench },
  { key: 'ppm', label: 'PPM schedules', icon: CalendarCheck },
  { key: 'managers', label: 'Managers', icon: ShieldCheck },
]

export default function Setup() {
  const { building, current } = useBuilding()
  const [step, setStep] = useState('checklists')

  return (
    <div>
      <PageHeader subtitle={`Onboarding — ${current?.name || building}`} />
      {/* horizontal tabs */}
      <div className="px-10 border-b border-border-soft">
        <div className="flex gap-1 overflow-x-auto">
          {STEPS.map((s) => {
            const Icon = s.icon
            const active = step === s.key
            return (
              <button
                key={s.key}
                onClick={() => setStep(s.key)}
                className={`flex items-center gap-2 px-4 py-3 text-sm whitespace-nowrap border-b-2 -mb-px ${
                  active ? 'border-gold text-text' : 'border-transparent text-text-faint hover:text-text'
                }`}
              >
                <Icon className="w-4 h-4" /> {s.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="px-10 pt-6 pb-12">
        {step === 'checklists' && <ChecklistStep building={building} />}
        {step === 'assets' && <AssetStep building={building} />}
        {step === 'roster' && <RosterStep building={building} />}
        {step === 'residents' && <ResidentStep building={building} />}
        {step === 'vendors' && <VendorStep building={building} />}
        {step === 'ppm' && <PpmStep building={building} />}
        {step === 'managers' && <ManagerStep />}
      </div>
    </div>
  )
}

function Section({ title, hint, children }) {
  return (
    <div className="max-w-2xl">
      <div className="text-xl font-serif text-text mb-1">{title}</div>
      {hint && <div className="text-sm text-text-faint mb-5">{hint}</div>}
      {children}
    </div>
  )
}

function AddBar({ children, onAdd, busy, label = 'Add' }) {
  return (
    <div className="flex items-end gap-2 flex-wrap bg-surface border border-border rounded-xl p-4 mb-5">
      {children}
      <button
        onClick={onAdd}
        disabled={busy}
        className="flex items-center gap-1.5 bg-primary text-white rounded-lg px-3 py-2.5 text-sm font-medium disabled:opacity-50"
      >
        <Plus className="w-4 h-4" /> {label}
      </button>
    </div>
  )
}

function err(e) {
  alert(e.message || String(e))
}

// ── Checklists (rich drag-and-drop builder lives in ChecklistBuilder.jsx) ──
function ChecklistStep({ building }) {
  const [key, setKey] = useState(0)
  const tpls = useAsync(() => api.templates(building), [building, key])
  const [editing, setEditing] = useState(null) // {} = blank new | template dict (+_clone) | null
  const [loading, setLoading] = useState(false)
  const refresh = () => setKey((k) => k + 1)

  async function open(tid, clone) {
    if (!tid) { setEditing({}); return }
    setLoading(true)
    try { const t = await api.template(tid, building); setEditing({ ...t, _clone: clone }) }
    catch (e) { err(e) } finally { setLoading(false) }
  }

  if (editing) {
    return (
      <ChecklistBuilder building={building}
        initial={Object.keys(editing).length ? editing : null}
        onSaved={() => { setEditing(null); refresh() }}
        onCancel={() => setEditing(null)} />
    )
  }

  return (
    <Section title="Checklists" hint="The shift rounds + PPM sheets technicians fill. Drag to reorder, click a type to add — build a new one or start from an existing template.">
      <button onClick={() => open(null)}
        className="flex items-center gap-1.5 bg-primary text-white rounded-lg px-3 py-2.5 text-sm font-medium mb-5">
        <Plus className="w-4 h-4" /> New checklist
      </button>
      {tpls.loading || loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(tpls.data?.templates || []).map((t) => (
            <Row key={t.template_id}>
              <div className="flex-1">
                <div className="text-sm text-text">{t.name}</div>
                <div className="text-xs text-text-faint">{t.template_id} · {t.cadence} · {t.items} checks{t.timing ? ` · ${t.timing}` : ''}</div>
              </div>
              <button onClick={() => open(t.template_id, false)} className="text-xs text-gold px-1">Edit</button>
              <button onClick={() => open(t.template_id, true)} className="text-xs text-text-dim px-1 flex items-center gap-1" title="Start a new checklist from this one"><Copy className="w-3.5 h-3.5" /> Clone</button>
              <button
                onClick={async () => { if (confirm(`Delete ${t.name}? (a building default reappears if one exists)`)) { try { await api.deleteTemplate(t.template_id, building); refresh() } catch (e) { err(e) } } }}
                className="text-text-faint hover:text-red" title="Delete"><Trash2 className="w-4 h-4" /></button>
            </Row>
          ))}
          {!tpls.data?.templates?.length && <Empty>No checklists yet — create one.</Empty>}
        </div>
      )}
    </Section>
  )
}

// A manual/datasheet attached to an asset (B1) — upload, view, or replace.
function ManualCell({ asset, onChange }) {
  const fileRef = useRef(null)
  const [busy, setBusy] = useState(false)
  async function upload(file) {
    if (!file) return
    setBusy(true)
    try { await api.uploadAssetManual(asset.id, file, file.type, file.name); onChange() }
    catch (e) { err(e) } finally { setBusy(false) }
  }
  return (
    <div className="flex items-center gap-1">
      <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,.txt,image/*" className="hidden"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      {asset.manual_path ? (
        <button onClick={() => api.openAssetManual(asset.manual_path)}
          className="text-xs text-gold hover:underline flex items-center gap-1" title={asset.manual_name}>
          <FileText className="w-3.5 h-3.5" /> manual
        </button>
      ) : (
        <button onClick={() => fileRef.current?.click()} disabled={busy}
          className="text-xs text-text-faint hover:text-text flex items-center gap-1">
          <FileUp className="w-3.5 h-3.5" /> {busy ? '…' : 'manual'}
        </button>
      )}
    </div>
  )
}

// ── Assets ───────────────────────────────────────────────────────────────────
function AssetStep({ building }) {
  const [key, setKey] = useState(0)
  const reg = useAsync(() => api.assetsRegistry(building), [building, key])
  const [f, setF] = useState({ name: '', kind: 'DG', location: '' })
  const [busy, setBusy] = useState(false)
  const refresh = () => setKey((k) => k + 1)

  async function add() {
    if (!f.name.trim()) return
    setBusy(true)
    try { await api.addAsset({ building, ...f }); setF({ name: '', kind: 'DG', location: '' }); refresh() }
    catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="Assets" hint="The building's equipment. Used as the asset picker for PPM and the checklist builder. Assets tagged in checklists also appear here.">
      <AddBar onAdd={add} busy={busy} label="Add asset">
        <Field label="Name"><Input value={f.name} onChange={(v) => setF({ ...f, name: v })} /></Field>
        <Field label="Type">
          <Select value={f.kind} options={['DG', 'Pump', 'Tank', 'Electrical', 'Fire', 'Lift', 'STP', 'WTP', 'HVAC', 'Other']} onChange={(v) => setF({ ...f, kind: v })} />
        </Field>
        <Field label="Location"><Input value={f.location} onChange={(v) => setF({ ...f, location: v })} /></Field>
      </AddBar>
      {reg.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(reg.data?.assets || []).map((a) => (
            <Row key={a.id ?? a.name}>
              <Box className="w-4 h-4 text-text-dim" />
              <div className="flex-1">
                <div className="text-sm text-text">{a.name}</div>
                <div className="text-xs text-text-faint">{[a.kind, a.location].filter(Boolean).join(' · ') || '—'}</div>
              </div>
              {a.id && <ManualCell asset={a} onChange={refresh} />}
              {a.in_checklists && <Pill tone="blue">in checklists</Pill>}
              {a.id ? <Pill tone="green">registered</Pill> : <Pill tone="neutral">from checklist</Pill>}
              {a.id && <Deact onClick={async () => { await api.deactivateAsset(a.id); refresh() }} />}
            </Row>
          ))}
          {!reg.data?.assets?.length && <Empty>No assets yet — add the building's equipment.</Empty>}
        </div>
      )}
    </Section>
  )
}

// ── Roster + PINs ──────────────────────────────────────────────────────────
function RosterStep({ building }) {
  const [key, setKey] = useState(0)
  const techs = useAsync(() => api.technicians(building), [building, key])
  const [f, setF] = useState({ name: '', phone: '', pin: '' })
  const [busy, setBusy] = useState(false)
  const refresh = () => setKey((k) => k + 1)

  async function add() {
    if (!f.name.trim()) return
    if (f.pin && !/^\d{4,6}$/.test(f.pin)) return err({ message: 'PIN must be 4–6 digits' })
    setBusy(true)
    try {
      const { id } = await api.addTechnician({ building, name: f.name.trim(), phone: f.phone.trim() })
      if (f.pin) await api.setTechPin(id, f.pin)
      setF({ name: '', phone: '', pin: '' })
      refresh()
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="Technicians" hint="Add each technician with a WhatsApp number and a distinct field PIN. They sign into the field app with the PIN.">
      <AddBar onAdd={add} busy={busy} label="Add technician">
        <Field label="Name"><Input value={f.name} onChange={(v) => setF({ ...f, name: v })} /></Field>
        <Field label="WhatsApp (no +)"><Input value={f.phone} onChange={(v) => setF({ ...f, phone: v })} /></Field>
        <Field label="PIN (4–6)"><Input value={f.pin} onChange={(v) => setF({ ...f, pin: v.replace(/\D/g, '').slice(0, 6) })} /></Field>
      </AddBar>
      {techs.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(techs.data?.technicians || []).map((t) => (
            <Row key={t.id}>
              <div className="flex-1">
                <div className="text-sm text-text">{t.name}</div>
                <div className="text-xs text-text-faint">{t.phone || 'no phone'}</div>
              </div>
              <span className={`text-xs flex items-center gap-1 ${t.has_pin ? 'text-green' : 'text-text-faint'}`}>
                <KeyRound className="w-3 h-3" /> {t.has_pin ? 'PIN set' : 'no PIN'}
              </span>
              <Pill tone={t.active ? 'green' : 'neutral'}>{t.active ? 'active' : 'inactive'}</Pill>
              {t.active && <Deact onClick={async () => { await api.deactivateTechnician(t.id); refresh() }} />}
            </Row>
          ))}
          {!techs.data?.technicians?.length && <Empty>No technicians yet.</Empty>}
        </div>
      )}
    </Section>
  )
}

// ── Vendors ─────────────────────────────────────────────────────────────────
function ResidentStep({ building }) {
  const [key, setKey] = useState(0)
  const residents = useAsync(() => api.residents(building), [building, key])
  const [f, setF] = useState({ name: '', phone: '', unit: '' })
  const [busy, setBusy] = useState(false)
  const refresh = () => setKey((k) => k + 1)

  async function add() {
    if (!f.name.trim() || !f.phone.trim()) return
    setBusy(true)
    try {
      await api.addResident({ building, name: f.name.trim(), phone: f.phone.trim(), unit: f.unit.trim() })
      setF({ name: '', phone: '', unit: '' })
      refresh()
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="Residents" hint="Pre-registered residents can flag common-area issues via WhatsApp (e.g. 'Lift not working in B block') — each becomes a ticket the team is notified about. Only numbers listed here can raise tickets.">
      <AddBar onAdd={add} busy={busy} label="Add resident">
        <Field label="Name"><Input value={f.name} onChange={(v) => setF({ ...f, name: v })} /></Field>
        <Field label="WhatsApp (no +)"><Input value={f.phone} onChange={(v) => setF({ ...f, phone: v })} /></Field>
        <Field label="Unit"><Input value={f.unit} onChange={(v) => setF({ ...f, unit: v })} /></Field>
      </AddBar>
      {residents.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(residents.data?.residents || []).map((r) => (
            <Row key={r.id}>
              <div className="flex-1">
                <div className="text-sm text-text">{r.name}{r.unit ? ` · ${r.unit}` : ''}</div>
                <div className="text-xs text-text-faint">{r.phone || 'no phone'}</div>
              </div>
              <Pill tone={r.active ? 'green' : 'neutral'}>{r.active ? 'active' : 'inactive'}</Pill>
              {r.active && <Deact onClick={async () => { await api.deactivateResident(r.id); refresh() }} />}
            </Row>
          ))}
          {!residents.data?.residents?.length && <Empty>No residents yet.</Empty>}
        </div>
      )}
    </Section>
  )
}

function VendorStep({ building }) {
  const [key, setKey] = useState(0)
  const vendors = useAsync(() => api.vendorsList(building), [building, key])
  const [f, setF] = useState({ name: '', category: 'Electrical', contact: '' })
  const [busy, setBusy] = useState(false)
  const refresh = () => setKey((k) => k + 1)

  async function add() {
    if (!f.name.trim()) return
    setBusy(true)
    try { await api.addVendor({ building, ...f }); setF({ name: '', category: 'Electrical', contact: '' }); refresh() }
    catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="Vendors / AMCs" hint="External parties who own off-site fixes (DG service, fire, lifts…).">
      <AddBar onAdd={add} busy={busy} label="Add vendor">
        <Field label="Name"><Input value={f.name} onChange={(v) => setF({ ...f, name: v })} /></Field>
        <Field label="Category">
          <Select value={f.category} options={['Electrical', 'Fire Safety', 'Lifts', 'Plumbing', 'STP', 'WTP', 'DG', 'Other']} onChange={(v) => setF({ ...f, category: v })} />
        </Field>
        <Field label="Contact"><Input value={f.contact} onChange={(v) => setF({ ...f, contact: v })} /></Field>
      </AddBar>
      {vendors.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(vendors.data?.vendors || []).map((v) => (
            <Row key={v.id}>
              <div className="flex-1">
                <div className="text-sm text-text">{v.name}</div>
                <div className="text-xs text-text-faint">{v.category} · {v.contact || '—'}</div>
              </div>
              <Pill tone={v.active ? 'green' : 'neutral'}>{v.active ? 'active' : 'inactive'}</Pill>
              {v.active && <Deact onClick={async () => { await api.deactivateVendor(v.id); refresh() }} />}
            </Row>
          ))}
          {!vendors.data?.vendors?.length && <Empty>No vendors yet.</Empty>}
        </div>
      )}
    </Section>
  )
}

// ── PPM schedules ────────────────────────────────────────────────────────────
const PPM_BLANK = { asset: '', interval_days: '90', last_done: '', run_hours_limit: '' }
function PpmStep({ building }) {
  const [key, setKey] = useState(0)
  const ppm = useAsync(() => api.ppmSchedule(building), [building, key])
  const assets = useAsync(() => api.assets(building), [building])
  const [f, setF] = useState(PPM_BLANK)
  const [busy, setBusy] = useState(false)
  const refresh = () => setKey((k) => k + 1)
  const editing = (ppm.data?.schedules || []).some((p) => p.asset === f.asset)
  const assetOpts = (assets.data?.assets || [])

  async function save() {
    if (!f.asset.trim()) return
    setBusy(true)
    try {
      await api.setPpm({
        building, asset: f.asset.trim(),
        interval_days: Number(f.interval_days) || 90,
        last_done: f.last_done || undefined,
        run_hours_limit: f.run_hours_limit ? Number(f.run_hours_limit) : undefined,
      })
      setF(PPM_BLANK)
      refresh()
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="PPM schedules" hint="Set each asset's service interval + last-service date. For run-hour assets (DG sets) add a run-hours limit — whichever comes first triggers service.">
      <AddBar onAdd={save} busy={busy} label={editing ? 'Update schedule' : 'Add schedule'}>
        <label className="flex flex-col gap-1 text-xs text-text-faint">
          Asset
          <input list="ppm-assets" value={f.asset} onChange={(e) => setF({ ...f, asset: e.target.value })}
            className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50" />
          <datalist id="ppm-assets">{assetOpts.map((a) => <option key={a} value={a} />)}</datalist>
        </label>
        <Field label="Interval (days)"><Input value={f.interval_days} onChange={(v) => setF({ ...f, interval_days: v.replace(/\D/g, '') })} /></Field>
        <Field label="Last done (YYYY-MM-DD)"><Input value={f.last_done} onChange={(v) => setF({ ...f, last_done: v })} /></Field>
        <Field label="Run-hours limit (optional)"><Input value={f.run_hours_limit} onChange={(v) => setF({ ...f, run_hours_limit: v.replace(/\D/g, '') })} /></Field>
      </AddBar>
      {editing && <div className="text-xs text-amber -mt-3 mb-3">Editing {f.asset} — saving overwrites its schedule. <button onClick={() => setF(PPM_BLANK)} className="text-gold">clear</button></div>}
      {ppm.loading ? <Spinner /> : (
        <div className="flex flex-col gap-2">
          {(ppm.data?.schedules || []).map((p) => (
            <Row key={p.asset}>
              <div className="flex-1">
                <div className="text-sm text-text">{p.asset}</div>
                <div className="text-xs text-text-faint">
                  every {p.interval_days}d · last {p.last_done || '—'} · due {p.due_date || '—'}
                  {p.run_hours_limit ? ` · ${p.run_hours_limit} run-hrs limit` : ''}
                </div>
              </div>
              <Pill tone={p.overdue ? 'red' : p.status === 'due_soon' ? 'amber' : 'green'}>{p.status}</Pill>
              <button onClick={() => setF({ asset: p.asset, interval_days: String(p.interval_days || 90), last_done: p.last_done || '', run_hours_limit: p.run_hours_limit ? String(p.run_hours_limit) : '' })} className="text-xs text-gold">edit</button>
            </Row>
          ))}
          {!ppm.data?.schedules?.length && <Empty>No PPM schedules yet.</Empty>}
        </div>
      )}
    </Section>
  )
}

// ── Managers (logins) ────────────────────────────────────────────────────────
function ManagerStep() {
  const [f, setF] = useState({ username: '', password: '', role: 'fm' })
  const [busy, setBusy] = useState(false)
  const [added, setAdded] = useState([])

  async function add() {
    if (!f.username.trim() || !f.password) return
    setBusy(true)
    try {
      await api.createUser({ username: f.username.trim(), password: f.password, role: f.role })
      setAdded((a) => [...a, `${f.username} (${f.role})`])
      setF({ username: '', password: '', role: 'fm' })
    } catch (e) { err(e) } finally { setBusy(false) }
  }

  return (
    <Section title="Manager logins" hint="Create console logins. owner = full; fm = manage ops; viewer = read-only. (Owner only.)">
      <AddBar onAdd={add} busy={busy} label="Create login">
        <Field label="Username"><Input value={f.username} onChange={(v) => setF({ ...f, username: v })} /></Field>
        <Field label="Password"><Input value={f.password} onChange={(v) => setF({ ...f, password: v })} /></Field>
        <Field label="Role"><Select value={f.role} options={['fm', 'owner', 'viewer']} onChange={(v) => setF({ ...f, role: v })} /></Field>
      </AddBar>
      {added.length > 0 && (
        <div className="flex flex-col gap-2">
          {added.map((a, i) => (
            <Row key={i}><Check className="w-4 h-4 text-green" /><span className="text-sm text-text">{a}</span></Row>
          ))}
        </div>
      )}
    </Section>
  )
}

// ── small shared bits ────────────────────────────────────────────────────────
function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-text-faint">
      {label}
      {children}
    </label>
  )
}
function Row({ children }) {
  return <div className="flex items-center gap-3 border border-border-soft rounded-xl px-4 py-3">{children}</div>
}
function Deact({ onClick }) {
  return <button onClick={onClick} className="text-text-faint hover:text-red" title="Deactivate"><Power className="w-4 h-4" /></button>
}
