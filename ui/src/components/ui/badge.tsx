import { useTranslation } from 'react-i18next'
// ── Device state badge (dot + text, used in Equipment/Mount) ──────────────────

type DeviceState = 'connected' | 'connecting' | 'disconnected' | 'busy' | 'error' | string

const stateClass: Record<string, string> = {
  connected:    'text-status-connected',
  connecting:   'text-status-busy',
  busy:         'text-status-busy',
  error:        'text-status-error',
  disconnected: 'text-status-idle',
  idle:         'text-status-idle',
  looping:      'text-accent',
  exposing:     'text-accent',
}

export function StateBadge({ state }: { state: DeviceState }) {
  const { t } = useTranslation()
  const cls = stateClass[state] ?? 'text-status-idle'
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono text-xs ${cls}`}>
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
  amber:  'text-amber-400',
  green:  'text-green-400',
  red:    'text-red-400',
  slate:  'text-slate-400',
  accent: 'text-accent',
}

export function StatusPill({ status, variant, pulse = false }: {
  status: string
  variant: StatusPillVariant
  pulse?: boolean
}) {
  return (
    <span className={`font-mono text-xs ${pillClasses[variant]} ${pulse ? 'animate-pulse' : ''}`}>
      {status}
    </span>
  )
}
