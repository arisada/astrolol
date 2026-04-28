import { useEffect, useRef, useState } from 'react'
import {
  Camera, ChevronLeft, CircleDot, Compass, Crosshair, Focus, Globe,
  Link2, LoaderPinwheel, MapPin, Pencil, Plug, PlugZap, Plus, RefreshCw,
  Telescope, Trash2, Wind,
} from 'lucide-react'
import { DmsInput } from '@/components/ui/dms-input'
import { api } from '@/api/client'
import type {
  ConnectedDevice, DeviceKind, DeviceProperty, DriverEntry,
  EquipmentItem, EquipmentItemType, PreConnectProps,
} from '@/api/types'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type WizardStep = 'type' | 'manufacturer' | 'model' | 'loading' | 'manual' | 'configure'

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
  if (kind === 'filter_wheel') return <LoaderPinwheel size={size} />
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

// Step for "Enter manually" — only needs executable; device name is discovered after loading
function ManualStep({
  kind,
  onBack,
  onLoadDriver,
  loading,
  error,
}: {
  kind: DeviceKind
  onBack: () => void
  onLoadDriver: (deviceName: string, executable: string) => void
  loading: boolean
  error: string | null
}) {
  const [executable, setExecutable] = useState('')
  const [deviceNameHint, setDeviceNameHint] = useState('')

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{KIND_LABELS[kind]}</span>
        {' · '}Enter driver manually
      </p>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            Driver executable <span className="text-status-error">*</span>
          </label>
          <Input
            placeholder="e.g. indi_asi_ccd"
            value={executable}
            onChange={(e) => setExecutable(e.target.value)}
            autoFocus
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            INDI device name hint
            <span className="ml-2 text-slate-600">(optional — leave blank to auto-discover)</span>
          </label>
          <Input
            placeholder="e.g. ZWO CCD ASI294MC Pro"
            value={deviceNameHint}
            onChange={(e) => setDeviceNameHint(e.target.value)}
          />
        </div>

        {error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
        )}

        <Button
          type="button"
          disabled={!executable.trim() || loading}
          className="self-start"
          onClick={() => onLoadDriver(deviceNameHint.trim(), executable.trim())}
        >
          <Plug size={14} className="mr-2" />
          {loading ? 'Loading driver…' : 'Load driver'}
        </Button>
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

// Step — configure driver properties and connect
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
  selectedDeviceName,
  onSelectDeviceName,
  deviceId,
  onDeviceIdChange,
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
  selectedDeviceName: string
  onSelectDeviceName: (name: string) => void
  deviceId: string
  onDeviceIdChange: (id: string) => void
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

  const deviceIdInvalid = deviceId !== '' && !DEVICE_ID_RE.test(deviceId)

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
        {' · '}Configure &amp; connect
      </p>

      {/* Device name — show picker if multiple, plain label if one */}
      <div className="flex flex-col gap-3 mb-4 pb-4 border-b border-surface-border">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">INDI device name</label>
          {discoveredDeviceNames.length > 1 ? (
            <select
              value={selectedDeviceName}
              onChange={(e) => onSelectDeviceName(e.target.value)}
              className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {discoveredDeviceNames.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-slate-200 bg-surface border border-surface-border rounded px-3 py-1.5">
              {selectedDeviceName || <span className="text-slate-600 italic">discovering…</span>}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            Device ID
            <span className="ml-2 text-slate-600">(leave blank to auto-generate)</span>
          </label>
          <Input
            placeholder={suggestDeviceId(kind, driver) || 'auto-generated'}
            value={deviceId}
            onChange={(e) => onDeviceIdChange(e.target.value)}
            className={deviceIdInvalid ? 'border-status-error focus-visible:ring-status-error' : ''}
          />
          {deviceIdInvalid && (
            <p className="text-xs text-status-error">
              Only letters, digits, hyphens, and underscores. Must start with a letter or digit (max 64 chars).
            </p>
          )}
        </div>
      </div>

      {editable.length === 0 ? (
        <p className="text-sm text-slate-500 mb-4">No configurable properties. Click Connect to proceed.</p>
      ) : (
        <div className="flex flex-col gap-6 mb-4 max-h-64 overflow-y-auto pr-1">
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

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2 mb-3">{error}</p>
      )}

      <Button
        type="button"
        disabled={connecting || !selectedDeviceName || deviceIdInvalid}
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
// Inventory helpers
// ---------------------------------------------------------------------------

const ITEM_TYPE_LABELS: Record<EquipmentItemType, string> = {
  site: 'Observation Site',
  mount: 'Mount',
  ota: 'Telescope / OTA',
  camera: 'Camera',
  filter_wheel: 'Filter Wheel',
  focuser: 'Focuser',
  rotator: 'Rotator',
  gps: 'GPS',
}

function ItemTypeIcon({ type, size = 16 }: { type: EquipmentItemType; size?: number }) {
  if (type === 'site') return <MapPin size={size} />
  if (type === 'mount') return <Compass size={size} />
  if (type === 'ota') return <Telescope size={size} />
  if (type === 'camera') return <Camera size={size} />
  if (type === 'filter_wheel') return <LoaderPinwheel size={size} />
  if (type === 'focuser') return <Focus size={size} />
  if (type === 'rotator') return <CircleDot size={size} />
  if (type === 'gps') return <Globe size={size} />
  return <Wind size={size} />
}

const ITEM_EXAMPLE_NAMES: Record<EquipmentItemType, string> = {
  site: "Bob's backyard",
  mount: 'Sky-Watcher EQ6-R Pro',
  ota: 'William Optics RedCat 51',
  camera: 'ZWO ASI2600MC Pro',
  filter_wheel: 'ZWO EFW 8-position',
  focuser: 'Pegasus FocusCube 3',
  rotator: 'Pegasus Falcon Rotator',
  gps: 'RaspiGPS',
}

function itemSubtitle(item: EquipmentItem): string {
  if (item.type === 'site') return `${item.latitude.toFixed(4)}° / ${item.longitude.toFixed(4)}° — ${item.altitude} m`
  if (item.type === 'ota') return `${item.focal_length} mm  f/${(item.focal_length / item.aperture).toFixed(1)}`
  if (item.type === 'camera' && item.pixel_size_um) return `${item.indi_device_name ?? item.indi_driver ?? ''}  ·  ${item.pixel_size_um} µm`
  if ('indi_device_name' in item) return item.indi_device_name ?? item.indi_driver ?? ''
  return ''
}

// ---------------------------------------------------------------------------
// Timezone selector
// ---------------------------------------------------------------------------

function TimezoneSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [zones, setZones] = useState<string[]>([])

  useEffect(() => {
    api.inventory.timezones().then(({ timezones }) => setZones(timezones)).catch(() => {})
  }, [])

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
        focus:outline-none focus:ring-1 focus:ring-accent w-full"
    >
      {zones.length === 0 && <option value={value}>{value || 'UTC'}</option>}
      {zones.map((z) => (
        <option key={z} value={z}>{z}</option>
      ))}
    </select>
  )
}

// ---------------------------------------------------------------------------
// Inventory form
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function emptyForm(type: EquipmentItemType): Omit<EquipmentItem, 'id'> {
  const r: Record<string, any> = { type, name: '' }
  if (type === 'site') Object.assign(r, { latitude: 0, longitude: 0, altitude: 0, timezone: 'UTC' })
  else if (type === 'ota') Object.assign(r, { focal_length: 500, aperture: 80 })
  else if (type === 'camera') Object.assign(r, { indi_driver: null, indi_device_name: null, pixel_size_um: null })
  else if (type === 'filter_wheel') Object.assign(r, { indi_driver: null, indi_device_name: null, filter_names: [] })
  else Object.assign(r, { indi_driver: null, indi_device_name: null })
  return r as Omit<EquipmentItem, 'id'>
}

type FieldValue = string | number | null | string[]

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-xs text-slate-500">{label}</label>
      {children}
    </div>
  )
}

function ItemForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: EquipmentItem | Omit<EquipmentItem, 'id'>
  onSave: (item: EquipmentItem | Omit<EquipmentItem, 'id'>) => Promise<void>
  onCancel: () => void
}) {
  const [form, setForm] = useState<EquipmentItem | Omit<EquipmentItem, 'id'>>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => { nameRef.current?.focus() }, [])

  // Pre-fill system timezone for new site items
  useEffect(() => {
    if (initial.type === 'site' && !('id' in initial)) {
      api.inventory.timezones()
        .then(({ system_default }) => {
          setForm((prev) => ({ ...prev, timezone: system_default }))
        })
        .catch(() => {})
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (key: string, value: FieldValue) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave(form)
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const type = form.type as EquipmentItemType

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-4"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-slate-400 uppercase tracking-wider">
        <ItemTypeIcon type={type} size={13} />
        {ITEM_TYPE_LABELS[type]}
      </div>

      <FieldRow label="Name">
        <input
          ref={nameRef}
          required
          value={(form as {name: string}).name}
          onChange={(e) => set('name', e.target.value)}
          placeholder={`e.g. ${ITEM_EXAMPLE_NAMES[type]}`}
          className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
            focus:outline-none focus:ring-1 focus:ring-accent w-full"
        />
      </FieldRow>

      {/* INDI fields — for all INDI device types */}
      {type !== 'site' && type !== 'ota' && (
        <>
          <FieldRow label="INDI driver">
            <input
              value={(form as { indi_driver: string | null }).indi_driver ?? ''}
              onChange={(e) => set('indi_driver', e.target.value || null)}
              placeholder="e.g. indi_eqmod_telescope"
              className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
          <FieldRow label="INDI device name">
            <input
              value={(form as { indi_device_name: string | null }).indi_device_name ?? ''}
              onChange={(e) => set('indi_device_name', e.target.value || null)}
              placeholder="Announced by driver, e.g. EQ6 Mount"
              className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
        </>
      )}

      {/* Site fields */}
      {type === 'site' && (
        <>
          <FieldRow label="Latitude">
            <DmsInput
              value={(form as { latitude: number }).latitude}
              onChange={(v) => set('latitude', v)}
              mode="lat"
            />
          </FieldRow>
          <FieldRow label="Longitude">
            <DmsInput
              value={(form as { longitude: number }).longitude}
              onChange={(v) => set('longitude', v)}
              mode="lon"
            />
          </FieldRow>
          <div className="grid grid-cols-2 gap-3">
            <FieldRow label="Altitude (m)">
              <input
                type="number" step="1"
                value={(form as { altitude: number }).altitude}
                onChange={(e) => set('altitude', parseFloat(e.target.value) || 0)}
                className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                  focus:outline-none focus:ring-1 focus:ring-accent w-full"
              />
            </FieldRow>
            <FieldRow label="Timezone">
              <TimezoneSelect
                value={(form as { timezone: string }).timezone}
                onChange={(v) => set('timezone', v)}
              />
            </FieldRow>
          </div>
        </>
      )}

      {/* OTA fields */}
      {type === 'ota' && (
        <div className="grid grid-cols-2 gap-3">
          <FieldRow label="Focal length (mm)">
            <input
              type="number" step="1" min="0"
              value={(form as { focal_length: number }).focal_length}
              onChange={(e) => set('focal_length', parseFloat(e.target.value) || 0)}
              className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
          <FieldRow label="Aperture (mm)">
            <input
              type="number" step="1" min="0"
              value={(form as { aperture: number }).aperture}
              onChange={(e) => set('aperture', parseFloat(e.target.value) || 0)}
              className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
        </div>
      )}

      {/* Camera extra field */}
      {type === 'camera' && (
        <FieldRow label="Pixel size (µm)">
          <input
            type="number" step="0.01" min="0"
            value={(form as { pixel_size_um: number | null }).pixel_size_um ?? ''}
            onChange={(e) => set('pixel_size_um', e.target.value ? parseFloat(e.target.value) : null)}
            placeholder="e.g. 3.76"
            className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
              focus:outline-none focus:ring-1 focus:ring-accent w-40"
          />
        </FieldRow>
      )}

      {/* Filter wheel extra field */}
      {type === 'filter_wheel' && (
        <FieldRow label="Filter names (comma-separated)">
          <input
            value={(form as { filter_names: string[] }).filter_names.join(', ')}
            onChange={(e) =>
              set('filter_names', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
            }
            placeholder="L, R, G, B, Ha, OIII, SII"
            className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
              focus:outline-none focus:ring-1 focus:ring-accent w-full"
          />
        </FieldRow>
      )}

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Inventory section
// ---------------------------------------------------------------------------

function InventorySection() {
  const [items, setItems] = useState<EquipmentItem[]>([])
  const [creating, setCreating] = useState<EquipmentItemType | null>(null)
  const [editing, setEditing] = useState<string | null>(null)  // item id
  const [showTypeMenu, setShowTypeMenu] = useState(false)

  const load = () => api.inventory.list().then(setItems).catch(console.error)
  useEffect(() => { load() }, [])

  const handleCreate = async (item: EquipmentItem | Omit<EquipmentItem, 'id'>) => {
    await api.inventory.create(item as Omit<EquipmentItem, 'id'>)
    setCreating(null)
    load()
  }

  const handleUpdate = async (item: EquipmentItem | Omit<EquipmentItem, 'id'>) => {
    await api.inventory.update(item as EquipmentItem)
    setEditing(null)
    load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Remove this item from inventory?')) return
    await api.inventory.delete(id)
    if (editing === id) setEditing(null)
    load()
  }

  // Group items by type for display
  const grouped = items.reduce<Partial<Record<EquipmentItemType, EquipmentItem[]>>>((acc, item) => {
    const t = item.type as EquipmentItemType
    if (!acc[t]) acc[t] = []
    acc[t]!.push(item)
    return acc
  }, {})

  const allTypes: EquipmentItemType[] = ['site', 'mount', 'ota', 'camera', 'filter_wheel', 'focuser', 'rotator', 'gps']

  return (
    <div className="flex flex-col gap-6">
      {/* Add button */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {items.length === 0 ? 'Your equipment inventory is empty.' : `${items.length} item${items.length !== 1 ? 's' : ''}`}
        </p>
        <div className="relative">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowTypeMenu((v) => !v)}
          >
            <Plus size={14} className="mr-1.5" />
            Add equipment
          </Button>
          {showTypeMenu && (
            <div className="absolute right-0 top-full mt-1 z-10 bg-surface border border-surface-border rounded shadow-lg min-w-44">
              {allTypes.map((t) => (
                <button
                  key={t}
                  className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-300
                    hover:bg-surface-raised transition-colors text-left"
                  onClick={() => {
                    setCreating(t)
                    setEditing(null)
                    setShowTypeMenu(false)
                  }}
                >
                  <ItemTypeIcon type={t} size={13} />
                  {ITEM_TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Create form */}
      {creating && (
        <ItemForm
          initial={emptyForm(creating)}
          onSave={handleCreate}
          onCancel={() => setCreating(null)}
        />
      )}

      {/* Item list grouped by type */}
      {allTypes.map((type) => {
        const group = grouped[type]
        if (!group?.length) return null
        return (
          <div key={type}>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <ItemTypeIcon type={type} size={11} />
              {ITEM_TYPE_LABELS[type]}
            </h3>
            <div className="flex flex-col gap-2">
              {group.map((item) => (
                <div key={item.id}>
                  {editing === item.id ? (
                    <ItemForm
                      initial={item}
                      onSave={handleUpdate}
                      onCancel={() => setEditing(null)}
                    />
                  ) : (
                    <div className="flex items-center justify-between bg-surface-raised border border-surface-border rounded px-4 py-3 group">
                      <div>
                        <p className="text-sm font-medium text-slate-200">{item.name}</p>
                        {itemSubtitle(item) && (
                          <p className="text-xs text-slate-500 mt-0.5">{itemSubtitle(item)}</p>
                        )}
                      </div>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => { setEditing(item.id); setCreating(null) }}
                          title="Edit"
                        >
                          <Pencil size={13} className="text-slate-400" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(item.id)}
                          title="Delete"
                        >
                          <Trash2 size={13} className="text-slate-500" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {items.length === 0 && !creating && (
        <p className="text-sm text-slate-600 text-center py-8">
          Click "Add equipment" to build your inventory.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function Equipment() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)

  const [activeTab, setActiveTab] = useState<'connections' | 'inventory'>('connections')

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
  } | null>(null)
  const [pendingDeviceId, setPendingDeviceId] = useState('')
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
      setStep('manual')
    } else {
      setStep('model')
    }
  }

  const handleSelectModel = (driver: DriverEntry) => {
    setSelectedDriver(driver)
    setError(null)
    // Auto-load: skip confirm step, device name comes from the catalog entry
    handleLoadDriver(driver.device_name, driver.executable)
  }

  const handleBack = () => {
    setError(null)
    if (step === 'configure') {
      // Back from configure: return to model list (catalog) or manual entry
      if (selectedManufacturer === null) {
        setStep('manual')
      } else {
        setStep('model')
      }
    } else if (step === 'manual') {
      setStep('manufacturer')
    } else if (step === 'loading') {
      // Can't really go back during loading; go to model list
      setStep(selectedManufacturer === null ? 'manufacturer' : 'model')
    } else if (step === 'model') {
      setStep('manufacturer')
    } else {
      setStep('type')
    }
  }

  const handleLoadDriver = async (deviceName: string, executable: string) => {
    setError(null)
    setLoadingDriver(true)
    setStep('loading')
    try {
      const result = await api.indi.loadDriver(executable, deviceName)
      const names = result.device_names ?? []
      const resolvedName = names[0] ?? deviceName
      setDiscoveredDeviceNames(names)
      setDriverProperties(result.properties)
      setPreConnectProps({})
      setPendingConnect({ deviceName: resolvedName, executable })
      setPendingDeviceId(suggestDeviceId(selectedKind, selectedDriver))
      setStep('configure')
    } catch (err) {
      setError((err as Error).message)
      // Return to the appropriate step on error
      setStep(selectedManufacturer === null ? 'manual' : 'model')
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
        device_id: pendingDeviceId || undefined,
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
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-slate-100">Equipment</h1>
        {activeTab === 'connections' && (
          <Button variant="ghost" size="icon" onClick={refresh} title="Refresh">
            <RefreshCw size={15} />
          </Button>
        )}
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-6 border-b border-surface-border">
        {(['connections', 'inventory'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={[
              'px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px',
              activeTab === tab
                ? 'border-accent text-slate-100'
                : 'border-transparent text-slate-500 hover:text-slate-300',
            ].join(' ')}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Inventory tab */}
      {activeTab === 'inventory' && <InventorySection />}

      {/* Connections tab */}
      {activeTab === 'connections' && <>

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
          Load driver
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
          {step === 'loading' && (
            <div className="flex items-center gap-3 py-6 text-slate-400 text-sm">
              <RefreshCw size={16} className="animate-spin shrink-0" />
              Loading driver…
            </div>
          )}
          {step === 'manual' && (
            <ManualStep
              kind={selectedKind}
              onBack={handleBack}
              onLoadDriver={handleLoadDriver}
              loading={loadingDriver}
              error={error}
            />
          )}
          {step === 'configure' && pendingConnect && (
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
              selectedDeviceName={pendingConnect.deviceName}
              onSelectDeviceName={(name) => setPendingConnect({ ...pendingConnect, deviceName: name })}
              deviceId={pendingDeviceId}
              onDeviceIdChange={setPendingDeviceId}
            />
          )}
        </div>
      </section>
      </>}
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
