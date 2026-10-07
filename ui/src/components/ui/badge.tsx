import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const cls = stateClass[state] ?? 'bg-surface-overlay text-status-idle'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {t(`state.${state}`, { defaultValue: state })}
    </span>
  )
}

// ── Status-bar chip: telemetry readout "LABEL value", hairline-separated ─────────
// The value is coloured by state; the text always says the state too, so nothing depends on colour alone.

export type ChipVariant = 'green' | 'amber' | 'red' | 'blue' | 'violet' | 'slate'

const chipValueClasses: Record<ChipVariant, string> = {
  green:  'text-emerald-400',
  amber:  'text-amber-400',
  red:    'text-rose-400',
  blue:   'text-sky-400',
  violet: 'text-violet-400',
  slate:  'text-slate-400',
}

export function Chip({ label, status, variant, pulse = false, icon }: {
  label?: string
  status: string
  variant: ChipVariant
  pulse?: boolean
  icon?: React.ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 h-5 px-2.5 border-l border-surface-border first:border-l-0 first:pl-0
        font-mono text-xs whitespace-nowrap ${pulse ? 'animate-pulse' : ''}`}
    >
      {icon}
      {label && <span className="label-caps text-slate-500 truncate max-w-[10rem]">{label}</span>}
      <span className={chipValueClasses[variant]}>{status}</span>
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
