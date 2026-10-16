import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown } from 'lucide-react'
import { useStore } from '@/store'
import type { LogEntry } from '@/store'
import { selectEntries } from '@/utils/log'

/** Log entries matching the filters, oldest first. */
export function useLogEntries(filter?: string[], levels?: string[]): LogEntry[] {
  const log = useStore((s) => s.log)
  const key = `${filter?.join(',') ?? '*'}|${levels?.join(',') ?? '*'}`
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => selectEntries(log, filter, levels), [log, key])
}

const edge = (level: string) => (level === 'error' ? 'border-status-error' : level === 'warning' ? 'border-status-busy' : 'border-transparent')
const tone = (level: string) => (level === 'error' ? 'text-status-error' : level === 'warning' ? 'text-status-busy' : 'text-slate-400')

/** One log line: time, then the message, with a severity edge. The colour is never the only cue. */
export function LogRow({ entry }: { entry: LogEntry }) {
  return (
    <div className={`flex gap-2 border-l-2 pl-2 text-xs leading-5 ${edge(entry.level)}`} title={entry.message}>
      <span className="text-slate-500 shrink-0">{entry.timestamp.slice(11, 19)}</span>
      <span className={`truncate ${tone(entry.level)}`}>{entry.message}</span>
    </div>
  )
}

/**
 * Entries oldest first, following the bottom (the newest line) until the user scrolls up; a button
 * then jumps back. `onFollowChange` lets a parent know whether the view is following.
 */
export function LogList({ entries, className = '', style, onFollowChange }: {
  entries: LogEntry[]
  className?: string
  style?: React.CSSProperties
  onFollowChange?: (following: boolean) => void
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const [behind, setBehind] = useState(false)

  const toBottom = () => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }
  const set = (value: boolean) => {
    if (following.current === value) return
    following.current = value
    setBehind(!value)
    onFollowChange?.(value)
  }

  useLayoutEffect(toBottom, [])
  useEffect(() => { if (following.current) toBottom() }, [entries.length])

  const onScroll = () => {
    const el = ref.current
    if (el) set(el.scrollHeight - el.scrollTop - el.clientHeight < 24)
  }

  return (
    <div className="relative min-h-0">
      <div ref={ref} onScroll={onScroll} role="log" aria-live="off"
        className={`overflow-y-auto bg-surface px-2 py-2 font-mono ${className}`} style={style}>
        {entries.map((e) => <LogRow key={e.id} entry={e} />)}
      </div>
      {behind && (
        <button type="button" onClick={() => { toBottom(); set(true) }}
          className="absolute bottom-2 right-3 inline-flex items-center gap-1 rounded-full border border-surface-border
                     bg-surface-raised px-2 py-0.5 text-[11px] text-slate-300 shadow hover:bg-surface-overlay">
          <ArrowDown size={11} /> {t('log.latest')}
        </button>
      )}
    </div>
  )
}
