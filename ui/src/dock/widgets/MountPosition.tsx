import { useTranslation } from 'react-i18next'
import { useMountSky } from './useMountSky'
import type { DockWidgetProps } from '../registry'
import { EquatorialSky } from '@/components/ui/mount-equatorial'
import { fmtDec, fmtRA } from '@/utils/formatting'

const deg = (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}°` : '—')

/** Where the first connected mount points: coordinates and its place on the sky. */
export function MountPositionWidget({ deviceId }: DockWidgetProps) {
  const { t } = useTranslation('mount')
  const { t: tc } = useTranslation()
  const { mountId, status, site, ra, dec, lst } = useMountSky(deviceId)
  if (!mountId) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-sm">
        <span className="text-slate-500 text-xs">{t('position.ra')}</span>
        <span className="text-slate-500 text-xs">{t('position.dec')}</span>
        <span className="text-slate-200">{fmtRA(ra)}</span>
        <span className="text-slate-200">{fmtDec(dec)}</span>
        <span className="text-slate-500 text-xs mt-1">{t('position.alt')}</span>
        <span className="text-slate-500 text-xs mt-1">{t('position.az')}</span>
        <span className="text-slate-300">{deg(status?.alt)}</span>
        <span className="text-slate-300">{deg(status?.az)}</span>
      </div>
      {site && lst != null && ra != null && dec != null && (
        <EquatorialSky latitude={site.latitude} lst={lst} ra={ra} dec={dec} label={t('sky.equatorial')} className="mx-auto w-full max-w-[260px]" />
      )}
    </div>
  )
}
