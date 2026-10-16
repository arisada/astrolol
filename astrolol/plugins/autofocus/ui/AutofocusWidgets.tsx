// Autofocus curve for the dock. The V-curve is not in the events (they carry only the step and
// the latest FWHM), so each event fetches the run once: no timer, and the result stays after the
// run ends because the final event also triggers a fetch.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import type { AutofocusRun } from '@/api/types'
import * as api from './api'
import { UCurveChart } from './AutofocusCurve'

export function AutofocusCurveWidget() {
  const { t } = useTranslation('autofocus')
  const live = useStore((s) => s.pluginStates['autofocus'] as { step: number } | null | undefined)
  const [run, setRun] = useState<AutofocusRun | null>(null)
  const trigger = live ? live.step : -1
  useEffect(() => {
    let alive = true
    api.run().then((r) => { if (alive) setRun(r) }).catch(() => {})
    return () => { alive = false }
  }, [trigger])

  if (!run || run.data_points.length === 0) {
    return <p className="text-xs text-slate-500">{t('widget.none')}</p>
  }
  return (
    <div className="flex flex-col gap-1">
      <UCurveChart dataPoints={run.data_points} curveFit={run.curve_fit} optimal={run.optimal_position}
        fitAlgo={run.config.fit_algo ?? 'parabola'} metric={run.config.metric ?? 'fwhm'} />
      <div className="flex justify-between font-mono text-xs text-slate-500">
        <span>{run.status === 'running' ? t('widget.step', { step: run.current_step, total: run.total_steps }) : t(`status.${run.status}`, { defaultValue: run.status })}</span>
        {run.optimal_position != null && <span>{t('widget.best', { position: run.optimal_position })}</span>}
      </div>
    </div>
  )
}
