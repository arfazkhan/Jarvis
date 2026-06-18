// AllGud mark — rounded-square "pixels" arranged as an upward pyramid with
// trailing scatter dots, echoing the brand pattern. Uses currentColor.
export function AllGudMark({ className = 'w-7 h-7' }) {
  return (
    <svg viewBox="0 0 48 44" fill="currentColor" className={className} aria-hidden="true">
      {/* apex */}
      <rect x="21" y="3" width="6" height="6" rx="2" />
      {/* row 2 */}
      <rect x="14" y="13" width="6" height="6" rx="2" />
      <rect x="28" y="13" width="6" height="6" rx="2" />
      {/* row 3 */}
      <rect x="7" y="23" width="6" height="6" rx="2" />
      <rect x="21" y="23" width="6" height="6" rx="2" opacity="0.55" />
      <rect x="35" y="23" width="6" height="6" rx="2" />
      {/* base row */}
      <rect x="0.5" y="33" width="6" height="6" rx="2" />
      <rect x="14" y="33" width="6" height="6" rx="2" opacity="0.55" />
      <rect x="28" y="33" width="6" height="6" rx="2" opacity="0.55" />
      <rect x="41.5" y="33" width="6" height="6" rx="2" />
      {/* trailing scatter dots */}
      <circle cx="10" cy="42" r="1.6" />
      <circle cx="24" cy="42" r="1.6" opacity="0.6" />
      <circle cx="38" cy="42" r="1.6" />
    </svg>
  )
}

export function AllGudWordmark({ className = '' }) {
  return (
    <span className={`font-sans font-medium tracking-tight ${className}`}>AllGud</span>
  )
}

export function AllGudLogo({ markClass, textClass = 'text-xl', className = '' }) {
  return (
    <div className={`flex items-center gap-2.5 text-primary ${className}`}>
      <AllGudMark className={markClass || 'w-7 h-7'} />
      <AllGudWordmark className={textClass} />
    </div>
  )
}
