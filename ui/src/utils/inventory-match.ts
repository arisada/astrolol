import type {
  ConnectedDevice, DeviceConfig, DeviceKind, DeviceState, EquipmentItem, EquipmentItemType,
} from '@/api/types'

export const DEVICE_ITEM_TYPE: Partial<Record<DeviceKind, EquipmentItemType>> = {
  camera: 'camera', mount: 'mount', focuser: 'focuser',
  filter_wheel: 'filter_wheel', rotator: 'rotator',
}

// Key order independent, so params round-tripped through the backend still match.
function canonicalJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(',')}]`
  if (v && typeof v === 'object') {
    return `{${Object.keys(v).sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalJson((v as Record<string, unknown>)[k])}`)
      .join(',')}}`
  }
  return JSON.stringify(v)
}

/** Whether an inventory item describes the connected device with this config. */
export function isInInventory(kind: DeviceKind, config: DeviceConfig, items: EquipmentItem[]): boolean {
  const type = DEVICE_ITEM_TYPE[kind]
  if (!type) return false
  const params = config.params ?? {}
  const deviceName = typeof params.device_name === 'string' ? params.device_name : null
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { pre_connect_props, ...connectParams } = params
  return items.some((item) => {
    if (item.type !== type || !('connect_params' in item)) return false
    if (deviceName !== null) return item.indi_device_name === deviceName
    return item.adapter_key === config.adapter_key
      && canonicalJson(item.connect_params ?? {}) === canonicalJson(connectParams)
  })
}

/**
 * The state of the connected device behind each inventory item, by item id. Items without a
 * matching device are left out. When several devices match, a connected one wins.
 */
export function itemDeviceStates(
  items: EquipmentItem[],
  devices: ConnectedDevice[],
  configs: Record<string, DeviceConfig>,
): Record<string, DeviceState> {
  const states: Record<string, DeviceState> = {}
  for (const item of items) {
    const matching = devices.filter((d) => {
      const config = configs[d.device_id]
      return config !== undefined && isInInventory(d.kind, config, [item])
    })
    const best = matching.find((d) => d.state === 'connected') ?? matching[0]
    if (best) states[item.id] = best.state
  }
  return states
}
