export function Logo({ className = 'size-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="#1E3A5F" />
      <path d="M9 12V9h3M20 9h3v3M23 20v3h-3M12 23H9v-3" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" fill="none" />
      <circle cx="16" cy="16" r="4.5" stroke="#34D399" strokeWidth="2.2" fill="none" />
    </svg>
  )
}
