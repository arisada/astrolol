import { useEffect, useState } from 'react'
import { Camera, ChevronLeft, CircleDot, Crosshair, FilterIcon, Link2, Plug, PlugZap, RefreshCw, Telescope, Trash2 } from 'lucide-react'
import { api } from '@/api/client'
import type { ConnectedDevice, DeviceKind, DeviceProperty, DriverEntry, PreConnectProps } from '@/api/types'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type WizardStep = 'type' | 'manufacturer' | 'model' | 'confirm' | 'configure'

const DEVICE_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/

function suggestDeviceId(kind: DeviceKind, driver: DriverEntry | null): string {
  if (!driver) return ''
  const raw = driver.executable.replace(/^indi_/, '') || driver.manufacturer
  const slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '').slice(0, 40)
  return slug ? `${kind}_${slug}` : ''
}

const KIND_LABELS: Record<DeviceKind, string> = {
  camera: 'Camera',
  mount: 'Mount',
  focuser: 'Focuser',
  filter_wheel: 'Filter Wheel',
  rotator: 'Rotator',
  indi: 'INDI Device',
}

const KIND_ADAPTER: Record<DeviceKind, string> = {
  camera: 'indi_camera',
  mount: 'indi_mount',
  focuser: 'indi_focuser',
  filter_wheel: 'indi_filter_wheel',
  rotator: 'indi_rotator',
  indi: 'indi_raw',
}

function KindIcon({ kind, size = 28 }: { kind: DeviceKind; size?: number }) {
  if (kind === 'camera') return <Camera size={size} />
  if (kind === 'mount') return <Telescope size={size} />
  if (kind === 'filter_wheel') return <FilterIcon size={size} />
  if (kind === 'rotator') return <CircleDot size={size} />
  return <Crosshair size={size} />
}

// ---------------------------------------------------------------------------
// Pre-connect props helpers
// ---------------------------------------------------------------------------

// Pre-connect props are intentionally NOT pre-populated with the driver's
// current values.  Sending back values the user hasn't changed can cause
// unexpected driver behaviour — for example, ZWO cameras hang on
// CONNECTION=CONNECT when ACTIVE_DEVICES is sent before connection with a
// stale telescope name from a previous session (Ekos sets it post-connect).
// Only properties the user explicitly modifies are included.

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StepBack({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-4 transition-colors"
    >
      <ChevronLeft size={14} /> Back
    </button>
  )
}

// Step 1 — choose device type (only manually-connectable kinds)
function TypeStep({ onSelect }: { onSelect: (kind: DeviceKind) => void }) {
  const kinds: DeviceKind[] = ['camera', 'mount', 'focuser']
  // filter_wheel, rotator, indi are auto-discovered as companions
  return (
    <div>
      <p className="text-xs text-slate-500 mb-4">What do you want to connect?</p>
      <div className="grid grid-cols-3 gap-3">
        {kinds.map((kind) => (
          <button
            key={kind}
            onClick={() => onSelect(kind)}
            className="flex flex-col items-center gap-3 rounded-lg border border-surface-border bg-surface-raised px-4 py-6 text-slate-400 transition-all hover:border-accent hover:text-slate-100 hover:bg-surface-overlay"
          >
            <KindIcon kind={kind} size={32} />
            <span className="text-sm font-medium">{KIND_LABELS[kind]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// Step 2 — choose manufacturer
function ManufacturerStep({
  kind,
  drivers,
  onSelect,
  onBack,
}: {
  kind: DeviceKind
  drivers: DriverEntry[]
  onSelect: (manufacturer: string | null) => void
  onBack: () => void
}) {
  const manufacturers = [...new Set(drivers.map((d) => d.manufacturer))].sort()

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{KIND_LABELS[kind]}</span>
        {' · '}Select manufacturer
      </p>
      <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto pr-1">
        {manufacturers.map((m) => (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className="text-left rounded px-3 py-2 text-sm text-slate-300 border border-transparent hover:border-surface-border hover:bg-surface-raised transition-colors"
          >
            {m}
          </button>
        ))}
        <button
          onClick={() => onSelect(null)}
          className="text-left rounded px-3 py-2 text-xs text-slate-500 hover:text-slate-400 transition-colors mt-1 border-t border-surface-border pt-3"
        >
          Enter manually…
        </button>
      </div>
    </div>
  )
}

// Step 3 — choose model
function ModelStep({
  kind,
  manufacturer,
  drivers,
  onSelect,
  onBack,
}: {
  kind: DeviceKind
  manufacturer: string
  drivers: DriverEntry[]
  onSelect: (driver: DriverEntry) => void
  onBack: () => void
}) {
  const models = drivers.filter((d) => d.manufacturer === manufacturer)

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{KIND_LABELS[kind]}</span>
        {' · '}
        <span className="text-slate-300">{manufacturer}</span>
        {' · '}Select model
      </p>
      <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto pr-1">
        {models.map((d) => (
          <button
            key={d.executable}
            onClick={() => onSelect(d)}
            className="text-left rounded px-3 py-2 border border-transparent hover:border-surface-border hover:bg-surface-raised transition-colors"
          >
            <span className="text-sm text-slate-200">{d.label}</span>
            <span className="block text-xs text-slate-500 mt-0.5">{d.executable}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// Step 4 — confirm details and load driver
function ConfirmStep({
  kind,
  driver,
  onBack,
  onLoadDriver,
  loading,
  error,
}: {
  kind: DeviceKind
  driver: DriverEntry | null
  onBack: () => void
  onLoadDriver: (deviceName: string, executable: string, deviceId: string) => void
  loading: boolean
  error: string | null
}) {
  const [deviceName, setDeviceName] = useState(driver?.device_name ?? '')
  const [executable, setExecutable] = useState(driver?.executable ?? '')
  const [deviceId, setDeviceId] = useState(() => suggestDeviceId(kind, driver))

  const deviceIdInvalid = deviceId !== '' && !DEVICE_ID_RE.test(deviceId)

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{KIND_LABELS[kind]}</span>
        {driver && (
          <>
            {' · '}
            <span className="text-slate-300">{driver.manufacturer}</span>
            {' · '}
            <span className="text-slate-300">{driver.label}</span>
          </>
        )}
      </p>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            INDI device name <span className="text-status-error">*</span>
          </label>
          <Input
            placeholder="e.g. ZWO CCD ASI294MC Pro"
            value={deviceName}
            onChange={(e) => setDeviceName(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            Driver executable
            {driver && <span className="ml-2 text-slate-600">(auto-filled from catalog)</span>}
          </label>
          <Input
            placeholder="e.g. indi_asi_ccd"
            value={executable}
            onChange={(e) => setExecutable(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            Device ID
            <span className="ml-2 text-slate-600">(leave blank to use suggestion)</span>
          </label>
          <Input
            placeholder={suggestDeviceId(kind, driver) || 'auto-generated'}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className={deviceIdInvalid ? 'border-status-error focus-visible:ring-status-error' : ''}
          />
          {deviceIdInvalid && (
            <p className="text-xs text-status-error">
              Only letters, digits, hyphens, and underscores. Must start with a letter or digit (max 64 chars).
            </p>
          )}
        </div>

        {error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
        )}

        <Button
          type="button"
          disabled={!deviceName || loading || deviceIdInvalid}
          className="self-start"
          onClick={() => onLoadDriver(deviceName, executable, deviceId)}
        >
          <Plug size={14} className="mr-2" />
          {loading ? 'Loading driver…' : 'Load driver'}
        </Button>

        <p className="text-xs text-slate-600">
          Loading the driver reads its available settings so you can configure them before connecting.
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Property editor for Step 5 (configure)
// ---------------------------------------------------------------------------

function PropEditor({
  prop,
  value,
  onChange,
}: {
  prop: DeviceProperty
  value: PreConnectProps[string] | undefined
  onChange: (spec: PreConnectProps[string]) => void
}) {
  if (prop.type === 'switch') {
    // Fall back to the driver's current snapshot value so the user sees the
    // existing state even if this prop hasn't been added to preConnectProps yet.
    const driverOn = prop.widgets.filter((w) => w.value === true).map((w) => w.name)
    const currentOn = (value as { on_elements: string[] } | undefined)?.on_elements ?? driverOn
    const rule = prop.switch_rule ?? '1ofmany'

    if (rule === '1ofmany' || rule === 'atmost1') {
      const selected = currentOn[0] ?? ''
      return (
        <select
          value={selected}
          onChange={(e) => onChange({ on_elements: e.target.value ? [e.target.value] : [] })}
          className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
            focus:outline-none focus:ring-1 focus:ring-accent"
        >
          {rule === 'atmost1' && <option value="">— none —</option>}
          {prop.widgets.map((w) => (
            <option key={w.name} value={w.name}>
              {w.label}
            </option>
          ))}
        </select>
      )
    }

    // nofmany — checkboxes
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {prop.widgets.map((w) => {
          const checked = currentOn.includes(w.name)
          return (
            <label key={w.name} className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => {
                  const next = e.target.checked
                    ? [...currentOn, w.name]
                    : currentOn.filter((n) => n !== w.name)
                  onChange({ on_elements: next })
                }}
                className="accent-accent"
              />
              {w.label}
            </label>
          )
        })}
      </div>
    )
  }

  if (prop.type === 'number') {
    const vals = (value as { values: Record<string, string | number> } | undefined)?.values ?? {}
    return (
      <div className="flex flex-wrap gap-3">
        {prop.widgets.map((w) => (
          <div key={w.name} className="flex flex-col gap-0.5">
            <span className="text-xs text-slate-500">{w.label}</span>
            <Input
              type="number"
              min={w.min}
              max={w.max}
              step={w.step}
              value={vals[w.name] ?? (w.value as number) ?? 0}
              onChange={(e) =>
                onChange({ values: { ...vals, [w.name]: parseFloat(e.target.value) || 0 } })
              }
              className="w-32"
            />
          </div>
        ))}
      </div>
    )
  }

  if (prop.type === 'text') {
    const vals = (value as { values: Record<string, string | number> } | undefined)?.values ?? {}
    return (
      <div className="flex flex-col gap-2">
        {prop.widgets.map((w) => (
          <div key={w.name} className="flex flex-col gap-0.5">
            {prop.widgets.length > 1 && (
              <span className="text-xs text-slate-500">{w.label}</span>
            )}
            <Input
              placeholder={w.label}
              value={(vals[w.name] as string) ?? (w.value as string) ?? ''}
              onChange={(e) => onChange({ values: { ...vals, [w.name]: e.target.value } })}
            />
          </div>
        ))}
      </div>
    )
  }

  return null
}

// Step 5 — configure driver properties and connect
function ConfigureStep({
  kind,
  driver,
  properties,
  preConnectProps,
  onPreConnectPropsChange,
  onBack,
  onConnect,
  connecting,
  error,
  discoveredDeviceNames = [],
}: {
  kind: DeviceKind
  driver: DriverEntry | null
  properties: DeviceProperty[]
  preConnectProps: PreConnectProps
  onPreConnectPropsChange: (props: PreConnectProps) => void
  onBack: () => void
  onConnect: () => void
  connecting: boolean
  error: string | null
  discoveredDeviceNames?: string[]
}) {
  // Only show writable properties that aren't CONNECTION itself
  const editable = properties.filter(
    (p) => p.name !== 'CONNECTION' && p.permission !== 'ro' && p.type !== 'blob',
  )

  // Group by group name
  const groups: Record<string, DeviceProperty[]> = {}
  for (const p of editable) {
    if (!groups[p.group]) groups[p.group] = []
    groups[p.group].push(p)
  }

  const handlePropChange = (propName: string, spec: PreConnectProps[string]) => {
    onPreConnectPropsChange({ ...preConnectProps, [propName]: spec })
  }

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{KIND_LABELS[kind]}</span>
        {driver && (
          <>
            {' · '}
            <span className="text-slate-300">{driver.label}</span>
          </>
        )}
        {' · '}Configure before connecting
      </p>

      {editable.length === 0 ? (
        <p className="text-sm text-slate-500 mb-4">No configurable properties. Click Connect to proceed.</p>
      ) : (
        <div className="flex flex-col gap-6 mb-4 max-h-80 overflow-y-auto pr-1">
          {Object.entries(groups).map(([group, props]) => (
            <div key={group}>
              {group && (
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
                  {group}
                </p>
              )}
              <div className="flex flex-col gap-3">
                {props.map((prop) => (
                  <div key={prop.name} className="flex flex-col gap-1">
                    <label className="text-xs text-slate-400">{prop.label || prop.name}</label>
                    <PropEditor
                      prop={prop}
                      value={preConnectProps[prop.name]}
                      onChange={(spec) => handlePropChange(prop.name, spec)}
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {discoveredDeviceNames.length > 1 && (
        <div className="bg-amber-950/30 border border-amber-700/40 rounded px-3 py-2 mb-3">
          <p className="text-xs text-amber-400 font-medium mb-1">
            {discoveredDeviceNames.length} cameras found on this driver
          </p>
          <p className="text-xs text-amber-300/80 mb-2">
            Connect will register the first one. Add the others by repeating
            "Load driver" with each name below:
          </p>
          <ul className="flex flex-col gap-0.5">
            {discoveredDeviceNames.map((name) => (
              <li key={name} className="text-xs font-mono text-amber-200 select-all">{name}</li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2 mb-3">{error}</p>
      )}

      <Button
        type="button"
        disabled={connecting}
        className="self-start"
        onClick={onConnect}
      >
        <Plug size={14} className="mr-2" />
        {connecting ? 'Connecting…' : 'Connect'}
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Connected device row
// ---------------------------------------------------------------------------

function DeviceRow({
  d,
  propertiesDeviceId,
  onToggleProperties,
  onDisconnect,
  onReconnect,
  onRemove,
  isCompanion = false,
}: {
  d: ConnectedDevice
  propertiesDeviceId: string | null
  onToggleProperties: (id: string) => void
  onDisconnect: (id: string) => void
  onReconnect: (id: string) => void
  onRemove: (id: string) => void
  isCompanion?: boolean
}) {
  return (
    <div
      className={[
        'flex items-center justify-between bg-surface-raised border rounded px-4 py-3 cursor-pointer transition-colors',
        d.state === 'disconnected' ? 'opacity-60' : '',
        isCompanion ? 'border-l-2 border-l-accent/30' : '',
        propertiesDeviceId === d.device_id
          ? 'border-accent'
          : 'border-surface-border hover:border-slate-600',
      ].join(' ')}
      onClick={() => onToggleProperties(d.device_id)}
    >
      <div className="flex items-center gap-3">
        <span className={isCompanion ? 'text-slate-600' : 'text-slate-500'}>
          <KindIcon kind={d.kind} size={16} />
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-medium text-slate-200">{d.device_id}</span>
          <span className="text-xs text-slate-500">
            {KIND_LABELS[d.kind] ?? d.kind}
            {isCompanion && <span className="ml-1 text-slate-600">· auto-discovered</span>}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <StateBadge state={d.state} />
        {d.state === 'disconnected' ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onReconnect(d.device_id) }}
            title="Reconnect"
          >
            <Link2 size={14} className="text-slate-400" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onDisconnect(d.device_id) }}
            title="Disconnect (keep registered)"
          >
            <PlugZap size={14} className="text-slate-400" />
          </Button>
        )}
        {!isCompanion && (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onRemove(d.device_id) }}
            title="Remove device"
          >
            <Trash2 size={14} className="text-slate-500" />
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function Equipment() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)

  const [step, setStep] = useState<WizardStep>('type')
  const [selectedKind, setSelectedKind] = useState<DeviceKind>('camera')
  const [selectedManufacturer, setSelectedManufacturer] = useState<string | null>(null)
  const [selectedDriver, setSelectedDriver] = useState<DriverEntry | null>(null)
  const [drivers, setDrivers] = useState<DriverEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loadingDriver, setLoadingDriver] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [propertiesDeviceId, setPropertiesDeviceId] = useState<string | null>(null)

  // Two-phase state
  const [driverProperties, setDriverProperties] = useState<DeviceProperty[]>([])
  const [preConnectProps, setPreConnectProps] = useState<PreConnectProps>({})
  const [pendingConnect, setPendingConnect] = useState<{
    deviceName: string
    executable: string
    deviceId: string
  } | null>(null)
  // All device names announced by the loaded driver (may be model-specific and/or multiple)
  const [discoveredDeviceNames, setDiscoveredDeviceNames] = useState<string[]>([])

  const refresh = () => {
    api.devices.connected().then(setConnectedDevices).catch(console.error)
  }

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step === 'type') return
    setDrivers([])
    api.indi.drivers(selectedKind).then(setDrivers).catch(() => setDrivers([]))
  }, [selectedKind, step])

  const handleSelectKind = (kind: DeviceKind) => {
    setSelectedKind(kind)
    setSelectedManufacturer(null)
    setSelectedDriver(null)
    setError(null)
    setStep('manufacturer')
  }

  const handleSelectManufacturer = (manufacturer: string | null) => {
    setSelectedManufacturer(manufacturer)
    setSelectedDriver(null)
    setError(null)
    if (manufacturer === null) {
      setStep('confirm')
    } else {
      setStep('model')
    }
  }

  const handleSelectModel = (driver: DriverEntry) => {
    setSelectedDriver(driver)
    setError(null)
    setStep('confirm')
  }

  const handleBack = () => {
    setError(null)
    if (step === 'configure') {
      setStep('confirm')
    } else if (step === 'confirm' && selectedManufacturer === null) {
      setStep('manufacturer')
    } else if (step === 'confirm') {
      setStep('model')
    } else if (step === 'model') {
      setStep('manufacturer')
    } else {
      setStep('type')
    }
  }

  const handleLoadDriver = async (deviceName: string, executable: string, deviceId: string) => {
    setError(null)
    setLoadingDriver(true)
    try {
      const result = await api.indi.loadDriver(executable, deviceName)
      // Use the actual announced device name (may differ from catalog, e.g. "ZWO CCD ASI294MC Pro")
      const resolvedName = result.device_names?.[0] ?? deviceName
      setDiscoveredDeviceNames(result.device_names ?? [])
      setDriverProperties(result.properties)
      setPreConnectProps({})
      setPendingConnect({ deviceName: resolvedName, executable, deviceId })
      setStep('configure')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoadingDriver(false)
    }
  }

  const handleConnect = async () => {
    if (!pendingConnect) return
    setError(null)
    setConnecting(true)
    try {
      await api.devices.connect({
        device_id: pendingConnect.deviceId || undefined,
        kind: selectedKind,
        adapter_key: KIND_ADAPTER[selectedKind],
        params: {
          device_name: pendingConnect.deviceName,
          executable: pendingConnect.executable,
          pre_connect_props: preConnectProps,
        },
      })
      refresh()
      setStep('type')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async (deviceId: string) => {
    await api.devices.disconnect(deviceId).catch(console.error)
    refresh()
  }

  const handleReconnect = async (deviceId: string) => {
    await api.devices.reconnect(deviceId).catch(console.error)
    refresh()
  }

  const handleRemove = async (deviceId: string) => {
    await api.devices.remove(deviceId).catch(console.error)
    if (propertiesDeviceId === deviceId) setPropertiesDeviceId(null)
    refresh()
  }

  return (
    <>
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-slate-100">Equipment</h1>
        <Button variant="ghost" size="icon" onClick={refresh} title="Refresh">
          <RefreshCw size={15} />
        </Button>
      </div>

      {/* Connected devices */}
      <section className="mb-8">
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
          Connected
        </h2>
        {connectedDevices.length === 0 ? (
          <p className="text-sm text-slate-500">No devices connected.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {connectedDevices
              .filter((d: ConnectedDevice) => d.primary_id === null)
              .map((primary: ConnectedDevice) => {
                const companions = connectedDevices.filter(
                  (d: ConnectedDevice) => d.primary_id === primary.device_id
                )
                return (
                  <div key={primary.device_id} className="flex flex-col gap-1">
                    <DeviceRow
                      d={primary}
                      propertiesDeviceId={propertiesDeviceId}
                      onToggleProperties={(id) =>
                        setPropertiesDeviceId(propertiesDeviceId === id ? null : id)
                      }
                      onDisconnect={handleDisconnect}
                      onReconnect={handleReconnect}
                      onRemove={handleRemove}
                    />
                    {companions.map((c: ConnectedDevice) => (
                      <div key={c.device_id} className="ml-6 flex flex-col gap-1">
                        <DeviceRow
                          d={c}
                          propertiesDeviceId={propertiesDeviceId}
                          onToggleProperties={(id) =>
                            setPropertiesDeviceId(propertiesDeviceId === id ? null : id)
                          }
                          onDisconnect={handleDisconnect}
                          onReconnect={handleReconnect}
                          onRemove={handleRemove}
                          isCompanion
                        />
                      </div>
                    ))}
                  </div>
                )
              })}
          </div>
        )}
      </section>

      {/* Connect wizard */}
      <section>
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
          Connect device
        </h2>
        <div className="bg-surface-raised border border-surface-border rounded p-4">
          {step === 'type' && (
            <TypeStep onSelect={handleSelectKind} />
          )}
          {step === 'manufacturer' && (
            <ManufacturerStep
              kind={selectedKind}
              drivers={drivers}
              onSelect={handleSelectManufacturer}
              onBack={handleBack}
            />
          )}
          {step === 'model' && selectedManufacturer !== null && (
            <ModelStep
              kind={selectedKind}
              manufacturer={selectedManufacturer}
              drivers={drivers}
              onSelect={handleSelectModel}
              onBack={handleBack}
            />
          )}
          {step === 'confirm' && (
            <ConfirmStep
              kind={selectedKind}
              driver={selectedDriver}
              onBack={handleBack}
              onLoadDriver={handleLoadDriver}
              loading={loadingDriver}
              error={error}
            />
          )}
          {step === 'configure' && (
            <ConfigureStep
              kind={selectedKind}
              driver={selectedDriver}
              properties={driverProperties}
              preConnectProps={preConnectProps}
              onPreConnectPropsChange={setPreConnectProps}
              onBack={handleBack}
              onConnect={handleConnect}
              connecting={connecting}
              error={error}
              discoveredDeviceNames={discoveredDeviceNames}
            />
          )}
        </div>
      </section>
    </div>
    {propertiesDeviceId && (
      <DevicePropertiesPanel
        deviceId={propertiesDeviceId}
        onClose={() => setPropertiesDeviceId(null)}
      />
    )}
    </>
  )
}
