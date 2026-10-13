// The guider's settings and records, one tab each: set-up, tuning, calibration, darks.
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { CountStepper } from '@/components/ui/count-stepper'
import { Input } from '@/components/ui/input'
import { NumberStepper } from '@/components/ui/number-stepper'
import { PillGroup } from '@/components/ui/pill-group'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type * as api from './api'
import { CalibrationGraph } from './CalibrationGraph'
import { summarizeCalibration } from './calibration'

// Guide exposures are short: whole milliseconds, stepping through the values people use.
const EXPOSURE_STEPS_MS = [100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000, 7500, 10000]
const SELECT_CLASS =
  'rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent'

export const fmt = (v: number | null | undefined, digits = 2) => (v == null ? '—' : v.toFixed(digits))

export type Save = (patch: Partial<api.GuiderSettings>, opts?: { soon?: boolean }) => void

interface Device { device_id: string }

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-48 shrink-0 pt-1.5">
        <div className="text-sm text-slate-300">{label}</div>
        {hint && <div className="text-[11px] text-slate-500 mt-0.5">{hint}</div>}
      </div>
      <div className="flex items-center gap-2 flex-wrap min-h-8">{children}</div>
    </div>
  )
}

export function Stat({ label, value, tone = 'text-slate-200' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-surface-border bg-surface px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`font-mono ${tone}`}>{value}</div>
    </div>
  )
}

export function SetupPanel({ settings, save, active, cameras, mounts, report, exposureMs, setExposureMs }: {
  settings: api.GuiderSettings
  save: Save
  active: boolean
  cameras: Device[]
  mounts: Device[]
  report: api.GuiderReport | null
  exposureMs: number
  setExposureMs: (ms: number) => void
}) {
  const { t } = useTranslation('guider')
  const [pixelScale, setPixelScale] = useState(settings.pixel_scale == null ? '' : String(settings.pixel_scale))
  const [scaleError, setScaleError] = useState(false)
  const fromOptics = report?.pixel_scale_source === 'optics'
  const savePixelScale = () => {
    const n = Number(pixelScale)
    if (pixelScale.trim() !== '' && !(n > 0)) { setScaleError(true); return }
    setScaleError(false)
    save({ pixel_scale: pixelScale.trim() === '' ? null : n })
  }
  return (
    <div className="flex flex-col gap-3">
      <Field label={t('settings.camera')}>
        <select className={SELECT_CLASS} value={settings.camera_id ?? ''} disabled={active}
          onChange={(e) => save({ camera_id: e.target.value || null })}>
          <option value="">{t('settings.choose')}</option>
          {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
        </select>
      </Field>
      <Field label={t('settings.output')}>
        <PillGroup options={['camera', 'mount'] as const} value={settings.guide_output}
          formatLabel={(v) => (v === 'camera' ? t('settings.output_camera') : t('settings.output_mount'))}
          onChange={(v) => save({ guide_output: v })} />
      </Field>
      <Field label={t('settings.mount')} hint={settings.guide_output === 'camera' ? t('settings.mountHint') : undefined}>
        <select className={SELECT_CLASS} value={settings.mount_id ?? ''} disabled={active}
          onChange={(e) => save({ mount_id: e.target.value || null })}>
          <option value="">{settings.guide_output === 'mount' ? t('settings.choose') : t('settings.mountAuto')}</option>
          {mounts.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
        </select>
      </Field>
      <Field label={t('settings.exposure')}>
        <CountStepper value={exposureMs} steps={EXPOSURE_STEPS_MS} min={50} max={60000} onChange={setExposureMs} />
        <span className="text-xs text-slate-500">ms</span>
      </Field>
      <Field label={t('settings.gain')} hint={t('settings.gainHint')}>
        <div className="w-24">
          <Input inputSize="sm" value={settings.gain == null ? '' : String(settings.gain)} placeholder="—"
            onChange={(e) => {
              const v = e.target.value.trim()
              const n = Number(v)
              if (v === '' || (Number.isInteger(n) && n >= 0)) save({ gain: v === '' ? null : n }, { soon: true })
            }} />
        </div>
      </Field>
      <Field label={t('settings.pixelScale')} hint={fromOptics && pixelScale.trim() === '' ? t('settings.pixelScaleOptics') : undefined}>
        <div className="w-24">
          <Input inputSize="sm" value={pixelScale} placeholder={fromOptics ? fmt(report?.status.pixel_scale, 2) : '—'}
            onChange={(e) => setPixelScale(e.target.value)} onBlur={savePixelScale} />
        </div>
        <span className="text-xs text-slate-500">″/px</span>
        {scaleError && <span className="text-xs text-status-error">{t('settings.invalidPixelScale')}</span>}
      </Field>
      <Field label={t('settings.stars')} hint={t('settings.starsHint')}>
        <PillGroup options={[1, 2, 3, 4, 5, 6] as const} value={settings.star_count} onChange={(v) => save({ star_count: v })} />
      </Field>
      <Field label={t('settings.lostTimeout')} hint={t('settings.lostTimeoutHint')}>
        <NumberStepper value={settings.lost_timeout_s} min={0} max={3600} step={30} unit="s"
          onChange={(v) => save({ lost_timeout_s: v }, { soon: true })} />
      </Field>
    </div>
  )
}

export function TuningPanel({ settings, save, autoMinMove }: { settings: api.GuiderSettings; save: Save; autoMinMove: number }) {
  const { t } = useTranslation('guider')
  const toggle = (key: 'dec_backlash_compensation' | 'dec_resist_reversals' | 'predict_drift', label: string, hint: string) => (
    <Field label={label} hint={hint}>
      <ToggleSwitch label={label} checked={settings[key]} onChange={() => save({ [key]: !settings[key] })} />
    </Field>
  )
  return (
    <div className="flex flex-col gap-3">
      <Field label={t('tuning.raAggressiveness')} hint={t('tuning.aggressivenessHint')}>
        <NumberStepper value={Math.round(settings.ra_aggressiveness * 100)} min={5} max={100} step={5} unit="%"
          onChange={(v) => save({ ra_aggressiveness: v / 100 }, { soon: true })} />
      </Field>
      <Field label={t('tuning.raHysteresis')} hint={t('tuning.hysteresisHint')}>
        <NumberStepper value={Math.round(settings.ra_hysteresis * 100)} min={0} max={90} step={5} unit="%"
          onChange={(v) => save({ ra_hysteresis: v / 100 }, { soon: true })} />
      </Field>
      <Field label={t('tuning.decAggressiveness')}>
        <NumberStepper value={Math.round(settings.dec_aggressiveness * 100)} min={5} max={100} step={5} unit="%"
          onChange={(v) => save({ dec_aggressiveness: v / 100 }, { soon: true })} />
      </Field>
      {toggle('predict_drift', t('tuning.predictDrift'), t('tuning.predictDriftHint'))}
      <Field label={t('tuning.minMove')} hint={t('tuning.minMoveHint')}>
        <PillGroup options={['auto', 'set'] as const} value={settings.min_move_px == null ? 'auto' : 'set'}
          formatLabel={(v) => (v === 'auto' ? t('tuning.auto', { value: autoMinMove.toFixed(2) }) : t('tuning.manual'))}
          onChange={(v) => save({ min_move_px: v === 'auto' ? null : autoMinMove })} />
        {settings.min_move_px != null && (
          <NumberStepper value={settings.min_move_px} min={0} max={5} step={0.05} decimals={2} unit="px"
            onChange={(v) => save({ min_move_px: v }, { soon: true })} />
        )}
      </Field>
      <Field label={t('tuning.maxPulse')}>
        <NumberStepper value={settings.max_pulse_ms} min={50} max={10000} step={250} unit="ms"
          onChange={(v) => save({ max_pulse_ms: v }, { soon: true })} />
      </Field>
      <Field label={t('tuning.decMode')} hint={t('tuning.decModeHint')}>
        <PillGroup options={['auto', 'north', 'south', 'off'] as const} value={settings.dec_mode}
          formatLabel={(v) => t(`tuning.decModes.${v}`)} onChange={(v) => save({ dec_mode: v })} />
      </Field>
      {toggle('dec_resist_reversals', t('settings.resistReversals'), t('tuning.resistHint'))}
      {toggle('dec_backlash_compensation', t('settings.compensateBacklash'), t('tuning.backlashHint'))}
      <Field label={t('tuning.flipDec')} hint={t('tuning.flipDecHint')}>
        <PillGroup options={['auto', 'yes', 'no'] as const} value={settings.flip_dec_after_meridian_flip}
          formatLabel={(v) => t(`tuning.flipDecs.${v}`)} onChange={(v) => save({ flip_dec_after_meridian_flip: v })} />
      </Field>
    </div>
  )
}

export function CalibrationPanel({ report, settings, save, active, onClear }: {
  report: api.GuiderReport | null
  settings: api.GuiderSettings
  save: Save
  active: boolean
  onClear: () => void
}) {
  const { t } = useTranslation('guider')
  const cal = report?.calibration ?? null
  const attempt = report?.calibration_attempt ?? null
  const shown = attempt ?? null
  const sum = cal ? summarizeCalibration(cal) : null
  const q = cal?.quality ?? null
  const adjusted = report?.active_calibration
  return (
    <div className="flex flex-col gap-4">
      {attempt && (
        <p className={`text-xs ${attempt.error ? 'text-status-error' : 'text-amber-300'}`}>
          {attempt.error
            ? t('calibration.failed', { error: attempt.error })
            : t('calibration.running', { phase: t(`calibration.phases.${attempt.phase}`, { defaultValue: attempt.phase }) })}
        </p>
      )}
      {shown ? (
        <CalibrationGraph trace={shown.trace} />
      ) : cal && sum ? (
        <div className="grid gap-4 md:grid-cols-[minmax(0,360px)_minmax(0,1fr)] items-start">
          <CalibrationGraph trace={cal.trace} calibration={cal} />
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <Stat label={t('calibration.raRate')} value={`${fmt(sum.raRate, 1)} px/s`} />
              <Stat label={t('calibration.decRate')} value={`${fmt(sum.decRate, 1)} px/s`} />
              <Stat label={t('calibration.axes')} value={`${fmt(q?.axes_angle_deg ?? sum.orthogonality, 0)}°`} />
              <Stat label={t('calibration.drift')} value={`${fmt(sum.drift, 2)} px/s`} />
              <Stat label={t('calibration.backlash')} value={`${fmt(sum.backlashMs, 0)} ms`} />
              <Stat label={t('calibration.raBacklash')} value={`${fmt(sum.raBacklashMs, 0)} ms`} />
              {q && <Stat label={t('calibration.scatter')} value={`${fmt(q.residual_px, 2)} px`} />}
              {q && <Stat label={t('calibration.travel')} value={`${fmt(q.ra_travel_px, 0)} / ${fmt(q.dec_travel_px, 0)} px`} />}
            </div>
            <p className="text-xs text-slate-400">
              {t('calibration.madeAt', {
                dec: cal.dec == null ? '—' : `${cal.dec.toFixed(0)}°`,
                side: cal.pier_side ? t(`pier.${cal.pier_side}`, { defaultValue: cal.pier_side }) : '—',
                when: cal.created ? new Date(cal.created * 1000).toLocaleString() : '—',
              })}
            </p>
            {adjusted && (adjusted.ra_x !== cal.ra_x || adjusted.dec_x !== cal.dec_x || adjusted.ra_y !== cal.ra_y || adjusted.dec_y !== cal.dec_y) && (
              <p className="text-xs text-slate-400">{t('calibration.adjusted')}</p>
            )}
            {q && q.issues.length > 0 ? (
              <ul className="flex flex-col gap-1 text-xs text-amber-300">
                {q.issues.map((code) => <li key={code}>{t(`calibration.issues.${code}`)}</li>)}
              </ul>
            ) : q ? (
              <p className="text-xs text-emerald-300">{t('calibration.good')}</p>
            ) : null}
          </div>
        </div>
      ) : (
        <p className="text-xs text-slate-500">{t('calibration.none')}</p>
      )}
      <div className="flex flex-col gap-3">
        <Field label={t('calibration.steps')}>
          <NumberStepper value={settings.calibration_steps} min={3} max={20} step={1}
            onChange={(v) => save({ calibration_steps: v }, { soon: true })} />
        </Field>
        <Field label={t('calibration.distance')} hint={t('calibration.distanceHint')}>
          <NumberStepper value={settings.calibration_travel_px} min={5} max={100} step={5} unit="px"
            onChange={(v) => save({ calibration_travel_px: v }, { soon: true })} />
        </Field>
      </div>
      {cal && (
        <div>
          <Button size="sm" variant="ghost" disabled={active} onClick={onClear}>{t('calibration.clear')}</Button>
        </div>
      )}
    </div>
  )
}

export function DarksPanel({ report, busy, active, canCapture, onCapture, onClear }: {
  report: api.GuiderReport | null
  busy: boolean
  active: boolean
  canCapture: boolean
  onCapture: (count: number) => void
  onClear: () => void
}) {
  const { t } = useTranslation('guider')
  const [count, setCount] = useState(10)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-500">{t('darks.hint')}</p>
      {report && (
        <p className={`text-xs ${report.dark_matches ? 'text-emerald-300' : 'text-amber-300'}`}>
          {report.dark_matches ? t('darks.matches') : t('darks.noMatch')}
        </p>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <NumberStepper value={count} min={1} max={50} step={1} onChange={setCount} />
        <span className="text-xs text-slate-500">{t('darks.frames')}</span>
        <Button size="sm" disabled={busy || active || !canCapture} onClick={() => onCapture(count)}>{t('darks.capture')}</Button>
        <Button size="sm" variant="ghost" disabled={busy || !report?.darks.length} onClick={onClear}>{t('darks.clear')}</Button>
      </div>
      <ul className="text-xs text-slate-400 flex flex-col gap-1">
        {report?.darks.map((d) => (
          <li key={`${d.exposure}-${d.gain}-${d.binning}-${d.region.join('x')}`}>
            {t('darks.entry', { exposure: d.exposure, gain: d.gain ?? '—', frames: d.frames, hot: d.hot_pixels })}
          </li>
        ))}
        {report && report.darks.length === 0 && <li>{t('darks.none')}</li>}
      </ul>
    </div>
  )
}
