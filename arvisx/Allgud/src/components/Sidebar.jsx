import { NavLink } from 'react-router-dom'
import { Target, ClipboardList, TriangleAlert, Box, Users, Sparkles, LogOut, Smartphone, Settings, BookOpen } from 'lucide-react'
import { AllGudLogo } from './Logo'
import { useAuth } from '../lib/AuthContext'

// Pilot console = the manager's 3 questions. Extra surfaces live under "More".
const primary = [
  { to: '/', label: 'Overview', icon: Target },
  { to: '/operations', label: 'Operations', icon: ClipboardList },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
]
const more = [
  { to: '/assets', label: 'Assets', icon: Box },
  { to: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { to: '/people', label: 'People', icon: Users },
  { to: '/intelligence', label: 'Intelligence', icon: Sparkles },
]

function link({ isActive }) {
  return `flex items-center gap-3 px-4 py-3 rounded-lg text-sm transition-colors ${
    isActive ? 'bg-primary text-white font-medium' : 'text-text-dim hover:text-text hover:bg-surface-2'
  }`
}

export default function Sidebar() {
  const { username, role, logout } = useAuth()
  const initials = (username || 'AG').slice(0, 2).toUpperCase()
  const canSetup = role === 'owner' || role === 'fm' || role === 'system' || role === 'open'

  return (
    <aside className="w-[260px] shrink-0 border-r border-border bg-surface flex flex-col h-full px-5 py-6">
      <AllGudLogo className="mb-10 pl-1" textClass="text-2xl" markClass="w-7 h-7" />

      <nav className="flex flex-col gap-1">
        {primary.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={link}>
            <Icon className="w-[18px] h-[18px]" /> {label}
          </NavLink>
        ))}

        <div className="text-[11px] uppercase tracking-wide text-text-faint px-4 mt-5 mb-1">More</div>
        {more.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={link}>
            <Icon className="w-[18px] h-[18px]" /> {label}
          </NavLink>
        ))}

        {canSetup && (
          <NavLink to="/setup" className={link}>
            <Settings className="w-[18px] h-[18px]" /> Setup
          </NavLink>
        )}

        <NavLink to="/field" className={link}>
          <Smartphone className="w-[18px] h-[18px]" /> Field app
        </NavLink>
      </nav>

      <div className="mt-auto border-t border-border-soft pt-4">
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="w-9 h-9 rounded-full bg-primary flex items-center justify-center text-xs text-white font-medium">
            {initials}
          </div>
          <div className="leading-tight flex-1 min-w-0">
            <div className="text-sm text-text truncate">{username || 'Signed in'}</div>
            <div className="text-xs text-text-faint capitalize">{role === 'open' ? 'dev mode' : role || 'user'}</div>
          </div>
          <button onClick={logout} title="Sign out" className="text-text-faint hover:text-text p-1">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  )
}
