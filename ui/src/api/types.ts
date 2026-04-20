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

export interface MountTarget {
  ra: number    // ICRS degrees (J2000)
  dec: number   // ICRS degrees (J2000)
  name: string | null
  source: string | null
  set_at: string
}

export type CoordFrame = 'icrs' | 'jnow'

export interface MountStatus {
  state: DeviceState
  ra: number | null       // ICRS (J2000) decimal hours (0–24)
  dec: number | null      // ICRS (J2000) decimal degrees (-90–90)
  ra_jnow: number | null  // JNow decimal hours (0–24)
  dec_jnow: number | null // JNow decimal degrees (-90–90)
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

export interface DitherConfig {
  every_frames?: number | null
  every_minutes?: number | null
  pixels?: number
  ra_only?: boolean
  settle_pixels?: number
  settle_time?: number
  settle_timeout?: number
}

export interface ExposureRequest {
  duration: number
  gain?: number
  binning?: number
  frame_type?: FrameType
  count?: number | null
  save?: boolean
  dither?: DitherConfig | null
}

export interface UserSettings {
  save_dir_template: string
  save_filename_template: string
  enabled_plugins: string[]
  phd2_host: string
  phd2_port: number
  astap_db_path: string
  astap_bin: string
  astap_search_radius: number
  astap_tolerance: number
  pixel_size_um: number | null
  indi_run_dir: string
}

// --- Plate solving ---

export interface SolveRequest {
  fits_path: string
  ra_hint?: number | null   // degrees J2000
  dec_hint?: number | null  // degrees J2000
  radius?: number           // search radius degrees (default 30)
  fov?: number | null       // field width degrees (null = auto)
}

export interface SolveResult {
  ra: number           // degrees J2000
  dec: number          // degrees J2000
  rotation: number     // degrees, North through East
  pixel_scale: number  // arcsec/pixel
  field_w: number      // degrees
  field_h: number      // degrees
  duration_ms: number
}

export interface DbStatus {
  installed: boolean
  db_path: string
}

export type SolveJobStatus = 'pending' | 'solving' | 'completed' | 'failed' | 'cancelled'

export interface SolveJob {
  id: string
  status: SolveJobStatus
  request: SolveRequest
  result?: SolveResult | null
  error?: string | null
  created_at: string
  completed_at?: string | null
}

export interface Phd2Status {
  connected: boolean
  state: string
  rms_ra: number | null
  rms_dec: number | null
  rms_total: number | null
  pixel_scale: number | null
  star_snr: number | null
  is_dithering: boolean
  debug_enabled: boolean
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
  ra: number   // ICRS degrees
  dec: number  // ICRS degrees
}

export interface MountSlewCompletedEvent extends BaseEvent {
  type: 'mount.slew_completed'
  device_id: string
  ra: number   // ICRS degrees
  dec: number  // ICRS degrees
}

export interface MountSlewAbortedEvent extends BaseEvent { type: 'mount.slew_aborted'; device_id: string }
export interface MountParkedEvent extends BaseEvent { type: 'mount.parked'; device_id: string }
export interface MountTargetSetEvent extends BaseEvent {
  type: 'mount.target_set'
  device_id: string
  ra: number    // ICRS degrees
  dec: number   // ICRS degrees
  name: string | null
  source: string | null
}
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

export interface Phd2ConnectedEvent extends BaseEvent { type: 'phd2.connected' }
export interface Phd2DisconnectedEvent extends BaseEvent { type: 'phd2.disconnected' }
export interface Phd2StateChangedEvent extends BaseEvent { type: 'phd2.state_changed'; state: string }
export interface Phd2GuideStepEvent extends BaseEvent {
  type: 'phd2.guide_step'
  frame: number
  ra_dist: number
  dec_dist: number
  ra_corr: number
  dec_corr: number
  star_snr: number | null
}
export interface Phd2SettledEvent extends BaseEvent { type: 'phd2.settled'; error: string | null }

export interface PlatesolveStartedEvent extends BaseEvent {
  type: 'platesolve.started'
  solve_id: string
  fits_path: string
}
export interface PlatesolveCompletedEvent extends BaseEvent {
  type: 'platesolve.completed'
  solve_id: string
  ra: number
  dec: number
  rotation: number
  pixel_scale: number
  field_w: number
  field_h: number
  duration_ms: number
}
export interface PlatesolveFailedEvent extends BaseEvent { type: 'platesolve.failed'; solve_id: string; reason: string }
export interface PlatesolveCancelledEvent extends BaseEvent { type: 'platesolve.cancelled'; solve_id: string }

export type AstrolollEvent =
  | DeviceConnectedEvent | DeviceDisconnectedEvent | DeviceStateChangedEvent
  | ExposureStartedEvent | ExposureCompletedEvent | ExposureFailedEvent
  | LoopStartedEvent | LoopStoppedEvent
  | MountSlewStartedEvent | MountSlewCompletedEvent | MountSlewAbortedEvent
  | MountParkedEvent | MountUnparkedEvent | MountTrackingChangedEvent | MountOperationFailedEvent
  | MountMeridianFlipStartedEvent | MountMeridianFlipCompletedEvent | MountTargetSetEvent
  | FocuserMoveStartedEvent | FocuserMoveCompletedEvent | FocuserHaltedEvent
  | Phd2ConnectedEvent | Phd2DisconnectedEvent | Phd2StateChangedEvent
  | Phd2GuideStepEvent | Phd2SettledEvent
  | PlatesolveStartedEvent | PlatesolveCompletedEvent | PlatesolveFailedEvent | PlatesolveCancelledEvent
  | LogEvent
