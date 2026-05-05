// ── Device state badge (dot + text, used in Equipment/Mount) ──────────────────

type DeviceState = 'connected' | 'connecting' | 'disconnected' | 'busy' | 'error' | string

const stateClass: Record<string, string> = {
  connected:    'bg-status-connected/20 text-status-connected',
  connecting:   'bg-status-busy/20 text-status-busy',
  busy:         'bg-status-busy/20 text-status-busy',
  error:        'bg-status-error/20 text-status-error',
  disconnected: 'bg-surface-overlay text-status-idle',
  idle:         'bg-surface-overlay text-status-idle',
  looping:      'bg-accent/20 text-accent',
  exposing:     'bg-accent/20 text-accent',
}

export function StateBadge({ state }: { state: DeviceState }) {
  const cls = stateClass[state] ?? 'bg-surface-overlay text-status-idle'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {state}
    </span>
  )
}

// ── Status-bar chip (label · status, with border — for the global status bar) ─

export type ChipVariant = 'green' | 'amber' | 'red' | 'blue' | 'violet' | 'slate'

const chipClasses: Record<ChipVariant, string> = {
  green:  'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  amber:  'bg-amber-500/20  text-amber-300  border-amber-500/30',
  red:    'bg-rose-500/20   text-rose-300   border-rose-500/30',
  blue:   'bg-sky-500/20    text-sky-300    border-sky-500/30',
  violet: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  slate:  'bg-slate-700/50  text-slate-400  border-slate-600/40',
}

export function Chip({ label, status, variant, pulse = false }: {
  label: string
  status: string
  variant: ChipVariant
  pulse?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium whitespace-nowrap
        ${chipClasses[variant]} ${pulse ? 'animate-pulse' : ''}`}
    >
      <span className="text-slate-400 truncate max-w-[10rem]">{label}</span>
      <span className="opacity-40">·</span>
      <span>{status}</span>
    </span>
  )
}

// ── Inline status pill (no label, rounded-full — for content areas) ────────────

export type StatusPillVariant = 'amber' | 'green' | 'red' | 'slate' | 'accent'

const pillClasses: Record<StatusPillVariant, string> = {
  amber:  'bg-amber-500/20 text-amber-400',
  green:  'bg-green-500/20 text-green-400',
  red:    'bg-red-500/20 text-red-400',
  slate:  'bg-slate-500/20 text-slate-400',
  accent: 'bg-accent/20 text-accent',
}

export function StatusPill({ status, variant, pulse = false }: {
  status: string
  variant: StatusPillVariant
  pulse?: boolean
}) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${pillClasses[variant]} ${pulse ? 'animate-pulse' : ''}`}>
      {status}
    </span>
  )
}
