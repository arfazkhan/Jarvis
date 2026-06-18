import { useState } from 'react'
import { UserPlus, Wrench, Phone, Power, Plus, X, BarChart3 } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { Pill, Drawer, Empty, Spinner, Avatar } from '../components/ui'
import { Input, Select } from './Issues'
import { useAsync } from '../lib/useAsync'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

export default function People() {
  const { building } = useBuilding()
  const [tab, setTab] = useState('technicians')
  const [refreshKey, setRefreshKey] = useState(0)
  const [add, setAdd] = useState(null) // 'tech' | 'vendor'

  const techs = useAsync(() => api.technicians(building), [building, refreshKey])
  const vendors = useAsync(() => api.vendorsList(building), [building, refreshKey])
  const perf = useAsync(() => api.vendors(building), [building, refreshKey])

  const refresh = () => setRefreshKey((k) => k + 1)
  const perfByVendor = {}
  for (const v of perf.data?.vendors || []) perfByVendor[v.vendor] = v

  return (
    <div>
      <PageHeader subtitle="Technician roster & vendor accountability" />

      <div className="px-10 pt-6 flex items-center justify-between">
        <div className="flex gap-2">
          {['technicians', 'vendors'].map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-sm px-4 py-2 rounded-lg border capitalize ${
                tab === t ? 'border-gold/40 text-gold-soft bg-surface-2' : 'border-border text-text-dim'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <button
          onClick={() => setAdd(tab === 'technicians' ? 'tech' : 'vendor')}
          className="flex items-center gap-2 text-sm bg-surface border border-border rounded-lg px-3 py-2 text-text-dim hover:border-gold/40"
        >
          <Plus className="w-4 h-4" /> Add {tab === 'technicians' ? 'Technician' : 'Vendor'}
        </button>
      </div>

      <div className="px-10 pt-6 pb-10">
        {tab === 'technicians' ? (
          techs.loading ? (
            <Spinner />
          ) : (techs.data?.technicians || []).length === 0 ? (
            <Empty>No technicians yet.</Empty>
          ) : (
            <div className="flex flex-col gap-2">
              {techs.data.technicians.map((t) => (
                <div key={t.id} className="flex items-center justify-between border border-border-soft rounded-xl px-4 py-3">
                  <div className="flex items-center gap-3">
                    <Avatar name={t.name} />
                    <div>
                      <div className="text-sm text-text">{t.name}</div>
                      <div className="text-xs text-text-faint flex items-center gap-1">
                        <Phone className="w-3 h-3" /> {t.phone || '—'}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <Pill tone={t.active ? 'green' : 'neutral'}>{t.active ? 'active' : 'inactive'}</Pill>
                    {t.active && (
                      <button
                        onClick={async () => {
                          await api.deactivateTechnician(t.id)
                          refresh()
                        }}
                        className="text-text-faint hover:text-red"
                        title="Deactivate"
                      >
                        <Power className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )
        ) : vendors.loading ? (
          <Spinner />
        ) : (vendors.data?.vendors || []).length === 0 ? (
          <Empty>No vendors yet.</Empty>
        ) : (
          <div className="flex flex-col gap-2">
            {vendors.data.vendors.map((v) => {
              const p = perfByVendor[v.name]
              return (
                <div key={v.id} className="border border-border-soft rounded-xl px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="w-9 h-9 rounded-full bg-surface-2 border border-border flex items-center justify-center text-gold-soft">
                        <Wrench className="w-4 h-4" />
                      </span>
                      <div>
                        <div className="text-sm text-text">{v.name}</div>
                        <div className="text-xs text-text-faint">
                          {v.category} · {v.contact}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <Pill tone={v.active ? 'green' : 'neutral'}>{v.active ? 'active' : 'inactive'}</Pill>
                      {v.active && (
                        <button
                          onClick={async () => {
                            await api.deactivateVendor(v.id)
                            refresh()
                          }}
                          className="text-text-faint hover:text-red"
                          title="Deactivate"
                        >
                          <Power className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                  {p && (
                    <div className="flex items-center gap-6 mt-3 pt-3 border-t border-border-soft text-xs text-text-faint">
                      <span className="flex items-center gap-1">
                        <BarChart3 className="w-3 h-3" /> {p.jobs} jobs
                      </span>
                      <span>{p.resolved} resolved</span>
                      <span>avg response {p.avg_response_hours}h</span>
                      <span>avg resolution {p.avg_resolution_hours}h</span>
                      {p.escalations > 0 && <span className="text-amber">{p.escalations} escalations</span>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <AddTechDrawer open={add === 'tech'} onClose={() => setAdd(null)} building={building} onAdded={refresh} />
      <AddVendorDrawer open={add === 'vendor'} onClose={() => setAdd(null)} building={building} onAdded={refresh} />
    </div>
  )
}

function AddTechDrawer({ open, onClose, building, onAdded }) {
  const [form, setForm] = useState({ name: '', phone: '' })
  return (
    <FormDrawer
      open={open}
      onClose={onClose}
      title="Add Technician"
      icon={UserPlus}
      onSubmit={async () => {
        if (!form.name.trim()) return
        await api.addTechnician({ building, ...form })
        onAdded()
        onClose()
        setForm({ name: '', phone: '' })
      }}
    >
      <Input label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
      <Input label="Phone" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
    </FormDrawer>
  )
}

function AddVendorDrawer({ open, onClose, building, onAdded }) {
  const [form, setForm] = useState({ name: '', category: 'DG', contact: '' })
  return (
    <FormDrawer
      open={open}
      onClose={onClose}
      title="Add Vendor"
      icon={Wrench}
      onSubmit={async () => {
        if (!form.name.trim()) return
        await api.addVendor({ building, ...form })
        onAdded()
        onClose()
        setForm({ name: '', category: 'DG', contact: '' })
      }}
    >
      <Input label="Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
      <Select
        label="Category"
        value={form.category}
        options={['DG', 'STP', 'WTP', 'Lift', 'Fire', 'Electrical', 'Plumbing', 'Other']}
        onChange={(v) => setForm({ ...form, category: v })}
      />
      <Input label="Contact" value={form.contact} onChange={(v) => setForm({ ...form, contact: v })} />
    </FormDrawer>
  )
}

function FormDrawer({ open, onClose, title, icon: Icon, onSubmit, children }) {
  const [busy, setBusy] = useState(false)
  return (
    <Drawer open={open} onClose={onClose} width={400}>
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2 font-serif text-xl text-text">
            <Icon className="w-5 h-5" /> {title}
          </div>
          <button onClick={onClose} className="text-text-faint">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex flex-col gap-4">
          {children}
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onSubmit()
              } catch (e) {
                alert(e.message)
              } finally {
                setBusy(false)
              }
            }}
            className="bg-primary text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </Drawer>
  )
}
