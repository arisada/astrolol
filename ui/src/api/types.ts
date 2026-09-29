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

export interface MountDeviceSettings {
  auto_park_enabled: boolean
  auto_park_time: string | null   // "HH:MM" local 24 h
  auto_flip_enabled: boolean
  auto_flip_ha_hours: number      // decimal hours
  meridian_limit_deg: number      // RA axis travel allowed past the meridian, either way (0–60)
  horizon_min_alt_deg: number     // flat horizon (−10–60): lower GOTOs refused
  horizon_action: 'none' | 'stop_tracking' | 'park'  // when a tracking mount sinks below it
}

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
  gain?: number | null
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
  indi_run_dir: string
  indi_local_upload: boolean
  indi_local_upload_dir: string
  low_memory_mode: boolean
  plugin_settings: Record<string, Record<string, unknown>>
  imager_settings: Record<string, Record<string, unknown>>
}

export interface ImagerDeviceSettings {
  duration: number
  binning: number
  frame_type: string
  save_subs: boolean
  dither_frames: string
  dither_minutes: string
  histo_auto: boolean
  target_temp: string
}

export interface FocuserDeviceSettings {
  step: number
}

// --- Per-plugin settings ---

export interface Phd2Settings {
  host: string
  port: number
}

export interface PlatesolveSettings {
  astap_bin: string
  astap_db_path: string
  astap_search_radius: number
  astap_tolerance: number
  pixel_size_um: number | null
}

// ── Autofocus ─────────────────────────────────────────────────────────────────

export type FitAlgo = 'parabola' | 'hyperbola'
export type FocusMetric = 'fwhm' | 'hfd'

export interface AutofocusSettings {
  step_size: number
  num_steps: number
  exposure_time: number
  binning: number
  gain: number | null
  filter_slot: number | null
  fit_algo: FitAlgo
  metric: FocusMetric
}

export interface AutofocusConfig {
  camera_id: string
  focuser_id: string
  step_size?: number
  num_steps?: number
  exposure_time?: number
  binning?: number
  gain?: number | null
  filter_slot?: number | null
  filter_wheel_id?: string | null
  fit_algo?: FitAlgo
  metric?: FocusMetric
}

export interface StarInfo {
  x: number
  y: number
  fwhm: number
}

export interface FocusDataPoint {
  step: number
  position: number
  fwhm: number
  star_count: number
}

export interface CurveFit {
  a: number
  b: number
  c: number
  optimal_position: number
}

export type AutofocusRunStatus = 'running' | 'completed' | 'failed' | 'aborted'

export interface AutofocusRun {
  id: string
  config: AutofocusConfig
  status: AutofocusRunStatus
  current_step: number
  total_steps: number
  data_points: FocusDataPoint[]
  curve_fit: CurveFit | null
  optimal_position: number | null
  error: string | null
  started_at: string
  completed_at: string | null
  latest_stars: StarInfo[]
  image_width: number | null
  image_height: number | null
}

// --- Guiding (mirrors astrolol/core/guiding/models.py) ---

export interface GuiderStatus {
  guider: string
  connected: boolean
  state: string
  guiding: boolean
  active: boolean
  settling: boolean
  pixel_scale: number | null
}

export interface GuidingHealth {
  guiding: boolean
  guiding_for_s: number | null
  unguided_for_s: number | null
  reason: string | null
}

export interface GuidingStats {
  duration_s: number
  steps: number
  rms_ra: number | null
  rms_dec: number | null
  rms_total: number | null
  unguided_s: number
  losses: number
}

export interface SettleParams {
  pixels: number
  time: number
  timeout: number
}

// --- Sequencer (mirrors astrolol/core/sequencer/models.py) ---

export interface SequencerTargetRef {
  kind: 'favorite' | 'catalog' | 'coordinates' | 'current'
  name: string
  favorite_id?: string | null
  catalog_id?: string | null
  ra?: number | null   // ICRS degrees (snapshot)
  dec?: number | null
}

export interface SequencerExposureGroup {
  filter_name: string | null
  duration: number
  count: number
  binning: number
  gain: number | null
  frame_type: 'light' | 'dark' | 'flat' | 'bias'
}

export interface SequencerLane {
  id?: string
  camera_id: string | null
  groups: SequencerExposureGroup[]
  order: 'sequential' | 'round_robin'
  round_robin_batch: number
  autofocus_on_filter_change: boolean
}

export interface SequencerTask {
  id?: string
  name: string | null
  target: SequencerTargetRef
  lanes: SequencerLane[]
  slew: boolean
  center: boolean
  start_guiding: boolean
  autofocus_at_start: boolean
  dither_every: number | null
  sub_delay_s: number
  on_error: 'skip' | 'defer' | 'pause' | 'abort'
}

export type SequencerTaskStatus = 'pending' | 'running' | 'interrupted' | 'completed' | 'failed' | 'skipped'
export type SequencerRunState = 'idle' | 'starting' | 'running' | 'pausing' | 'paused' | 'stopping'
export type SequencerActivity =
  | 'unparking' | 'slewing' | 'centering' | 'starting_guiding' | 'focusing' | 'changing_filter'
  | 'exposing' | 'dithering' | 'waiting_for_primary' | 'waiting_for_guiding' | 'meridian_flip'
  | 'parking' | 'waiting'
export type SequencerStallKind = 'guiding' | 'centering' | 'autofocus'
export type SequencerBoundary = 'now' | 'frame' | 'task'

export interface SequencerStall {
  kind: SequencerStallKind
  since: string
  attempts: number
  last_error: string | null
  next_attempt_at: string | null
}

export interface SequencerInterruption {
  at: string
  kind: 'pause' | 'stop' | 'switch' | 'defer' | 'skip' | 'cancel' | 'crash'
  actor: string
  reason: string | null
  stall_kind: SequencerStallKind | null
}

export interface SequencerLaneRuntime {
  lane_id: string
  groups: { frames_done: number }[]
  current_group: number | null
  activity: SequencerActivity | null
}

export interface SequencerTaskRuntime {
  task_id: string
  status: SequencerTaskStatus
  lanes: SequencerLaneRuntime[]
  started_at: string | null
  finished_at: string | null
  last_error: string | null
  resolved_ra: number | null
  resolved_dec: number | null
  stall: SequencerStall | null
  interruptions: SequencerInterruption[]
}

export interface SequencerQueueEntry {
  task: SequencerTask & { id: string }
  runtime: SequencerTaskRuntime
}

export interface SequencerStatus {
  run_state: SequencerRunState
  activity: SequencerActivity | null
  message: string | null
  current_task_id: string | null
  lanes: SequencerLaneRuntime[]
  pause_reason: string | null
  pending_request: string | null
  stall: SequencerStall | null
  last_run_outcome: 'completed' | 'stopped' | 'cancelled' | 'failed' | null
  last_error: string | null
  session_id: string | null
  tasks_total: number
  tasks_done: number
  exposure_started_at: string | null
  exposure_duration: number | null
  eta_s: number | null
}

export interface SequencerPreflightIssue {
  severity: 'error' | 'warning'
  task_id: string | null
  lane_id: string | null
  code: string
  message: string
}

export interface SequencerPreflightReport {
  ok: boolean
  issues: SequencerPreflightIssue[]
}

export interface SequencerSettings {
  unpark_on_start: boolean
  park_on_complete: boolean
  guide_settle_pixels: number
  guide_settle_time_s: number
  guide_settle_timeout_s: number
  dither_pixels: number
  dither_ra_only: boolean
  meridian_flip_enabled: boolean
  meridian_flip_ha_hours: number
  center_after_flip: boolean
  center_tolerance_arcsec: number
  center_max_attempts: number
  center_exposure_s: number
  center_binning: number
  guide_healthy_after_s: number
  guide_retry_interval_s: number
  recenter_after_guide_loss_min: number
  center_retry_interval_s: number
  stall_timeout_min: number | null
  uncount_if_unguided_s: number | null
  recenter_after_pause_min: number
  slew_timeout_s: number
  flip_timeout_s: number
  park_timeout_s: number
  exposure_timeout_margin_s: number
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

export type SolveJobStatus = 'pending' | 'exposing' | 'solving' | 'completed' | 'failed' | 'cancelled'

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
  nav_order: number
  nav_before: string | null
}

export interface LogScopeEntry {
  key: string
  label: string
  logger: string
  level: 'debug' | 'info'
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

export interface ImageStats {
  histogram: number[]     // 128 ADU-bin counts
  hist_min: number        // ADU sample minimum
  hist_max: number        // ADU sample maximum
  stretch_low: number     // auto-stretch black point (median, ADU)
  stretch_high: number    // auto-stretch white point (99th pct, ADU)
  mean: number
  median: number
  fwhm: number | null     // median FWHM in pixels (null if autofocus plugin not loaded)
  star_count: number
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

// --- Equipment inventory ---

export type EquipmentItemType =
  | 'site' | 'mount' | 'ota' | 'camera'
  | 'filter_wheel' | 'focuser' | 'rotator' | 'gps'

interface BaseEquipmentItem { id: string; name: string }

export interface SiteEquipmentItem extends BaseEquipmentItem {
  type: 'site'
  latitude: number
  longitude: number
  altitude: number
  timezone: string
}
export interface MountEquipmentItem extends BaseEquipmentItem {
  type: 'mount'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
}
export interface OTAEquipmentItem extends BaseEquipmentItem {
  type: 'ota'
  focal_length: number
  aperture: number
}
export interface CameraEquipmentItem extends BaseEquipmentItem {
  type: 'camera'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
  pixel_size_um: number | null
}
export interface FilterWheelEquipmentItem extends BaseEquipmentItem {
  type: 'filter_wheel'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
  filter_names: string[]
}
export interface FocuserEquipmentItem extends BaseEquipmentItem {
  type: 'focuser'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
}
export interface RotatorEquipmentItem extends BaseEquipmentItem {
  type: 'rotator'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
}
export interface GpsEquipmentItem extends BaseEquipmentItem {
  type: 'gps'
  indi_driver: string | null
  indi_device_name: string | null
  adapter_key: string | null
  connect_params: Record<string, unknown>
}

export type EquipmentItem =
  | SiteEquipmentItem | MountEquipmentItem | OTAEquipmentItem
  | CameraEquipmentItem | FilterWheelEquipmentItem | FocuserEquipmentItem
  | RotatorEquipmentItem | GpsEquipmentItem

// --- Equipment profiles ---

export interface ProfileNode {
  item_id: string
  role: string | null
  children: ProfileNode[]
}

export interface Profile {
  id: string
  name: string
  roots: ProfileNode[]
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

// Per-camera ancestry resolved from the active profile's equipment tree (mount/site/OTA/
// focuser/filter-wheel/rotator), with live device ids — GET /profiles/active/optical-paths.
// Used to associate a camera with the *correct* focuser/filter wheel panel in the Imaging
// page instead of guessing via INDI "companions" or "first connected".
export interface OpticalPath {
  camera: CameraEquipmentItem
  camera_device_id: string | null

  mount: MountEquipmentItem | null
  mount_device_id: string | null
  site: SiteEquipmentItem | null

  ota: OTAEquipmentItem | null

  focuser: FocuserEquipmentItem | null
  focuser_device_id: string | null

  filter_wheel: FilterWheelEquipmentItem | null
  filter_wheel_device_id: string | null

  rotator: RotatorEquipmentItem | null
  rotator_device_id: string | null
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
  /** Actual INDI device names announced by the driver.
   *  May differ from the catalog name (e.g. indi_asi_ccd → "ZWO CCD ASI294MC Pro").
   *  Multiple entries when several cameras of the same model are connected. */
  device_names: string[]
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
  stats: ImageStats | null
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
/** High-frequency: fired on every ABS_FOCUS_POSITION driver update. Not written to the log. */
export interface FocuserPositionUpdatedEvent extends BaseEvent { type: 'focuser.position_updated'; device_id: string; position: number }
/** High-frequency: fired at most 1 Hz when EQUATORIAL_EOD_COORD changes. Not written to the log. */
export interface MountCoordsUpdatedEvent extends BaseEvent {
  type: 'mount.coords_updated'
  device_id: string
  ra: number | null       // ICRS J2000 decimal hours
  dec: number | null      // ICRS J2000 decimal degrees
  ra_jnow: number | null  // JNow decimal hours (raw driver value)
  dec_jnow: number | null // JNow decimal degrees
  alt: number | null
  az: number | null
  pier_side: 'East' | 'West' | null
  hour_angle: number | null
  lst: number | null
  is_tracking: boolean
  is_parked: boolean
}

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

export interface AutofocusStartedEvent extends BaseEvent {
  type: 'autofocus.started'
  run_id: string
  camera_id: string
  focuser_id: string
  total_steps: number
}
export interface AutofocusDataPointEvent extends BaseEvent {
  type: 'autofocus.data_point'
  run_id: string
  step: number
  total_steps: number
  position: number
  fwhm: number
  star_count: number
}
export interface AutofocusCompletedEvent extends BaseEvent {
  type: 'autofocus.completed'
  run_id: string
  optimal_position: number
}
export interface AutofocusAbortedEvent extends BaseEvent { type: 'autofocus.aborted'; run_id: string }
export interface AutofocusFailedEvent extends BaseEvent { type: 'autofocus.failed'; run_id: string; reason: string }

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

export interface GuidingStateChangedEvent extends BaseEvent {
  type: 'guiding.state_changed'
  guider: string
  guiding: boolean
  reason: string | null
}
export interface GuidingSettledEvent extends BaseEvent {
  type: 'guiding.settled'
  guider: string
  after: 'guide' | 'dither'
  error: string | null
}
export interface SequencerStatusEvent extends BaseEvent { type: 'sequencer.status'; status: SequencerStatus }
export interface SequencerQueueChangedEvent extends BaseEvent {
  type: 'sequencer.queue_changed'
  entries: SequencerQueueEntry[]
}
export interface SequencerFrameSavedEvent extends BaseEvent {
  type: 'sequencer.frame_saved'
  task_id: string
  lane_id: string
  group_idx: number
  frame_idx: number
  frames_total: number
  filter_name: string | null
  duration: number
  fits_path: string
  counted: boolean
  guide_rms_total: number | null
  unguided_s: number | null
  guiding_losses: number | null
}
export interface SequencerTaskFinishedEvent extends BaseEvent {
  type: 'sequencer.task_finished'
  task_id: string
  status: SequencerTaskStatus
  error: string | null
}
export interface SequencerStepFailedEvent extends BaseEvent {
  type: 'sequencer.step_failed'
  task_id: string | null
  step: string
  error: string
  handling: string
}

// --- System management plugin ---

export type NetworkMode = 'wifi' | 'hotspot' | 'disconnected' | 'unknown'

export interface WifiNetwork {
  ssid: string
  bssid: string
  signal: number
  security: string
  in_use: boolean
}

export interface NetworkStatus {
  mode: NetworkMode
  interface: string | null
  ssid: string | null
  ip_address: string | null
  gateway: string | null
  hotspot_ssid: string | null
  hotspot_ip: string | null
  nmcli_available: boolean
}

export interface SystemStatus {
  cpu_percent: number
  memory_percent: number
  memory_used_mb: number
  memory_total_mb: number
  disk_percent: number
  disk_used_gb: number
  disk_total_gb: number
  temperature_celsius: number | null
  uptime_seconds: number
  hostname: string
  platform: string
}

export interface SystemSettings {
  hotspot_ssid: string
  hotspot_password: string
  hotspot_interface: string
  throttle_monitor_enabled: boolean
  throttle_check_interval_seconds: number
}

export interface ThrottleStatus {
  available: boolean
  source: string
  raw_hex: string | null
  under_voltage: boolean
  freq_capped: boolean
  throttled: boolean
  soft_temp_limit: boolean
  under_voltage_occurred: boolean
  freq_capped_occurred: boolean
  throttled_occurred: boolean
  soft_temp_limit_occurred: boolean
  underpowered: boolean
}

export interface SudoSetup {
  nmcli_sudo_ok: boolean
  reboot_sudo_ok: boolean
  shutdown_sudo_ok: boolean
  setup_commands: string[]
}

export interface TimeInfo {
  datetime_local: string
  datetime_utc: string
  timezone: string
  ntp_synced: boolean
  ntp_service_active: boolean
  rtc_time: string | null
}

export interface StorageDisk {
  device: string
  mountpoint: string
  filesystem: string
  total_gb: number
  used_gb: number
  free_gb: number
  percent: number
  removable: boolean
}

export interface HostnameInfo {
  hostname: string
  fqdn: string | null
}

export interface UsbDevice {
  bus: string
  device: string
  vendor_id: string
  product_id: string
  name: string
}

export interface SavedWifiConnection {
  name: string
  interface: string | null
  autoconnect: boolean
}

export type AstrolollEvent =
  | DeviceConnectedEvent | DeviceDisconnectedEvent | DeviceStateChangedEvent
  | ExposureStartedEvent | ExposureCompletedEvent | ExposureFailedEvent
  | LoopStartedEvent | LoopStoppedEvent
  | MountSlewStartedEvent | MountSlewCompletedEvent | MountSlewAbortedEvent
  | MountParkedEvent | MountUnparkedEvent | MountTrackingChangedEvent | MountOperationFailedEvent
  | MountMeridianFlipStartedEvent | MountMeridianFlipCompletedEvent | MountTargetSetEvent
  | MountCoordsUpdatedEvent
  | FocuserMoveStartedEvent | FocuserMoveCompletedEvent | FocuserHaltedEvent
  | FocuserPositionUpdatedEvent
  | Phd2ConnectedEvent | Phd2DisconnectedEvent | Phd2StateChangedEvent
  | Phd2GuideStepEvent | Phd2SettledEvent
  | PlatesolveStartedEvent | PlatesolveCompletedEvent | PlatesolveFailedEvent | PlatesolveCancelledEvent
  | AutofocusStartedEvent | AutofocusDataPointEvent | AutofocusCompletedEvent
  | AutofocusAbortedEvent | AutofocusFailedEvent
  | GuidingStateChangedEvent | GuidingSettledEvent
  | SequencerStatusEvent | SequencerQueueChangedEvent | SequencerFrameSavedEvent
  | SequencerTaskFinishedEvent | SequencerStepFailedEvent
  | LogEvent
