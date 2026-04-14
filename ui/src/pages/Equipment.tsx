import { useEffect, useState } from 'react'
import { Camera, ChevronLeft, Crosshair, Plug, PlugZap, RefreshCw, Telescope } from 'lucide-react'
import { api } from '@/api/client'
import type { ConnectedDevice, DeviceKind, DriverEntry } from '@/api/types'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type WizardStep = 'type' | 'manufacturer' | 'model' | 'confirm'

const DEVICE_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/

function suggestDeviceId(kind: DeviceKind, driver: DriverEntry | null): string {
  if (!driver) return ''
  // Prefer executable stem (strip indi_ prefix) as it's always URL-safe
  const raw = driver.executable.replace(/^indi_/, '') || driver.manufacturer
  const slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '').slice(0, 40)
  return slug ? `${kind}_${slug}` : ''
}

const KIND_LABELS: Record<DeviceKind, string> = {
  camera: 'Camera',
  mount: 'Mount',
  focuser: 'Focuser',
}

const KIND_ADAPTER: Record<DeviceKind, string> = {
  camera: 'indi_camera',
  mount: 'indi_mount',
  focuser: 'indi_focuser',
}

function KindIcon({ kind, size = 28 }: { kind: DeviceKind; size?: number }) {
  if (kind === 'camera') return <Camera size={size} />
  if (kind === 'mount') return <Telescope size={size} />
  return <Crosshair size={size} />
}

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

// Step 1 — choose device type
function TypeStep({ onSelect }: { onSelect: (kind: DeviceKind) => void }) {
  const kinds: DeviceKind[] = ['camera', 'mount', 'focuser']
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
        {/* Always offer a manual path */}
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

const BAUD_RATES = ['9600', '19200', '38400', '57600', '115200', '230400']

// Serial connection fields shown for mount and focuser (not USB cameras)
function SerialFields({
  devicePort,
  baudRate,
  onPortChange,
  onBaudChange,
}: {
  devicePort: string
  baudRate: string
  onPortChange: (v: string) => void
  onBaudChange: (v: string) => void
}) {
  return (
    <div className="flex flex-col gap-3 pt-2 border-t border-surface-border">
      <p className="text-xs text-slate-500">Serial / USB-serial connection</p>
      <div className="flex gap-3">
        <div className="flex flex-col gap-1 flex-1">
          <label className="text-xs text-slate-400">Device port</label>
          <Input
            placeholder="/dev/ttyUSB0"
            value={devicePort}
            onChange={(e) => onPortChange(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1 w-36">
          <label className="text-xs text-slate-400">Baud rate</label>
          <select
            value={baudRate}
            onChange={(e) => onBaudChange(e.target.value)}
            className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
              focus:outline-none focus:ring-1 focus:ring-accent h-9"
          >
            <option value="">Driver default</option>
            {BAUD_RATES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
      </div>
      <p className="text-xs text-slate-600">
        Run <code className="text-slate-500">ls /dev/ttyUSB* /dev/ttyACM*</code> to find your port.
        Most mounts use 9600 baud (EQ8 and some others use 115200).
      </p>
    </div>
  )
}

// Step 4 — confirm and connect
function ConfirmStep({
  kind,
  driver,
  onBack,
  onConnect,
  connecting,
  error,
}: {
  kind: DeviceKind
  driver: DriverEntry | null  // null = manual entry
  onBack: () => void
  onConnect: (deviceName: string, executable: string, deviceId: string, devicePort: string, baudRate: string) => void
  connecting: boolean
  error: string | null
}) {
  const [deviceName, setDeviceName] = useState(driver?.device_name ?? '')
  const [executable, setExecutable] = useState(driver?.executable ?? '')
  const [deviceId, setDeviceId] = useState(() => suggestDeviceId(kind, driver))
  const [devicePort, setDevicePort] = useState('')
  const [baudRate, setBaudRate] = useState('')

  const deviceIdInvalid = deviceId !== '' && !DEVICE_ID_RE.test(deviceId)
  const needsSerial = kind === 'mount' || kind === 'focuser'

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
        {/* INDI device name — pre-filled from catalog, editable */}
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

        {/* Driver executable — pre-filled from catalog, always editable */}
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

        {/* Device ID — suggested from driver, editable, validated */}
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

        {/* Serial connection — mounts and focusers only */}
        {needsSerial && (
          <SerialFields
            devicePort={devicePort}
            baudRate={baudRate}
            onPortChange={setDevicePort}
            onBaudChange={setBaudRate}
          />
        )}

        {error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
        )}

        <Button
          type="button"
          disabled={!deviceName || connecting || deviceIdInvalid}
          className="self-start"
          onClick={() => onConnect(deviceName, executable, deviceId, devicePort, baudRate)}
        >
          <Plug size={14} className="mr-2" />
          {connecting ? 'Connecting…' : 'Connect'}
        </Button>
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
  const [connecting, setConnecting] = useState(false)
  const [propertiesDeviceId, setPropertiesDeviceId] = useState<string | null>(null)

  const refresh = () => {
    api.devices.connected().then(setConnectedDevices).catch(console.error)
  }

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Load catalog whenever kind changes
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
      // Manual entry — skip model step
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
    if (step === 'confirm' && selectedManufacturer === null) {
      setStep('manufacturer')
    } else if (step === 'confirm') {
      setStep('model')
    } else if (step === 'model') {
      setStep('manufacturer')
    } else {
      setStep('type')
    }
  }

  const handleConnect = async (deviceName: string, executable: string, deviceId: string, devicePort: string, baudRate: string) => {
    setError(null)
    setConnecting(true)
    try {
      await api.devices.connect({
        device_id: deviceId || undefined,
        kind: selectedKind,
        adapter_key: KIND_ADAPTER[selectedKind],
        params: {
          device_name: deviceName,
          executable,
          ...(devicePort ? { device_port: devicePort } : {}),
          ...(baudRate  ? { device_baud_rate: baudRate }  : {}),
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
          <div className="flex flex-col gap-2">
            {connectedDevices.map((d: ConnectedDevice) => (
              <div
                key={d.device_id}
                className={[
                  'flex items-center justify-between bg-surface-raised border rounded px-4 py-3 cursor-pointer transition-colors',
                  propertiesDeviceId === d.device_id
                    ? 'border-accent'
                    : 'border-surface-border hover:border-slate-600',
                ].join(' ')}
                onClick={() =>
                  setPropertiesDeviceId(
                    propertiesDeviceId === d.device_id ? null : d.device_id
                  )
                }
              >
                <div className="flex items-center gap-3">
                  <span className="text-slate-500">
                    <KindIcon kind={d.kind} size={16} />
                  </span>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium text-slate-200">{d.device_id}</span>
                    <span className="text-xs text-slate-500">{d.adapter_key}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <StateBadge state={d.state} />
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => { e.stopPropagation(); handleDisconnect(d.device_id) }}
                    title="Disconnect"
                  >
                    <PlugZap size={14} className="text-slate-400" />
                  </Button>
                </div>
              </div>
            ))}
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
              onConnect={handleConnect}
              connecting={connecting}
              error={error ?? null}
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
