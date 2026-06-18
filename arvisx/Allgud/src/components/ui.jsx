export function Card({ children, className = '' }) {
  return (
    <div className={`bg-surface border border-border rounded-2xl ${className}`}>
      {children}
    </div>
  )
}

const TONES = {
  amber: 'text-amber bg-amber-bg',
  red: 'text-red bg-red-bg',
  green: 'text-green bg-green-bg',
  blue: 'text-blue bg-blue-bg',
  purple: 'text-purple bg-purple-bg',
  gold: 'text-gold bg-surface-2',
  neutral: 'text-text-dim bg-surface-2',
}

export function Pill({ tone = 'neutral', children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center px-3 py-1 rounded-md text-xs font-medium ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

export function ProgressBar({ pct, tone = 'gold', className = '' }) {
  const barTone =
    {
      gold: 'bg-gold',
      green: 'bg-green',
      amber: 'bg-amber',
      red: 'bg-red',
      blue: 'bg-blue',
      purple: 'bg-purple',
    }[tone] || 'bg-gold'
  return (
    <div className={`h-1.5 w-full rounded-full bg-surface-2 overflow-hidden ${className}`}>
      <div className={`h-full rounded-full ${barTone}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  )
}

export function Avatar({ name, tone = 'neutral' }) {
  const initials = name
    ? name
        .split(' ')
        .map((s) => s[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : '?'
  return (
    <div className={`w-9 h-9 rounded-full border border-border flex items-center justify-center text-xs font-medium ${TONES[tone]}`}>
      {initials}
    </div>
  )
}

export function IconCircle({ tone = 'neutral', children, className = '' }) {
  return (
    <div className={`w-11 h-11 rounded-full flex items-center justify-center ${TONES[tone]} ${className}`}>
      {children}
    </div>
  )
}

export function Drawer({ open, onClose, children, width = 460 }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        className="relative h-full bg-bg border-l border-border overflow-y-auto"
        style={{ width }}
      >
        {children}
      </div>
    </div>
  )
}

export function Empty({ children }) {
  return <div className="text-sm text-text-faint py-10 text-center">{children}</div>
}

// Provenance badge per honesty convention §6.7: agent (LLM, passed grounding guard)
// vs deterministic (rules). Always surface which produced an answer.
export function SourceBadge({ source }) {
  if (!source) return null
  const isAgent = source === 'agent'
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium ${
        isAgent ? 'text-purple bg-purple-bg' : 'text-text-dim bg-surface-2'
      }`}
      title={isAgent ? 'AI-generated, passed the no-fabricated-numbers guard' : 'Deterministic rules over real data'}
    >
      {isAgent ? 'Arvis AI' : source.replace('-', ' ')}
    </span>
  )
}

// Confidence is a BAND — Low/Medium/High — never a percentage (§6.1).
export function ConfidenceBadge({ confidence }) {
  if (!confidence) return null
  const tone = { High: 'green', Medium: 'amber', Low: 'red' }[confidence] || 'neutral'
  return <Pill tone={tone}>Confidence: {confidence}</Pill>
}

export function Spinner({ label = 'Loading…' }) {
  return <div className="text-sm text-text-faint py-10 text-center">{label}</div>
}
