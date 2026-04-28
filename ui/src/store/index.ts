import { create } from 'zustand'
import type { AstrolollEvent, CameraStatus, ConnectedDevice, FilterWheelStatus, FocuserStatus, ImageStats, MountStatus, PluginInfo } from '@/api/types'

const MAX_LOG_ENTRIES = 1000


// ---------------------------------------------------------------------------
// Plugin event handler registry (module-level — no React overhead)
// Handler: (event, currentPluginState) → newPluginState | undefined
//   undefined  = no state change
//   null       = clear plugin state
//   anything else = new plugin state
// ---------------------------------------------------------------------------

type PluginEventHandler = (event: AstrolollEvent, pluginState: unknown) => unknown

const _pluginHandlers = new Map<string, Map<string, PluginEventHandler>>()
// Silent event types bypass the log and dedup — used for high-frequency events
// such as phd2.guide_step. Registered by plugins via registerSilentEventTypes.
const _silentEventTypes = new Set<string>()

export function registerPluginEventHandlers(
  pluginId: string,
  handlers: Partial<Record<string, PluginEventHandler>>,
) {
  const map = _pluginHandlers.get(pluginId) ?? new Map<string, PluginEventHandler>()
  for (const [eventType, handler] of Object.entries(handlers)) {
    if (handler) map.set(eventType, handler)
  }
  _pluginHandlers.set(pluginId, map)
}

export function registerSilentEventTypes(...types: string[]) {
  types.forEach((t) => _silentEventTypes.add(t))
}

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
  latestImages: Record<string, LatestImage>    // device_id -> latest image for that camera
  imageStats: Record<string, ImageStats>       // device_id -> stats from last exposure
  imagerBusy: Record<string, boolean>          // device_id -> is busy
  imagerLooping: Record<string, boolean>     // device_id -> loop is running
  imagerExposures: Record<string, { startedAt: number; duration: number } | null>  // for countdown

  // Event log
  log: LogEntry[]

  // Last error (shown as global toast)
  lastError: LastError | null

  // Plugin metadata from /plugins endpoint
  pluginInfos: PluginInfo[]

  // Plugin-owned state slices — keyed by plugin id
  pluginStates: Record<string, unknown>

  // Actions
  setWsConnected: (v: boolean) => void
  setConnectedDevices: (devices: ConnectedDevice[]) => void
  setCameraStatus: (deviceId: string, status: CameraStatus) => void
  setFocuserStatus: (deviceId: string, status: FocuserStatus) => void
  setFilterWheelStatus: (deviceId: string, status: FilterWheelStatus) => void
  setMountStatus: (deviceId: string, status: MountStatus) => void
  applyEvent: (event: AstrolollEvent) => void
  clearLastError: () => void
  setPluginInfos: (infos: PluginInfo[]) => void
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
  latestImages: {},
  imageStats: {},
  imagerBusy: {},
  imagerLooping: {},
  imagerExposures: {},
  log: [],
  lastError: null,
  pluginInfos: [],
  pluginStates: {},

  setWsConnected: (v) => set({ wsConnected: v }),
  clearLastError: () => set({ lastError: null }),
  setPluginInfos: (infos) => set({ pluginInfos: infos }),

  setConnectedDevices: (devices) => set({ connectedDevices: devices }),
  setCameraStatus: (deviceId, status) =>
    set((s) => ({ cameraStatuses: { ...s.cameraStatuses, [deviceId]: status } })),
  setFocuserStatus: (deviceId, status) =>
    set((s) => ({ focuserStatuses: { ...s.focuserStatuses, [deviceId]: status } })),
  setFilterWheelStatus: (deviceId, status) =>
    set((s) => ({ filterWheelStatuses: { ...s.filterWheelStatuses, [deviceId]: status } })),
  setMountStatus: (deviceId, status) =>
    set((s) => ({ mountStatuses: { ...s.mountStatuses, [deviceId]: status } })),

  applyEvent: (event) => {
    const state = get()

    // Silent events — dispatch to plugin handlers, skip log and dedup entirely
    if (_silentEventTypes.has(event.type)) {
      const pluginUpdates: Record<string, unknown> = {}
      for (const [pluginId, handlers] of _pluginHandlers) {
        const handler = handlers.get(event.type)
        if (handler) {
          const newState = handler(event, get().pluginStates[pluginId])
          if (newState !== undefined) pluginUpdates[pluginId] = newState
        }
      }
      if (Object.keys(pluginUpdates).length > 0) {
        set((s) => ({ pluginStates: { ...s.pluginStates, ...pluginUpdates } }))
      }
      return
    }

    if (event.type === 'focuser.position_updated') {
      set((s) => ({
        focuserStatuses: {
          ...s.focuserStatuses,
          [event.device_id]: {
            state: s.focuserStatuses[event.device_id]?.state ?? 'connected',
            position: event.position,
            is_moving: s.focuserStatuses[event.device_id]?.is_moving ?? false,
            temperature: s.focuserStatuses[event.device_id]?.temperature ?? null,
          },
        },
      }))
      return
    }

    if (event.type === 'mount.coords_updated') {
      set((s) => {
        const cur = s.mountStatuses[event.device_id]
        return {
          mountStatuses: {
            ...s.mountStatuses,
            [event.device_id]: {
              state: cur?.state ?? 'connected',
              ra: event.ra,
              dec: event.dec,
              ra_jnow: event.ra_jnow,
              dec_jnow: event.dec_jnow,
              alt: cur?.alt ?? null,
              az: cur?.az ?? null,
              is_tracking: cur?.is_tracking ?? false,
              is_parked: cur?.is_parked ?? false,
              is_slewing: cur?.is_slewing ?? false,
              pier_side: cur?.pier_side ?? null,
              hour_angle: cur?.hour_angle ?? null,
              lst: cur?.lst ?? null,
            },
          },
        }
      })
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
        set({
          imagerBusy: { ...state.imagerBusy, [event.device_id]: true },
          imagerExposures: { ...state.imagerExposures, [event.device_id]: { startedAt: Date.now(), duration: event.duration } },
          log, lastError,
        })
        break
      }
      case 'imager.exposure_completed': {
        const filename = event.preview_path.split('/').pop()!
        const filenameLinear = event.preview_path_linear?.split('/').pop() ?? null
        set((s) => ({
          imagerBusy: { ...state.imagerBusy, [event.device_id]: false },
          imagerExposures: { ...state.imagerExposures, [event.device_id]: null },
          latestImages: {
            ...s.latestImages,
            [event.device_id]: {
              previewUrl: `/imager/images/${filename}`,
              previewUrlLinear: filenameLinear ? `/imager/images/${filenameLinear}` : null,
              fitsPath: event.fits_path,
              deviceId: event.device_id,
              width: event.width,
              height: event.height,
              duration: event.duration,
            },
          },
          ...(event.stats ? { imageStats: { ...s.imageStats, [event.device_id]: event.stats } } : {}),
          log, lastError,
        }))
        break
      }
      case 'imager.loop_started': {
        set({ imagerLooping: { ...state.imagerLooping, [event.device_id]: true }, log, lastError })
        break
      }
      case 'imager.loop_stopped': {
        set({
          imagerBusy: { ...state.imagerBusy, [event.device_id]: false },
          imagerLooping: { ...state.imagerLooping, [event.device_id]: false },
          imagerExposures: { ...state.imagerExposures, [event.device_id]: null },
          log, lastError,
        })
        break
      }
      case 'imager.exposure_failed': {
        set({
          imagerBusy: { ...state.imagerBusy, [event.device_id]: false },
          imagerExposures: { ...state.imagerExposures, [event.device_id]: null },
          log, lastError,
        })
        break
      }
      case 'mount.slew_started': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_slewing: true } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.slew_completed':
      case 'mount.slew_aborted': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_slewing: false } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.parked': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_parked: true, is_slewing: false, is_tracking: false } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.unparked': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_parked: false } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.tracking_changed': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_tracking: event.tracking } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.meridian_flip_started': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_slewing: true } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.meridian_flip_completed': {
        set((s) => {
          const cur = s.mountStatuses[event.device_id]
          return {
            mountStatuses: cur ? { ...s.mountStatuses, [event.device_id]: { ...cur, is_slewing: false } } : s.mountStatuses,
            log, lastError,
          }
        })
        break
      }
      case 'mount.operation_failed':
      case 'mount.target_set': {
        set({ log, lastError })
        break
      }
      case 'focuser.move_started': {
        set((s) => ({
          focuserStatuses: {
            ...s.focuserStatuses,
            [event.device_id]: {
              state: 'busy',
              position: s.focuserStatuses[event.device_id]?.position ?? null,
              is_moving: true,
              temperature: s.focuserStatuses[event.device_id]?.temperature ?? null,
            },
          },
          log, lastError,
        }))
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


      case 'phd2.settled':
      default:
        set({ log, lastError })
    }

    // Dispatch to plugin-registered event handlers
    const pluginUpdates: Record<string, unknown> = {}
    for (const [pluginId, handlers] of _pluginHandlers) {
      const handler = handlers.get(event.type)
      if (handler) {
        const newState = handler(event, state.pluginStates[pluginId])
        if (newState !== undefined) pluginUpdates[pluginId] = newState
      }
    }
    if (Object.keys(pluginUpdates).length > 0) {
      set((s) => ({ pluginStates: { ...s.pluginStates, ...pluginUpdates } }))
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
    case 'platesolve.started': return `Plate solve started: ${event.fits_path.split('/').pop()}`
    case 'platesolve.completed': return `Plate solve done: RA ${(event.ra / 15).toFixed(4)}h Dec ${event.dec.toFixed(4)}° (${event.duration_ms}ms)`
    case 'platesolve.failed': return `Plate solve failed: ${event.reason}`
    case 'platesolve.cancelled': return `Plate solve cancelled`
    case 'autofocus.started': return `Autofocus started (${event.total_steps} steps)`
    case 'autofocus.data_point': return `AF step ${event.step}/${event.total_steps}: pos ${event.position}, FWHM ${event.fwhm.toFixed(2)}px (${event.star_count} stars)`
    case 'autofocus.completed': return `Autofocus complete — optimal position: ${event.optimal_position}`
    case 'autofocus.aborted': return `Autofocus aborted`
    case 'autofocus.failed': return `Autofocus failed: ${event.reason}`
    default: return (event as { type: string }).type
  }
}
