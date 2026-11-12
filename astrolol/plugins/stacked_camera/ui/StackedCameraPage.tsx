// Stacked camera: put it on a connected camera, set the short frame length, watch the stream.
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { DurationStepper, EXPOSURE_STEPS } from '@/components/ui/duration-stepper'
import { Page } from '@/components/Page'
import * as api from './api'

const FRAME_STEPS = EXPOSURE_STEPS.filter((s) => s >= 0.5 && s <= 60)

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="font-medium text-slate-500 label-caps mb-2">{title}</h2>
      {children}
    </section>
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

export function StackedCameraPage() {
  const { t } = useTranslation('stacked_camera')
  const [status, setStatus] = useState<api.StackedStatus | null>(null)
  const [settings, setSettings] = useState<api.StackedCameraSettings | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(() => {
    api.getStatus().then((s) => { setStatus(s); setError(null) }).catch((e: Error) => setError(e.message))
  }, [])

  // Polled only while the page is open.
  useEffect(() => {
    refresh()
    api.getSettings().then(setSettings).catch((e: Error) => setError(e.message))
    const timer = setInterval(refresh, 1000)
    return () => clearInterval(timer)
  }, [refresh])

  const act = (fn: () => Promise<unknown>) => () => {
    fn().then(refresh).catch((e: Error) => setError(e.message))
  }

  const setSubExposure = (value: number) => {
    const next = { ...settings, sub_exposure: value }
    setSettings(next)
    api.putSettings(next).then(setSettings).catch((e: Error) => setError(e.message))
  }

  return (
    <Page width="medium" className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
        <p className="text-xs text-slate-500 mt-1">{t('intro')}</p>
      </div>
      {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>}

      <Section title={t('cameras.title')}>
        {status && status.cameras.length === 0 && <p className="text-xs text-slate-500">{t('cameras.none')}</p>}
        <ul className="flex flex-col gap-2">
          {status?.cameras.map((camera) => (
            <li key={camera.device_id} className="flex items-center justify-between gap-3 rounded border border-surface-border bg-surface-raised px-3 py-2">
              <div className="min-w-0">
                <div className="font-mono text-sm text-slate-200 truncate">{camera.device_id}</div>
                <div className="text-xs text-slate-500">
                  {camera.attached
                    ? t('cameras.inUse', { stacked: camera.attached.stacked, fast: camera.attached.fast })
                    : t('cameras.notInUse')}
                </div>
              </div>
              {camera.attached
                ? <Button size="sm" variant="outline" onClick={act(() => api.detach(camera.device_id))}>{t('cameras.detach')}</Button>
                : <Button size="sm" onClick={act(() => api.attach(camera.device_id))}>{t('cameras.attach')}</Button>}
            </li>
          ))}
        </ul>
      </Section>

      {settings && (
        <Section title={t('settings.title')}>
          <DurationStepper
            steps={FRAME_STEPS}
            value={settings.sub_exposure}
            onChange={setSubExposure}
            label={t('settings.subExposure')}
          />
          <p className="text-xs text-slate-500 mt-2">{t('settings.hint')}</p>
        </Section>
      )}

      <Section title={t('status.title')}>
        {status && status.sources.length === 0 && <p className="text-xs text-slate-500">{t('status.none')}</p>}
        <div className="flex flex-col gap-3">
          {status?.sources.map((source) => (
            <div key={source.source_id}>
              <div className="font-mono text-xs text-slate-400 mb-1">{source.source_id}</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                <Stat
                  label={t('status.state')}
                  value={source.error ? t('status.failed') : source.running ? t('status.running') : t('status.idle')}
                  tone={source.error ? 'text-rose-300' : source.running ? 'text-emerald-300' : 'text-slate-300'}
                />
                <Stat label={t('status.frames')} value={String(source.frames)} />
                <Stat label={t('status.lost')} value={String(source.dropped)} tone={source.dropped > 0 ? 'text-amber-300' : 'text-slate-200'} />
                <Stat label={t('status.duty')} value={source.duty == null ? '—' : `${Math.round(source.duty * 100)} %`} />
              </div>
              {source.error && <p className="text-xs text-rose-300 mt-2">{source.error}</p>}
            </div>
          ))}
        </div>
      </Section>
    </Page>
  )
}
