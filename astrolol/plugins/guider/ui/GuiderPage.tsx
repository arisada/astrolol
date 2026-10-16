// Built-in guider: the controls and what guiding looks like up top, set-up and records in tabs.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EventLog } from '@/components/ui/event-log'
import { GuideGraph } from '@/components/ui/guide-graph'
import { GuideTarget } from '@/components/ui/guide-target'
import { NumberStepper } from '@/components/ui/number-stepper'
import { PillGroup } from '@/components/ui/pill-group'
import { Tabs } from '@/components/ui/tabs'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { StatusPill, type StatusPillVariant } from '@/components/ui/badge'
import { useStore } from '@/store'
import { niceRange } from '@/utils/guiding'
import * as api from './api'
import { GuiderView } from './GuiderView'
import { CalibrationPanel, DarksPanel, SetupPanel, Stat, TuningPanel, fmt, type Save } from './GuiderPanels'

const RANGE_OPTIONS = ['auto', 2, 4, 8, 16] as const
const SAMPLE_OPTIONS = [50, 100, 200, 500] as const
const NO_STEPS: api.GuiderPluginState['steps'] = []
type Tab = 'setup' | 'tuning' | 'calibration' | 'darks'

/** Same rule as the backend's auto_min_move_px. */
const autoMinMove = (scale: number | null | undefined) => (scale ? Math.max(0.1, Math.min(0.5, 0.3 / scale)) : 0.15)

export function GuiderPage() {
  const { t } = useTranslation('guider')
  const devices = useStore((s) => s.connectedDevices)
  const steps = useStore((s) => (s.pluginStates['guider'] as api.GuiderPluginState | null | undefined)?.steps ?? NO_STEPS)
  const live = useStore((s) => s.pluginStates['guider'] as api.GuiderPluginState | null | undefined)
  const snr = live?.snr ?? null
  const starsFound = live?.stars ?? null
  const [rangeOpt, setRangeOpt] = useState<(typeof RANGE_OPTIONS)[number]>('auto')
  const [samples, setSamples] = useState<(typeof SAMPLE_OPTIONS)[number]>(100)
  const [report, setReport] = useState<api.GuiderReport | null>(null)
  const [settings, setSettings] = useState<api.GuiderSettings | null>(null)
  const [exposureMs, setExposureMs] = useState<number | null>(null)
  const [recalibrate, setRecalibrate] = useState(false)
  const [ditherPx, setDitherPx] = useState(3)
  const [tab, setTab] = useState<Tab>('setup')
  const [busy, setBusy] = useState(false)
  // An error stays until the user dismisses it or the next action succeeds: polling must not
  // wipe it before it can be read.
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const pending = useRef<{ timer: ReturnType<typeof setTimeout> | null; next: api.GuiderSettings | null }>({ timer: null, next: null })

  const refresh = useCallback(() => {
    api.getStatus().then(setReport).catch(() => {})
  }, [])
  useEffect(() => {
    refresh()
    api.getSettings().then((s) => { setSettings(s); setExposureMs(Math.round(s.exposure * 1000)) }).catch((e: Error) => setError(e.message))
    const timer = setInterval(refresh, 1000)
    return () => clearInterval(timer)
  }, [refresh])

  const act = (fn: () => Promise<unknown>) => () => {
    fn().then(() => { setError(null); refresh() }).catch((e: Error) => setError(e.message))
  }

  const put = useCallback((next: api.GuiderSettings) => {
    api.putSettings(next)
      .then((s) => { setSettings(s); setNotice(t('settings.saved')); refresh() })
      .catch((e: Error) => setError(e.message))
  }, [refresh, t])

  // Steppers and typed values wait until they rest; choices save at once.
  const save: Save = (patch, opts) => {
    if (!settings) return
    const next = { ...(pending.current.next ?? settings), ...patch }
    setSettings(next)
    const p = pending.current
    if (p.timer) clearTimeout(p.timer)
    p.next = next
    p.timer = setTimeout(() => { p.timer = null; p.next = null; put(next) }, opts?.soon ? 700 : 0)
  }

  // The exposure applies at once, even while guiding: wait until the stepper rests.
  useEffect(() => {
    if (!settings || exposureMs == null || exposureMs / 1000 === settings.exposure) return
    save({ exposure: exposureMs / 1000 }, { soon: true })
  }, [exposureMs]) // eslint-disable-line react-hooks/exhaustive-deps

  const captureDark = (count: number) => {
    setBusy(true)
    setNotice(t('darks.capturing'))
    api.captureDark(count)
      .then(() => { setNotice(t('darks.done')); setError(null) })
      .catch((e: Error) => { setNotice(null); setError(e.message) })
      .finally(() => { setBusy(false); refresh() })
  }

  const pick = (x: number, y: number) => {
    api.selectStar(x, y).then(() => { setError(null); setNotice(t('view.picked')) }).catch((e: Error) => setError(e.message))
  }

  const cameras = devices.filter((d) => d.kind === 'camera')
  const mounts = devices.filter((d) => d.kind === 'mount')
  const st = report?.status
  const h = report?.health
  const w = report?.last_minute
  const active = !!st?.active
  const previewing = st?.state === 'Previewing'
  const paused = st?.state === 'Paused'
  const unit = st?.pixel_scale ? '"' : 'px'
  const unitName = st?.pixel_scale ? t('graph.arcsec') : t('graph.pixels')
  const points = steps.slice(-samples)
  const range = rangeOpt === 'auto' ? niceRange(points.flatMap((p) => [p.ra, p.dec])) : rangeOpt
  const stateKey = st ? st.state.toLowerCase().replace(/ /g, '_') : null
  const [pillVariant, pulse]: [StatusPillVariant, boolean] = h?.guiding
    ? ['green', false]
    : active ? ['amber', true] : ['slate', false]
  // Why the last run ended, when it was not the user stopping it.
  const runError = !active && report?.last_error && h?.reason !== 'stopped' ? report.last_error : null
  const issues = report?.calibration?.quality?.issues ?? []

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl flex flex-col gap-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
              <p className="text-xs text-slate-500 mt-1 max-w-xl">{t('intro')}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill variant={pillVariant} pulse={pulse}
                status={stateKey ? t(`state.${stateKey}`, { defaultValue: st!.state }) : '…'} />
              {h && !h.guiding && active && h.reason && h.reason !== 'not_guiding' && (
                <span className="text-xs text-slate-500">{t(`reason.${h.reason}`, { defaultValue: h.reason.replace(/_/g, ' ') })}</span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-[10px] border border-surface-border bg-surface-raised px-3 py-2">
            {active ? (
              <Button size="sm" variant="outline" disabled={busy} onClick={act(api.stop)}>{t('guiding.stop')}</Button>
            ) : (
              <Button size="sm" disabled={!settings?.camera_id} onClick={act(() => api.guide(recalibrate))}>{t('guiding.start')}</Button>
            )}
            {paused
              ? <Button size="sm" variant="outline" onClick={act(api.resume)}>{t('guiding.resume')}</Button>
              : <Button size="sm" variant="outline" disabled={!active || st?.state !== 'Guiding'} onClick={act(api.pause)}>{t('guiding.pause')}</Button>}
            <span className="mx-1 h-6 w-px bg-surface-border" />
            <Button size="sm" variant="outline" disabled={!h?.guiding || paused} onClick={act(() => api.dither(ditherPx))}>{t('guiding.dither')}</Button>
            <NumberStepper value={ditherPx} min={0.5} max={50} step={0.5} decimals={1} unit="px" label={t('guiding.ditherAmount')} onChange={setDitherPx} />
            <span className="mx-1 h-6 w-px bg-surface-border" />
            <ToggleSwitch label={t('guiding.recalibrate')} checked={recalibrate} onChange={() => setRecalibrate(!recalibrate)} />
            <span className="text-xs text-slate-400">{t('guiding.recalibrate')}</span>
          </div>

          {error && <Banner tone="error" onClose={() => setError(null)}>{error}</Banner>}
          {runError && <Banner tone="error">{t('status.lastError', { error: runError })}</Banner>}
          {issues.length > 0 && !report?.calibration_attempt && (
            <Banner tone="warning">
              {t('calibration.warnings', { count: issues.length })}{' '}
              <button type="button" className="underline" onClick={() => setTab('calibration')}>{t('calibration.show')}</button>
            </Banner>
          )}

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="flex flex-col gap-5 min-w-0">
              <Card className="p-3" title={t('view.title')} action={!active && (
                <div className="flex gap-2">
                  {report?.preferred_star && (
                    <Button size="sm" variant="ghost" onClick={act(api.clearStar)}>{t('view.autoStar')}</Button>
                  )}
                  {previewing
                    ? <Button size="sm" variant="outline" onClick={act(api.stopPreview)}>{t('view.hide')}</Button>
                    : <Button size="sm" variant="outline" disabled={!settings?.camera_id} onClick={act(api.startPreview)}>{t('view.show')}</Button>}
                </div>
              )}>
                <div className="mt-2">
                  <GuiderView poll={active || previewing} onPick={previewing ? pick : undefined} />
                </div>
              </Card>
              <Card className="p-3" title={t('graph.title', { unit: unitName })} action={
                <div className="flex flex-wrap gap-2">
                  <PillGroup options={RANGE_OPTIONS} value={rangeOpt} onChange={setRangeOpt}
                    formatLabel={(v) => (v === 'auto' ? t('graph.auto') : `±${v / 2}`)} />
                  <PillGroup options={SAMPLE_OPTIONS} value={samples} onChange={setSamples}
                    formatLabel={(v) => t('graph.samples', { count: v })} />
                </div>
              }>
                <div className="mt-2">
                  <GuideGraph points={points} range={range} rmsTotal={w?.rms_total} unit={unit} />
                </div>
              </Card>
            </div>

            <div className="flex flex-col gap-5">
              <Card className="p-3" title={t('target.title')}>
                <div className="flex flex-col items-center gap-3 mt-2">
                  <GuideTarget points={points} range={range} rmsTotal={w?.rms_total} unit={unit} />
                  <div className="grid grid-cols-3 gap-2 w-full text-sm">
                    <Stat label={t('target.rmsRa')} value={fmt(w?.rms_ra)} />
                    <Stat label={t('target.rmsDec')} value={fmt(w?.rms_dec)} />
                    <Stat label={t('target.rmsTotal')} value={fmt(w?.rms_total)} />
                  </div>
                  <p className="text-[11px] text-slate-600">{t('target.unit', { unit: unitName })}</p>
                </div>
              </Card>
              <Card className="p-3" title={t('status.title')}>
                <div className="grid grid-cols-2 gap-2 text-sm mt-2">
                  <Stat label={h?.guiding ? t('status.guidingFor') : t('status.unguidedFor')}
                    value={h ? `${fmt(h.guiding ? h.guiding_for_s : h.unguided_for_s, 0)} s` : '—'} />
                  <Stat label={t('status.losses')} value={w ? `${w.losses} / ${fmt(w.unguided_s, 0)} s` : '—'} />
                  <Stat label={t('status.starSnr')} value={h?.guiding && snr != null ? fmt(snr, 0) : '—'} />
                  <Stat label={t('status.stars')} value={h?.guiding && starsFound != null ? String(starsFound) : '—'} />
                  <Stat label={t('status.pointing')} value={report?.mount?.dec != null ? `${report.mount.dec.toFixed(0)}°` : '—'} />
                  <Stat label={t('status.pierSide')}
                    value={report?.mount?.pier_side ? t(`pier.${report.mount.pier_side}`, { defaultValue: report.mount.pier_side }) : '—'} />
                </div>
                {report?.prediction && (report.prediction.pe_period_s != null || Math.abs(report.prediction.drift_ra) + Math.abs(report.prediction.drift_dec) > 0) && (
                  <p className="text-xs text-slate-400 mt-2">
                    {t('status.drift', { ra: fmt(report.prediction.drift_ra * 60, 1), dec: fmt(report.prediction.drift_dec * 60, 1), unit })}
                    {report.prediction.pe_period_s != null && (
                      <> · {t('status.periodicError', { period: fmt(report.prediction.pe_period_s, 0), amplitude: fmt(report.prediction.pe_amplitude, 1), unit })}</>
                    )}
                  </p>
                )}
                {report?.calibration_attempt?.running && (
                  <p className="text-xs text-amber-300 mt-2">
                    {t('calibration.running', { phase: t(`calibration.phases.${report.calibration_attempt.phase}`, { defaultValue: report.calibration_attempt.phase }) })}{' '}
                    <button type="button" className="underline" onClick={() => setTab('calibration')}>{t('calibration.show')}</button>
                  </p>
                )}
              </Card>
            </div>
          </div>

          {notice && <p className="text-xs text-slate-400">{notice}</p>}

          {settings && (
            <div className="flex flex-col gap-3">
              <Tabs<Tab>
                tabs={[
                  { id: 'setup', label: t('tabs.setup') },
                  { id: 'tuning', label: t('tabs.tuning') },
                  { id: 'calibration', label: t('tabs.calibration') },
                  { id: 'darks', label: t('tabs.darks') },
                ]}
                value={tab}
                onChange={setTab}
              />
              <Card className="p-4">
                {tab === 'setup' && (
                  <SetupPanel settings={settings} save={save} active={active} cameras={cameras} mounts={mounts}
                    report={report} exposureMs={exposureMs ?? 0} setExposureMs={setExposureMs} />
                )}
                {tab === 'tuning' && <TuningPanel settings={settings} save={save} autoMinMove={autoMinMove(st?.pixel_scale)} />}
                {tab === 'calibration' && (
                  <CalibrationPanel report={report} settings={settings} save={save} active={active} onClear={act(api.clearCalibration)} />
                )}
                {tab === 'darks' && (
                  <DarksPanel report={report} busy={busy} active={active} canCapture={!!settings.camera_id}
                    onCapture={captureDark} onClear={act(api.clearDarks)} />
                )}
              </Card>
            </div>
          )}
        </div>
      </div>
      <EventLog filter={['guider', 'guiding']} />
    </div>
  )
}

function Banner({ tone, onClose, children }: { tone: 'error' | 'warning'; onClose?: () => void; children: React.ReactNode }) {
  const { t } = useTranslation('guider')
  const cls = tone === 'error' ? 'text-status-error bg-status-error/10' : 'text-amber-300 bg-amber-500/10'
  return (
    <div className={`flex items-start justify-between gap-3 text-xs rounded px-3 py-2 ${cls}`}>
      <span>{children}</span>
      {onClose && <button type="button" className="shrink-0 underline" onClick={onClose}>{t('dismiss')}</button>}
    </div>
  )
}
