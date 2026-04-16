// Hand-written types mirroring the Python Pydantic models.
// Run `npm run generate-api-types` to regenerate from the live OpenAPI spec.

export type DeviceKind = 'camera' | 'mount' | 'focuser' | 'filter_wheel' | 'rotator' | 'indi'
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
  companions: string[]
  primary_id: string | null
  driver_name: string | null
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
  pier_side: 'East' | 'West' | null
  hour_angle: number | null  // decimal hours; negative = east of meridian (pre-flip), positive = west (post)
  lst: number | null         // Local Sidereal Time in decimal hours
}

export interface FocuserStatus {
  state: DeviceState
  position: number | null
  is_moving: boolean
  temperature: number | null
}

export type FrameType = 'light' | 'dark' | 'flat' | 'bias'

export interface ExposureRequest {
  duration: number
  gain?: number
  binning?: number
  frame_type?: FrameType
  count?: number | null
  save?: boolean
}

export interface UserSettings {
  save_dir_template: string
  save_filename_template: string
  enabled_plugins: string[]
}

export interface PluginInfo {
  id: string
  name: string
  version: string
  description: string
  enabled: boolean
}

export interface CameraStatus {
  state: DeviceState
  temperature: number | null
  cooler_on: boolean
  cooler_power: number | null
}

export interface FilterWheelStatus {
  state: DeviceState
  current_slot: number | null
  filter_count: number | null
  filter_names: string[]
  is_moving: boolean
}

export interface ExposureResult {
  device_id: string
  fits_path: string
  preview_path: string
  preview_path_linear: string | null
  duration: number
  width: number
  height: number
}

export interface ImagerStatus {
  device_id: string
  state: 'idle' | 'exposing' | 'looping' | 'error'
}

// --- Equipment profiles ---

export interface ObserverLocation {
  name: string
  latitude: number
  longitude: number
  altitude: number
}

export interface Telescope {
  name: string
  focal_length: number
  aperture: number
}

export type DeviceRole = 'camera' | 'mount' | 'focuser' | 'filter_wheel' | 'rotator' | 'indi'

export interface ProfileDevice {
  role: DeviceRole
  config: DeviceConfig
}

export interface Profile {
  id: string
  name: string
  location?: ObserverLocation
  telescope?: Telescope
  devices: ProfileDevice[]
}

export interface DeviceResult {
  device_id: string
  role: string
  error?: string
}

export interface ActivationResult {
  profile_id: string
  connected: DeviceResult[]
  failed: DeviceResult[]
}

// --- Device properties (INDI) ---

export type PropertyType = 'number' | 'switch' | 'text' | 'light' | 'blob'
export type PropertyState = 'idle' | 'ok' | 'busy' | 'alert'
export type PropertyPermission = 'ro' | 'rw' | 'wo'
export type SwitchRule = '1ofmany' | 'atmost1' | 'nofmany'

export interface PropertyWidget {
  name: string
  label: string
  value?: number | string | boolean
  min?: number
  max?: number
  step?: number
  state?: PropertyState  // for light widgets
}

export interface DeviceProperty {
  name: string
  label: string
  group: string
  type: PropertyType
  state: PropertyState
  permission: PropertyPermission
  switch_rule?: SwitchRule
  widgets: PropertyWidget[]
}

export interface SetPropertyRequest {
  values?: Record<string, number | string>
  on_elements?: string[]
}

export type PreConnectPropSpec =
  | { values: Record<string, string | number>; on_elements?: never }
  | { on_elements: string[]; values?: never }

export type PreConnectProps = Record<string, PreConnectPropSpec>

export interface LoadDriverResponse {
  properties: DeviceProperty[]
}

export interface IndiDeviceMessage {
  timestamp: string
  message: string
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
  preview_path_linear: string | null
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
export type TrackingMode = 'sidereal' | 'lunar' | 'solar'

export interface MountTrackingChangedEvent extends BaseEvent { type: 'mount.tracking_changed'; device_id: string; tracking: boolean; mode: TrackingMode | null }
export interface MountUnparkedEvent extends BaseEvent { type: 'mount.unparked'; device_id: string }
export interface MountOperationFailedEvent extends BaseEvent { type: 'mount.operation_failed'; device_id: string; operation: string; reason: string }
export interface MountMeridianFlipStartedEvent extends BaseEvent { type: 'mount.meridian_flip_started'; device_id: string }
export interface MountMeridianFlipCompletedEvent extends BaseEvent { type: 'mount.meridian_flip_completed'; device_id: string }

export interface FocuserMoveStartedEvent extends BaseEvent { type: 'focuser.move_started'; device_id: string; target_position: number }
export interface FocuserMoveCompletedEvent extends BaseEvent { type: 'focuser.move_completed'; device_id: string; position: number }
export interface FocuserHaltedEvent extends BaseEvent { type: 'focuser.halted'; device_id: string; position: number | null }

export interface LogEvent extends BaseEvent { type: 'log'; level: string; component: string; message: string }

export type AstrolollEvent =
  | DeviceConnectedEvent | DeviceDisconnectedEvent | DeviceStateChangedEvent
  | ExposureStartedEvent | ExposureCompletedEvent | ExposureFailedEvent
  | LoopStartedEvent | LoopStoppedEvent
  | MountSlewStartedEvent | MountSlewCompletedEvent | MountSlewAbortedEvent
  | MountParkedEvent | MountUnparkedEvent | MountTrackingChangedEvent | MountOperationFailedEvent
  | MountMeridianFlipStartedEvent | MountMeridianFlipCompletedEvent
  | FocuserMoveStartedEvent | FocuserMoveCompletedEvent | FocuserHaltedEvent
  | LogEvent
