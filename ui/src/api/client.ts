import type {
  ActivationResult,
  CameraStatus,
  CoordFrame,
  ConnectedDevice,
  DbStatus,
  DeviceConfig,
  DeviceProperty,
  DriverEntry,
  ExposureRequest,
  ExposureResult,
  FilterWheelStatus,
  FocuserStatus,
  ImagerDeviceSettings,
  ImagerStatus,
  IndiDeviceMessage,
  LoadDriverResponse,
  MountStatus,
  MountTarget,
  Phd2Status,
  PluginInfo,
  Profile,
  SetPropertyRequest,
  SolveJob,
  SolveRequest,
  TrackingMode,
  UserSettings,
} from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// --- Devices ---

export const api = {
  devices: {
    available: () => request<Record<string, string[]>>('/devices/available'),
    connected: () => request<ConnectedDevice[]>('/devices/connected'),
    connect: (config: DeviceConfig) =>
      request<{ device_id: string }>('/devices/connect', {
        method: 'POST',
        body: JSON.stringify(config),
      }),
    disconnect: (deviceId: string) =>
      request<void>(`/devices/connected/${deviceId}/disconnect`, { method: 'POST' }),
    remove: (deviceId: string) =>
      request<void>(`/devices/connected/${deviceId}`, { method: 'DELETE' }),
    reconnect: (deviceId: string) =>
      request<void>(`/devices/connected/${deviceId}/reconnect`, { method: 'POST' }),
    getConfig: (deviceId: string) =>
      request<DeviceConfig>(`/devices/connected/${deviceId}/config`),
    properties: (deviceId: string) =>
      request<DeviceProperty[]>(`/devices/${deviceId}/properties`),
    setProperty: (deviceId: string, propName: string, body: SetPropertyRequest) =>
      request<void>(`/devices/${deviceId}/properties/${propName}`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  },

  imager: {
    status: (deviceId: string) => request<ImagerStatus>(`/imager/${deviceId}/status`),
    cameraStatus: (deviceId: string) => request<CameraStatus>(`/imager/${deviceId}/camera_status`),
    getSettings: (deviceId: string) => request<ImagerDeviceSettings>(`/imager/${deviceId}/settings`),
    putSettings: (deviceId: string, body: ImagerDeviceSettings) =>
      request<ImagerDeviceSettings>(`/imager/${deviceId}/settings`, {
        method: 'PUT',
        body: JSON.stringify(body),
      }),
    setCooler: (deviceId: string, enabled: boolean, targetTemperature?: number) =>
      request<void>(`/imager/${deviceId}/cooler`, {
        method: 'POST',
        body: JSON.stringify({ enabled, target_temperature: targetTemperature ?? null }),
      }),
    expose: (deviceId: string, body: ExposureRequest) =>
      request<ExposureResult>(`/imager/${deviceId}/expose`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    startLoop: (deviceId: string, body: ExposureRequest) =>
      request<void>(`/imager/${deviceId}/loop`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    stopLoop: (deviceId: string) =>
      request<void>(`/imager/${deviceId}/loop`, { method: 'DELETE' }),
    halt: (deviceId: string) =>
      request<void>(`/imager/${deviceId}/halt`, { method: 'POST' }),
    previewUrl: (previewPath: string) => {
      const filename = previewPath.split('/').pop()!
      return `/imager/images/${filename}`
    },
  },

  filterWheel: {
    status: (deviceId: string) => request<FilterWheelStatus>(`/filter_wheel/${deviceId}/status`),
    select: (deviceId: string, slot: number) =>
      request<void>(`/filter_wheel/${deviceId}/select`, {
        method: 'POST',
        body: JSON.stringify({ slot }),
      }),
  },

  mount: {
    status: (deviceId: string) => request<MountStatus>(`/mount/${deviceId}/status`),
    // Target: ICRS degrees (J2000)
    setTarget: (deviceId: string, ra_deg: number, dec_deg: number, name?: string, source?: string, frame: CoordFrame = 'icrs') =>
      request<MountTarget>(`/mount/${deviceId}/target`, {
        method: 'PUT',
        body: JSON.stringify({ ra: ra_deg, dec: dec_deg, name: name ?? null, source: source ?? null, frame }),
      }),
    getTarget: (deviceId: string) => request<MountTarget>(`/mount/${deviceId}/target`),
    clearTarget: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/target`, { method: 'DELETE' }),
    slew: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/slew`, { method: 'POST' }),
    stop: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/stop`, { method: 'POST' }),
    park: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/park`, { method: 'POST' }),
    unpark: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/unpark`, { method: 'POST' }),
    setTracking: (deviceId: string, enabled: boolean, mode?: TrackingMode) =>
      request<void>(`/mount/${deviceId}/tracking`, {
        method: 'POST',
        body: JSON.stringify({ enabled, mode: mode ?? null }),
      }),
    meridianFlip: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/meridian_flip`, { method: 'POST' }),
    // sync: ICRS degrees (J2000)
    sync: (deviceId: string, ra_deg: number, dec_deg: number) =>
      request<void>(`/mount/${deviceId}/sync`, {
        method: 'POST',
        body: JSON.stringify({ ra: ra_deg, dec: dec_deg }),
      }),
    setParkPosition: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/set_park_position`, { method: 'POST' }),
    startMove: (deviceId: string, direction: string, rate: string) =>
      request<void>(`/mount/${deviceId}/move`, {
        method: 'POST',
        body: JSON.stringify({ direction, rate }),
      }),
    stopMove: (deviceId: string) =>
      request<void>(`/mount/${deviceId}/move`, { method: 'DELETE' }),
  },

  profiles: {
    list: () => request<Profile[]>('/profiles'),
    get: (id: string) => request<Profile>(`/profiles/${id}`),
    active: () => request<Profile | null>('/profiles/active'),
    create: (p: Omit<Profile, 'id'>) => request<Profile>('/profiles', { method: 'POST', body: JSON.stringify(p) }),
    update: (p: Profile) => request<Profile>(`/profiles/${p.id}`, { method: 'PUT', body: JSON.stringify(p) }),
    delete: (id: string) => request<void>(`/profiles/${id}`, { method: 'DELETE' }),
    activate: (id: string) => request<ActivationResult>(`/profiles/${id}/activate`, { method: 'POST' }),
    deactivate: () => request<void>('/profiles/active', { method: 'DELETE' }),
  },

  indi: {
    drivers: (kind?: string) =>
      request<DriverEntry[]>(kind ? `/indi/drivers/${kind}` : '/indi/drivers'),
    loadDriver: (executable: string, deviceName: string) =>
      request<LoadDriverResponse>('/indi/load_driver', {
        method: 'POST',
        body: JSON.stringify({ executable, device_name: deviceName }),
      }),
    deviceMessages: (deviceName: string) =>
      request<IndiDeviceMessage[]>(`/indi/messages/${encodeURIComponent(deviceName)}`),
    setDebugLevel: (level: number) =>
      request<void>('/indi/debug', { method: 'POST', body: JSON.stringify({ level }) }),
  },

  settings: {
    get: () => request<UserSettings>('/settings'),
    put: (body: UserSettings) => request<UserSettings>('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  },

  admin: {
    restart: () => request<{ status: string }>('/admin/restart', { method: 'POST' }),
    indiStop: () => request<{ status: string }>('/admin/indi/stop', { method: 'POST' }),
  },

  plugins: {
    list: () => request<PluginInfo[]>('/plugins'),
    getSettings: <T>(pluginId: string) => request<T>(`/plugins/${pluginId}/settings`),
    putSettings: <T>(pluginId: string, body: T) =>
      request<T>(`/plugins/${pluginId}/settings`, { method: 'PUT', body: JSON.stringify(body) }),
  },

  phd2: {
    connect: () => request<void>('/plugins/phd2/connect', { method: 'POST' }),
    disconnect: () => request<void>('/plugins/phd2/disconnect', { method: 'POST' }),
    status: () => request<Phd2Status>('/plugins/phd2/status'),
    guide: (settlePixels?: number, settleTime?: number, settleTimeout?: number, recalibrate?: boolean) =>
      request<void>('/plugins/phd2/guide', {
        method: 'POST',
        body: JSON.stringify({
          settle: { pixels: settlePixels ?? 1.5, time: settleTime ?? 10, timeout: settleTimeout ?? 60 },
          recalibrate: recalibrate ?? false,
        }),
      }),
    stop: () => request<void>('/plugins/phd2/stop', { method: 'POST' }),
    dither: (pixels?: number, raOnly?: boolean) =>
      request<void>('/plugins/phd2/dither', {
        method: 'POST',
        body: JSON.stringify({ pixels: pixels ?? 5.0, ra_only: raOnly ?? false }),
      }),
    pause: () => request<void>('/plugins/phd2/pause', { method: 'POST' }),
    resume: () => request<void>('/plugins/phd2/resume', { method: 'POST' }),
    setDebug: (enabled: boolean) =>
      request<void>('/plugins/phd2/debug', { method: 'POST', body: JSON.stringify({ enabled }) }),
  },

  platesolve: {
    exposeAndSolve: (body: { device_id: string; duration: number; binning: number; gain?: number | null }) =>
      request<SolveJob>('/plugins/platesolve/expose_and_solve', { method: 'POST', body: JSON.stringify(body) }),
    solve: (req: SolveRequest) =>
      request<SolveJob>('/plugins/platesolve/solve', { method: 'POST', body: JSON.stringify(req) }),
    jobs: () => request<SolveJob[]>('/plugins/platesolve/jobs'),
    status: (jobId: string) => request<SolveJob>(`/plugins/platesolve/${jobId}/status`),
    cancel: (jobId: string) => request<void>(`/plugins/platesolve/${jobId}/cancel`, { method: 'DELETE' }),
    dbStatus: () => request<DbStatus>('/plugins/platesolve/db_status'),
    installDb: () => request<{ status: string }>('/plugins/platesolve/install_db', { method: 'POST' }),
  },

  focuser: {
    status: (deviceId: string) => request<FocuserStatus>(`/focuser/${deviceId}/status`),
    moveTo: (deviceId: string, position: number) =>
      request<void>(`/focuser/${deviceId}/move_to`, {
        method: 'POST',
        body: JSON.stringify({ position }),
      }),
    moveBy: (deviceId: string, steps: number) =>
      request<void>(`/focuser/${deviceId}/move_by`, {
        method: 'POST',
        body: JSON.stringify({ steps }),
      }),
    halt: (deviceId: string) =>
      request<void>(`/focuser/${deviceId}/halt`, { method: 'POST' }),
  },
}
