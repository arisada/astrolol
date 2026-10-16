import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { FocuserRuler } from '@/components/ui/focuser-ruler'
import type { DockWidgetProps } from '../registry'
import { useDevice } from './useDevice'

const SPAN = 500

/** Focuser position on a ruler that stays still until the position nears its edge. */
export function FocuserWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('imaging')
  const { t: tc } = useTranslation()
  const id = useDevice('focuser', deviceId)
  const status = useStore((s) => (id ? s.focuserStatuses[id] : undefined))
  const position = status?.position ?? null
  const [centre, setCentre] = useState<number | null>(null)
  useEffect(() => {
    if (position == null) return
    setCentre((c) => (c == null || Math.abs(position - c) > SPAN * 0.8 ? position : c))
  }, [position])

  if (!id) return <p className="text-xs text-slate-500">{tc('dock.noFocuser')}</p>
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-2">
        <span className="text-xs text-slate-400">{t('focuser.position')}</span>
        <span className="text-sm font-mono text-slate-200">{position ?? '—'}</span>
        {status?.is_moving && <span className="text-xs text-slate-500">{t('filterWheel.moving')}</span>}
        {status?.temperature != null && <span className="ml-auto text-xs font-mono text-slate-500">{status.temperature.toFixed(1)}°C</span>}
      </div>
      {position != null && centre != null && (
        <FocuserRuler position={position} min={Math.max(0, Math.round(centre - SPAN))} max={Math.round(centre + SPAN)} label={t('focuser.title')} />
      )}
    </div>
  )
}
