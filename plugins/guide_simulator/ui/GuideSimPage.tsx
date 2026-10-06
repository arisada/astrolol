// Guide simulator: status, manual guiding controls, fault injection and settings.
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { EventLog } from '@/components/ui/event-log'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import * as sim from './api'

const FIELD_KEYS: Record<string, string> = {
  rms_arcsec: 'rms', step_interval_s: 'interval', settle_extra_s: 'settleExtra', pixel_scale: 'pixelScale', time_scale: 'timeScale',
}

const fmt = (v: number | null | undefined, digits = 2) => (v == null ? '—' : v.toFixed(digits))

export function GuideSimPage() {
  const { t } = useTranslation('guide_simulator')
  const [report, setReport] = useState<sim.SimReport | null>(null)
  const [settings, setSettings] = useState<sim.GuideSimSettings | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refresh = useCallback(() => {
    sim.getStatus().then((r) => { setReport(r); setError(null) }).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(() => {
    refresh()
    sim.getSettings().then(setSettings).catch(() => {})
    const t = setInterval(refresh, 1000)   // a debugging tool: polling its own status is fine
    return () => clearInterval(t)
  }, [refresh])

  const act = (fn: () => Promise<unknown>) => () => {
    fn().then(refresh).catch((e: Error) => setError(e.message))
  }

  const saveSettings = async () => {
    if (!settings) return
    const next = { ...settings } as Record<string, unknown>
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v)
      if (v.trim() === '' || !(n > 0)) { setMessage(t('settings.invalid', { field: t(`settings.${FIELD_KEYS[k] ?? k}`, { defaultValue: k }) })); return }
      next[k] = n
    }
    try {
      setSettings(await sim.putSettings(next as unknown as sim.GuideSimSettings))
      setDraft({})
      setMessage(t('settings.saved'))
    } catch (e) {
      setMessage((e as Error).message)
    }
  }

  const st = report?.status
  const h = report?.health
  const w = report?.last_minute
  const f = report?.faults

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl flex flex-col gap-6">
          <div>
            <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
            <p className="text-xs text-slate-500 mt-1">
              {t('intro')}
            </p>
          </div>
          {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>}

          <Section title={t('status.title')}>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <Stat label={t('status.state')} value={st ? t(`state.${st.state.toLowerCase().replace(' ', '_')}`, { defaultValue: st.state }) : '…'}
                tone={h?.guiding ? 'text-emerald-300' : st?.active ? 'text-amber-300' : 'text-slate-300'} />
              <Stat label={h?.guiding ? t('status.guidingFor') : t('status.unguidedFor')}
                value={h ? `${fmt(h.guiding ? h.guiding_for_s : h.unguided_for_s, 0)} s` : '—'} />
              <Stat label={t('status.rms')} value={`${fmt(w?.rms_total)}″`} />
              <Stat label={t('status.losses')} value={w ? `${w.losses} / ${fmt(w.unguided_s, 0)} s` : '—'} />
            </div>
            {h && !h.guiding && h.reason && <p className="text-xs text-slate-500 mt-2">{t('status.reason', { reason: t(`reason.${h.reason}`, { defaultValue: h.reason.replace('_', ' ') }) })}</p>}
          </Section>

          <Section title={t('guiding.title')}>
            <div className="flex gap-2 flex-wrap">
              {st?.connected
                ? <Button size="sm" variant="outline" onClick={act(sim.disconnect)}>{t('guiding.disconnect')}</Button>
                : <Button size="sm" onClick={act(sim.connect)}>{t('guiding.connect')}</Button>}
              <Button size="sm" disabled={!st?.connected || st.active} onClick={act(() => sim.guide())}>{t('guiding.start')}</Button>
              <Button size="sm" variant="outline" disabled={!st?.active} onClick={act(sim.stop)}>{t('guiding.stop')}</Button>
              <Button size="sm" variant="outline" disabled={!h?.guiding} onClick={act(() => sim.dither())}>{t('guiding.dither')}</Button>
            </div>
          </Section>

          <Section title={t('faults.title')}>
            <div className="flex gap-2 flex-wrap">
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(10))}>{t('faults.lose10')}</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(120))}>{t('faults.lose120')}</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.loseStar(null))}>{t('faults.loseUntil')}</Button>
              <Button size="sm" variant="outline" onClick={act(sim.stopGuidingFault)}>{t('faults.stops')}</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.failSettles(1))}>{t('faults.failOne')}</Button>
              <Button size="sm" variant="outline" onClick={act(() => sim.failSettles(3))}>{t('faults.failThree')}</Button>
              <Button size="sm" variant="ghost" onClick={act(sim.clearFaults)}>{t('faults.clear')}</Button>
            </div>
            {f && (f.star_lost || f.settle_failures_left > 0) && (
              <p className="text-xs text-amber-300 mt-2">
                {f.star_lost && (f.star_back_in_s == null ? t('faults.starLostUntil') : t('faults.starBack', { seconds: fmt(f.star_back_in_s, 0) })) + ' '}
                {f.settle_failures_left > 0 && t('faults.settlePending', { count: f.settle_failures_left })}
              </p>
            )}
            <p className="text-xs text-slate-500 mt-2">
              {t('faults.hint')}
            </p>
          </Section>

          {settings && (
            <Section title={t('settings.title')}>
              {([
                ['rms_arcsec', 'rms', '″'],
                ['step_interval_s', 'interval', 's'],
                ['settle_extra_s', 'settleExtra', 's'],
                ['pixel_scale', 'pixelScale', '″/px'],
                ['time_scale', 'timeScale', '×'],
              ] as const).map(([key, labelKey, unit]) => (
                <label key={key} className="flex items-center gap-3 py-1">
                  <span className="text-sm text-slate-300 w-48">{t(`settings.${labelKey}`)}</span>
                  <div className="w-24">
                    <Input inputSize="sm" value={draft[key] ?? String(settings[key])}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
                  </div>
                  <span className="text-xs text-slate-500">{unit}</span>
                </label>
              ))}
              {([
                ['lose_star_on_slew', 'loseOnSlew'],
                ['connected_at_startup', 'atStartup'],
              ] as const).map(([key, labelKey]) => (
                <div key={key} className="flex items-center gap-3 py-1">
                  <ToggleSwitch label={t(`settings.${labelKey}`)} checked={settings[key]}
                    onChange={() => setSettings({ ...settings, [key]: !settings[key] })} />
                  <span className="text-sm text-slate-300">{t(`settings.${labelKey}`)}</span>
                </div>
              ))}
              <div className="flex items-center gap-3 mt-2">
                <Button size="sm" onClick={saveSettings}>{t('settings.save')}</Button>
                {message && <span className="text-xs text-slate-400">{message}</span>}
              </div>
            </Section>
          )}
        </div>
      </div>
      <EventLog filter={['guide_simulator', 'guiding']} />
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">{title}</h2>
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
