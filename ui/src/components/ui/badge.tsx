type DeviceState = 'connected' | 'connecting' | 'disconnected' | 'busy' | 'error' | string

const stateClass: Record<string, string> = {
  connected: 'bg-status-connected/20 text-status-connected',
  connecting: 'bg-status-busy/20 text-status-busy',
  busy: 'bg-status-busy/20 text-status-busy',
  error: 'bg-status-error/20 text-status-error',
  disconnected: 'bg-surface-overlay text-status-idle',
  idle: 'bg-surface-overlay text-status-idle',
  looping: 'bg-accent/20 text-accent',
  exposing: 'bg-accent/20 text-accent',
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
