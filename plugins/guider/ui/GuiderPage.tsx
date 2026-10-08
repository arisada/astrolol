// Built-in guider: set-up, guiding controls, calibration and dark frames.
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { EventLog } from '@/components/ui/event-log'
import { GuideGraph } from '@/components/ui/guide-graph'
import { GuideTarget } from '@/components/ui/guide-target'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { useStore } from '@/store'
import * as api from './api'
import { summarizeCalibration } from './calibration'
import { GuiderView } from './GuiderView'
import { niceRange } from '@/utils/guiding'

const RANGE_OPTIONS = ['auto', 2, 4, 8, 16] as const
const SAMPLE_OPTIONS = [50, 100, 200, 500] as const
const NO_STEPS: api.GuiderPluginState['steps'] = []

const fmt = (v: number | null | undefined, digits = 2) => (v == null ? '—' : v.toFixed(digits))
const SELECT_CLASS =
  'rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent'

export function GuiderPage() {
  const { t } = useTranslation('guider')
  const devices = useStore((s) => s.connectedDevices)
  const steps = useStore((s) => (s.pluginStates['guider'] as api.GuiderPluginState | null | undefined)?.steps ?? NO_STEPS)
  const [rangeOpt, setRangeOpt] = useState<(typeof RANGE_OPTIONS)[number]>('auto')
  const [samples, setSamples] = useState<(typeof SAMPLE_OPTIONS)[number]>(100)
  const [pixelScale, setPixelScale] = useState('')
  const [report, setReport] = useState<api.GuiderReport | null>(null)
  const [settings, setSettings] = useState<api.GuiderSettings | null>(null)
  const [exposure, setExposure] = useState('')
  const [recalibrate, setRecalibrate] = useState(false)
  const [darkCount, setDarkCount] = useState('10')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refresh = useCallback(() => {
    api.getStatus().then((r) => { setReport(r); setError(null) }).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(() => {
    refresh()
    api.getSettings().then((s) => { setSettings(s); setExposure(String(s.exposure)); setPixelScale(s.pixel_scale == null ? '' : String(s.pixel_scale)) }).catch(() => {})
    const timer = setInterval(refresh, 1000)
    return () => clearInterval(timer)
  }, [refresh])

  const act = (fn: () => Promise<unknown>) => () => {
    fn().then(refresh).catch((e: Error) => setError(e.message))
  }

  const save = async (next: api.GuiderSettings) => {
    try {
      setSettings(await api.putSettings(next))
      setMessage(t('settings.saved'))
      setError(null)
      refresh()
    } catch (e) {
      setMessage((e as Error).message)
    }
  }
  const saveExposure = () => {
    const n = Number(exposure)
    if (!settings || !(n > 0)) { setMessage(t('settings.invalidExposure')); return }
    void save({ ...settings, exposure: n })
  }

  const savePixelScale = () => {
    if (!settings) return
    const n = Number(pixelScale)
    if (pixelScale.trim() !== '' && !(n > 0)) { setMessage(t('settings.invalidPixelScale')); return }
    void save({ ...settings, pixel_scale: pixelScale.trim() === '' ? null : n })
  }

  const captureDark = () => {
    setBusy(true)
    setMessage(t('darks.capturing'))
    api.captureDark(Math.max(1, Math.min(50, Math.round(Number(darkCount)) || 10)))
      .then(() => { setMessage(t('darks.done')); setError(null) })
      .catch((e: Error) => { setMessage(null); setError(e.message) })
      .finally(() => { setBusy(false); refresh() })
  }

  const cameras = devices.filter((d) => d.kind === 'camera')
  const mounts = devices.filter((d) => d.kind === 'mount')
  const st = report?.status
  const h = report?.health
  const w = report?.last_minute
  const cal = report?.calibration ? summarizeCalibration(report.calibration) : null
  const previewing = st?.state === 'Previewing'
  const unit = st?.pixel_scale ? '"' : 'px'
  const unitName = st?.pixel_scale ? t('graph.arcsec') : t('graph.pixels')
  const points = steps.slice(-samples)
  const range = rangeOpt === 'auto' ? niceRange(points.flatMap((p) => [p.ra, p.dec])) : rangeOpt

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl flex flex-col gap-6">
          <div>
            <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
            <p className="text-xs text-slate-500 mt-1">{t('intro')}</p>
          </div>
          {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>}

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
            <Section title={t('view.title')}>
              <GuiderView poll={!!st?.active || previewing} />
              {!st?.active && (
                <div className="mt-2">
                  {previewing
                    ? <Button size="sm" variant="outline" onClick={act(api.stopPreview)}>{t('view.hide')}</Button>
                    : <Button size="sm" variant="outline" disabled={!settings?.camera_id} onClick={act(api.startPreview)}>{t('view.show')}</Button>}
                </div>
              )}
            </Section>
            <Section title={t('target.title')}>
              <div className="flex flex-col items-center gap-3">
                <GuideTarget points={points} range={range} rmsTotal={w?.rms_total} unit={unit} />
                <div className="grid grid-cols-3 gap-2 w-full text-sm">
                  <Stat label={t('target.rmsRa')} value={`${fmt(w?.rms_ra)}`} />
                  <Stat label={t('target.rmsDec')} value={`${fmt(w?.rms_dec)}`} />
                  <Stat label={t('target.rmsTotal')} value={`${fmt(w?.rms_total)}`} />
                </div>
                <p className="text-[11px] text-slate-600">{t('target.unit', { unit: unitName })}</p>
              </div>
            </Section>
          </div>

          <Section title={t('graph.title', { unit: unitName })}>
            <div className="flex flex-wrap gap-4 mb-2">
              <PillGroup options={RANGE_OPTIONS} value={rangeOpt} onChange={setRangeOpt}
                formatLabel={(v) => (v === 'auto' ? t('graph.auto') : `±${v / 2}`)} />
              <PillGroup options={SAMPLE_OPTIONS} value={samples} onChange={setSamples} />
            </div>
            <div className="rounded border border-surface-border bg-surface-raised p-3">
              <GuideGraph points={points} range={range} rmsTotal={w?.rms_total} unit={unit} />
            </div>
          </Section>

          {settings && (
            <Section title={t('settings.title')}>
              <div className="flex flex-col gap-3">
                <Field label={t('settings.camera')}>
                  <select className={SELECT_CLASS} value={settings.camera_id ?? ''} disabled={st?.active}
                    onChange={(e) => void save({ ...settings, camera_id: e.target.value || null })}>
                    <option value="">{t('settings.choose')}</option>
                    {cameras.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
                  </select>
                </Field>
                <Field label={t('settings.output')}>
                  <PillGroup options={['camera', 'mount'] as const} value={settings.guide_output}
                    formatLabel={(v) => (v === 'camera' ? t('settings.output_camera') : t('settings.output_mount'))}
                    onChange={(v) => void save({ ...settings, guide_output: v })} />
                </Field>
                {settings.guide_output === 'mount' && (
                  <Field label={t('settings.mount')}>
                    <select className={SELECT_CLASS} value={settings.mount_id ?? ''} disabled={st?.active}
                      onChange={(e) => void save({ ...settings, mount_id: e.target.value || null })}>
                      <option value="">{t('settings.choose')}</option>
                      {mounts.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
                    </select>
                  </Field>
                )}
                <Field label={t('settings.exposure')}>
                  <div className="flex items-center gap-2">
                    <div className="w-24">
                      <Input inputSize="sm" value={exposure} disabled={st?.active}
                        onChange={(e) => setExposure(e.target.value)} onBlur={saveExposure} />
                    </div>
                    <span className="text-xs text-slate-500">s</span>
                  </div>
                </Field>
                <Field label={t('settings.pixelScale')}>
                  <div className="flex items-center gap-2">
                    <div className="w-24">
                      <Input inputSize="sm" value={pixelScale} placeholder="—" onChange={(e) => setPixelScale(e.target.value)} onBlur={savePixelScale} />
                    </div>
                    <span className="text-xs text-slate-500">″/px</span>
                  </div>
                </Field>
                <Field label={t('settings.stars')}>
                  <PillGroup options={[1, 2, 3, 4, 5, 6] as const} value={settings.star_count}
                    onChange={(v) => void save({ ...settings, star_count: v })} />
                </Field>
                {message && <span className="text-xs text-slate-400">{message}</span>}
              </div>
            </Section>
          )}

          <Section title={t('status.title')}>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <Stat label={t('status.state')} value={st ? t(`state.${st.state.toLowerCase().replace(/ /g, '_')}`, { defaultValue: st.state }) : '…'}
                tone={h?.guiding ? 'text-emerald-300' : st?.active ? 'text-amber-300' : 'text-slate-300'} />
              <Stat label={h?.guiding ? t('status.guidingFor') : t('status.unguidedFor')}
                value={h ? `${fmt(h.guiding ? h.guiding_for_s : h.unguided_for_s, 0)} s` : '—'} />
              <Stat label={t('status.rms')} value={`${fmt(w?.rms_total)} ${st?.pixel_scale ? '″' : 'px'}`} />
              <Stat label={t('status.losses')} value={w ? `${w.losses} / ${fmt(w.unguided_s, 0)} s` : '—'} />
            </div>
            {h && !h.guiding && h.reason && (
              <p className="text-xs text-slate-500 mt-2">{t('status.reason', { reason: t(`reason.${h.reason}`, { defaultValue: h.reason.replace('_', ' ') }) })}</p>
            )}
            <div className="flex gap-2 flex-wrap items-center mt-3">
              <Button size="sm" disabled={!!st?.active || !settings?.camera_id} onClick={act(() => api.guide(recalibrate))}>{t('guiding.start')}</Button>
              <Button size="sm" variant="outline" disabled={!st?.active || busy} onClick={act(api.stop)}>{t('guiding.stop')}</Button>
              {st?.state === 'Paused'
                ? <Button size="sm" variant="outline" onClick={act(api.resume)}>{t('guiding.resume')}</Button>
                : <Button size="sm" variant="outline" disabled={!h?.guiding} onClick={act(api.pause)}>{t('guiding.pause')}</Button>}
              <Button size="sm" variant="outline" disabled={!h?.guiding} onClick={act(() => api.dither())}>{t('guiding.dither')}</Button>
              <label className="flex items-center gap-2 text-xs text-slate-400 ml-2">
                <input type="checkbox" checked={recalibrate} onChange={(e) => setRecalibrate(e.target.checked)} />
                {t('guiding.recalibrate')}
              </label>
            </div>
          </Section>

          <Section title={t('calibration.title')}>
            {cal ? (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                  <Stat label={t('calibration.raRate')} value={`${fmt(cal.raRate, 1)} px/s`} />
                  <Stat label={t('calibration.decRate')} value={`${fmt(cal.decRate, 1)} px/s`} />
                  <Stat label={t('calibration.axes')} value={`${fmt(cal.orthogonality, 0)}°`}
                    tone={Math.abs(cal.orthogonality - 90) > 20 ? 'text-amber-300' : 'text-slate-200'} />
                  <Stat label={t('calibration.backlash')} value={`${fmt(cal.backlashMs, 0)} ms`} />
                </div>
                <Button size="sm" variant="ghost" className="mt-2" disabled={!!st?.active} onClick={act(api.clearCalibration)}>{t('calibration.clear')}</Button>
              </>
            ) : (
              <p className="text-xs text-slate-500">{t('calibration.none')}</p>
            )}
          </Section>

          <Section title={t('darks.title')}>
            <p className="text-xs text-slate-500 mb-2">{t('darks.hint')}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="w-16"><Input inputSize="sm" value={darkCount} onChange={(e) => setDarkCount(e.target.value)} /></div>
              <span className="text-xs text-slate-500">{t('darks.frames')}</span>
              <Button size="sm" disabled={busy || !!st?.active || !settings?.camera_id} onClick={captureDark}>{t('darks.capture')}</Button>
              <Button size="sm" variant="ghost" disabled={busy || !report?.darks.length} onClick={act(api.clearDarks)}>{t('darks.clear')}</Button>
            </div>
            <ul className="mt-2 text-xs text-slate-400 flex flex-col gap-1">
              {report?.darks.map((d) => (
                <li key={`${d.exposure}-${d.gain}-${d.binning}-${d.region.join('x')}`}>
                  {t('darks.entry', { exposure: d.exposure, gain: d.gain ?? '—', frames: d.frames, hot: d.hot_pixels })}
                </li>
              ))}
              {report && report.darks.length === 0 && <li>{t('darks.none')}</li>}
            </ul>
          </Section>
        </div>
      </div>
      <EventLog filter={['guider', 'guiding']} />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-medium text-slate-500 label-caps mb-2">{title}</h2>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-slate-300 w-40 shrink-0">{label}</span>
      {children}
    </div>
  )
}

function Stat({ label, value, tone = 'text-slate-200' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-surface-border bg-surface-raised px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`font-mono ${tone}`}>{value}</div>
    </div>
  )
}
