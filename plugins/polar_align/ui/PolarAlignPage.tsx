import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
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

function altHint(t: TFunction, arcmin: number): string {
  return arcmin >= 0
    ? t('altHigh', { arcmin: arcmin.toFixed(1) })
    : t('altLow', { arcmin: (-arcmin).toFixed(1) })
}

function azHint(t: TFunction, arcmin: number): string {
  return arcmin >= 0
    ? t('azEast', { arcmin: arcmin.toFixed(1) })
    : t('azWest', { arcmin: (-arcmin).toFixed(1) })
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

const QUALITY_CLASS: Record<PaQuality, string> = {
  excellent: 'text-emerald-400', good: 'text-sky-400', fair: 'text-amber-400', poor: 'text-red-400',
}

function QualityBadge({ altArcmin, azArcmin }: { altArcmin: number; azArcmin: number }) {
  const { t } = useTranslation('polar_align')
  const q = paQuality(altArcmin, azArcmin)
  const total = Math.hypot(altArcmin, azArcmin)
  return (
    <span className={`text-xs font-medium ${QUALITY_CLASS[q]}`}>
      {t('quality.total', { label: t(`quality.${q}`), total: total.toFixed(1) })}
    </span>
  )
}

export function PolarAlignPage() {
  const { t } = useTranslation('polar_align')
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
      .catch((e) => setReticleError(e instanceof Error ? e.message : t('reticleFailed')))
  }, [t])

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
    if (!mountId || !cameraId) { setWizardError(t('needDevices')); return }
    if (decInvalid) { setWizardError(t('decInvalid')); return }
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
      setWizardError(e instanceof Error ? e.message : t('startFailed'))
    }
  }, [mountId, cameraId, exposureS, binning, decOverride, decInvalid, convergeExposureS,
      convergeSearchRadiusDeg, fetchRun, setWizardError, t])

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
      setWizardError(e instanceof Error ? e.message : t('toggleFailed'))
    } finally {
      setAutoRefreshBusy(false)
    }
  }, [run?.auto_refresh_interval_s, autoRefreshIntervalInput, fetchRun, setWizardError, t])

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
        <Compass size={18} /> {t('title')}
      </h1>

      {mounts.length > 0 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-400">{t('mount')}</span>
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
      <Card title={t('reticle.title')} className="p-4 space-y-3">
        <p className="text-xs text-slate-500">
          {t('reticle.intro')}
        </p>

        <div className="flex items-start justify-between gap-3 rounded border border-surface-border bg-surface-overlay/50 px-3 py-2">
          <label className="text-xs text-slate-400 leading-tight">
            {t('reticle.invert')}
            <span className="block text-[10px] text-slate-600">
              {t('reticle.invertHint')}
            </span>
          </label>
          <ToggleSwitch
            label={t('reticle.invertLabel')}
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
      <Card title={t('wizard.title')} className="p-4 space-y-3">
        {!run && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-slate-400">{t('wizard.camera')}</label>
                {cameras.length === 0 ? (
                  <span className="text-xs text-slate-600">{t('wizard.noneConnected')}</span>
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
                <label className="text-xs text-slate-400">{t('wizard.exposure')}</label>
                <Input inputSize="sm" type="number" min={0.1} step={0.5}
                  value={exposureS} onChange={(e) => setExposureS(Number(e.target.value) || 1)} />
              </div>
            </div>

            <PillGroup options={[1, 2, 3, 4]} value={binning} onChange={setBinning}
              label={t('wizard.binning')} formatLabel={(b) => `${b}×${b}`} />

            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">{t('wizard.dec')}</label>
              <Input inputSize="sm" type="number" min={-80} max={80} step={5} placeholder={t('wizard.auto')}
                value={decInput} onChange={(e) => setDecInput(e.target.value)} />
              <span className="text-[10px] text-slate-600">
                {t('wizard.decHint')}
              </span>
            </div>

            <div className="rounded border border-surface-border bg-surface-overlay/30 p-2.5 space-y-2">
              <p className="text-xs text-slate-400">{t('wizard.recheck')}</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">{t('wizard.exposure')}</label>
                  <Input inputSize="sm" type="number" min={0.1} step={0.5} placeholder={t('wizard.sameExposure', { value: exposureS })}
                    value={convergeExposureInput} onChange={(e) => setConvergeExposureInput(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">{t('wizard.radius')}</label>
                  <Input inputSize="sm" type="number" min={0.5} step={0.5}
                    value={convergeSearchRadiusDeg}
                    onChange={(e) => setConvergeSearchRadiusDeg(Number(e.target.value) || 0.5)} />
                </div>
              </div>
              <p className="text-[10px] text-slate-600">
                {t('wizard.recheckHint')}
              </p>
            </div>

            {wizardError && <p className="text-xs text-red-400">{wizardError}</p>}

            <Button onClick={handleStart} disabled={busy || mounts.length === 0 || cameras.length === 0} className="w-full">
              <Compass size={13} className="mr-2" />
              {busy ? t('wizard.starting') : t('wizard.start')}
            </Button>
            <p className="text-xs text-slate-600">
              {t('wizard.startHint')}
            </p>
          </>
        )}

        {run && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-300">
                {run.status === 'running' ? t('wizard.pointProgress', { done: run.points.length }) : t('wizard.pointCount', { count: run.points.length })}
              </span>
              <StatusPill status={t(`status.${run.status}`)} variant={RUN_PILL_VARIANT[run.status]}
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
                {t('wizard.plan', { dec: run.plan.dec_jnow_deg.toFixed(0), side: t(`side.${run.plan.side}`, { defaultValue: run.plan.side }) })}
                {run.request.dec_deg == null ? t('wizard.planAuto') : ''}
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
                  <p className="text-xs text-slate-400">{t('wizard.initial')}</p>
                  <QualityBadge altArcmin={run.result.alt_error_arcmin} azArcmin={run.result.az_error_arcmin} />
                </div>
                <p className="text-xs text-slate-200">{altHint(t, run.result.alt_error_arcmin)}</p>
                <p className="text-xs text-slate-200">{azHint(t, run.result.az_error_arcmin)}</p>
              </div>
            )}

            {run.status === 'converging' && (
              <div className="space-y-2">
                {run.live_offset ? (
                  <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2.5 space-y-1">
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-amber-300">{t('wizard.latest')}</p>
                      <QualityBadge altArcmin={run.live_offset.alt_error_arcmin} azArcmin={run.live_offset.az_error_arcmin} />
                    </div>
                    <p className="text-xs text-slate-200">{altHint(t, run.live_offset.alt_error_arcmin)}</p>
                    <p className="text-xs text-slate-200">{azHint(t, run.live_offset.az_error_arcmin)}</p>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">
                    {t('wizard.knobs')}
                  </p>
                )}

                {run.last_recheck_error && (
                  <p className="text-xs text-red-400 break-words">
                    {run.last_recheck_at && (
                      <span className="text-red-300/70 mr-1">
                        [{new Date(run.last_recheck_at).toLocaleTimeString()}]
                      </span>
                    )}
                    {t('wizard.recheckFailed', { error: run.last_recheck_error })}
                  </p>
                )}

                <div className="flex gap-2">
                  <Button size="sm" onClick={handleRecheck} disabled={rechecking} className="flex-1">
                    <RefreshCw size={13} className="mr-1.5" />
                    {rechecking ? t('wizard.rechecking') : t('wizard.recheckNow')}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleStop}>
                    {t('wizard.done')}
                  </Button>
                </div>

                <div className="rounded border border-surface-border bg-surface-overlay/30 p-2.5 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-slate-400">{t('wizard.autoRefresh')}</p>
                    {run.auto_refresh_interval_s != null && (
                      <span className="text-[10px] text-emerald-400">
                        {t('wizard.every', { seconds: run.auto_refresh_interval_s })}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Input inputSize="sm" type="number" min={5} max={600} step={5}
                      value={autoRefreshIntervalInput}
                      disabled={run.auto_refresh_interval_s != null}
                      onChange={(e) => setAutoRefreshIntervalInput(Number(e.target.value) || 5)}
                      className="w-20" />
                    <span className="text-xs text-slate-500">{t('wizard.seconds')}</span>
                    <Button size="sm" variant={run.auto_refresh_interval_s != null ? 'outline' : 'default'}
                      onClick={handleToggleAutoRefresh} disabled={autoRefreshBusy} className="flex-1">
                      {run.auto_refresh_interval_s != null ? t('wizard.stopAuto') : t('wizard.startAuto')}
                    </Button>
                  </div>
                  <p className="text-[10px] text-slate-600">
                    {t('wizard.autoHint')}
                  </p>
                </div>
              </div>
            )}

            {run.status === 'running' && (
              <Button size="sm" variant="danger" onClick={handleStop} className="w-full">
                <StopCircle size={13} className="mr-1.5" />
                {t('wizard.cancel')}
              </Button>
            )}

            {isTerminal && (
              <Button size="sm" variant="outline" onClick={handleStartNew} className="w-full">
                {t('wizard.startNew')}
              </Button>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
