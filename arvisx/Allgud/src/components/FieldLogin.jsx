import { useState } from 'react'
import { LogIn, KeyRound, Building2, Loader2, Delete } from 'lucide-react'
import { AllGudLogo } from './Logo'
import { useAuth } from '../lib/AuthContext'

// Technician entry — a short PIN, phone-first. Deliberately NOT the manager
// sign-in: a tech tapping a round link should never hit username/password.
// (A deep-link ?t= token skips this screen entirely; this is the manual door.)
const PIN_LEN = 4

export default function FieldLogin() {
  const { fieldLogin } = useAuth()
  // Building comes from the deep link (?building=) when present; the field still
  // shows so a tech on a shared phone can correct it. Defaults to the pilot.
  const params = new URLSearchParams(window.location.search)
  const [building, setBuilding] = useState(params.get('building') || 'one-anthem')
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function submit(value) {
    setBusy(true)
    setErr(null)
    try {
      await fieldLogin(building.trim(), value)
    } catch (e2) {
      setErr(String(e2.message).startsWith('401') ? 'PIN not recognised.' : e2.message)
      setPin('')
      setBusy(false)
    }
  }

  function press(d) {
    if (busy) return
    const next = (pin + d).slice(0, PIN_LEN)
    setPin(next)
    setErr(null)
    if (next.length === PIN_LEN) submit(next)
  }
  const back = () => !busy && setPin((p) => p.slice(0, -1))

  return (
    <div className="h-screen w-full bg-bg flex items-center justify-center p-6">
      <div className="w-full max-w-xs">
        <div className="mb-8 flex justify-center">
          <AllGudLogo textClass="text-2xl" />
        </div>
        <div className="bg-surface border border-border rounded-2xl p-6">
          <div className="font-serif text-xl text-text mb-1">Field sign-in</div>
          <div className="text-sm text-text-faint mb-5">Enter your technician PIN</div>

          <label className="block text-xs text-text-faint mb-1">Building</label>
          <div className="flex items-center gap-2 bg-bg border border-border rounded-xl px-3 mb-5 focus-within:border-gold/50">
            <Building2 size={16} className="text-text-faint" />
            <input
              value={building}
              onChange={(e) => setBuilding(e.target.value)}
              className="flex-1 bg-transparent py-3 text-sm text-text outline-none"
              placeholder="one-anthem"
            />
          </div>

          {/* PIN dots */}
          <div className="flex items-center justify-center gap-3 mb-4">
            {Array.from({ length: PIN_LEN }).map((_, i) => (
              <span
                key={i}
                className={`h-3 w-3 rounded-full border ${
                  i < pin.length ? 'bg-primary border-primary' : 'border-border'
                }`}
              />
            ))}
          </div>

          {err && <div className="text-sm text-red bg-red-bg rounded-lg px-3 py-2 mb-4 text-center">{err}</div>}

          {/* keypad */}
          <div className="grid grid-cols-3 gap-2">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
              <button
                key={n}
                onClick={() => press(String(n))}
                disabled={busy}
                className="py-4 rounded-xl bg-bg border border-border text-lg text-text active:bg-surface disabled:opacity-50"
              >
                {n}
              </button>
            ))}
            <div />
            <button
              onClick={() => press('0')}
              disabled={busy}
              className="py-4 rounded-xl bg-bg border border-border text-lg text-text active:bg-surface disabled:opacity-50"
            >
              0
            </button>
            <button
              onClick={back}
              disabled={busy || !pin.length}
              className="py-4 rounded-xl flex items-center justify-center text-text-faint active:bg-surface disabled:opacity-30"
              aria-label="Delete"
            >
              <Delete size={20} />
            </button>
          </div>

          <div className="mt-5 flex items-center justify-center gap-2 text-xs text-text-faint">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <KeyRound size={14} />}
            {busy ? 'Checking…' : 'Ask your manager for a PIN'}
          </div>

          <a href="/" className="mt-4 flex items-center justify-center gap-1.5 text-xs text-gold">
            <LogIn size={13} /> Manager sign-in
          </a>
        </div>
      </div>
    </div>
  )
}
