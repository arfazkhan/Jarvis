import { useState } from 'react'
import { LogIn, Lock, User, Loader2 } from 'lucide-react'
import { AllGudLogo } from './Logo'
import { useAuth } from '../lib/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await login(username.trim(), password)
    } catch (e2) {
      setErr(String(e2.message).startsWith('401') ? 'Wrong username or password.' : e2.message)
      setBusy(false)
    }
  }

  return (
    <div className="h-screen w-full bg-bg flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <AllGudLogo textClass="text-2xl" />
        </div>
        <div className="bg-surface border border-border rounded-2xl p-6">
          <div className="font-serif text-xl text-text mb-1">Sign in</div>
          <div className="text-sm text-text-faint mb-5">Building operations console</div>

          <label className="block text-xs text-text-faint mb-1">Username</label>
          <div className="flex items-center gap-2 bg-bg border border-border rounded-xl px-3 mb-4 focus-within:border-gold/50">
            <User size={16} className="text-text-faint" />
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="flex-1 bg-transparent py-3 text-sm text-text outline-none"
              placeholder="athul"
            />
          </div>

          <label className="block text-xs text-text-faint mb-1">Password</label>
          <div className="flex items-center gap-2 bg-bg border border-border rounded-xl px-3 mb-5 focus-within:border-gold/50">
            <Lock size={16} className="text-text-faint" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex-1 bg-transparent py-3 text-sm text-text outline-none"
              placeholder="••••••••"
            />
          </div>

          {err && <div className="text-sm text-red bg-red-bg rounded-lg px-3 py-2 mb-4">{err}</div>}

          <button
            type="submit"
            disabled={busy || !username || !password}
            className="w-full flex items-center justify-center gap-2 bg-primary text-white rounded-xl py-3 text-sm font-medium disabled:opacity-50"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LogIn size={16} />}
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </form>
    </div>
  )
}
