import type { AlpacaDeviceInfo, AlpacaServerInfo, ConnectedAlpacaDevice } from './api'

// Same shape as the core's own device IDs (astrolol/devices/config.py): "<kind>_<name>".
const DEVICE_ID_MAX = 64

// Words of a device's name that only repeat its kind or the protocol ("Alpaca Telescope
// Simulator" is a mount: "mount_simulator").
const KIND_WORDS: Record<string, string[]> = {
  camera: ['camera'],
  mount: ['mount', 'telescope'],
  focuser: ['focuser'],
  filter_wheel: ['filter', 'wheel', 'filterwheel'],
  rotator: ['rotator'],
  flat_panel: ['flat', 'panel', 'cover', 'calibrator', 'covercalibrator'],
}
const PROTOCOL_WORDS = ['alpaca', 'ascom']

/** A device ID for *device*, made from its kind and name, not one of *taken*. */
export function suggestDeviceId(device: AlpacaDeviceInfo, taken: Iterable<string>): string {
  const used = new Set(taken)
  const skip = new Set([...PROTOCOL_WORDS, ...(KIND_WORDS[device.kind ?? ''] ?? [])])
  const slug = device.name.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w && !skip.has(w))
    .join('_').slice(0, 40).replace(/_+$/, '')
  const base = `${device.kind ?? 'device'}${slug ? `_${slug}` : ''}`.slice(0, DEVICE_ID_MAX - 3)
  if (!used.has(base)) return base
  for (let n = 2; ; n++) {
    const id = `${base}_${n}`
    if (!used.has(id)) return id
  }
}

/** The astrolol device already connected to this Alpaca device, if any. */
export function connectedAs(
  server: AlpacaServerInfo,
  device: AlpacaDeviceInfo,
  connected: ConnectedAlpacaDevice[],
): ConnectedAlpacaDevice | undefined {
  return connected.find((c) =>
    c.adapter_key === device.adapter_key && c.port === server.port && c.device_number === device.device_number
    && sameHost(c.host, server.host))
}

const LOOPBACK = new Set(['127.0.0.1', 'localhost', '::1'])

function sameHost(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase() || (LOOPBACK.has(a.toLowerCase()) && LOOPBACK.has(b.toLowerCase()))
}

/** "host:port", with brackets around an IPv6 host. */
export function formatAddress(host: string, port: number): string {
  return host.includes(':') ? `[${host}]:${port}` : `${host}:${port}`
}

/** Supported devices first (in astrolol's kind order), then the others, by name. */
export function sortDevices(devices: AlpacaDeviceInfo[]): AlpacaDeviceInfo[] {
  const order = ['mount', 'camera', 'filter_wheel', 'focuser', 'rotator', 'flat_panel']
  const rank = (d: AlpacaDeviceInfo) => (d.kind ? order.indexOf(d.kind) : order.length)
  return [...devices].sort((a, b) => rank(a) - rank(b) || a.device_number - b.device_number || a.name.localeCompare(b.name))
}
