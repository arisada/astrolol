import type { EquipmentItem } from '@/api/types'

/** What the tag on a device item says: INDI, INDIGO, a plugin, or the adapter when nothing loaded provides it. */
export type DeviceSource =
  | { kind: 'indi' }
  | { kind: 'indigo' }
  | { kind: 'plugin'; plugin: string }
  | { kind: 'adapter'; adapter: string }

/** From the item's source (filled in by the server); null for items that are not devices or name nothing. */
export function deviceSource(item: EquipmentItem): DeviceSource | null {
  if (!('adapter_key' in item)) return null
  if (item.source === 'indi' || item.source === 'indigo') return { kind: item.source }
  if (item.source) return { kind: 'plugin', plugin: item.source }
  return item.adapter_key ? { kind: 'adapter', adapter: item.adapter_key } : null
}
