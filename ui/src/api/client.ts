import type {
  ActivationResult,
  CameraStatus,
  ConnectedDevice,
  DeviceConfig,
  DeviceProperty,
  DriverEntry,
  ExposureRequest,
  ExposureResult,
  FilterWheelStatus,
  FocuserStatus,
  ImagerStatus,
  IndiDeviceMessage,
  LoadDriverResponse,
  MountStatus,
  Phd2Status,
  PluginInfo,
  Profile,
  SetPropertyRequest,
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
    slew: (deviceId: string, ra: number, dec: number) =>
      request<void>(`/mount/${deviceId}/slew`, {
        method: 'POST',
        body: JSON.stringify({ ra, dec }),
      }),
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
    sync: (deviceId: string, ra: number, dec: number) =>
      request<void>(`/mount/${deviceId}/sync`, {
        method: 'POST',
        body: JSON.stringify({ ra, dec }),
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
  },

  settings: {
    get: () => request<UserSettings>('/settings'),
    put: (body: UserSettings) => request<UserSettings>('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  },

  plugins: {
    list: () => request<PluginInfo[]>('/plugins'),
  },

  phd2: {
    connect: () => request<void>('/phd2/connect', { method: 'POST' }),
    disconnect: () => request<void>('/phd2/disconnect', { method: 'POST' }),
    status: () => request<Phd2Status>('/phd2/status'),
    guide: (settlePixels?: number, settleTime?: number, settleTimeout?: number, recalibrate?: boolean) =>
      request<void>('/phd2/guide', {
        method: 'POST',
        body: JSON.stringify({
          settle: { pixels: settlePixels ?? 1.5, time: settleTime ?? 10, timeout: settleTimeout ?? 60 },
          recalibrate: recalibrate ?? false,
        }),
      }),
    stop: () => request<void>('/phd2/stop', { method: 'POST' }),
    dither: (pixels?: number, raOnly?: boolean) =>
      request<void>('/phd2/dither', {
        method: 'POST',
        body: JSON.stringify({ pixels: pixels ?? 5.0, ra_only: raOnly ?? false }),
      }),
    pause: () => request<void>('/phd2/pause', { method: 'POST' }),
    resume: () => request<void>('/phd2/resume', { method: 'POST' }),
    setDebug: (enabled: boolean) =>
      request<void>('/phd2/debug', { method: 'POST', body: JSON.stringify({ enabled }) }),
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
