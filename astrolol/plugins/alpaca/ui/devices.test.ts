import { describe, expect, it } from 'vitest'
import type { AlpacaDeviceInfo, AlpacaServerInfo, ConnectedAlpacaDevice } from './api'
import { connectedAs, formatAddress, sortDevices, suggestDeviceId } from './devices'

const device = (over: Partial<AlpacaDeviceInfo> = {}): AlpacaDeviceInfo => ({
  name: 'Alpaca Camera Simulator', device_type: 'Camera', device_number: 0, unique_id: 'u',
  kind: 'camera', adapter_key: 'alpaca_camera', ...over,
})
const server: AlpacaServerInfo = {
  host: '127.0.0.1', port: 32323, name: 'Sim', manufacturer: '', version: '', location: '', devices: [],
}
const connected = (over: Partial<ConnectedAlpacaDevice> = {}): ConnectedAlpacaDevice => ({
  device_id: 'cam', kind: 'camera', adapter_key: 'alpaca_camera', state: 'connected',
  host: '127.0.0.1', port: 32323, device_number: 0, ...over,
})

describe('suggestDeviceId', () => {
  it('is made from the kind and the name', () => {
    expect(suggestDeviceId(device({ name: 'ZWO ASI2600MM Pro' }), [])).toBe('camera_zwo_asi2600mm_pro')
  })
  it('leaves out the words that repeat the kind or the protocol', () => {
    expect(suggestDeviceId(device(), [])).toBe('camera_simulator')
    expect(suggestDeviceId(device({ name: 'Alpaca Telescope Simulator', kind: 'mount' }), [])).toBe('mount_simulator')
    expect(suggestDeviceId(device({ name: 'Alpaca Filter Wheel Simulator', kind: 'filter_wheel' }), []))
      .toBe('filter_wheel_simulator')
    expect(suggestDeviceId(device({ name: 'Alpaca CoverCalibrator Simulator', kind: 'flat_panel' }), []))
      .toBe('flat_panel_simulator')
  })
  it('avoids IDs in use', () => {
    expect(suggestDeviceId(device(), ['camera_simulator'])).toBe('camera_simulator_2')
    expect(suggestDeviceId(device(), ['camera_simulator', 'camera_simulator_2'])).toBe('camera_simulator_3')
  })
  it('keeps to the allowed characters and length', () => {
    const id = suggestDeviceId(device({ name: '  ZWO ASI2600MM Pro (#1) — très long nom de caméra ici  ' }), [])
    expect(id).toMatch(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/)
    expect(suggestDeviceId(device({ name: '***' }), [])).toBe('camera')
    expect(suggestDeviceId(device({ name: 'Alpaca Camera' }), [])).toBe('camera')
  })
})

describe('connectedAs', () => {
  it('finds the device by server, number and adapter', () => {
    expect(connectedAs(server, device(), [connected()])?.device_id).toBe('cam')
    expect(connectedAs(server, device({ device_number: 1 }), [connected()])).toBeUndefined()
    expect(connectedAs(server, device(), [connected({ port: 11111 })])).toBeUndefined()
    expect(connectedAs(server, device(), [connected({ adapter_key: 'alpaca_focuser' })])).toBeUndefined()
  })
  it('treats the loopback names as one host', () => {
    expect(connectedAs(server, device(), [connected({ host: 'localhost' })])?.device_id).toBe('cam')
    expect(connectedAs({ ...server, host: '192.168.1.5' }, device(), [connected()])).toBeUndefined()
  })
})

it('formats addresses', () => {
  expect(formatAddress('192.168.1.5', 11111)).toBe('192.168.1.5:11111')
  expect(formatAddress('fe80::1', 11111)).toBe('[fe80::1]:11111')
})

it('lists supported devices first', () => {
  const sorted = sortDevices([
    device({ name: 'Roof', kind: null, adapter_key: null }),
    device({ name: 'Cam' }),
    device({ name: 'Scope', kind: 'mount', adapter_key: 'alpaca_mount' }),
  ])
  expect(sorted.map((d) => d.name)).toEqual(['Scope', 'Cam', 'Roof'])
})
