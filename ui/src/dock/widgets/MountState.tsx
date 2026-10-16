import { useTranslation } from 'react-i18next'
import { StatusPill, type StatusPillVariant } from '@/components/ui/badge'
import { fmtHA, fmtMeridianDistance } from '@/utils/meridian'
import { useMountSky } from './useMountSky'
import type { DockWidgetProps } from '../registry'

/** What the mount is doing, and how close it is to the meridian. */
export function MountStateWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('mount')
  const { t: tc } = useTranslation()
  const { mountId, status } = useMountSky(deviceId)
  if (!mountId) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>
  if (!status) return null

  const [key, variant, pulse]: [string, StatusPillVariant, boolean] = status.is_parked
    ? ['parked', 'slate', false]
    : status.is_slewing ? ['slewing', 'amber', true]
    : status.is_tracking ? ['tracking', 'green', false]
    : ['stopped', 'amber', false]
  const ha = status.hour_angle
  return (
    <div className="flex flex-col gap-2">
      <StatusPill variant={variant} pulse={pulse} status={t(`widget.state.${key}`)} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-sm">
        <span className="text-slate-500 text-xs">{t('position.pier')}</span>
        <span className="text-slate-500 text-xs">{t('position.ha')}</span>
        <span className="text-slate-300">{status.pier_side ? t(`pier.${status.pier_side}`, { defaultValue: status.pier_side }) : '—'}</span>
        <span className="text-slate-300">{fmtHA(ha)}</span>
      </div>
      {ha != null && <p className="text-xs text-slate-500">{fmtMeridianDistance(ha, t)}</p>}
    </div>
  )
}
