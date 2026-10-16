import { useStore } from '@/store'
import { useMountSite } from '@/hooks/useMountSite'
import { useDevice } from './useDevice'

/** The first connected mount, its status and observing site: what the sky widgets draw. */
export function useMountSky(deviceId?: string) {
  const mountId = useDevice('mount', deviceId)
  const status = useStore((s) => (mountId ? s.mountStatuses[mountId] : undefined))
  const site = useMountSite(mountId)
  return {
    mountId,
    status,
    site,
    ra: status?.ra_jnow ?? status?.ra ?? null,
    dec: status?.dec_jnow ?? status?.dec ?? null,
    lst: status?.lst ?? null,
  }
}
