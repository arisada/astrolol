import { useTranslation } from 'react-i18next'
import { HorizontalSky } from '@/components/ui/mount-horizontal'
import { useMountSky } from './useMountSky'
import type { DockWidgetProps } from '../registry'

/** Where the mount points over the local horizon, centred on the zenith. */
export function MountHorizonWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('mount')
  const { t: tc } = useTranslation()
  const { mountId, site, ra, dec, lst } = useMountSky(deviceId)
  if (!mountId) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>
  if (!site || lst == null || ra == null || dec == null) return <p className="text-xs text-slate-500">{t('widget.noSite')}</p>
  return <HorizontalSky latitude={site.latitude} lst={lst} ra={ra} dec={dec} label={t('sky.horizontal')} className="mx-auto w-full max-w-[260px]" />
}
