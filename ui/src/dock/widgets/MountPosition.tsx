import { useTranslation } from 'react-i18next'
import { useStore } from '@/store'
import { useMountSite } from '@/hooks/useMountSite'
import { EquatorialSky } from '@/components/ui/mount-equatorial'
import { fmtDec, fmtRA } from '@/utils/formatting'

const deg = (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}°` : '—')

/** Where the first connected mount points: coordinates and its place on the sky. */
export function MountPositionWidget() {
  const { t } = useTranslation('mount')
  const { t: tc } = useTranslation()
  const mountId = useStore((s) => s.connectedDevices.find((d) => d.kind === 'mount')?.device_id)
  const status = useStore((s) => (mountId ? s.mountStatuses[mountId] : undefined))
  const site = useMountSite(mountId)
  if (!mountId) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>

  const ra = status?.ra_jnow ?? status?.ra ?? null
  const dec = status?.dec_jnow ?? status?.dec ?? null
  const lst = status?.lst ?? null
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
