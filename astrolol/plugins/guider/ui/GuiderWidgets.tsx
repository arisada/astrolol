// Guider read-outs for the dock: the same target and graph as the page, from the live steps.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { GuideGraph } from '@/components/ui/guide-graph'
import { GuideTarget } from '@/components/ui/guide-target'
import { useStore } from '@/store'
import { niceRange } from '@/utils/guiding'
import * as api from './api'
import { Stat, fmt } from './GuiderPanels'

const NO_STEPS: api.GuiderPluginState['steps'] = []
const SAMPLES = 100

function useGuiding() {
  const steps = useStore((s) => (s.pluginStates['guider'] as api.GuiderPluginState | null | undefined)?.steps ?? NO_STEPS)
  const [report, setReport] = useState<api.GuiderReport | null>(null)
  useEffect(() => {
    let alive = true
    const poll = () => api.getStatus().then((r) => { if (alive) setReport(r) }).catch(() => {})
    poll()
    const timer = setInterval(poll, 2000)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  const points = steps.slice(-SAMPLES)
  const range = niceRange(points.flatMap((p) => [p.ra, p.dec]))
  const arcsec = !!report?.status.pixel_scale
  return { points, range, unit: arcsec ? '"' : 'px', rms: report?.last_minute }
}

export function GuiderTargetWidget() {
  const { t } = useTranslation('guider')
  const { points, range, unit, rms } = useGuiding()
  return (
    <div className="flex flex-col items-center gap-3">
      <GuideTarget points={points} range={range} rmsTotal={rms?.rms_total} unit={unit} />
      <div className="grid grid-cols-3 gap-2 w-full text-sm">
        <Stat label={t('target.rmsRa')} value={fmt(rms?.rms_ra)} />
        <Stat label={t('target.rmsDec')} value={fmt(rms?.rms_dec)} />
        <Stat label={t('target.rmsTotal')} value={fmt(rms?.rms_total)} />
      </div>
    </div>
  )
}

export function GuiderGraphWidget() {
  const { points, range, unit, rms } = useGuiding()
  return <GuideGraph points={points} range={range} rmsTotal={rms?.rms_total} unit={unit} />
}
