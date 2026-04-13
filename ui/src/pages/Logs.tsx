import { useState } from 'react'
import { useStore } from '@/store'
import type { LogEntry } from '@/store'

// ── Helpers ───────────────────────────────────────────────────────────────────

const FILTERS = [
  { label: 'All',     prefix: '' },
  { label: 'Imager',  prefix: 'imager' },
  { label: 'Mount',   prefix: 'mount' },
  { label: 'Focuser', prefix: 'focuser' },
  { label: 'Device',  prefix: 'device' },
  { label: 'Errors',  prefix: '__errors__' },
] as const

type FilterLabel = (typeof FILTERS)[number]['label']

function levelColor(level: string, eventType: string): string {
  if (level === 'error' || eventType.endsWith('_failed') || eventType.endsWith('_error')) {
    return 'text-status-error'
  }
  if (level === 'warning') return 'text-status-busy'
  if (
    eventType.endsWith('_completed') ||
    eventType.endsWith('_done') ||
    eventType === 'mount.parked' ||
    eventType === 'mount.unparked'
  ) {
    return 'text-status-connected'
  }
  return 'text-slate-400'
}

function fmtTime(ts: string): string {
  // ts is ISO 8601; show date + time to ms
  try {
    const d = new Date(ts)
    const date = d.toISOString().slice(0, 10)
    const time = d.toISOString().slice(11, 23)
    return `${date} ${time}`
  } catch {
    return ts
  }
}

function componentBadge(component: string): string {
  const map: Record<string, string> = {
    imager:  'bg-blue-900/40 text-blue-300',
    mount:   'bg-purple-900/40 text-purple-300',
    focuser: 'bg-yellow-900/40 text-yellow-300',
    device:  'bg-green-900/40 text-green-300',
    log:     'bg-slate-700 text-slate-300',
  }
  return map[component] ?? 'bg-slate-700 text-slate-300'
}

// ── Row ───────────────────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  return (
    <div className="flex items-start gap-3 py-1.5 border-b border-surface-border/50 hover:bg-surface-raised/30 px-4">
      <span className="shrink-0 font-mono text-xs text-slate-600 w-44">{fmtTime(entry.timestamp)}</span>
      <span className={`shrink-0 text-xs rounded px-1.5 py-0.5 font-mono ${componentBadge(entry.component)}`}>
        {entry.component}
      </span>
      <span className={`text-xs flex-1 min-w-0 break-words ${levelColor(entry.level, entry.eventType)}`}>
        {entry.message}
      </span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Logs() {
  const log = useStore((s) => s.log)
  const [activeFilter, setActiveFilter] = useState<FilterLabel>('All')

  const filtered = log.filter((e) => {
    const f = FILTERS.find((f) => f.label === activeFilter)!
    if (f.prefix === '') return true
    if (f.prefix === '__errors__') return e.level === 'error'
    return e.eventType.startsWith(f.prefix) || e.component === f.prefix
  })

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border shrink-0">
        <h1 className="text-sm font-semibold text-slate-300">Event Log</h1>
        <div className="flex items-center gap-1">
          {FILTERS.map(({ label }) => (
            <button
              key={label}
              type="button"
              onClick={() => setActiveFilter(label)}
              className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                activeFilter === label
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-600">{filtered.length} entries</span>
      </div>

      {/* Log entries — newest first */}
      <div className="flex-1 overflow-y-auto font-mono">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-600 text-sm">
            No entries yet.
          </div>
        ) : (
          filtered.map((e) => <LogRow key={e.id} entry={e} />)
        )}
      </div>

      <div className="shrink-0 px-4 py-2 border-t border-surface-border text-xs text-slate-600">
        Logs are also written to <code>astrolol.log</code> in the server working directory.
      </div>
    </div>
  )
}
