import { describe, expect, it } from 'vitest'
import type { EquipmentItem } from '@/api/types'
import { deviceSource } from './device-source'

function camera(fields: Partial<{ adapter_key: string | null; source: string | null }>): EquipmentItem {
  return {
    id: 'c', type: 'camera', name: 'Cam', indi_driver: null, indi_device_name: null, adapter_key: null,
    connect_params: {}, pixel_size_um: null, default_gain: null, ...fields,
  } as EquipmentItem
}

describe('deviceSource', () => {
  it('INDI and INDIGO', () => {
    expect(deviceSource(camera({ source: 'indi' }))).toEqual({ kind: 'indi' })
    expect(deviceSource(camera({ source: 'indigo' }))).toEqual({ kind: 'indigo' })
  })

  it('a plugin', () => {
    expect(deviceSource(camera({ source: 'alpaca', adapter_key: 'alpaca_camera' }))).toEqual({ kind: 'plugin', plugin: 'alpaca' })
  })

  it('an adapter nothing loaded provides keeps its key', () => {
    expect(deviceSource(camera({ adapter_key: 'alpaca_camera' }))).toEqual({ kind: 'adapter', adapter: 'alpaca_camera' })
  })

  it('nothing for items that are not devices, or name nothing', () => {
    expect(deviceSource(camera({}))).toBeNull()
    const site = { id: 's', type: 'site', name: 'Home', latitude: 0, longitude: 0, altitude: 0, timezone: 'UTC' } as EquipmentItem
    expect(deviceSource(site)).toBeNull()
  })
})
