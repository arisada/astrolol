import { create } from 'zustand'
import type { AstrolollEvent, CameraStatus, ConnectedDevice, FilterWheelStatus, FocuserStatus, MountStatus, Phd2Status, PluginInfo } from '@/api/types'

const MAX_LOG_ENTRIES = 1000
const MAX_GUIDE_STEPS = 500   // keep a large buffer; graph slices client-side

export interface LogEntry {
  id: string
  timestamp: string
  level: string
  component: string
  message: string
  eventType: string
}

export interface LatestImage {
  previewUrl: string
  previewUrlLinear: string | null
  fitsPath: string
  deviceId: string
  width: number
  height: number
  duration: number
}

export interface LastError {
  message: string
  timestamp: string
  eventType: string
}

export interface GuidePoint {
  frame: number
  ra: number
  dec: number
  ts: string  // ISO timestamp from the guide_step event
}

interface AppState {
  // Connection
  wsConnected: boolean

  // Devices
  connectedDevices: ConnectedDevice[]

  // Per-device status (keyed by device_id)
  mountStatuses: Record<string, MountStatus>
  focuserStatuses: Record<string, FocuserStatus>
  cameraStatuses: Record<string, CameraStatus>
  filterWheelStatuses: Record<string, FilterWheelStatus>

  // Imager
  latestImage: LatestImage | null
  imagerBusy: Record<string, boolean>  // device_id -> is busy

  // Event log
  log: LogEntry[]

  // Last error (shown as global toast)
  lastError: LastError | null

  // Plugin metadata from /plugins endpoint
  pluginInfos: PluginInfo[]

  // PHD2 guiding
  phd2Status: Phd2Status | null
  phd2GuidePoints: GuidePoint[]

  // Actions
  setWsConnected: (v: boolean) => void
  setConnectedDevices: (devices: ConnectedDevice[]) => void
  setCameraStatus: (deviceId: string, status: CameraStatus) => void
  setFocuserStatus: (deviceId: string, status: FocuserStatus) => void
  setFilterWheelStatus: (deviceId: string, status: FilterWheelStatus) => void
  applyEvent: (event: AstrolollEvent) => void
  clearLastError: () => void
  setPluginInfos: (infos: PluginInfo[]) => void
  setPhd2Status: (status: Phd2Status) => void
}

// Event types that represent errors and should set lastError
const ERROR_TYPES = new Set([
  'imager.exposure_failed',
  'mount.operation_failed',
])

export const useStore = create<AppState>((set, get) => ({
  wsConnected: false,
  connectedDevices: [],
  mountStatuses: {},
  focuserStatuses: {},
  cameraStatuses: {},
  filterWheelStatuses: {},
  latestImage: null,
  imagerBusy: {},
  log: [],
  lastError: null,
  pluginInfos: [],
  phd2Status: null,
  phd2GuidePoints: [],

  setWsConnected: (v) => set({ wsConnected: v }),
  clearLastError: () => set({ lastError: null }),
  setPluginInfos: (infos) => set({ pluginInfos: infos }),
  setPhd2Status: (status) => set({ phd2Status: status }),

  setConnectedDevices: (devices) => set({ connectedDevices: devices }),
  setCameraStatus: (deviceId, status) =>
    set((s) => ({ cameraStatuses: { ...s.cameraStatuses, [deviceId]: status } })),
  setFocuserStatus: (deviceId, status) =>
    set((s) => ({ focuserStatuses: { ...s.focuserStatuses, [deviceId]: status } })),
  setFilterWheelStatus: (deviceId, status) =>
    set((s) => ({ filterWheelStatuses: { ...s.filterWheelStatuses, [deviceId]: status } })),

  applyEvent: (event) => {
    const state = get()

    // High-frequency data events — update state only, never write to the log
    if (event.type === 'phd2.guide_step') {
      const point: GuidePoint = { frame: event.frame, ra: event.ra_dist, dec: event.dec_dist, ts: event.timestamp }
      set((s) => ({
        phd2GuidePoints: [...s.phd2GuidePoints, point].slice(-MAX_GUIDE_STEPS),
      }))
      return
    }

    const eventId = (event as { id: string }).id
    // Dedup: history replay and brief dual-connection windows can send the same event twice
    if (state.log.some((e) => e.id === eventId)) return

    const isError = ERROR_TYPES.has(event.type)
    const entry: LogEntry = {
      id: eventId,
      timestamp: (event as { timestamp: string }).timestamp,
      level: isError ? 'error' : (event.type === 'log' ? event.level : 'info'),
      component: event.type === 'log' ? (event.component || 'app') : event.type.split('.')[0],
      message: eventSummary(event),
      eventType: event.type,
    }
    const log = [entry, ...state.log].slice(0, MAX_LOG_ENTRIES)
    const lastError = isError
      ? { message: entry.message, timestamp: entry.timestamp, eventType: event.type }
      : state.lastError

    switch (event.type) {
      case 'device.connected': {
        set({ log, lastError })
        break
      }
      case 'device.disconnected': {
        const connectedDevices = state.connectedDevices.filter(
          (d) => d.device_id !== event.device_key,
        )
        set({ connectedDevices, log, lastError })
        break
      }
      case 'imager.exposure_started': {
        set({ imagerBusy: { ...state.imagerBusy, [event.device_id]: true }, log, lastError })
        break
      }
      case 'imager.exposure_completed': {
        const filename = event.preview_path.split('/').pop()!
        const filenameLinear = event.preview_path_linear?.split('/').pop() ?? null
        set({
          imagerBusy: { ...state.imagerBusy, [event.device_id]: false },
          latestImage: {
            previewUrl: `/imager/images/${filename}`,
            previewUrlLinear: filenameLinear ? `/imager/images/${filenameLinear}` : null,
            fitsPath: event.fits_path,
            deviceId: event.device_id,
            width: event.width,
            height: event.height,
            duration: event.duration,
          },
          log, lastError,
        })
        break
      }
      case 'imager.loop_stopped':
      case 'imager.exposure_failed': {
        set({ imagerBusy: { ...state.imagerBusy, [event.device_id]: false }, log, lastError })
        break
      }
      case 'mount.slew_completed':
      case 'mount.slew_aborted':
      case 'mount.parked':
      case 'mount.unparked':
      case 'mount.operation_failed': {
        set({ log, lastError })
        break
      }
      case 'focuser.move_completed':
      case 'focuser.halted': {
        if (event.type === 'focuser.move_completed' || event.position !== null) {
          const pos = event.type === 'focuser.move_completed' ? event.position : event.position
          if (pos !== null && pos !== undefined) {
            set({
              focuserStatuses: {
                ...state.focuserStatuses,
                [event.device_id]: {
                  ...state.focuserStatuses[event.device_id],
                  position: pos,
                  is_moving: false,
                  state: 'connected',
                  temperature: null,
                },
              },
              log, lastError,
            })
            break
          }
        }
        set({ log, lastError })
        break
      }
      case 'phd2.connected': {
        set({ phd2Status: { connected: true, state: 'Unknown', rms_ra: null, rms_dec: null, rms_total: null, pixel_scale: null, star_snr: null }, log, lastError })
        break
      }
      case 'phd2.disconnected': {
        set({ phd2Status: { connected: false, state: 'Disconnected', rms_ra: null, rms_dec: null, rms_total: null, pixel_scale: null, star_snr: null }, phd2GuidePoints: [], log, lastError })
        break
      }
      case 'phd2.state_changed': {
        set((s) => ({ phd2Status: s.phd2Status ? { ...s.phd2Status, state: event.state } : null, log, lastError }))
        break
      }
      case 'phd2.settled':
      default:
        set({ log, lastError })
    }
  },
}))

function eventSummary(event: AstrolollEvent): string {
  switch (event.type) {
    case 'log': return event.message
    case 'device.connected': return `${event.device_kind} connected: ${event.device_key}`
    case 'device.disconnected': return `${event.device_kind} disconnected: ${event.device_key}`
    case 'device.state_changed': return `${event.device_key} → ${event.new_state}`
    case 'imager.exposure_started': return `Exposing ${event.duration}s`
    case 'imager.exposure_completed': return `Exposure done (${event.duration}s, ${event.width}×${event.height})`
    case 'imager.exposure_failed': return `Exposure failed: ${event.reason}`
    case 'imager.loop_started': return 'Loop started'
    case 'imager.loop_stopped': return 'Loop stopped'
    case 'mount.slew_started': return `Slewing to RA ${event.ra.toFixed(3)}h Dec ${event.dec.toFixed(2)}°`
    case 'mount.slew_completed': return `Slew complete`
    case 'mount.slew_aborted': return `Slew aborted`
    case 'mount.parked': return `Mount parked`
    case 'mount.unparked': return `Mount unparked`
    case 'mount.operation_failed': return `${event.operation} failed: ${event.reason}`
    case 'mount.tracking_changed': return `Tracking ${event.tracking ? 'on' : 'off'}${event.mode ? ` (${event.mode})` : ''}`
    case 'mount.meridian_flip_started': return `Meridian flip started`
    case 'mount.meridian_flip_completed': return `Meridian flip complete`
    case 'focuser.move_started': return `Focuser → ${event.target_position}`
    case 'focuser.move_completed': return `Focuser at ${event.position}`
    case 'focuser.halted': return `Focuser halted at ${event.position ?? '?'}`
    case 'phd2.connected': return 'PHD2 connected'
    case 'phd2.disconnected': return 'PHD2 disconnected'
    case 'phd2.state_changed': return `PHD2 ${event.state}`
    case 'phd2.guide_step': return `Guide step #${event.frame}: RA ${event.ra_dist.toFixed(3)}" Dec ${event.dec_dist.toFixed(3)}"`
    case 'phd2.settled': return event.error ? `PHD2 settle failed: ${event.error}` : 'PHD2 settled'
    default: return (event as { type: string }).type
  }
}
