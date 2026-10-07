import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Camera, ChevronLeft, CircleDot, Compass, Crosshair, Focus, Globe,
  Link2, LoaderPinwheel, MapPin, PackagePlus, Pencil, Plug, PlugZap, Plus, RefreshCw,
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
import { Tabs } from '@/components/ui/tabs'

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type WizardStep = 'type' | 'source' | 'manufacturer' | 'model' | 'loading' | 'manual' | 'configure' | 'generic'

const DEVICE_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/

function suggestDeviceId(kind: DeviceKind, driver: DriverEntry | null): string {
  if (!driver) return ''
  const raw = driver.executable.replace(/^indi_/, '') || driver.manufacturer
  const slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '').slice(0, 40)
  return slug ? `${kind}_${slug}` : ''
}

const KIND_ADAPTER: Record<DeviceKind, string> = {
  camera: 'indi_camera',
  mount: 'indi_mount',
  focuser: 'indi_focuser',
  filter_wheel: 'indi_filter_wheel',
  rotator: 'indi_rotator',
  indi: 'indi_raw',
}

// DeviceKind -> the plural key GET /devices/available groups adapters under
const KIND_REGISTRY_KEY: Record<DeviceKind, string> = {
  camera: 'cameras',
  mount: 'mounts',
  focuser: 'focusers',
  filter_wheel: 'filter_wheels',
  rotator: 'rotators',
  indi: 'indi_raws',
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
  const { t } = useTranslation('equipment')
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-4 transition-colors"
    >
      <ChevronLeft size={14} /> {t('wizard.back')}
    </button>
  )
}

// Step 1 — choose device type
function TypeStep({ onSelect }: { onSelect: (kind: DeviceKind) => void }) {
  const { t } = useTranslation('equipment')
  const kinds: DeviceKind[] = ['camera', 'mount', 'focuser', 'filter_wheel']
  return (
    <div>
      <p className="text-xs text-slate-500 mb-4">{t('wizard.typeQuestion')}</p>
      <div className="grid grid-cols-2 gap-3">
        {kinds.map((kind) => (
          <button
            key={kind}
            onClick={() => onSelect(kind)}
            className="flex flex-col items-center gap-3 rounded-lg border border-surface-border bg-surface-raised px-4 py-6 text-slate-400 transition-all hover:border-accent hover:text-slate-100 hover:bg-surface-overlay"
          >
            <KindIcon kind={kind} size={32} />
            <span className="text-sm font-medium">{t(`kind.${kind}`)}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// Step 1b — INDI catalog vs. any other registered adapter (native drivers, simulators, …)
function SourceStep({
  kind,
  onChooseIndi,
  onChooseGeneric,
  onBack,
}: {
  kind: DeviceKind
  onChooseIndi: () => void
  onChooseGeneric: () => void
  onBack: () => void
}) {
  const { t } = useTranslation('equipment')
  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {' · '}{t('wizard.howConnected')}
      </p>
      <div className="flex flex-col gap-2">
        <button
          onClick={onChooseIndi}
          className="text-left rounded px-3 py-2.5 text-sm text-slate-300 border border-transparent hover:border-surface-border hover:bg-surface-raised transition-colors"
        >
          {t('wizard.browseIndi')}
          <span className="block text-xs text-slate-500 mt-0.5">
            {t('wizard.browseIndiHint')}
          </span>
        </button>
        <button
          onClick={onChooseGeneric}
          className="text-left rounded px-3 py-2.5 text-sm text-slate-300 border border-transparent hover:border-surface-border hover:bg-surface-raised transition-colors"
        >
          {t('wizard.otherAdapter')}
          <span className="block text-xs text-slate-500 mt-0.5">
            {t('wizard.otherAdapterHint')}
          </span>
        </button>
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
  const { t } = useTranslation('equipment')
  const manufacturers = [...new Set(drivers.map((d) => d.manufacturer))].sort()

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {' · '}{t('wizard.selectManufacturer')}
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
          {t('wizard.enterManually')}
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
  const { t } = useTranslation('equipment')
  const models = drivers.filter((d) => d.manufacturer === manufacturer)

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {' · '}
        <span className="text-slate-300">{manufacturer}</span>
        {' · '}{t('wizard.selectModel')}
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
  const { t } = useTranslation('equipment')
  const [executable, setExecutable] = useState('')
  const [deviceNameHint, setDeviceNameHint] = useState('')

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {' · '}{t('wizard.enterDriver')}
      </p>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            {t('wizard.executable')} <span className="text-status-error">*</span>
          </label>
          <Input
            placeholder={t('wizard.executablePlaceholder')}
            value={executable}
            onChange={(e) => setExecutable(e.target.value)}
            autoFocus
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            {t('wizard.deviceHint')}
            <span className="ml-2 text-slate-600">{t('wizard.deviceHintOptional')}</span>
          </label>
          <Input
            placeholder={t('wizard.deviceHintPlaceholder')}
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
          {loading ? t('wizard.loadingDriver') : t('wizard.loadDriver')}
        </Button>
      </div>
    </div>
  )
}

// Step for "Other adapter" — any adapter_key registered in the device registry
// (e.g. by a plugin) that isn't part of the INDI catalog flow above. Connect
// params are fully adapter-specific, so this collects them as raw JSON rather
// than assuming any particular shape.
function GenericAdapterStep({
  kind,
  adapterKeys,
  onBack,
  onConnect,
  connecting,
  error,
}: {
  kind: DeviceKind
  adapterKeys: string[]
  onBack: () => void
  onConnect: (adapterKey: string, deviceId: string, params: Record<string, unknown>) => void
  connecting: boolean
  error: string | null
}) {
  const { t } = useTranslation('equipment')
  const [adapterKey, setAdapterKey] = useState(adapterKeys[0] ?? '')
  const [deviceId, setDeviceId] = useState('')
  const [paramsText, setParamsText] = useState('{}')
  const [paramsError, setParamsError] = useState<string | null>(null)

  // adapterKeys arrives asynchronously (fetched after this step mounts), so the
  // useState initialiser above only ever sees the empty first render — keep
  // adapterKey in sync once the real list lands.
  useEffect(() => {
    if (adapterKeys.length > 0 && !adapterKeys.includes(adapterKey)) {
      setAdapterKey(adapterKeys[0])
    }
  }, [adapterKeys]) // eslint-disable-line react-hooks/exhaustive-deps

  // Pre-fill the JSON with whatever defaults the chosen adapter declares.
  useEffect(() => {
    if (!adapterKey) return
    let cancelled = false
    api.devices.adapterDefaults(kind, adapterKey)
      .then((d) => { if (!cancelled) setParamsText(JSON.stringify(d, null, 2)) })
      .catch(() => { if (!cancelled) setParamsText('{}') })
    return () => { cancelled = true }
  }, [kind, adapterKey])

  const deviceIdInvalid = deviceId !== '' && !DEVICE_ID_RE.test(deviceId)

  const handleConnect = () => {
    let params: Record<string, unknown>
    try {
      params = paramsText.trim() ? JSON.parse(paramsText) : {}
    } catch {
      setParamsError(t('wizard.paramsInvalid'))
      return
    }
    setParamsError(null)
    onConnect(adapterKey, deviceId, params)
  }

  if (adapterKeys.length === 0) {
    return (
      <div>
        <StepBack onClick={onBack} />
        <p className="text-sm text-slate-500">
          {t('wizard.noAdapters', { kind: t(`kind.${kind}`) })}
        </p>
      </div>
    )
  }

  return (
    <div>
      <StepBack onClick={onBack} />
      <p className="text-xs text-slate-500 mb-4">
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {' · '}{t('wizard.otherAdapter')}
      </p>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">{t('wizard.adapter')}</label>
          <select
            value={adapterKey}
            onChange={(e) => setAdapterKey(e.target.value)}
            className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
              focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          >
            {adapterKeys.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            {t('wizard.deviceId')}
            <span className="ml-2 text-slate-600">{t('wizard.deviceIdOptional')}</span>
          </label>
          <Input
            placeholder={t('wizard.autoGenerated')}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            className={deviceIdInvalid ? 'border-status-error focus-visible:ring-status-error' : ''}
          />
          {deviceIdInvalid && (
            <p className="text-xs text-status-error">
              {t('wizard.deviceIdInvalid')}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            {t('wizard.params')}
            <span className="ml-2 text-slate-600">{t('wizard.paramsHint', { example: '{"state_key": "rig1"}' })}</span>
          </label>
          <textarea
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
            rows={4}
            className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
              font-mono focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          />
          {paramsError && <p className="text-xs text-status-error">{paramsError}</p>}
        </div>

        {error && (
          <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
        )}

        <Button
          type="button"
          disabled={connecting || !adapterKey || deviceIdInvalid}
          className="self-start"
          onClick={handleConnect}
        >
          <Plug size={14} className="mr-2" />
          {connecting ? t('wizard.connecting') : t('wizard.connect')}
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
  const { t } = useTranslation('equipment')
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
          className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
            focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
        >
          {rule === 'atmost1' && <option value="">{t('wizard.none')}</option>}
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
  const { t } = useTranslation('equipment')
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
        <span className="text-slate-300 font-medium">{t(`kind.${kind}`)}</span>
        {driver && (
          <>
            {' · '}
            <span className="text-slate-300">{driver.label}</span>
          </>
        )}
        {' · '}{t('wizard.configure')}
      </p>

      {/* Device name — show picker if multiple, plain label if one */}
      <div className="flex flex-col gap-3 mb-4 pb-4 border-b border-surface-border">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">{t('wizard.indiName')}</label>
          {discoveredDeviceNames.length > 1 ? (
            <select
              value={selectedDeviceName}
              onChange={(e) => onSelectDeviceName(e.target.value)}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            >
              {discoveredDeviceNames.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-slate-200 bg-surface border border-surface-border rounded-lg px-3 py-1.5">
              {selectedDeviceName || <span className="text-slate-600 italic">{t('wizard.discovering')}</span>}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400">
            {t('wizard.deviceId')}
            <span className="ml-2 text-slate-600">{t('wizard.deviceIdOptional')}</span>
          </label>
          <Input
            placeholder={suggestDeviceId(kind, driver) || t('wizard.autoGenerated')}
            value={deviceId}
            onChange={(e) => onDeviceIdChange(e.target.value)}
            className={deviceIdInvalid ? 'border-status-error focus-visible:ring-status-error' : ''}
          />
          {deviceIdInvalid && (
            <p className="text-xs text-status-error">
              {t('wizard.deviceIdInvalid')}
            </p>
          )}
        </div>
      </div>

      {editable.length === 0 ? (
        <p className="text-sm text-slate-500 mb-4">{t('wizard.noProps')}</p>
      ) : (
        <div className="flex flex-col gap-6 mb-4 max-h-64 overflow-y-auto pr-1">
          {Object.entries(groups).map(([group, props]) => (
            <div key={group}>
              {group && (
                <p className="font-medium text-slate-500 label-caps mb-2">
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
        {connecting ? t('wizard.connecting') : t('wizard.connect')}
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
  onImport,
  isCompanion = false,
}: {
  d: ConnectedDevice
  propertiesDeviceId: string | null
  onToggleProperties: (id: string) => void
  onDisconnect: (id: string) => void
  onReconnect: (id: string) => void
  onRemove: (id: string) => void
  onImport: () => void
  isCompanion?: boolean
}) {
  const { t } = useTranslation('equipment')
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
            {t(`kind.${d.kind}`, { defaultValue: d.kind })}
            {isCompanion && <span className="ml-1 text-slate-600">· {t('device.autoDiscovered')}</span>}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <StateBadge state={d.state} />
        <Button
          variant="ghost"
          size="icon"
          onClick={(e) => { e.stopPropagation(); onImport() }}
          title={t('device.import')}
        >
          <PackagePlus size={14} className="text-slate-400" />
        </Button>
        {d.state === 'disconnected' ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onReconnect(d.device_id) }}
            title={t('device.reconnect')}
          >
            <Link2 size={14} className="text-slate-400" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onDisconnect(d.device_id) }}
            title={t('device.disconnect')}
          >
            <PlugZap size={14} className="text-slate-400" />
          </Button>
        )}
        {!isCompanion && (
          <Button
            variant="ghost"
            size="icon"
            onClick={(e) => { e.stopPropagation(); onRemove(d.device_id) }}
            title={t('device.remove')}
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
      className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
        focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
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
  else if (type === 'camera') Object.assign(r, { indi_driver: null, indi_device_name: null, adapter_key: null, connect_params: {}, pixel_size_um: null, default_gain: null })
  else if (type === 'filter_wheel') Object.assign(r, { indi_driver: null, indi_device_name: null, adapter_key: null, connect_params: {}, filter_names: [] })
  else Object.assign(r, { indi_driver: null, indi_device_name: null, adapter_key: null, connect_params: {} })
  return r as Omit<EquipmentItem, 'id'>
}

type FieldValue = string | number | null | string[] | Record<string, unknown>

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
  const { t } = useTranslation('equipment')
  const [form, setForm] = useState<EquipmentItem | Omit<EquipmentItem, 'id'>>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  const initialConnectParams = (initial as { connect_params?: Record<string, unknown> }).connect_params
  const [connectParamsText, setConnectParamsText] = useState(
    JSON.stringify(initialConnectParams ?? {}),
  )
  const [connectParamsError, setConnectParamsError] = useState<string | null>(null)

  const initialFilterNames = (initial as { filter_names?: string[] }).filter_names
  const [filterNamesText, setFilterNamesText] = useState(
    (initialFilterNames ?? []).join(', '),
  )

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
    let connectParams: Record<string, unknown> = {}
    if (form.type !== 'site' && form.type !== 'ota') {
      try {
        connectParams = connectParamsText.trim() ? JSON.parse(connectParamsText) : {}
        setConnectParamsError(null)
      } catch {
        setConnectParamsError(t('form.paramsInvalid'))
        return
      }
    }
    setSaving(true)
    setError(null)
    try {
      await onSave({ ...form, connect_params: connectParams } as typeof form)
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
      <div className="flex items-center gap-2 font-medium text-slate-400 label-caps">
        <ItemTypeIcon type={type} size={13} />
        {t(`itemType.${type}`)}
      </div>

      <FieldRow label={t('form.name')}>
        <input
          ref={nameRef}
          required
          value={(form as {name: string}).name}
          onChange={(e) => set('name', e.target.value)}
          placeholder={t('form.eg', { example: type === 'site' ? t('form.exampleSite') : ITEM_EXAMPLE_NAMES[type] })}
          className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
            focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
        />
      </FieldRow>

      {/* INDI fields — for all INDI device types */}
      {type !== 'site' && type !== 'ota' && (
        <>
          <FieldRow label={t('form.indiDriver')}>
            <input
              value={(form as { indi_driver: string | null }).indi_driver ?? ''}
              onChange={(e) => set('indi_driver', e.target.value || null)}
              placeholder={t('form.indiDriverPlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
          <FieldRow label={t('form.indiDeviceName')}>
            <input
              value={(form as { indi_device_name: string | null }).indi_device_name ?? ''}
              onChange={(e) => set('indi_device_name', e.target.value || null)}
              placeholder={t('form.indiDeviceNamePlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>

          <p className="text-xs text-slate-600 -mb-1">
            {t('form.nonIndi')}
          </p>
          <FieldRow label={t('form.adapterKey')}>
            <input
              value={(form as { adapter_key: string | null }).adapter_key ?? ''}
              onChange={(e) => set('adapter_key', e.target.value || null)}
              placeholder={t('form.adapterKeyPlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
          <FieldRow label={t('form.params')}>
            <textarea
              value={connectParamsText}
              onChange={(e) => setConnectParamsText(e.target.value)}
              rows={3}
              placeholder={t('form.paramsPlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                font-mono focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
            {connectParamsError && <p className="text-xs text-status-error mt-1">{connectParamsError}</p>}
          </FieldRow>
        </>
      )}

      {/* Site fields */}
      {type === 'site' && (
        <>
          <FieldRow label={t('form.latitude')}>
            <DmsInput
              value={(form as { latitude: number }).latitude}
              onChange={(v) => set('latitude', v)}
              mode="lat"
            />
          </FieldRow>
          <FieldRow label={t('form.longitude')}>
            <DmsInput
              value={(form as { longitude: number }).longitude}
              onChange={(v) => set('longitude', v)}
              mode="lon"
            />
          </FieldRow>
          <div className="grid grid-cols-2 gap-3">
            <FieldRow label={t('form.altitude')}>
              <input
                type="number" step="1"
                value={(form as { altitude: number }).altitude}
                onChange={(e) => set('altitude', parseFloat(e.target.value) || 0)}
                className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                  focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
              />
            </FieldRow>
            <FieldRow label={t('form.timezone')}>
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
          <FieldRow label={t('form.focalLength')}>
            <input
              type="number" step="1" min="0"
              value={(form as { focal_length: number }).focal_length}
              onChange={(e) => set('focal_length', parseFloat(e.target.value) || 0)}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
          <FieldRow label={t('form.aperture')}>
            <input
              type="number" step="1" min="0"
              value={(form as { aperture: number }).aperture}
              onChange={(e) => set('aperture', parseFloat(e.target.value) || 0)}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
            />
          </FieldRow>
        </div>
      )}

      {/* Camera extra fields */}
      {type === 'camera' && (
        <div className="flex gap-3">
          <FieldRow label={t('form.pixelSize')}>
            <input
              type="number" step="0.01" min="0"
              value={(form as { pixel_size_um: number | null }).pixel_size_um ?? ''}
              onChange={(e) => set('pixel_size_um', e.target.value ? parseFloat(e.target.value) : null)}
              placeholder={t('form.pixelSizePlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-40"
            />
          </FieldRow>
          <FieldRow label={t('form.defaultGain')}>
            <input
              type="number" step="1" min="0"
              value={(form as { default_gain: number | null }).default_gain ?? ''}
              onChange={(e) => set('default_gain', e.target.value ? parseInt(e.target.value, 10) : null)}
              placeholder={t('form.defaultGainPlaceholder')}
              className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-56"
            />
          </FieldRow>
        </div>
      )}

      {/* Filter wheel extra field */}
      {type === 'filter_wheel' && (
        <FieldRow label={t('form.filterNames')}>
          <input
            value={filterNamesText}
            onChange={(e) => {
              setFilterNamesText(e.target.value)
              set('filter_names', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))
            }}
            placeholder="L, R, G, B, Ha, OIII, SII"
            className="bg-surface border border-surface-border rounded-lg px-3 py-1.5 text-sm text-slate-200
              focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent w-full"
          />
        </FieldRow>
      )}

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? t('form.saving') : t('form.save')}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t('form.cancel')}
        </Button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Inventory section
// ---------------------------------------------------------------------------

function InventorySection({ importItem, onImportDone }: {
  importItem?: Omit<EquipmentItem, 'id'> | null
  onImportDone?: () => void
}) {
  const { t } = useTranslation('equipment')
  const [items, setItems] = useState<EquipmentItem[]>([])
  const [creating, setCreating] = useState<Omit<EquipmentItem, 'id'> | null>(null)
  const [editing, setEditing] = useState<string | null>(null)  // item id
  const [showTypeMenu, setShowTypeMenu] = useState(false)

  useEffect(() => {
    if (importItem) {
      setCreating(importItem)
      setEditing(null)
      onImportDone?.()
    }
  }, [importItem]) // eslint-disable-line react-hooks/exhaustive-deps

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
    if (!confirm(t('inventory.confirmRemove'))) return
    await api.inventory.delete(id)
    if (editing === id) setEditing(null)
    load()
  }

  // Group items by type for display
  const grouped = items.reduce<Partial<Record<EquipmentItemType, EquipmentItem[]>>>((acc, item) => {
    const ty = item.type as EquipmentItemType
    if (!acc[ty]) acc[ty] = []
    acc[ty]!.push(item)
    return acc
  }, {})

  const allTypes: EquipmentItemType[] = ['site', 'mount', 'ota', 'camera', 'filter_wheel', 'focuser', 'rotator', 'gps']

  return (
    <div className="flex flex-col gap-6">
      {/* Add button */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {items.length === 0 ? t('inventory.empty') : t('inventory.items', { count: items.length })}
        </p>
        <div className="relative">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowTypeMenu((v) => !v)}
          >
            <Plus size={14} className="mr-1.5" />
            {t('inventory.add')}
          </Button>
          {showTypeMenu && (
            <div className="absolute right-0 top-full mt-1 z-10 bg-surface border border-surface-border rounded shadow-lg min-w-44">
              {allTypes.map((ty) => (
                <button
                  key={ty}
                  className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-300
                    hover:bg-surface-raised transition-colors text-left"
                  onClick={() => {
                    setCreating(emptyForm(ty))
                    setEditing(null)
                    setShowTypeMenu(false)
                  }}
                >
                  <ItemTypeIcon type={ty} size={13} />
                  {t(`itemType.${ty}`)}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Create form */}
      {creating && (
        <ItemForm
          initial={creating}
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
            <h3 className="font-medium text-slate-500 label-caps mb-2 flex items-center gap-1.5">
              <ItemTypeIcon type={type} size={11} />
              {t(`itemType.${type}`)}
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
                          title={t('inventory.edit')}
                        >
                          <Pencil size={13} className="text-slate-400" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(item.id)}
                          title={t('inventory.delete')}
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
          {t('inventory.hint')}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function Equipment() {
  const { t } = useTranslation('equipment')
  const connectedDevices = useStore((s) => s.connectedDevices)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)

  const [activeTab, setActiveTab] = useState<'connections' | 'inventory'>('connections')
  const [importItem, setImportItem] = useState<Omit<EquipmentItem, 'id'> | null>(null)

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

  // "Other adapter" (non-INDI) path
  const [genericAdapters, setGenericAdapters] = useState<string[]>([])

  const refresh = () => {
    api.devices.connected().then(setConnectedDevices).catch(console.error)
  }

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (step === 'type' || step === 'source' || step === 'generic') return
    setDrivers([])
    api.indi.drivers(selectedKind).then(setDrivers).catch(() => setDrivers([]))
  }, [selectedKind, step])

  const handleSelectKind = (kind: DeviceKind) => {
    setSelectedKind(kind)
    setSelectedManufacturer(null)
    setSelectedDriver(null)
    setError(null)
    setStep('source')
  }

  const handleChooseIndi = () => {
    setError(null)
    setStep('manufacturer')
  }

  const handleChooseGeneric = () => {
    setError(null)
    api.devices.available()
      .then((reg) => {
        const keys = reg[KIND_REGISTRY_KEY[selectedKind]] ?? []
        setGenericAdapters(keys.filter((k) => !k.startsWith('indi_')))
      })
      .catch(() => setGenericAdapters([]))
    setStep('generic')
  }

  const handleGenericConnect = async (
    adapterKey: string, deviceId: string, params: Record<string, unknown>,
  ) => {
    setError(null)
    setConnecting(true)
    try {
      await api.devices.connect({
        device_id: deviceId || undefined,
        kind: selectedKind,
        adapter_key: adapterKey,
        params,
      })
      refresh()
      setStep('type')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setConnecting(false)
    }
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
    } else if (step === 'manufacturer' || step === 'generic') {
      setStep('source')
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

  const handleImportDevice = async (device: ConnectedDevice) => {
    const typeMap: Partial<Record<DeviceKind, EquipmentItemType>> = {
      camera: 'camera', mount: 'mount', focuser: 'focuser',
      filter_wheel: 'filter_wheel', rotator: 'rotator',
    }
    const invType = typeMap[device.kind]
    if (!invType) return

    try {
      const config = await api.devices.getConfig(device.device_id)
      const isIndi = typeof config.params?.device_name === 'string'
      const deviceName = (config.params?.device_name as string) || device.device_id

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const item: Record<string, any> = isIndi
        ? {
            type: invType,
            name: deviceName,
            indi_driver: (config.params?.executable as string) || null,
            indi_device_name: deviceName,
            adapter_key: null,
            connect_params: {},
          }
        : {
            type: invType,
            name: deviceName,
            indi_driver: null,
            indi_device_name: null,
            adapter_key: config.adapter_key,
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            connect_params: (({ pre_connect_props, ...rest }) => rest)(config.params ?? {}),
          }

      if (invType === 'filter_wheel') item.filter_names = []

      if (invType === 'camera') {
        item.pixel_size_um = null
        item.default_gain = null
        // Opportunistically read CCD_INFO to pre-fill pixel size
        try {
          const props = await api.devices.properties(device.device_id)
          const ccdInfo = props.find((p) => p.name === 'CCD_INFO')
          const pixelWidget = ccdInfo?.widgets.find((w) => w.name === 'CCD_PIXEL_SIZE')
          if (typeof pixelWidget?.value === 'number' && pixelWidget.value > 0) {
            item.pixel_size_um = pixelWidget.value
          }
        } catch { /* properties unavailable — leave null */ }
      }

      setImportItem(item as Omit<EquipmentItem, 'id'>)
      setActiveTab('inventory')
    } catch (err) {
      console.error('Import to inventory failed:', err)
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
        <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
        {activeTab === 'connections' && (
          <Button variant="ghost" size="icon" onClick={refresh} title={t('refresh')}>
            <RefreshCw size={15} />
          </Button>
        )}
      </div>

      {/* Tab switcher */}
      <Tabs
        className="mb-6"
        tabs={(['connections', 'inventory'] as const).map((tab) => ({ id: tab, label: t(`tabs.${tab}`) }))}
        value={activeTab}
        onChange={setActiveTab}
      />

      {/* Inventory tab */}
      {activeTab === 'inventory' && (
        <InventorySection
          importItem={importItem}
          onImportDone={() => setImportItem(null)}
        />
      )}

      {/* Connections tab */}
      {activeTab === 'connections' && <>

      {/* Connected devices */}
      <section className="mb-8">
        <h2 className="font-medium text-slate-500 label-caps mb-3">
          {t('connected')}
        </h2>
        {connectedDevices.length === 0 ? (
          <p className="text-sm text-slate-500">{t('noDevices')}</p>
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
                      onImport={() => handleImportDevice(primary)}
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
                          onImport={() => handleImportDevice(c)}
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
        <h2 className="font-medium text-slate-500 label-caps mb-3">
          {t('loadDriver')}
        </h2>
        <div className="bg-surface-raised border border-surface-border rounded p-4">
          {step === 'type' && (
            <TypeStep onSelect={handleSelectKind} />
          )}
          {step === 'source' && (
            <SourceStep
              kind={selectedKind}
              onChooseIndi={handleChooseIndi}
              onChooseGeneric={handleChooseGeneric}
              onBack={handleBack}
            />
          )}
          {step === 'generic' && (
            <GenericAdapterStep
              kind={selectedKind}
              adapterKeys={genericAdapters}
              onBack={handleBack}
              onConnect={handleGenericConnect}
              connecting={connecting}
              error={error}
            />
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
              {t('loading')}
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
