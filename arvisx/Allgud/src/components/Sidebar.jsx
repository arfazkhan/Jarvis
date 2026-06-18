import { NavLink } from 'react-router-dom'
import { Target, ClipboardList, TriangleAlert, Box, Users, Sparkles, ChevronDown } from 'lucide-react'
import { AllGudLogo } from './Logo'

const items = [
  { to: '/', label: 'Overview', icon: Target },
  { to: '/operations', label: 'Operations', icon: ClipboardList },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
  { to: '/assets', label: 'Assets', icon: Box },
  { to: '/people', label: 'People', icon: Users },
  { to: '/intelligence', label: 'Intelligence', icon: Sparkles },
]

export default function Sidebar() {
  return (
    <aside className="w-[260px] shrink-0 border-r border-border bg-surface flex flex-col h-full px-5 py-6">
      <AllGudLogo className="mb-10 pl-1" textClass="text-2xl" markClass="w-7 h-7" />

      <nav className="flex flex-col gap-1">
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-primary text-white font-medium'
                  : 'text-text-dim hover:text-text hover:bg-surface-2'
              }`
            }
          >
            <Icon className="w-[18px] h-[18px]" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex items-center gap-3 px-2 py-3 border-t border-border-soft pt-5">
        <div className="w-9 h-9 rounded-full bg-primary flex items-center justify-center text-xs text-white font-medium">
          AG
        </div>
        <div className="leading-tight">
          <div className="text-sm text-text">Athul G</div>
          <div className="text-xs text-text-faint">Facility Manager</div>
        </div>
        <ChevronDown className="w-4 h-4 text-text-faint ml-auto" />
      </div>
    </aside>
  )
}
