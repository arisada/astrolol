import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EventLog } from '@/components/ui/event-log'
import { useStore } from '@/store'
import type {
  SequencerBoundary,
  SequencerPreflightIssue,
  SequencerQueueEntry,
} from '@/api/types'
import * as seq from './api'
import { ControlBar } from './ControlBar'
import { JournalView } from './JournalView'
import { SequencesDialog } from './SequencesDialog'
import { SettingsPanel } from './SettingsPanel'
import { TaskCard } from './TaskCard'
import { TaskEditor } from './TaskEditor'
import { patchSequencerState, useSequencer } from './state'
import { Tabs } from '@/components/ui/tabs'

type Tab = 'queue' | 'journal' | 'settings'

export function SequencerPage() {
  const { t } = useTranslation('sequencer')
  const { status, entries } = useSequencer()
  const wsConnected = useStore((s) => s.wsConnected)
  const [tab, setTab] = useState<Tab>('queue')
  const [editing, setEditing] = useState<SequencerQueueEntry | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showSequences, setShowSequences] = useState(false)
  const [issues, setIssues] = useState<SequencerPreflightIssue[]>([])
  const dragId = useRef<string | null>(null)

  // Seed the store slice from REST on mount and whenever the WebSocket (re)connects —
  // events missed while disconnected would otherwise leave it stale.
  const refresh = useCallback(async () => {
    try {
      const [s, q] = await Promise.all([seq.getStatus(), seq.getQueue()])
      patchSequencerState({ status: s, entries: q })
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])
  useEffect(() => { void refresh() }, [refresh, wsConnected])

  // Pre-flight whenever the queue changes while idle, so problems show before Start.
  const idle = status?.run_state === 'idle'
  useEffect(() => {
    if (!idle || !entries) return
    if (!entries.some((e) => e.runtime.status === 'pending' || e.runtime.status === 'interrupted')) {
      setIssues([])
      return
    }
    const timer = setTimeout(() => {
      seq.preflight().then((r) => setIssues(r.issues)).catch(() => setIssues([]))
    }, 400)
    return () => clearTimeout(timer)
  }, [idle, entries])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      setError(null)
    } catch (e) {
      const err = e as seq.ApiError
      const report = (err.detail as { report?: { issues: SequencerPreflightIssue[] } } | undefined)?.report
      if (report) setIssues(report.issues)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!status || !entries) {
    return <div className="p-6 text-sm text-slate-500">{error ?? t('loading')}</div>
  }

  const done = entries.filter((e) => e.runtime.status === 'completed' || e.runtime.status === 'skipped')

  const onDrop = (targetId: string) => {
    const from = dragId.current
    dragId.current = null
    if (!from || from === targetId) return
    const ids = entries.map((e) => e.task.id).filter((id) => id !== from)
    ids.splice(ids.indexOf(targetId), 0, from)
    void act(() => seq.reorder(ids))
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl flex flex-col gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-semibold text-slate-100">{t('page.title')}</h1>
            <Tabs
              tabs={(['queue', 'journal', 'settings'] as const).map((name) => ({ id: name, label: t(`page.tabs.${name}`) }))}
              value={tab}
              onChange={setTab}
            />
          </div>

          {error && (
            <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
          )}

          {tab === 'settings' ? <SettingsPanel /> : tab === 'journal' ? <JournalView /> : (
            <>
              <ControlBar
                status={status}
                entries={entries}
                preflightIssues={issues}
                busy={busy}
                onStart={() => act(() => seq.start())}
                onPause={(w: SequencerBoundary) => act(() => seq.pause(w))}
                onResume={() => act(() => seq.resume())}
                onStop={(w: SequencerBoundary) => act(() => seq.stop(w))}
                onSkip={(w: SequencerBoundary) => act(() => seq.skipCurrent(w))}
              />

              <section className="flex flex-col gap-2">
                {entries.length === 0 && (
                  <p className="text-sm text-slate-500 py-6 text-center">
                    {t('page.empty')}
                  </p>
                )}
                {entries.map((entry) => {
                  const id = entry.task.id
                  const draggable = entry.runtime.status !== 'running'
                  return (
                    <TaskCard
                      key={id}
                      entry={entry}
                      isCurrent={status.current_task_id === id}
                      runState={status.run_state}
                      issues={idle ? issues.filter((i) => i.task_id === id) : []}
                      dragProps={{
                        draggable,
                        onDragStart: () => { dragId.current = id },
                        onDragOver: (e) => e.preventDefault(),
                        onDrop: () => onDrop(id),
                      }}
                      actions={{
                        edit: () => setEditing(entry),
                        duplicate: () => act(() => seq.duplicateTask(id)),
                        download: () => { window.location.href = seq.exportUrl([id]) },
                        startFrom: () => act(() => seq.start({ from_task: id })),
                        switchTo: () => act(() => seq.switchTo(id, 'frame')),
                        resetProgress: () => act(() => seq.resetProgress(id)),
                        skip: () => act(() => seq.skipTask(id)),
                        unskip: () => act(() => seq.unskipTask(id)),
                        remove: () => {
                          if (entry.runtime.lanes[0]?.groups.some((g) => g.frames_done > 0)
                            && !window.confirm(t('page.confirmDelete', { name: entry.task.name || entry.task.target.name }))) return
                          void act(() => seq.removeTask(id))
                        },
                      }}
                    />
                  )
                })}
                <div className="flex gap-2 mt-1">
                  <Button size="sm" onClick={() => setEditing('new')}>
                    <Plus size={13} className="mr-1" /> {t('page.add')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setShowSequences(true)}>
                    <FolderOpen size={13} className="mr-1" /> {t('page.sequences')}
                  </Button>
                  {done.length > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => act(() => seq.clearQueue(['completed', 'skipped']))}>
                      <Trash2 size={13} className="mr-1" /> {t('page.clearDone', { count: done.length })}
                    </Button>
                  )}
                  {entries.length > 1 && <span className="ml-auto self-center text-xs text-slate-500">{t('page.drag')}</span>}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
      <EventLog filter={['sequencer']} />

      {showSequences && (
        <SequencesDialog
          queueSize={entries.length}
          hasCompleted={entries.some((e) => e.runtime.status === 'completed')}
          onClose={() => setShowSequences(false)}
        />
      )}
      {editing && (
        <TaskEditor entry={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}
