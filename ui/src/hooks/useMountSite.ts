import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { EquipmentItem, ProfileNode, SiteEquipmentItem } from '@/api/types'

/** The observing site a mount is attached to (from the active profile's equipment tree).
 *  Falls back to the first site in the profile when the mount is not under a camera. */
export function useMountSite(deviceId: string | undefined): SiteEquipmentItem | null {
  const [site, setSite] = useState<SiteEquipmentItem | null>(null)
  useEffect(() => {
    if (!deviceId) return
    Promise.all([
      api.profiles.activeOpticalPaths().catch(() => []),
      api.profiles.active().catch(() => null),
      api.inventory.list().catch(() => [] as EquipmentItem[]),
    ]).then(([paths, profile, items]) => {
      const viaPath = paths.find((p) => p.mount_device_id === deviceId)?.site
      if (viaPath) { setSite(viaPath); return }
      const byId = new Map(items.map((i) => [i.id, i]))
      const firstSite = (nodes: ProfileNode[]): SiteEquipmentItem | null => {
        for (const n of nodes) {
          const item = byId.get(n.item_id)
          if (item?.type === 'site') return item as SiteEquipmentItem
          const inner = firstSite(n.children)
          if (inner) return inner
        }
        return null
      }
      setSite(firstSite(profile?.roots ?? []))
    })
  }, [deviceId])
  return site
}
