import { useState } from 'react'
import { ChevronDown, Sun, Check, Plus } from 'lucide-react'
import { useBuilding } from '../lib/BuildingContext'
import Onboard from './Onboard'

export default function PageHeader({ subtitle = 'Everything in your community', date }) {
  const { current, buildings, building, selectBuilding } = useBuilding()
  const [open, setOpen] = useState(false)
  const [onboarding, setOnboarding] = useState(false)

  const today =
    date ||
    new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) +
      ' · ' +
      new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="flex items-center justify-between px-10 pt-8 pb-2">
      <div className="relative">
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 text-xl text-text">
          {current?.name || building}
          <ChevronDown className="w-4 h-4 text-text-faint" />
        </button>
        <div className="text-sm text-text-faint mt-0.5">{subtitle}</div>

        {open && (
          <div className="absolute left-0 top-9 z-10 w-64 bg-surface border border-border rounded-xl py-2 shadow-lg">
            {buildings.map((b) => (
              <button
                key={b.building_id}
                onClick={() => {
                  selectBuilding(b.building_id)
                  setOpen(false)
                }}
                className="w-full flex items-center justify-between px-4 py-2 text-sm text-text-dim hover:bg-surface-2 hover:text-text"
              >
                {b.name}
                {b.building_id === building && <Check className="w-4 h-4 text-gold" />}
              </button>
            ))}
            <div className="border-t border-border-soft mt-2 pt-2">
              <button
                onClick={() => {
                  setOnboarding(true)
                  setOpen(false)
                }}
                className="w-full flex items-center gap-2 px-4 py-2 text-sm text-gold hover:bg-surface-2"
              >
                <Plus className="w-4 h-4" /> Onboard building
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 text-sm text-text-dim">
        <Sun className="w-4 h-4 text-gold" />
        {today}
      </div>

      {onboarding && <Onboard onClose={() => setOnboarding(false)} />}
    </div>
  )
}
