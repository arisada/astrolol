// Hand-written types mirroring the Python Pydantic models.
// Run `npm run generate-api-types` to regenerate from the live OpenAPI spec.

export type DeviceKind = 'camera' | 'mount' | 'focuser'
export type DeviceState = 'disconnected' | 'connecting' | 'connected' | 'busy' | 'error'

export interface DeviceConfig {
  device_id?: string
  kind: DeviceKind
  adapter_key: string
  params?: Record<string, unknown>
}

export interface DriverEntry {
  label: string
  executable: string
  device_name: string
  group: string
  kind: string
  manufacturer: string
}

export interface ConnectedDevice {
  device_id: string
  kind: DeviceKind
  adapter_key: string
  state: DeviceState
}

export interface MountStatus {
  state: DeviceState
  ra: number | null
  dec: number | null
  alt: number | null
  az: number | null
  is_tracking: boolean
  is_parked: boolean
  is_slewing: boolean
}

export interface FocuserStatus {
  state: DeviceState
  position: number | null
  is_moving: boolean
  temperature: number | null
}

export interface ExposureRequest {
  duration: number
  gain?: number
  binning?: number
  count?: number | null
}

export interface ExposureResult {
  device_id: string
  fits_path: string
  preview_path: string
  duration: number
  width: number
  height: number
}

export interface ImagerStatus {
  device_id: string
  state: 'idle' | 'exposing' | 'looping' | 'error'
}

// --- WebSocket events (discriminated union) ---

interface BaseEvent {
  id: string
  timestamp: string
}

export interface DeviceConnectedEvent extends BaseEvent {
  type: 'device.connected'
  device_kind: string
  device_key: string
}

export interface DeviceDisconnectedEvent extends BaseEvent {
  type: 'device.disconnected'
  device_kind: string
  device_key: string
  reason: string | null
}

export interface DeviceStateChangedEvent extends BaseEvent {
  type: 'device.state_changed'
  device_kind: string
  device_key: string
  old_state: DeviceState
  new_state: DeviceState
}

export interface ExposureCompletedEvent extends BaseEvent {
  type: 'imager.exposure_completed'
  device_id: string
  fits_path: string
  preview_path: string
  duration: number
  width: number
  height: number
}

export interface ExposureStartedEvent extends BaseEvent {
  type: 'imager.exposure_started'
  device_id: string
  duration: number
}

export interface ExposureFailedEvent extends BaseEvent {
  type: 'imager.exposure_failed'
  device_id: string
  reason: string
}

export interface LoopStartedEvent extends BaseEvent { type: 'imager.loop_started'; device_id: string }
export interface LoopStoppedEvent extends BaseEvent { type: 'imager.loop_stopped'; device_id: string }

export interface MountSlewStartedEvent extends BaseEvent {
  type: 'mount.slew_started'
  device_id: string
  ra: number
  dec: number
}

export interface MountSlewCompletedEvent extends BaseEvent {
  type: 'mount.slew_completed'
  device_id: string
  ra: number
  dec: number
}

export interface MountSlewAbortedEvent extends BaseEvent { type: 'mount.slew_aborted'; device_id: string }
export interface MountParkedEvent extends BaseEvent { type: 'mount.parked'; device_id: string }
export interface MountTrackingChangedEvent extends BaseEvent { type: 'mount.tracking_changed'; device_id: string; tracking: boolean }

export interface FocuserMoveStartedEvent extends BaseEvent { type: 'focuser.move_started'; device_id: string; target_position: number }
export interface FocuserMoveCompletedEvent extends BaseEvent { type: 'focuser.move_completed'; device_id: string; position: number }
export interface FocuserHaltedEvent extends BaseEvent { type: 'focuser.halted'; device_id: string; position: number | null }

export interface LogEvent extends BaseEvent { type: 'log'; level: string; component: string; message: string }

export type AstrolollEvent =
  | DeviceConnectedEvent | DeviceDisconnectedEvent | DeviceStateChangedEvent
  | ExposureStartedEvent | ExposureCompletedEvent | ExposureFailedEvent
  | LoopStartedEvent | LoopStoppedEvent
  | MountSlewStartedEvent | MountSlewCompletedEvent | MountSlewAbortedEvent
  | MountParkedEvent | MountTrackingChangedEvent
  | FocuserMoveStartedEvent | FocuserMoveCompletedEvent | FocuserHaltedEvent
  | LogEvent
