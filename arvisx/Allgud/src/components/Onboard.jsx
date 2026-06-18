import { useState } from 'react'
import { Building2, Sparkles, X } from 'lucide-react'
import { api } from '../api/client'
import { useBuilding } from '../lib/BuildingContext'

// Seeds a NEW building by cloning an existing starter pack (POST /forms/seed).
// `from` defaults to the first available pack (e.g. one-anthem).
export default function Onboard({ onClose, embedded = false }) {
  const { buildings, reload, selectBuilding } = useBuilding()
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [from, setFrom] = useState(buildings[0]?.building_id || 'one-anthem')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)

  async function submit() {
    const slug = id.trim() || name.trim().toLowerCase().replace(/\s+/g, '-')
    if (!slug) return
    setBusy(true)
    setErr(null)
    try {
      const res = await api.seedBuilding({ building: slug, from, name: name.trim() || undefined })
      setResult(res)
      await reload(slug)
      selectBuilding(slug)
      onClose?.()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  const body = (
    <div className="w-full max-w-md bg-surface border border-border rounded-2xl p-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2 font-serif text-xl text-text">
          <Building2 className="w-5 h-5 text-gold" /> Onboard a Building
        </div>
        {onClose && (
          <button onClick={onClose} className="text-text-faint">
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      <p className="text-sm text-text-faint mb-5">
        Clones a starter checklist pack into a new building — 4 templates, no code change.
      </p>

      <div className="flex flex-col gap-4">
        <label className="block">
          <div className="text-xs text-text-faint mb-1">Building name</div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Green Meadows Apartments"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50"
          />
        </label>

        <label className="block">
          <div className="text-xs text-text-faint mb-1">Building id (slug, optional)</div>
          <input
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="green-meadows"
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50"
          />
        </label>

        {buildings.length > 0 && (
          <label className="block">
            <div className="text-xs text-text-faint mb-1">Copy templates from</div>
            <select
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm text-text outline-none focus:border-gold/50"
            >
              {buildings.map((b) => (
                <option key={b.building_id} value={b.building_id}>
                  {b.name} ({b.templates} templates)
                </option>
              ))}
            </select>
          </label>
        )}

        {err && <div className="text-sm text-red">{err}</div>}
        {result && (
          <div className="text-sm text-green flex items-center gap-2">
            <Sparkles className="w-4 h-4" /> Seeded {result.seeded?.length || 0} templates.
          </div>
        )}

        <button
          disabled={busy}
          onClick={submit}
          className="bg-primary text-white rounded-lg py-2.5 text-sm font-medium disabled:opacity-50"
        >
          {busy ? 'Seeding…' : 'Create & Seed'}
        </button>
      </div>
    </div>
  )

  if (embedded) return body

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative">{body}</div>
    </div>
  )
}
