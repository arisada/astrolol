import { describe, expect, it } from 'vitest'
import type { ConnectedDevice, DeviceConfig, DeviceState, EquipmentItem } from '@/api/types'
import { itemDeviceStates } from './inventory-match'

const indiItem = (id: string, type: string, deviceName: string) =>
  ({ id, type, name: deviceName, indi_device_name: deviceName, connect_params: {} }) as unknown as EquipmentItem
const device = (device_id: string, kind: string, state: DeviceState) =>
  ({ device_id, kind, state, primary_id: null, companions: [] }) as unknown as ConnectedDevice
const indiConfig = (name: string) =>
  ({ device_id: 'x', kind: 'camera', adapter_key: 'indi_camera', params: { device_name: name } }) as unknown as DeviceConfig

describe('itemDeviceStates', () => {
  const items = [indiItem('cam', 'camera', 'ZWO CCD'), indiItem('foc', 'focuser', 'ZWO EAF')]

  it('gives each item the state of its device', () => {
    const states = itemDeviceStates(
      items,
      [device('camera_zwo', 'camera', 'connected')],
      { camera_zwo: indiConfig('ZWO CCD') },
    )
    expect(states).toEqual({ cam: 'connected' })
  })

  it('reports a registered but disconnected device', () => {
    const states = itemDeviceStates(items, [device('c', 'camera', 'disconnected')], { c: indiConfig('ZWO CCD') })
    expect(states.cam).toBe('disconnected')
  })

  it('prefers a connected device when several match', () => {
    const states = itemDeviceStates(
      items,
      [device('a', 'camera', 'error'), device('b', 'camera', 'connected')],
      { a: indiConfig('ZWO CCD'), b: indiConfig('ZWO CCD') },
    )
    expect(states.cam).toBe('connected')
  })

  it('does not match a device of another kind, or one whose config is not loaded yet', () => {
    expect(itemDeviceStates(items, [device('c', 'focuser', 'connected')], { c: indiConfig('ZWO CCD') })).toEqual({})
    expect(itemDeviceStates(items, [device('c', 'camera', 'connected')], {})).toEqual({})
  })
})
