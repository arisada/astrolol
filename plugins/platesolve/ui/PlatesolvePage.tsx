import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Camera, ChevronDown, ChevronUp, Download, ScanSearch, Settings, X } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import type { ConnectedDevice, DbStatus, MountStatus, Profile, SolveJob, SolveResult, UserSettings } from '@/api/types'

// ── Types ──────────────────────────────────────────────────────────────────────

type AfterSolve = 'nothing' | 'sync' | 'sync_slew'

// ── Coordinate formatters (RA in hours, Dec in degrees) ───────────────────────

function fmtRA(h: number | null | undefined): string {
  if (h == null) return '—'
  const H = Math.floor(h)
  const mf = (h - H) * 60
  const M = Math.floor(mf)
  const S = ((mf - M) * 60).toFixed(1)
  return `${String(H).padStart(2, '0')}h ${String(M).padStart(2, '0')}m ${S.padStart(4, '0')}s`
}

function fmtDec(d: number | null | undefined): string {
  if (d == null) return '—'
  const sign = d < 0 ? '−' : '+'
  const abs = Math.abs(d)
  const deg = Math.floor(abs)
  const mf = (abs - deg) * 60
  const min = Math.floor(mf)
  const sec = Math.round((mf - min) * 60)
  return `${sign}${String(deg).padStart(2, '0')}° ${String(min).padStart(2, '0')}′ ${String(sec).padStart(2, '0')}″`
}

function fmtField(deg: number): string {
  return deg >= 1 ? `${deg.toFixed(2)}°` : `${(deg * 60).toFixed(1)}′`
}

// ── localStorage helpers ───────────────────────────────────────────────────────

function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored !== null ? (JSON.parse(stored) as T) : initial
    } catch { return initial }
  })
  const set = useCallback((v: T) => {
    setValue(v)
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* full */ }
  }, [key])
  return [value, set]
}

// ── Exposure duration stepper ──────────────────────────────────────────────────

const EXPOSURE_STEPS = [
  0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8,
  1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15,
]

function fmtDuration(s: number): string {
  if (s < 1) return `${Math.round(s * 1000)} ms`
  return `${s} s`
}

function DurationStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const idx = EXPOSURE_STEPS.reduce(
    (best, v, i) => Math.abs(v - value) < Math.abs(EXPOSURE_STEPS[best] - value) ? i : best, 0,
  )
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">Duration</span>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="outline" disabled={idx === 0}
          onClick={() => onChange(EXPOSURE_STEPS[idx - 1])} title="Shorter">
          <ChevronDown size={14} />
        </Button>
        <span className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5">
          {fmtDuration(value)}
        </span>
        <Button size="icon" variant="outline" disabled={idx === EXPOSURE_STEPS.length - 1}
          onClick={() => onChange(EXPOSURE_STEPS[idx + 1])} title="Longer">
          <ChevronUp size={14} />
        </Button>
      </div>
    </div>
  )
}

// ── Status badge ───────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: SolveJob['status'] }) {
  const styles: Record<SolveJob['status'], string> = {
    pending:   'bg-surface-border text-muted',
    solving:   'bg-accent/20 text-accent animate-pulse',
    completed: 'bg-green-500/20 text-green-400',
    failed:    'bg-red-500/20 text-red-400',
    cancelled: 'bg-surface-border text-muted',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status]}`}>
      {status}
    </span>
  )
}

// ── Result panel ───────────────────────────────────────────────────────────────

function ResultPanel({ result }: { result: SolveResult }) {
  return (
    <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-4">
      <div className="text-xs font-medium text-green-400 uppercase tracking-wider mb-2">Solved</div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
        <div><span className="text-slate-500">RA</span>
          <span className="ml-2 font-mono text-slate-200">{fmtRA(result.ra / 15)}</span></div>
        <div><span className="text-slate-500">Dec</span>
          <span className="ml-2 font-mono text-slate-200">{fmtDec(result.dec)}</span></div>
        <div><span className="text-slate-500">Rotation</span>
          <span className="ml-2 font-mono text-slate-200">{result.rotation.toFixed(2)}°</span></div>
        <div><span className="text-slate-500">Scale</span>
          <span className="ml-2 font-mono text-slate-200">{result.pixel_scale.toFixed(3)}″/px</span></div>
        <div><span className="text-slate-500">Field</span>
          <span className="ml-2 font-mono text-slate-200">{fmtField(result.field_w)} × {fmtField(result.field_h)}</span></div>
        <div><span className="text-slate-500">Solved in</span>
          <span className="ml-2 font-mono text-slate-200">{(result.duration_ms / 1000).toFixed(1)}s</span></div>
      </div>
    </div>
  )
}

// ── Job history row ────────────────────────────────────────────────────────────

function JobRow({ job, onCancel }: { job: SolveJob; onCancel: (id: string) => void }) {
  const filename = job.request.fits_path.split('/').pop() ?? job.request.fits_path
  const active = job.status === 'pending' || job.status === 'solving'
  return (
    <div className="flex items-start gap-3 py-2 border-b border-surface-border last:border-0">
      <div className="mt-0.5 shrink-0"><StatusBadge status={job.status} /></div>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-slate-300 truncate font-mono">{filename}</div>
        {job.status === 'completed' && job.result && (
          <div className="text-xs text-slate-500 mt-0.5">
            {fmtRA(job.result.ra / 15)} {fmtDec(job.result.dec)}
            {' · '}{job.result.pixel_scale.toFixed(3)}″/px
            {' · '}{(job.result.duration_ms / 1000).toFixed(1)}s
          </div>
        )}
        {job.status === 'failed' && (
          <div className="text-xs text-red-400 mt-0.5 truncate">{job.error}</div>
        )}
      </div>
      {active && (
        <button onClick={() => onCancel(job.id)}
          className="shrink-0 text-slate-600 hover:text-slate-300 transition-colors" title="Cancel">
          <X size={14} />
        </button>
      )}
    </div>
  )
}

// ── Settings panel ─────────────────────────────────────────────────────────────

function SettingsPanel({ settings, onChange }: { settings: UserSettings; onChange: (s: UserSettings) => void }) {
  const [saving, setSaving] = useState(false)
  const [local, setLocal] = useState(settings)
  useEffect(() => { setLocal(settings) }, [settings])

  const save = async () => {
    setSaving(true)
    try { onChange(await api.settings.put(local)) } catch { /* ignore */ } finally { setSaving(false) }
  }

  const inp = (value: string, fn: (v: string) => void, placeholder?: string) => (
    <input value={value} placeholder={placeholder}
      onChange={(e) => fn(e.target.value)}
      className="rounded border border-surface-border bg-surface-overlay px-2 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:ring-1 focus:ring-accent w-full"
    />
  )

  return (
    <div className="border border-surface-border rounded-lg p-4 flex flex-col gap-3">
      <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Settings</h3>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">ASTAP binary</span>
        {inp(local.astap_bin, (v) => setLocal({ ...local, astap_bin: v }))}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">Star database path</span>
        {inp(local.astap_db_path, (v) => setLocal({ ...local, astap_db_path: v }))}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">Search radius (°)</span>
        {inp(String(local.astap_search_radius), (v) => setLocal({ ...local, astap_search_radius: parseFloat(v) || 30 }))}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">Pixel size (µm, optional)</span>
        {inp(
          local.pixel_size_um != null ? String(local.pixel_size_um) : '',
          (v) => setLocal({ ...local, pixel_size_um: v ? (parseFloat(v) || null) : null }),
          'e.g. 3.76'
        )}
      </div>
      <Button size="sm" onClick={save} disabled={saving} className="self-start">
        {saving ? 'Saving…' : 'Save'}
      </Button>
    </div>
  )
}

// ── DB warning banner ──────────────────────────────────────────────────────────

function DbWarningBanner({ dbPath, onInstall, installing }: {
  dbPath: string
  onInstall: () => void
  installing: boolean
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-yellow-600/40 bg-yellow-500/10 px-4 py-3">
      <AlertTriangle size={16} className="text-yellow-500 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-yellow-300 font-medium">Star database not found</p>
        <p className="text-xs text-yellow-600 mt-0.5">
          No <code>.290</code> or <code>.dat</code> files in <code className="font-mono">{dbPath}</code>.
          ASTAP needs a star database to solve images.
        </p>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={onInstall}
        disabled={installing}
        className="shrink-0 border-yellow-600/50 text-yellow-400 hover:bg-yellow-500/10"
      >
        <Download size={12} className="mr-1.5" />
        {installing ? 'Installing…' : 'Install d05'}
      </Button>
    </div>
  )
}

// ── Plate-solve log panel ──────────────────────────────────────────────────────

function SolveLog() {
  const log = useStore((s) => s.log.filter((e) => e.component === 'platesolve'))
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log.length])

  return (
    <div className="h-36 bg-black border-t border-surface-border overflow-y-auto px-3 py-2 font-mono">
      {log.length === 0 ? (
        <span className="text-xs text-slate-700">Plate-solve log</span>
      ) : (
        [...log].reverse().map((e) => (
          <div key={e.id} className="flex gap-2 text-xs leading-5">
            <span className="text-slate-600 shrink-0">{e.timestamp.slice(11, 19)}</span>
            <span className={`truncate ${e.level === 'error' ? 'text-red-400' : e.level === 'warning' ? 'text-yellow-400' : 'text-slate-400'}`}>
              {e.message}
            </span>
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  )
}

// ── Image viewer ───────────────────────────────────────────────────────────────

function ImageViewer() {
  const image = useStore((s) => s.latestImage)
  return (
    <div className="bg-black flex items-center justify-center relative" style={{ minHeight: '200px', maxHeight: '300px', overflow: 'hidden' }}>
      {image ? (
        <>
          <img src={image.previewUrl} alt="Latest exposure"
            className="max-w-full object-contain" style={{ maxHeight: '300px' }} />
          <div className="absolute bottom-2 left-2 text-xs text-slate-400 bg-black/60 px-2 py-1 rounded">
            {image.width}×{image.height} · {image.duration}s
          </div>
        </>
      ) : (
        <div className="text-slate-700 text-sm flex flex-col items-center gap-2 py-8">
          <Camera size={28} />
          <span>No image</span>
        </div>
      )}
    </div>
  )
}

// ── FOV calculator ─────────────────────────────────────────────────────────────

function computeFov(
  focalLength: number | undefined,
  pixelSizeUm: number | null | undefined,
  imageWidth: number | null | undefined,
): number | null {
  if (!focalLength || !pixelSizeUm || !imageWidth) return null
  const pixelScaleArcsec = (pixelSizeUm / focalLength) * 206.265
  return (pixelScaleArcsec * imageWidth) / 3600
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function PlatesolvePage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const mountStatuses    = useStore((s) => s.mountStatuses)
  const latestImage      = useStore((s) => s.latestImage)
  const solveJobsMap     = useStore((s) => s.solveJobs)
  const mergeSolveJobs   = useStore((s) => s.mergeSolveJobs)

  const cameras = connectedDevices.filter((d) => d.kind === 'camera')
  const [selectedCameraId, setSelectedCameraId] = useLocalStorage<string>(
    'platesolve.cameraId', cameras[0]?.device_id ?? ''
  )
  const camera = cameras.find((d) => d.device_id === selectedCameraId) ?? cameras[0] ?? null

  const mount = connectedDevices.find((d) => d.kind === 'mount') ?? null
  const mountStatus: MountStatus | null = mount ? (mountStatuses[mount.device_id] ?? null) : null

  const [duration, setDuration] = useLocalStorage('platesolve.duration', 5)
  const [binning,  setBinning]  = useLocalStorage('platesolve.binning', 1)
  const [afterSolve, setAfterSolve] = useLocalStorage<AfterSolve>('platesolve.afterSolve', 'nothing')

  const [settings, setSettings]       = useState<UserSettings | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [activeProfile, setActiveProfile] = useState<Profile | null>(null)
  const [dbStatus, setDbStatus]       = useState<DbStatus | null>(null)
  const [installing, setInstalling]   = useState(false)

  const [error, setError]           = useState<string | null>(null)
  const [busy, setBusy]             = useState(false)
  const [activeSolveId, setActiveSolveId] = useState<string | null>(null)
  const pendingSolveRef = useRef(false)
  const prevSolveStatusRef = useRef<string | undefined>(undefined)

  useEffect(() => {
    api.settings.get().then(setSettings).catch(console.error)
    api.profiles.active().then(setActiveProfile).catch(console.error)
    api.platesolve.jobs().then(mergeSolveJobs).catch(console.error)
    api.platesolve.dbStatus().then(setDbStatus).catch(console.error)
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-launch solve once new image arrives
  useEffect(() => {
    if (!pendingSolveRef.current || !latestImage) return
    pendingSolveRef.current = false
    launchSolve(latestImage.fitsPath, latestImage.width)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestImage?.fitsPath])

  // React to solve completion
  const activeSolveJob = activeSolveId ? solveJobsMap[activeSolveId] : null
  useEffect(() => {
    if (!activeSolveJob) return
    const prev = prevSolveStatusRef.current
    prevSolveStatusRef.current = activeSolveJob.status
    if (prev === activeSolveJob.status) return
    if (activeSolveJob.status === 'completed' && activeSolveJob.result) {
      handlePostSolve(activeSolveJob.result)
    } else if (activeSolveJob.status === 'failed') {
      setError(activeSolveJob.error ?? 'Solve failed')
      setBusy(false)
    } else if (activeSolveJob.status === 'cancelled') {
      setBusy(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSolveJob?.status])

  const handlePostSolve = async (result: SolveResult) => {
    if (!mount || afterSolve === 'nothing') { setBusy(false); return }
    try {
      await api.mount.sync(mount.device_id, result.ra / 15, result.dec)
      if (afterSolve === 'sync_slew') {
        await api.mount.slew(mount.device_id, result.ra / 15, result.dec)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const launchSolve = async (fitsPath: string, imageWidth?: number) => {
    if (!settings) return
    setError(null)
    const ra  = mountStatus?.ra  != null ? mountStatus.ra * 15  : undefined
    const dec = mountStatus?.dec != null ? mountStatus.dec       : undefined
    const fov = computeFov(
      activeProfile?.telescope?.focal_length,
      settings.pixel_size_um,
      imageWidth ?? latestImage?.width,
    ) ?? undefined

    try {
      const job = await api.platesolve.solve({
        fits_path: fitsPath,
        ra_hint: ra, dec_hint: dec,
        radius: settings.astap_search_radius,
        fov,
      })
      mergeSolveJobs([job])
      setActiveSolveId(job.id)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const handleExposeAndSolve = async () => {
    if (!camera) return
    setError(null)
    setBusy(true)
    setActiveSolveId(null)
    prevSolveStatusRef.current = undefined
    try {
      pendingSolveRef.current = true
      await api.imager.expose(camera.device_id, { duration, binning, frame_type: 'light', save: true })
    } catch (e) {
      pendingSolveRef.current = false
      setBusy(false)
      setError((e as Error).message)
    }
  }

  const handleCancel = async (jobId: string) => {
    try { await api.platesolve.cancel(jobId) } catch (e) { setError((e as Error).message) }
  }

  const handleInstallDb = async () => {
    setInstalling(true)
    try {
      await api.platesolve.installDb()
      // Re-check after a delay (installation is async on the server)
      setTimeout(() => {
        api.platesolve.dbStatus().then(setDbStatus).catch(console.error)
        setInstalling(false)
      }, 3000)
    } catch (e) {
      setError((e as Error).message)
      setInstalling(false)
    }
  }

  const BINNINGS = [1, 2, 3, 4]
  const jobs = Object.values(solveJobsMap).sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )
  const lastCompleted = jobs.find((j) => j.status === 'completed' && j.result)

  const fovHint = settings ? computeFov(
    activeProfile?.telescope?.focal_length, settings.pixel_size_um, latestImage?.width,
  ) : null

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Scrollable controls area */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-xl mx-auto flex flex-col gap-4">

          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ScanSearch size={18} className="text-accent" />
              <h1 className="text-base font-semibold text-slate-200">Plate Solving</h1>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setShowSettings((v) => !v)}
              className={showSettings ? 'text-accent' : ''} title="Settings">
              <Settings size={15} />
            </Button>
          </div>

          {/* Settings panel */}
          {showSettings && settings && (
            <SettingsPanel settings={settings} onChange={setSettings} />
          )}

          {/* DB warning */}
          {dbStatus && !dbStatus.installed && (
            <DbWarningBanner
              dbPath={dbStatus.db_path}
              onInstall={handleInstallDb}
              installing={installing}
            />
          )}

          {/* Controls */}
          <div className="border border-surface-border rounded-lg p-4 flex flex-col gap-4">

            {/* Camera selector */}
            <div className="flex flex-col gap-1">
              <span className="text-xs text-slate-400">Camera</span>
              {cameras.length === 0 ? (
                <span className="text-xs text-slate-600">No camera connected</span>
              ) : cameras.length === 1 ? (
                <span className="text-xs text-slate-300 font-mono">{cameras[0].device_id}</span>
              ) : (
                <select value={camera?.device_id ?? ''} onChange={(e) => setSelectedCameraId(e.target.value)}
                  className="rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
                  {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
                </select>
              )}
            </div>

            {/* Duration + Binning */}
            <div className="grid grid-cols-2 gap-4">
              <DurationStepper value={duration} onChange={setDuration} />
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-400">Binning</span>
                <div className="flex gap-1">
                  {BINNINGS.map((b) => (
                    <button key={b} type="button" onClick={() => setBinning(b)}
                      className={`px-2 py-0.5 text-xs rounded border transition-colors
                        ${binning === b
                          ? 'border-accent text-accent bg-accent/10'
                          : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'}`}>
                      {b}×{b}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* FOV info */}
            {fovHint != null && settings?.pixel_size_um && activeProfile?.telescope?.focal_length && (
              <p className="text-xs text-slate-600">
                {`Optics: ${((settings.pixel_size_um / activeProfile.telescope.focal_length) * 206.265).toFixed(3)}″/px · FOV hint ${fmtField(fovHint)}`}
              </p>
            )}

            {/* After-solve action */}
            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-slate-400">After solve</span>
              {(['nothing', 'sync', 'sync_slew'] as const).map((v) => {
                const labels: Record<AfterSolve, string> = {
                  nothing: 'Do nothing', sync: 'Sync mount', sync_slew: 'Sync and slew',
                }
                return (
                  <label key={v} className="flex items-center gap-2 cursor-pointer select-none">
                    <input type="radio" name="afterSolve" value={v}
                      checked={afterSolve === v} onChange={() => setAfterSolve(v)}
                      className="accent-accent" />
                    <span className={`text-xs ${afterSolve === v ? 'text-slate-200' : 'text-slate-400'}`}>
                      {labels[v]}
                    </span>
                  </label>
                )
              })}
              {afterSolve !== 'nothing' && !mount && (
                <p className="text-xs text-yellow-600">No mount connected</p>
              )}
            </div>

            {error && <p className="text-xs text-red-400">{error}</p>}

            <Button onClick={handleExposeAndSolve} disabled={busy || !camera} className="w-full">
              <ScanSearch size={14} className="mr-2" />
              {busy
                ? (activeSolveJob?.status === 'solving' ? 'Solving…' : 'Exposing…')
                : 'Expose & Solve'}
            </Button>
          </div>

          {/* Last result */}
          {lastCompleted?.result && <ResultPanel result={lastCompleted.result} />}

          {/* Job history */}
          {jobs.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Recent solves</h2>
              <div className="rounded-lg border border-surface-border bg-surface px-4">
                {jobs.map((job) => <JobRow key={job.id} job={job} onCancel={handleCancel} />)}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Image preview — bottom */}
      <ImageViewer />

      {/* Plate-solve log — very bottom */}
      <SolveLog />
    </div>
  )
}
