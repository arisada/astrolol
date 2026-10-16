import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { peekDuration } from '@/utils/log'
import { LogList, LogRow, useLogEntries } from './log-list'

const STRIP_H = 28          // px: the folded bar, always in the page's flow
const MIN_H = 80
const DEFAULT_H = 176
const MAX_SCREEN_SHARE = 0.5
const REPLAY_GRACE_MS = 1500   // entries replayed when the app connects must not pop the log open

const maxHeight = () => Math.max(MIN_H, Math.round(window.innerHeight * MAX_SCREEN_SHARE))

/**
 * A log that sits over the bottom of the page without taking its space. Folded it is a thin strip with
 * the latest line; a new entry unfolds it for a few seconds ("peek") and it folds again; the handle at
 * the bottom left pins it open. Drag its top edge to resize. Put it where the page's last child goes,
 * inside a `relative` box that reaches the bottom of the area it should cover (the content area by
 * default; a column that also holds an image viewer, for example).
 */
export function LogPanel({ filter, levels }: { filter?: string[]; levels?: string[] }) {
  const { t } = useTranslation()
  const entries = useLogEntries(filter, levels)
  const [pinned, setPinned] = useLocalStorage('astrolol.log.open', false)
  const [height, setHeight] = useLocalStorage('astrolol.log.height', DEFAULT_H)
  const [peek, setPeek] = useState(false)
  const open = pinned || peek
  const h = Math.min(Math.max(height, MIN_H), maxHeight())

  const last = entries[entries.length - 1]
  const hovering = useRef(false)
  const following = useRef(true)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const seenId = useRef(last?.id)
  const mountedAt = useRef(Date.now())
  const pinnedRef = useRef(pinned)
  pinnedRef.current = pinned

  const fold = useCallback((ms: number) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(function tick() {
      // Stay open while the pointer is over it or the user is reading older lines.
      if (hovering.current || !following.current) { timer.current = setTimeout(tick, 1000); return }
      setPeek(false)
    }, ms)
  }, [])

  // A new entry unfolds a folded log for a moment.
  useEffect(() => {
    if (!last || last.id === seenId.current) return
    seenId.current = last.id
    if (pinnedRef.current || Date.now() - mountedAt.current < REPLAY_GRACE_MS) return
    setPeek(true)
    fold(peekDuration(last.level))
  }, [last, fold])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useEffect(() => { if (!open) following.current = true }, [open])

  const toggle = () => {
    if (timer.current) clearTimeout(timer.current)
    if (pinned) { setPinned(false); setPeek(false) }       // fold it
    else if (peek) { setPinned(true); setPeek(false) }     // keep what is peeking
    else setPinned(true)
  }

  const drag = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    const startY = e.clientY, startH = h
    const el = e.currentTarget
    el.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent) => setHeight(Math.min(maxHeight(), Math.max(MIN_H, Math.round(startH + startY - ev.clientY))))
    const up = () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up) }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
  }

  const label = open ? t('log.hide') : t('log.show')
  return (
    <>
      {/* The strip's place in the page; the panel itself overlays everything above it. */}
      <div className="shrink-0" style={{ height: STRIP_H }} />
      <div className="absolute inset-x-0 bottom-0 z-30 flex flex-col border-t border-surface-border bg-surface-raised"
        onMouseEnter={() => { hovering.current = true }} onMouseLeave={() => { hovering.current = false }}>
        {open && (
          <>
            <div onPointerDown={drag} title={t('log.resize')} role="separator" aria-orientation="horizontal"
              className="h-1.5 shrink-0 cursor-ns-resize touch-none bg-surface-border hover:bg-accent/50 active:bg-accent transition-colors" />
            <LogList entries={entries} style={{ height: h }} onFollowChange={(f) => { following.current = f }} />
          </>
        )}
        <div className="flex shrink-0 items-center gap-1 px-1" style={{ height: STRIP_H }}>
          <button type="button" onClick={toggle} aria-expanded={open} aria-label={label} title={label}
            className="p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-surface-overlay transition-colors">
            {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>
          {!open && (last
            ? <div className="min-w-0 flex-1 font-mono"><LogRow entry={last} /></div>
            : <span className="text-xs text-slate-600">{t('log.empty')}</span>)}
        </div>
      </div>
    </>
  )
}
