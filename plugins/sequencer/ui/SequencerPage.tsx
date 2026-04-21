import { useEffect, useRef, useState } from 'react'
import { Play, Pause, Square, RotateCcw, Plus, Trash2, ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useStore } from '@/store'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FilterExposure {
  filter_name: string | null
  duration: number
  count: number
  binning: number
  gain: number
}

interface ImagingTask {
  id: string
  name: string | null
  target_name: string | null
  target_ra: number | null
  target_dec: number | null
  camera_device_id: string | null
  exposures: FilterExposure[]
  do_slew: boolean
  do_plate_solve: boolean
  dither_every: number | null
  on_error: 'skip' | 'pause' | 'abort'
}

interface TaskStatusMap {
  [id: string]: 'pending' | 'running' | 'completed' | 'failed'
}

interface SequencerStatus {
  state: string
  current_task_id: string | null
  current_task_name: string | null
  current_group_idx: number | null
  frames_done: number | null
  frames_total: number | null
  step_message: string | null
  error: string | null
  queue_length: number
  tasks_done: number
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const BASE = '/plugins/sequencer'

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail ?? `${r.status}`)
  }
  if (r.status === 204) return undefined as T
  return r.json()
}

// ---------------------------------------------------------------------------
// State badge
// ---------------------------------------------------------------------------

const STATE_COLORS: Record<string, string> = {
  idle:          'bg-slate-700 text-slate-300',
  imaging:       'bg-green-900 text-green-300',
  slewing:       'bg-blue-900 text-blue-300',
  plate_solving: 'bg-blue-900 text-blue-300',
  dithering:     'bg-purple-900 text-purple-300',
  meridian_flip: 'bg-yellow-900 text-yellow-300',
  paused:        'bg-yellow-900 text-yellow-300',
  parking:       'bg-slate-700 text-slate-400',
  unparking:     'bg-slate-700 text-slate-400',
  completed:     'bg-green-900 text-green-300',
  failed:        'bg-red-900 text-red-300',
  cancelled:     'bg-slate-700 text-slate-400',
}

function StateBadge({ state }: { state: string }) {
  const cls = STATE_COLORS[state] ?? 'bg-slate-700 text-slate-300'
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-mono font-medium ${cls}`}>
      {state.replace('_', ' ')}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Task row
// ---------------------------------------------------------------------------

function TaskRow({
  task,
  status,
  isCurrent,
  onRemove,
}: {
  task: ImagingTask
  status: 'pending' | 'running' | 'completed' | 'failed'
  isCurrent: boolean
  onRemove: () => void
}) {
  const totalFrames = task.exposures.reduce((s, e) => s + e.count, 0)
  const statusColor = {
    pending:   'border-surface-border',
    running:   'border-accent',
    completed: 'border-green-700',
    failed:    'border-red-700',
  }[status]

  return (
    <div className={`flex items-center gap-3 rounded border px-3 py-2 ${statusColor} ${isCurrent ? 'bg-surface-overlay' : 'bg-surface-raised'}`}>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-200 truncate">
          {task.name ?? task.target_name ?? `Task ${task.id.slice(0, 8)}`}
        </p>
        <p className="text-xs text-slate-500 truncate">
          {task.exposures.map(e => `${e.count}×${e.duration}s`).join(' · ')}
          {' · '}{totalFrames} frames
          {task.target_name && ` · ${task.target_name}`}
        </p>
      </div>
      <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${
        status === 'completed' ? 'bg-green-900/40 text-green-400' :
        status === 'failed'    ? 'bg-red-900/40 text-red-400' :
        status === 'running'   ? 'bg-accent/20 text-accent' :
        'text-slate-500'
      }`}>{status}</span>
      {status === 'pending' && (
        <Button variant="ghost" size="icon" onClick={onRemove} title="Remove">
          <Trash2 size={13} className="text-slate-500" />
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Add-task form
// ---------------------------------------------------------------------------

function AddTaskForm({ onAdd }: { onAdd: (task: Partial<ImagingTask>) => void }) {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const cameras = connectedDevices.filter((d) => d.kind === 'camera')

  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [targetName, setTargetName] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [duration, setDuration] = useState('300')
  const [count, setCount] = useState('20')
  const [gain, setGain] = useState('0')
  const [binning, setBinning] = useState('1')
  const [doSlew, setDoSlew] = useState(false)
  const [doPlate, setDoPlate] = useState(false)

  const handleAdd = () => {
    onAdd({
      name: name || null,
      target_name: targetName || null,
      target_ra: null,
      target_dec: null,
      camera_device_id: cameraId || null,
      exposures: [{ filter_name: null, duration: parseFloat(duration) || 300, count: parseInt(count) || 1, binning: parseInt(binning) || 1, gain: parseInt(gain) || 0 }],
      do_slew: doSlew,
      do_plate_solve: doPlate,
      dither_every: 1,
      on_error: 'pause',
    })
    setName('')
    setTargetName('')
    setOpen(false)
  }

  return (
    <div className="border border-surface-border rounded">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
      >
        <Plus size={14} />
        Add task
        {open ? <ChevronUp size={13} className="ml-auto" /> : <ChevronDown size={13} className="ml-auto" />}
      </button>

      {open && (
        <div className="border-t border-surface-border px-3 py-3 flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Task name</label>
              <Input placeholder="optional" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Target name</label>
              <Input placeholder="e.g. M31" value={targetName} onChange={(e) => setTargetName(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-4 gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Duration (s)</label>
              <Input type="number" min={1} value={duration} onChange={(e) => setDuration(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Count</label>
              <Input type="number" min={1} value={count} onChange={(e) => setCount(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Gain</label>
              <Input type="number" min={0} value={gain} onChange={(e) => setGain(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Binning</label>
              <Input type="number" min={1} max={4} value={binning} onChange={(e) => setBinning(e.target.value)} />
            </div>
          </div>

          {cameras.length > 1 && (
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Camera</label>
              <select
                value={cameraId}
                onChange={(e) => setCameraId(e.target.value)}
                className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
              >
                <option value="">First connected camera</option>
                {cameras.map((c) => <option key={c.device_id} value={c.device_id}>{c.device_id}</option>)}
              </select>
            </div>
          )}

          <div className="flex gap-4 text-xs text-slate-400">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={doSlew} onChange={(e) => setDoSlew(e.target.checked)} className="accent-accent" />
              Slew to target
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={doPlate} onChange={(e) => setDoPlate(e.target.checked)} className="accent-accent" />
              Plate solve
            </label>
          </div>

          <Button className="self-start" onClick={handleAdd}>
            <Plus size={13} className="mr-1" /> Add to queue
          </Button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function SequencerPage() {
  const [status, setStatus] = useState<SequencerStatus | null>(null)
  const [queue, setQueue] = useState<ImagingTask[]>([])
  const [taskStatuses, setTaskStatuses] = useState<TaskStatusMap>({})
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = async () => {
    try {
      const [s, q] = await Promise.all([
        apiFetch<SequencerStatus>('/status'),
        apiFetch<{ task: ImagingTask; status: string }[]>('/queue'),
      ])
      setStatus(s)
      setQueue(q.map((e) => e.task))
      const statuses: TaskStatusMap = {}
      for (const e of q) statuses[e.task.id] = e.status as TaskStatusMap[string]
      setTaskStatuses(statuses)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  useEffect(() => {
    refresh()
    pollRef.current = setInterval(refresh, 2000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); await refresh() }
    catch (e) { setError((e as Error).message) }
  }

  const handleAdd = (task: Partial<ImagingTask>) =>
    act(() => apiFetch('/queue', { method: 'POST', body: JSON.stringify(task) }))

  const handleRemove = (id: string) =>
    act(() => apiFetch(`/queue/${id}`, { method: 'DELETE' }))

  const handleStart  = () => act(() => apiFetch('/start',  { method: 'POST' }))
  const handlePause  = () => act(() => apiFetch('/pause',  { method: 'POST' }))
  const handleResume = () => act(() => apiFetch('/resume', { method: 'POST' }))
  const handleCancel = () => act(() => apiFetch('/cancel', { method: 'POST' }))
  const handleReset  = () => act(() => apiFetch('/reset',  { method: 'POST' }))

  const state = status?.state ?? 'idle'
  const isRunning = state === 'imaging' || state === 'slewing' || state === 'plate_solving' ||
                    state === 'dithering' || state === 'meridian_flip' || state === 'unparking' ||
                    state === 'parking' || state === 'guiding' || state === 'focusing'
  const isPaused = state === 'paused'
  const isIdle = state === 'idle' || state === 'completed' || state === 'cancelled' || state === 'failed'

  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">Sequencer</h1>

      {/* Status panel */}
      <section className="bg-surface-raised border border-surface-border rounded p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <StateBadge state={state} />
          <span className="text-xs text-slate-500">
            {status && `${status.tasks_done} / ${status.queue_length} tasks`}
          </span>
        </div>

        {status?.step_message && (
          <p className="text-sm text-slate-300 mb-2">{status.step_message}</p>
        )}

        {status?.current_task_name && isRunning && (
          <p className="text-xs text-slate-500 mb-2">
            Task: <span className="text-slate-300">{status.current_task_name}</span>
            {status.frames_done != null && status.frames_total != null && (
              <> · frame {status.frames_done}/{status.frames_total}</>
            )}
          </p>
        )}

        {status?.error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-2 py-1 mb-2">
            {status.error}
          </p>
        )}

        {error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-2 py-1 mb-2">{error}</p>
        )}

        {/* Controls */}
        <div className="flex gap-2 mt-3">
          {isIdle && queue.length > 0 && (
            <Button onClick={handleStart} size="sm">
              <Play size={13} className="mr-1" /> Start
            </Button>
          )}
          {isRunning && (
            <Button onClick={handlePause} variant="outline" size="sm">
              <Pause size={13} className="mr-1" /> Pause
            </Button>
          )}
          {isPaused && (
            <Button onClick={handleResume} size="sm">
              <Play size={13} className="mr-1" /> Resume
            </Button>
          )}
          {(isRunning || isPaused) && (
            <Button onClick={handleCancel} variant="outline" size="sm">
              <Square size={13} className="mr-1" /> Cancel
            </Button>
          )}
          {!isRunning && !isPaused && (
            <Button onClick={handleReset} variant="ghost" size="sm">
              <RotateCcw size={13} className="mr-1" /> Clear
            </Button>
          )}
        </div>
      </section>

      {/* Queue */}
      <section>
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Queue</h2>
        <div className="flex flex-col gap-2 mb-3">
          {queue.length === 0 ? (
            <p className="text-sm text-slate-500">No tasks queued.</p>
          ) : (
            queue.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                status={taskStatuses[task.id] ?? 'pending'}
                isCurrent={status?.current_task_id === task.id}
                onRemove={() => handleRemove(task.id)}
              />
            ))
          )}
        </div>
        <AddTaskForm onAdd={handleAdd} />
      </section>
    </div>
  )
}
