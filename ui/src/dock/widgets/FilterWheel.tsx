import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import type { DockWidgetProps } from '../registry'
import { useDevice } from './useDevice'

/** The filter in the beam. */
export function FilterWheelWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('imaging')
  const { t: tc } = useTranslation()
  const id = useDevice('filter_wheel', deviceId)
  const status = useStore((s) => (id ? s.filterWheelStatuses[id] : undefined))
  if (!id) return <p className="text-xs text-slate-500">{tc('dock.noFilterWheel')}</p>
  const slot = status?.current_slot ?? null
  const name = slot != null ? (status?.filter_names[slot - 1] ?? t('filterWheel.filter', { slot })) : '—'
  return (
    <div className="flex items-baseline gap-2">
      {slot != null && <span className="font-mono text-xs text-slate-500">{slot}</span>}
      <span className="text-sm font-mono text-slate-200">{name}</span>
      {status?.is_moving && <span className="text-xs text-slate-500">{t('filterWheel.moving')}</span>}
    </div>
  )
}
