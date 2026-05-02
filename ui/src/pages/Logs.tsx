import { useEffect, useRef, useState } from 'react'
import { Settings } from 'lucide-react'
import { useStore } from '@/store'
import type { LogEntry } from '@/store'
import { api } from '@/api/client'
import type { LogScopeEntry } from '@/api/types'

// ── Filter matching ────────────────────────────────────────────────────────────

function matchesFilters(entry: LogEntry, active: Set<string>): boolean {
  if (active.size === 0) return true
  return [...active].some((key) => {
    if (key === '__errors__') return entry.level === 'error'
    return entry.component === key || entry.eventType.startsWith(key + '.')
  })
}

// ── Colours ───────────────────────────────────────────────────────────────────

function levelColor(entry: LogEntry): string {
  if (
    entry.level === 'error' ||
    entry.eventType.endsWith('_failed') ||
    entry.eventType === 'mount.operation_failed'
  ) return 'text-status-error'
  if (entry.level === 'warning') return 'text-status-busy'
  if (entry.level === 'debug') return 'text-slate-600'
  if (
    entry.eventType.endsWith('_completed') ||
    entry.eventType === 'mount.parked' ||
    entry.eventType === 'mount.unparked'
  ) return 'text-status-connected'
  return 'text-slate-400'
}

function componentBadge(component: string): string {
  const map: Record<string, string> = {
    imager:     'bg-blue-900/40 text-blue-300',
    mount:      'bg-purple-900/40 text-purple-300',
    focuser:    'bg-yellow-900/40 text-yellow-300',
    device:     'bg-green-900/40 text-green-300',
    app:        'bg-slate-700 text-slate-300',
    api:        'bg-slate-700 text-slate-300',
    profiles:   'bg-slate-700 text-slate-300',
    indi:       'bg-orange-900/40 text-orange-300',
    phd2:       'bg-cyan-900/40 text-cyan-300',
    platesolve: 'bg-violet-900/40 text-violet-300',
    autofocus:  'bg-teal-900/40 text-teal-300',
    sequencer:  'bg-rose-900/40 text-rose-300',
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

// ── Sub-components ────────────────────────────────────────────────────────────

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

function DebugToggle({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${
        active ? 'bg-amber-500/80' : 'bg-slate-700'
      }`}
      aria-pressed={active}
    >
      <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-transform ${
        active ? 'translate-x-4' : 'translate-x-0.5'
      }`} />
    </button>
  )
}

// ── Verbosity panel (gear menu) ───────────────────────────────────────────────

function VerbosityPanel({
  scopes,
  onToggle,
  onClose,
}: {
  scopes: LogScopeEntry[]
  onToggle: (key: string, current: 'debug' | 'info') => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [onClose])

  return (
    <div
      ref={ref}
      className="absolute right-4 top-full mt-1 z-50 w-64 rounded-lg border border-surface-border bg-surface shadow-xl"
    >
      <div className="px-3 py-2 border-b border-surface-border flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-300">Verbosity</span>
        <span className="text-xs text-slate-600">resets on restart</span>
      </div>
      <div className="py-1 max-h-72 overflow-y-auto">
        {scopes.map((scope) => (
          <div
            key={scope.key}
            className="flex items-center justify-between px-3 py-1.5 hover:bg-surface-raised/40"
          >
            <span className={`text-xs ${scope.level === 'debug' ? 'text-amber-300' : 'text-slate-400'}`}>
              {scope.label}
            </span>
            <div className="flex items-center gap-2">
              {scope.level === 'debug' && (
                <span className="text-xs text-amber-500/70">debug</span>
              )}
              <DebugToggle
                active={scope.level === 'debug'}
                onToggle={() => onToggle(scope.key, scope.level)}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Logs() {
  const log = useStore((s) => s.log)
  const [active, setActive] = useState<Set<string>>(new Set())
  const [scopes, setScopes] = useState<LogScopeEntry[]>([])
  const [verbosityOpen, setVerbosityOpen] = useState(false)

  useEffect(() => {
    api.admin.logScopes().then(setScopes).catch(() => {})
  }, [])

  function toggleFilter(key: string) {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function toggleVerbosity(key: string, current: 'debug' | 'info') {
    const newLevel = current === 'debug' ? 'info' : 'debug'
    await api.admin.setLogLevel(key, newLevel).catch(() => {})
    setScopes((prev) =>
      prev.map((s) => (s.key === key ? { ...s, level: newLevel } : s))
    )
  }

  // Filter pills: one per scope + special Errors filter
  const filterItems = [
    ...scopes.map((s) => ({ key: s.key, label: s.label })),
    { key: '__errors__', label: 'Errors' },
  ]

  const filtered = log.filter((e) => matchesFilters(e, active))

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="relative flex items-center gap-3 px-4 py-3 border-b border-surface-border shrink-0 flex-wrap">
        <h1 className="text-sm font-semibold text-slate-300 shrink-0">Event Log</h1>

        {/* Dynamic filter pills */}
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
          {filterItems.map(({ key, label }) => {
            const on = active.has(key)
            const isError = key === '__errors__'
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleFilter(key)}
                className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                  on
                    ? isError
                      ? 'border-red-500/60 text-red-400 bg-red-500/10'
                      : 'border-accent text-accent bg-accent/10'
                    : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-600">{filtered.length} / {log.length}</span>

          {/* Gear / verbosity button */}
          <button
            type="button"
            onClick={() => setVerbosityOpen((v) => !v)}
            className={`p-1 rounded transition-colors ${
              verbosityOpen || scopes.some((s) => s.level === 'debug')
                ? 'text-amber-400 bg-amber-500/10'
                : 'text-slate-500 hover:text-slate-300'
            }`}
            title="Log verbosity"
          >
            <Settings size={14} />
          </button>
        </div>

        {verbosityOpen && (
          <VerbosityPanel
            scopes={scopes}
            onToggle={toggleVerbosity}
            onClose={() => setVerbosityOpen(false)}
          />
        )}
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
