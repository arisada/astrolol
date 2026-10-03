import { useCallback, useEffect, useRef, useState } from 'react'
import { Compass, RefreshCw, StopCircle } from 'lucide-react'
import * as polarAlignApi from './api'
import { ReticleDial } from './ReticleDial'
import { useStore } from '@/store'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { StatusPill } from '@/components/ui/badge'
import type { StatusPillVariant } from '@/components/ui/badge'
import type { ReticleState, WizardRun, WizardStatus } from '@/api/types'

const RUN_PILL_VARIANT: Record<WizardStatus, StatusPillVariant> = {
  running: 'amber', converging: 'accent', completed: 'green', failed: 'red', cancelled: 'slate',
}

function altHint(arcmin: number): string {
  return arcmin >= 0
    ? `${arcmin.toFixed(1)}′ too high — lower the altitude adjustment`
    : `${(-arcmin).toFixed(1)}′ too low — raise the altitude adjustment`
}

function azHint(arcmin: number): string {
  return arcmin >= 0
    ? `${arcmin.toFixed(1)}′ east of true north — decrease azimuth`
    : `${(-arcmin).toFixed(1)}′ west of true north — increase azimuth`
}

// Thresholds on the combined (quadrature-summed) alt/az error — rough amateur-imaging
// guidance, not a hard physical cutoff: 1' is comfortable for long narrowband subs at
// most focal lengths, 3' is fine for most imaging, beyond 7' field rotation over a
// sub-length exposure starts being visible on longer focal lengths.
type PaQuality = 'excellent' | 'good' | 'fair' | 'poor'

function paQuality(altArcmin: number, azArcmin: number): PaQuality {
  const total = Math.hypot(altArcmin, azArcmin)
  if (total <= 1) return 'excellent'
  if (total <= 3) return 'good'
  if (total <= 7) return 'fair'
  return 'poor'
}

const QUALITY_LABEL: Record<PaQuality, string> = {
  excellent: 'Excellent', good: 'Good', fair: 'Fair', poor: 'Needs work',
}
const QUALITY_CLASS: Record<PaQuality, string> = {
  excellent: 'text-emerald-400', good: 'text-sky-400', fair: 'text-amber-400', poor: 'text-red-400',
}

function QualityBadge({ altArcmin, azArcmin }: { altArcmin: number; azArcmin: number }) {
  const q = paQuality(altArcmin, azArcmin)
  const total = Math.hypot(altArcmin, azArcmin)
  return (
    <span className={`text-xs font-medium ${QUALITY_CLASS[q]}`}>
      {QUALITY_LABEL[q]} ({total.toFixed(1)}′ total)
    </span>
  )
}

export function PolarAlignPage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const mounts = connectedDevices.filter((d) => d.kind === 'mount')
  const cameras = connectedDevices.filter((d) => d.kind === 'camera')

  const [mountId, setMountId] = useState('')
  const [cameraId, setCameraId] = useState('')
  useEffect(() => {
    if (!mountId && mounts.length > 0) setMountId(mounts[0].device_id)
  }, [mounts]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!cameraId && cameras.length > 0) setCameraId(cameras[0].device_id)
  }, [cameras]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─────────────────────────────────────────────────────────────────────────
  // Part 1: reticle
  // ─────────────────────────────────────────────────────────────────────────

  const [reticle, setReticle] = useState<ReticleState | null>(null)
  const [reticleError, setReticleError] = useState<string | null>(null)

  // Purely a per-viewer display convenience (SPEC.md section 2): most polar scopes have
  // no erecting prism, so a simple lens inverts the image -- both axes at once, i.e. a
  // 180deg rotation, not a mirror.
  const [assumeInvertingScope, setAssumeInvertingScope] = useLocalStorage('polar_align.assume_inverting_scope', true)
  const displayReticle: ReticleState | null = reticle && assumeInvertingScope
    ? { ...reticle, angle_deg: (reticle.angle_deg + 180) % 360 }
    : reticle

  const fetchReticle = useCallback(() => {
    polarAlignApi.getReticle()
      .then((s) => { setReticle(s); setReticleError(null) })
      .catch((e) => setReticleError(e instanceof Error ? e.message : 'Failed to read reticle'))
  }, [])

  useEffect(() => {
    fetchReticle()
    const id = setInterval(fetchReticle, 5000) // Polaris barely moves; no need to poll fast
    return () => clearInterval(id)
  }, [fetchReticle])

  // ─────────────────────────────────────────────────────────────────────────
  // Part 2: plate-solve wizard
  // ─────────────────────────────────────────────────────────────────────────

  const [run, setRun] = useState<WizardRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [wizardError, setWizardErrorText] = useState<string | null>(null)
  const [wizardErrorAt, setWizardErrorAt] = useState<Date | null>(null)
  const setWizardError = useCallback((msg: string | null) => {
    setWizardErrorText(msg)
    setWizardErrorAt(msg ? new Date() : null)
  }, [])
  const [exposureS, setExposureS] = useState(5)
  const [binning, setBinning] = useState(2)
  // '' = let the wizard pick the Dec (it never inherits the mount's current Dec).
  const [decInput, setDecInput] = useState('')
  const decOverride = decInput.trim() === '' ? null : Number(decInput)
  const decInvalid = decOverride !== null && (!Number.isFinite(decOverride) || Math.abs(decOverride) > 80)
  // Recheck (CONVERGING-phase) settings -- '' = reuse the main fit's own exposure_s,
  // same default as the backend (WizardRequest.converge_exposure_s: None).
  const [convergeExposureInput, setConvergeExposureInput] = useState('')
  const convergeExposureS = convergeExposureInput.trim() === '' ? null : Number(convergeExposureInput)
  const [convergeSearchRadiusDeg, setConvergeSearchRadiusDeg] = useState(3)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRun = useCallback(async () => {
    try {
      const r = await polarAlignApi.getWizard()
      setRun(r)
      if (r.status !== 'running' && r.status !== 'converging') {
        setBusy(false)
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      }
    } catch { /* 404 = no run yet */ }
  }, [])

  useEffect(() => {
    polarAlignApi.getWizard().then((r) => {
      setRun(r)
      if (r.status === 'running') setBusy(true)
      // Keep polling through CONVERGING too: the backend can be driving its own
      // auto-refresh rechecks (see handleToggleAutoRefresh) with no browser tab
      // watching, so this tab needs to pick those up on its own, not just whatever
      // a local button click last set.
      if (r.status === 'running' || r.status === 'converging') {
        pollRef.current = setInterval(fetchRun, 1500)
      }
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchRun])

  const handleStart = useCallback(async () => {
    if (!mountId || !cameraId) { setWizardError('A mount and camera must be connected.'); return }
    if (decInvalid) { setWizardError('Dec must be a number between -80 and 80, or blank for automatic.'); return }
    setWizardError(null)
    setBusy(true)
    setRun(null)
    try {
      const r = await polarAlignApi.startWizard({
        mount_id: mountId, camera_id: cameraId, exposure_s: exposureS, binning, dec_deg: decOverride,
        converge_exposure_s: convergeExposureS, converge_search_radius_deg: convergeSearchRadiusDeg,
      })
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (e) {
      setBusy(false)
      setWizardError(e instanceof Error ? e.message : 'Failed to start')
    }
  }, [mountId, cameraId, exposureS, binning, decOverride, decInvalid, convergeExposureS,
      convergeSearchRadiusDeg, fetchRun, setWizardError])

  const [rechecking, setRechecking] = useState(false)
  const handleRecheck = useCallback(async () => {
    setRechecking(true)
    try {
      setRun(await polarAlignApi.recheckWizard())
    } catch {
      // The run itself now carries last_recheck_error/last_recheck_at (set by the
      // backend regardless of whether a manual click or auto-refresh triggered the
      // failed reading) -- refetch it instead of keeping a separate local error string,
      // so both paths render through the same place below.
      await fetchRun()
    } finally {
      setRechecking(false)
    }
  }, [fetchRun])

  const [autoRefreshIntervalInput, setAutoRefreshIntervalInput] = useState(20)
  const [autoRefreshBusy, setAutoRefreshBusy] = useState(false)
  const handleToggleAutoRefresh = useCallback(async () => {
    setAutoRefreshBusy(true)
    try {
      if (run?.auto_refresh_interval_s != null) {
        await polarAlignApi.stopAutoRefresh()
      } else {
        await polarAlignApi.startAutoRefresh({ interval_s: autoRefreshIntervalInput })
      }
      await fetchRun()
    } catch (e) {
      setWizardError(e instanceof Error ? e.message : 'Failed to toggle auto-refresh')
    } finally {
      setAutoRefreshBusy(false)
    }
  }, [run?.auto_refresh_interval_s, autoRefreshIntervalInput, fetchRun, setWizardError])

  const handleStop = useCallback(async () => {
    try {
      await polarAlignApi.cancelWizard()
    } finally {
      await fetchRun()
      setBusy(false)
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    }
  }, [fetchRun])

  const handleStartNew = useCallback(() => {
    setRun(null)
    setWizardError(null)
  }, [setWizardError])

  const isTerminal = run && (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled')

  return (
    <div className="p-4 md:p-6 max-w-2xl space-y-4 overflow-y-auto h-full">
      <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
        <Compass size={18} /> Polar Alignment
      </h1>

      {mounts.length > 0 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-400">Mount</span>
          {mounts.length === 1 ? (
            <span className="text-slate-300 font-mono">{mounts[0].device_id}</span>
          ) : (
            <select value={mountId} onChange={(e) => setMountId(e.target.value)}
              className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
              {mounts.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
            </select>
          )}
        </div>
      )}

      {/* ── Part 1: reticle ── */}
      <Card title="Polar Scope Reticle" className="p-4 space-y-3">
        <p className="text-xs text-slate-500">
          The dot shows where Polaris should sit on your polar scope's reticle right now.
          With tracking off, rotate the RA axis by hand until the real star (seen through
          your eyepiece) matches the dot's position below.
        </p>

        <div className="flex items-start justify-between gap-3 rounded border border-surface-border bg-surface-overlay/50 px-3 py-2">
          <label className="text-xs text-slate-400 leading-tight">
            Assume a typical inverting scope
            <span className="block text-[10px] text-slate-600">
              Most polar scopes have no erecting prism, so a simple lens flips the image
              both left-right and top-bottom at once — equivalent to a 180° rotation, not
              a mirror. Leave this on unless you know yours shows the sky upright.
            </span>
          </label>
          <ToggleSwitch
            label="Assume a typical 180deg-inverting scope"
            checked={assumeInvertingScope}
            onChange={() => setAssumeInvertingScope(!assumeInvertingScope)}
          />
        </div>

        {reticleError && <p className="text-xs text-red-400">{reticleError}</p>}

        <div className="flex flex-col items-center">
          <ReticleDial state={displayReticle} />
        </div>
      </Card>

      {/* ── Part 2: wizard ── */}
      <Card title="Plate-Solve Wizard" className="p-4 space-y-3">
        {!run && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-400">Camera</label>
                {cameras.length === 0 ? (
                  <span className="text-xs text-slate-600">None connected</span>
                ) : cameras.length === 1 ? (
                  <span className="text-xs text-slate-300 font-mono">{cameras[0].device_id}</span>
                ) : (
                  <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}
                    className="rounded bg-surface-overlay border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent">
                    {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
                  </select>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-400">Exposure (s)</label>
                <Input inputSize="sm" type="number" min={0.1} step={0.5}
                  value={exposureS} onChange={(e) => setExposureS(Number(e.target.value) || 1)} />
              </div>
            </div>

            <PillGroup options={[1, 2, 3, 4]} value={binning} onChange={setBinning}
              label="Binning" formatLabel={(b) => `${b}×${b}`} />

            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Dec (°)</label>
              <Input inputSize="sm" type="number" min={-80} max={80} step={5} placeholder="Auto"
                value={decInput} onChange={(e) => setDecInput(e.target.value)} />
              <span className="text-[10px] text-slate-600">
                Leave blank to let the wizard choose a well-conditioned Dec (not the mount's current one).
              </span>
            </div>

            <div className="rounded border border-surface-border bg-surface-overlay/30 p-2.5 space-y-2">
              <p className="text-xs text-slate-400">Live-adjustment rechecks</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">Exposure (s)</label>
                  <Input inputSize="sm" type="number" min={0.1} step={0.5} placeholder={`${exposureS} (same)`}
                    value={convergeExposureInput} onChange={(e) => setConvergeExposureInput(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">Search radius (°)</label>
                  <Input inputSize="sm" type="number" min={0.5} step={0.5}
                    value={convergeSearchRadiusDeg}
                    onChange={(e) => setConvergeSearchRadiusDeg(Number(e.target.value) || 0.5)} />
                </div>
              </div>
              <p className="text-[10px] text-slate-600">
                Used for every reading while turning the knobs — a shorter exposure and a
                tight search radius (the mount hasn't been slewed) make each recheck fast.
                Leave exposure blank to reuse the fit's own.
              </p>
            </div>

            {wizardError && <p className="text-xs text-red-400">{wizardError}</p>}

            <Button onClick={handleStart} disabled={busy || mounts.length === 0 || cameras.length === 0} className="w-full">
              <Compass size={13} className="mr-2" />
              {busy ? 'Starting…' : 'Start 3-Point Fit'}
            </Button>
            <p className="text-xs text-slate-600">
              Slews to 3 points at one Dec, all on the side of the meridian the mount is
              currently pointing at, so no meridian flip happens mid-run (a flip would
              invalidate the fit). The mount stays on the last point for the rechecks.
            </p>
          </>
        )}

        {run && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-300">
                {run.status === 'running' ? `Point ${run.points.length} / 3` : `${run.points.length} points`}
              </span>
              <StatusPill status={run.status} variant={RUN_PILL_VARIANT[run.status]}
                pulse={run.status === 'running' || run.status === 'converging'} />
            </div>

            {run.status === 'running' && (
              <div className="h-1.5 bg-surface-overlay rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{ width: `${(run.points.length / 3) * 100}%` }} />
              </div>
            )}

            {run.plan && (
              <p className="text-xs text-slate-500">
                Dec {run.plan.dec_jnow_deg.toFixed(0)}° · {run.plan.side} of the meridian
                {run.request.dec_deg == null ? ' (auto)' : ''}
              </p>
            )}

            {run.error && <p className="text-xs text-red-400 break-words">{run.error}</p>}

            {wizardError && (
              <p className="text-xs text-red-400 break-words">
                {wizardErrorAt && <span className="text-red-300/70 mr-1">[{wizardErrorAt.toLocaleTimeString()}]</span>}
                {wizardError}
              </p>
            )}

            {run.result && (
              <div className="rounded border border-surface-border bg-surface-overlay/50 p-2.5 space-y-1">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-slate-400">Initial fit:</p>
                  <QualityBadge altArcmin={run.result.alt_error_arcmin} azArcmin={run.result.az_error_arcmin} />
                </div>
                <p className="text-xs text-slate-200">{altHint(run.result.alt_error_arcmin)}</p>
                <p className="text-xs text-slate-200">{azHint(run.result.az_error_arcmin)}</p>
              </div>
            )}

            {run.status === 'converging' && (
              <div className="space-y-2">
                {run.live_offset ? (
                  <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2.5 space-y-1">
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-amber-300">Latest reading:</p>
                      <QualityBadge altArcmin={run.live_offset.alt_error_arcmin} azArcmin={run.live_offset.az_error_arcmin} />
                    </div>
                    <p className="text-xs text-slate-200">{altHint(run.live_offset.alt_error_arcmin)}</p>
                    <p className="text-xs text-slate-200">{azHint(run.live_offset.az_error_arcmin)}</p>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">
                    Turn the altitude/azimuth adjustment knobs toward the initial fit's
                    numbers above, then recheck to see the error shrink -- no need to
                    re-slew between readings.
                  </p>
                )}

                {run.last_recheck_error && (
                  <p className="text-xs text-red-400 break-words">
                    {run.last_recheck_at && (
                      <span className="text-red-300/70 mr-1">
                        [{new Date(run.last_recheck_at).toLocaleTimeString()}]
                      </span>
                    )}
                    Recheck failed: {run.last_recheck_error}
                  </p>
                )}

                <div className="flex gap-2">
                  <Button size="sm" onClick={handleRecheck} disabled={rechecking} className="flex-1">
                    <RefreshCw size={13} className="mr-1.5" />
                    {rechecking ? 'Rechecking…' : 'Recheck now'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleStop}>
                    Done
                  </Button>
                </div>

                <div className="rounded border border-surface-border bg-surface-overlay/30 p-2.5 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-slate-400">Auto-refresh</p>
                    {run.auto_refresh_interval_s != null && (
                      <span className="text-[10px] text-emerald-400">
                        Every {run.auto_refresh_interval_s}s
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Input inputSize="sm" type="number" min={5} max={600} step={5}
                      value={autoRefreshIntervalInput}
                      disabled={run.auto_refresh_interval_s != null}
                      onChange={(e) => setAutoRefreshIntervalInput(Number(e.target.value) || 5)}
                      className="w-20" />
                    <span className="text-xs text-slate-500">seconds</span>
                    <Button size="sm" variant={run.auto_refresh_interval_s != null ? 'outline' : 'default'}
                      onClick={handleToggleAutoRefresh} disabled={autoRefreshBusy} className="flex-1">
                      {run.auto_refresh_interval_s != null ? 'Stop auto-refresh' : 'Start auto-refresh'}
                    </Button>
                  </div>
                  <p className="text-[10px] text-slate-600">
                    Rechecks automatically on this interval while you turn the knobs,
                    even if nobody clicks Recheck — keeps going from the server side, so
                    it survives this tab reloading or closing.
                  </p>
                </div>
              </div>
            )}

            {run.status === 'running' && (
              <Button size="sm" variant="danger" onClick={handleStop} className="w-full">
                <StopCircle size={13} className="mr-1.5" />
                Cancel
              </Button>
            )}

            {isTerminal && (
              <Button size="sm" variant="outline" onClick={handleStartNew} className="w-full">
                Start New Fit
              </Button>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
