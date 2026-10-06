import { create } from 'zustand'
import i18n from '@/i18n'
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
              alt: event.alt,
              az: event.az,
              is_tracking: event.is_tracking,
              is_parked: event.is_parked,
              is_slewing: cur?.is_slewing ?? false,
              pier_side: event.pier_side,
              hour_angle: event.hour_angle,
              lst: event.lst,
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
      case 'device.state_changed': {
        if (event.device_kind === 'mount') {
          set((s) => {
            const cur = s.mountStatuses[event.device_key]
            if (!cur) return { log, lastError }
            return {
              mountStatuses: { ...s.mountStatuses, [event.device_key]: { ...cur, state: event.new_state as MountStatus['state'] } },
              log, lastError,
            }
          })
        } else {
          set({ log, lastError })
        }
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

// Summaries are rendered once, when the event arrives, in the language active at that moment.
function eventSummary(event: AstrolollEvent): string {
  const t = (key: string, opts?: Record<string, unknown>) => i18n.t(key, { ns: 'events', ...opts })
  const kind = (k: string) => i18n.t(`kind.${k}`, { ns: 'equipment', defaultValue: k })
  switch (event.type) {
    case 'log': return event.message
    case 'device.connected': return t('deviceConnected', { kind: kind(event.device_kind), key: event.device_key })
    case 'device.disconnected': return t('deviceDisconnected', { kind: kind(event.device_kind), key: event.device_key })
    case 'device.state_changed': return `${event.device_key} → ${event.new_state}`
    case 'imager.exposure_started': return t('exposureStarted', { duration: event.duration })
    case 'imager.exposure_completed': return t('exposureCompleted', { duration: event.duration, width: event.width, height: event.height })
    case 'imager.exposure_failed': return t('exposureFailed', { reason: event.reason })
    case 'imager.loop_started': return t('loopStarted')
    case 'imager.loop_stopped': return t('loopStopped')
    case 'mount.slew_started': return t('slewStarted', { ra: event.ra.toFixed(3), dec: event.dec.toFixed(2) })
    case 'mount.slew_completed': return t('slewCompleted')
    case 'mount.slew_aborted': return t('slewAborted')
    case 'mount.parked': return t('parked')
    case 'mount.unparked': return t('unparked')
    case 'mount.operation_failed': return t('operationFailed', { operation: event.operation, reason: event.reason })
    case 'mount.tracking_changed': return t(`${event.tracking ? 'trackingOn' : 'trackingOff'}${event.mode ? 'Mode' : ''}`, { mode: event.mode })
    case 'mount.meridian_flip_started': return t('flipStarted')
    case 'mount.meridian_flip_completed': return t('flipCompleted')
    case 'focuser.move_started': return t('focuserMoveStarted', { target: event.target_position })
    case 'focuser.move_completed': return t('focuserMoveCompleted', { position: event.position })
    case 'focuser.halted': return t('focuserHalted', { position: event.position ?? '?' })
    case 'phd2.connected': return t('phd2Connected')
    case 'phd2.disconnected': return t('phd2Disconnected')
    case 'phd2.state_changed': return t('phd2State', { state: event.state })
    case 'phd2.guide_step': return t('guideStep', { frame: event.frame, ra: event.ra_dist.toFixed(3), dec: event.dec_dist.toFixed(3) })
    case 'phd2.settled': return event.error ? t('phd2SettleFailed', { error: event.error }) : t('phd2Settled')
    case 'guiding.state_changed': return event.guiding
      ? t('guiding', { guider: event.guider })
      : t('guidingInterrupted', { guider: event.guider, reason: event.reason ?? t('unknown') })
    case 'guiding.settled': return event.error
      ? t('settleFailed', { after: event.after, guider: event.guider, error: event.error })
      : t('settled', { after: event.after, guider: event.guider })
    case 'platesolve.started': return t('solveStarted', { file: event.fits_path.split('/').pop() })
    case 'platesolve.completed': return t('solveCompleted', { ra: (event.ra / 15).toFixed(4), dec: event.dec.toFixed(4), ms: event.duration_ms })
    case 'platesolve.failed': return t('solveFailed', { reason: event.reason })
    case 'platesolve.cancelled': return t('solveCancelled')
    case 'autofocus.started': return t('afStarted', { steps: event.total_steps })
    case 'autofocus.data_point': return t('afPoint', { step: event.step, steps: event.total_steps, position: event.position, fwhm: event.fwhm.toFixed(2), stars: event.star_count })
    case 'autofocus.completed': return t('afCompleted', { position: event.optimal_position })
    case 'autofocus.aborted': return t('afAborted')
    case 'autofocus.failed': return t('afFailed', { reason: event.reason })
    default: return (event as { type: string }).type
  }
}
