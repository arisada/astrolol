// Last plate-solve result for the dock, with the offset from where the mount was pointing.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StatusPill } from '@/components/ui/badge'
import { useStore } from '@/store'
import * as api from './api'
import { ResultPanel } from './ResultPanel'

const isActive = (j: api.SolveJob) => j.status === 'pending' || j.status === 'exposing' || j.status === 'solving'

export function PlatesolveResultWidget() {
  const { t } = useTranslation('platesolve')
  const live = useStore((s) => (s.pluginStates['platesolve'] as api.PlateSolvePluginState | null | undefined)?.jobs)
  // After a reload the store is empty until the next solve: read the history once.
  const [past, setPast] = useState<api.SolveJob[]>([])
  useEffect(() => { api.jobs().then(setPast).catch(() => {}) }, [])

  const all = new Map(past.map((j) => [j.id, j]))
  for (const j of Object.values(live ?? {})) all.set(j.id, j)
  const jobs = [...all.values()]
  const active = jobs.find(isActive)
  const last = jobs
    .filter((j) => j.status === 'completed' && j.result)
    .sort((a, b) => (b.completed_at ?? '').localeCompare(a.completed_at ?? ''))[0]

  if (!active && !last) return <p className="text-xs text-slate-500">{t('widget.none')}</p>
  return (
    <div className="flex flex-col gap-2">
      {active && <StatusPill status={t(`status.${active.status}`)} variant="amber" pulse />}
      {last && <ResultPanel job={last} className="" />}
    </div>
  )
}
