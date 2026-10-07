import { useEffect, useRef } from 'react'
import { useStore } from '@/store'
import type { LogEntry } from '@/store'

export function EventLog({
  filter,
  className = '',
  style,
}: {
  filter: string[]
  className?: string
  style?: React.CSSProperties
}) {
  const log = useStore((s) => s.log.filter((e: LogEntry) => filter.includes(e.component)))
  const ref = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  const handleScroll = () => {
    const el = ref.current
    if (!el) return
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  useEffect(() => {
    const el = ref.current
    if (!el || !pinned.current) return
    el.scrollTop = el.scrollHeight
  }, [log.length])

  return (
    <div
      ref={ref}
      onScroll={handleScroll}
      className={`h-28 shrink-0 bg-surface border-t border-surface-border overflow-y-auto px-2 py-2 font-mono ${className}`}
      style={style}
    >
      {log.map((e: LogEntry) => (
        <div
          key={e.id}
          className={`flex gap-2 border-l-2 pl-2 text-xs leading-5
            ${e.level === 'error' ? 'border-status-error' : e.level === 'warning' ? 'border-status-busy' : 'border-transparent'}`}
        >
          <span className="text-slate-500 shrink-0">{e.timestamp.slice(11, 19)}</span>
          <span className={`truncate ${e.level === 'error' ? 'text-status-error' : e.level === 'warning' ? 'text-status-busy' : 'text-slate-400'}`}>
            {e.message}
          </span>
        </div>
      ))}
    </div>
  )
}
