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
  const [wizardError, setWizardError] = useState<string | null>(null)
  const [exposureS, setExposureS] = useState(5)
  const [binning, setBinning] = useState(2)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRun = useCallback(async () => {
    try {
      const r = await polarAlignApi.getWizard()
      setRun(r)
      if (r.status !== 'running') {
        setBusy(false)
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      }
    } catch { /* 404 = no run yet */ }
  }, [])

  useEffect(() => {
    polarAlignApi.getWizard().then((r) => {
      setRun(r)
      if (r.status === 'running') {
        setBusy(true)
        pollRef.current = setInterval(fetchRun, 1500)
      }
    }).catch(() => {})
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchRun])

  const handleStart = useCallback(async () => {
    if (!mountId || !cameraId) { setWizardError('A mount and camera must be connected.'); return }
    setWizardError(null)
    setBusy(true)
    setRun(null)
    try {
      const r = await polarAlignApi.startWizard({
        mount_id: mountId, camera_id: cameraId, exposure_s: exposureS, binning,
      })
      setRun(r)
      pollRef.current = setInterval(fetchRun, 1500)
    } catch (e) {
      setBusy(false)
      setWizardError(e instanceof Error ? e.message : 'Failed to start')
    }
  }, [mountId, cameraId, exposureS, binning, fetchRun])

  const [rechecking, setRechecking] = useState(false)
  const handleRecheck = useCallback(async () => {
    setRechecking(true)
    setWizardError(null)
    try {
      setRun(await polarAlignApi.recheckWizard())
    } catch (e) {
      setWizardError(e instanceof Error ? e.message : 'Recheck failed')
    } finally {
      setRechecking(false)
    }
  }, [])

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
  }, [])

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

            {wizardError && <p className="text-xs text-red-400">{wizardError}</p>}

            <Button onClick={handleStart} disabled={busy || mounts.length === 0 || cameras.length === 0} className="w-full">
              <Compass size={13} className="mr-2" />
              {busy ? 'Starting…' : 'Start 3-Point Fit'}
            </Button>
            <p className="text-xs text-slate-600">
              Slews to 3 points near the meridian, tracking off. Keep the mount on one
              side of the pier throughout -- a meridian flip mid-run invalidates the fit.
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

            {run.error && <p className="text-xs text-red-400 break-words">{run.error}</p>}

            {run.result && (
              <div className="rounded border border-surface-border bg-surface-overlay/50 p-2.5 space-y-1">
                <p className="text-xs text-slate-400">Initial fit:</p>
                <p className="text-xs text-slate-200">{altHint(run.result.alt_error_arcmin)}</p>
                <p className="text-xs text-slate-200">{azHint(run.result.az_error_arcmin)}</p>
              </div>
            )}

            {run.status === 'converging' && (
              <div className="space-y-2">
                {run.live_offset ? (
                  <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2.5 space-y-1">
                    <p className="text-xs text-amber-300">Latest reading:</p>
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
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleRecheck} disabled={rechecking} className="flex-1">
                    <RefreshCw size={13} className="mr-1.5" />
                    {rechecking ? 'Rechecking…' : 'Recheck'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleStop}>
                    Done
                  </Button>
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
