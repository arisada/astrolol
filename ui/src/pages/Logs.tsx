import { useState } from 'react'
import { useStore } from '@/store'
import type { LogEntry } from '@/store'

// ── Filter config ─────────────────────────────────────────────────────────────

const FILTERS = [
  { label: 'Imager',   prefix: 'imager'   },
  { label: 'Mount',    prefix: 'mount'    },
  { label: 'Focuser',  prefix: 'focuser'  },
  { label: 'Device',   prefix: 'device'   },
  { label: 'App logs', prefix: 'log'      },
  { label: 'Errors',   prefix: '__errors__' },
] as const

type FilterPrefix = (typeof FILTERS)[number]['prefix']

function matchesFilters(entry: LogEntry, active: Set<FilterPrefix>): boolean {
  if (active.size === 0) return true  // nothing selected = show all
  return [...active].some((prefix) => {
    if (prefix === '__errors__') return entry.level === 'error'
    return entry.eventType.startsWith(prefix) || entry.component === prefix
  })
}

// ── Colours ──────────────────────────────────────────────────────────────────

function levelColor(entry: LogEntry): string {
  if (
    entry.level === 'error' ||
    entry.eventType.endsWith('_failed') ||
    entry.eventType === 'mount.operation_failed'
  ) return 'text-status-error'
  if (entry.level === 'warning') return 'text-status-busy'
  if (
    entry.eventType.endsWith('_completed') ||
    entry.eventType === 'mount.parked' ||
    entry.eventType === 'mount.unparked'
  ) return 'text-status-connected'
  return 'text-slate-400'
}

function componentBadge(component: string): string {
  const map: Record<string, string> = {
    imager:   'bg-blue-900/40 text-blue-300',
    mount:    'bg-purple-900/40 text-purple-300',
    focuser:  'bg-yellow-900/40 text-yellow-300',
    device:   'bg-green-900/40 text-green-300',
    app:      'bg-slate-700 text-slate-300',
    api:      'bg-slate-700 text-slate-300',
    profiles: 'bg-slate-700 text-slate-300',
    indi:     'bg-orange-900/40 text-orange-300',
  }
  return map[component] ?? 'bg-slate-700 text-slate-300'
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toISOString().slice(0, 10) + ' ' + d.toISOString().slice(11, 23)
  } catch {
    return ts
  }
}

// ── Row ───────────────────────────────────────────────────────────────────────

function LogRow({ entry }: { entry: LogEntry }) {
  return (
    <div className="flex items-start gap-3 py-1.5 border-b border-surface-border/50 hover:bg-surface-raised/30 px-4">
      <span className="shrink-0 font-mono text-xs text-slate-600 w-44 tabular-nums">{fmtTime(entry.timestamp)}</span>
      <span className={`shrink-0 text-xs rounded px-1.5 py-0.5 font-mono ${componentBadge(entry.component)}`}>
        {entry.component}
      </span>
      <span className={`text-xs flex-1 min-w-0 break-words ${levelColor(entry)}`}>
        {entry.message}
      </span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Logs() {
  const log = useStore((s) => s.log)
  const [active, setActive] = useState<Set<FilterPrefix>>(new Set())

  function toggle(prefix: FilterPrefix) {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(prefix)) next.delete(prefix)
      else next.add(prefix)
      return next
    })
  }

  const filtered = log.filter((e) => matchesFilters(e, active))

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-border shrink-0 flex-wrap">
        <h1 className="text-sm font-semibold text-slate-300 shrink-0">Event Log</h1>

        {/* Multi-select filter pills */}
        <div className="flex items-center gap-1 flex-wrap flex-1">
          {active.size > 0 && (
            <button
              type="button"
              onClick={() => setActive(new Set())}
              className="px-2 py-0.5 text-xs rounded border border-surface-border text-slate-500 hover:text-slate-300 hover:border-slate-500 transition-colors"
            >
              All
            </button>
          )}
          {FILTERS.map(({ label, prefix }) => {
            const on = active.has(prefix)
            return (
              <button
                key={prefix}
                type="button"
                onClick={() => toggle(prefix)}
                className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                  on
                    ? 'border-accent text-accent bg-accent/10'
                    : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>

        <span className="text-xs text-slate-600 shrink-0">{filtered.length} / {log.length}</span>
      </div>

      {/* Log entries — newest first */}
      <div className="flex-1 overflow-y-auto font-mono">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-600 text-sm">
            {log.length === 0 ? 'No events yet.' : 'No events match the selected filters.'}
          </div>
        ) : (
          filtered.map((e) => <LogRow key={e.id} entry={e} />)
        )}
      </div>

      <div className="shrink-0 px-4 py-2 border-t border-surface-border text-xs text-slate-600">
        Last {log.length} events in memory · Full history in <code>astrolol.log</code>
      </div>
    </div>
  )
}
