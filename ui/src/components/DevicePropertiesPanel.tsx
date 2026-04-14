import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { api } from '@/api/client'
import type { DeviceProperty, IndiDeviceMessage, PropertyWidget } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATE_DOT: Record<string, string> = {
  idle: 'bg-slate-500',
  ok: 'bg-green-500',
  busy: 'bg-yellow-500',
  alert: 'bg-red-500',
}

function StateDot({ state }: { state: string }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${STATE_DOT[state] ?? 'bg-slate-500'}`}
      title={state}
    />
  )
}

function groupBy<T>(items: T[], key: (item: T) => string): [string, T[]][] {
  const map = new Map<string, T[]>()
  for (const item of items) {
    const k = key(item)
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(item)
  }
  return Array.from(map.entries())
}

// ---------------------------------------------------------------------------
// Switch property row
// ---------------------------------------------------------------------------

function SwitchProperty({
  prop,
  deviceId,
}: {
  prop: DeviceProperty
  deviceId: string
}) {
  const isReadOnly = prop.permission === 'ro'

  const handleClick = async (widgetName: string) => {
    if (isReadOnly) return
    let on: string[]
    if (prop.switch_rule === 'nofmany') {
      const current = prop.widgets.find((w) => w.name === widgetName)
      on = current?.value
        ? prop.widgets.filter((w) => w.name !== widgetName && w.value).map((w) => w.name)
        : [...prop.widgets.filter((w) => w.value).map((w) => w.name), widgetName]
    } else {
      on = [widgetName]
    }
    await api.devices.setProperty(deviceId, prop.name, { on_elements: on }).catch(console.error)
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {prop.widgets.map((w) => (
        <button
          key={w.name}
          disabled={isReadOnly}
          onClick={() => handleClick(w.name)}
          className={[
            'px-2 py-0.5 rounded text-xs border transition-colors',
            w.value
              ? 'bg-accent border-accent text-white'
              : 'border-surface-border text-slate-400 hover:border-slate-500',
            isReadOnly ? 'cursor-default opacity-60' : 'cursor-pointer',
          ].join(' ')}
        >
          {w.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Number property row
// ---------------------------------------------------------------------------

function NumberProperty({
  prop,
  deviceId,
}: {
  prop: DeviceProperty
  deviceId: string
}) {
  const isReadOnly = prop.permission === 'ro'
  const [localValues, setLocalValues] = useState<Record<string, string>>({})
  const focusedRef = useRef(false)

  // Sync from server when not editing
  useEffect(() => {
    if (focusedRef.current) return
    setLocalValues(
      Object.fromEntries(
        prop.widgets.map((w) => [w.name, w.value != null ? String(w.value) : ''])
      )
    )
  }, [prop.widgets])

  const handleSet = async () => {
    const values = Object.fromEntries(
      Object.entries(localValues).map(([k, v]) => [k, parseFloat(v)])
    )
    await api.devices.setProperty(deviceId, prop.name, { values }).catch(console.error)
  }

  return (
    <div className="flex flex-col gap-2">
      {prop.widgets.map((w) => (
        <div key={w.name}>
          {prop.widgets.length > 1 && (
            <span className="block text-xs text-slate-500 mb-0.5">{w.label}</span>
          )}
          <div className="flex items-center gap-2">
            {isReadOnly ? (
              <span className="text-sm text-slate-300 font-mono">
                {w.value != null ? Number(w.value).toFixed(4).replace(/\.?0+$/, '') : '—'}
              </span>
            ) : (
              <Input
                className="h-7 text-sm py-0 px-2 w-40"
                value={localValues[w.name] ?? ''}
                onChange={(e) =>
                  setLocalValues((prev) => ({ ...prev, [w.name]: e.target.value }))
                }
                onFocus={() => { focusedRef.current = true }}
                onBlur={() => { focusedRef.current = false }}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSet() }}
              />
            )}
            {w.min != null && w.max != null && (
              <span className="text-xs text-slate-600">
                [{w.min}–{w.max}]
              </span>
            )}
          </div>
        </div>
      ))}
      {!isReadOnly && (
        <Button size="sm" variant="outline" className="self-start h-6 text-xs px-2" onClick={handleSet}>
          Set
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Text property row
// ---------------------------------------------------------------------------

function TextProperty({
  prop,
  deviceId,
}: {
  prop: DeviceProperty
  deviceId: string
}) {
  const isReadOnly = prop.permission === 'ro'
  const [localValues, setLocalValues] = useState<Record<string, string>>({})
  const focusedRef = useRef(false)

  useEffect(() => {
    if (focusedRef.current) return
    setLocalValues(
      Object.fromEntries(
        prop.widgets.map((w) => [w.name, w.value != null ? String(w.value) : ''])
      )
    )
  }, [prop.widgets])

  const handleSet = async () => {
    await api.devices.setProperty(deviceId, prop.name, { values: localValues }).catch(console.error)
  }

  return (
    <div className="flex flex-col gap-2">
      {prop.widgets.map((w) => (
        <div key={w.name}>
          {prop.widgets.length > 1 && (
            <span className="block text-xs text-slate-500 mb-0.5">{w.label}</span>
          )}
          {isReadOnly ? (
            <span className="text-sm text-slate-300 font-mono break-all">
              {w.value != null ? String(w.value) : '—'}
            </span>
          ) : (
            <Input
              className="h-7 text-sm py-0 px-2 w-full"
              value={localValues[w.name] ?? ''}
              onChange={(e) =>
                setLocalValues((prev) => ({ ...prev, [w.name]: e.target.value }))
              }
              onFocus={() => { focusedRef.current = true }}
              onBlur={() => { focusedRef.current = false }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSet() }}
            />
          )}
        </div>
      ))}
      {!isReadOnly && (
        <Button size="sm" variant="outline" className="self-start h-6 text-xs px-2" onClick={handleSet}>
          Set
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Light property row
// ---------------------------------------------------------------------------

function LightProperty({ widgets }: { widgets: PropertyWidget[] }) {
  return (
    <div className="flex flex-col gap-1">
      {widgets.map((w) => (
        <div key={w.name} className="flex items-center gap-2">
          <StateDot state={w.state ?? 'idle'} />
          <span className="text-xs text-slate-400">{w.label}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single property row — stacked layout so widgets get the full panel width
// ---------------------------------------------------------------------------

function PropertyRow({
  prop,
  deviceId,
}: {
  prop: DeviceProperty
  deviceId: string
}) {
  return (
    <div className="py-2.5 border-b border-surface-border last:border-0">
      {/* Header: state dot + human label + internal name */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <StateDot state={prop.state} />
        <span className="text-xs font-medium text-slate-300" title={prop.name}>
          {prop.label || prop.name}
        </span>
        {prop.label && prop.label !== prop.name && (
          <span className="text-xs text-slate-600 font-mono">{prop.name}</span>
        )}
      </div>

      {/* Widgets — full width */}
      <div className="pl-3.5">
        {prop.type === 'switch' && (
          <SwitchProperty prop={prop} deviceId={deviceId} />
        )}
        {prop.type === 'number' && (
          <NumberProperty prop={prop} deviceId={deviceId} />
        )}
        {prop.type === 'text' && (
          <TextProperty prop={prop} deviceId={deviceId} />
        )}
        {prop.type === 'light' && (
          <LightProperty widgets={prop.widgets} />
        )}
        {prop.type === 'blob' && (
          <span className="text-xs text-slate-600">BLOB (binary)</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Messages tab
// ---------------------------------------------------------------------------

function MessagesTab({ indiDeviceName }: { indiDeviceName: string | null }) {
  const [messages, setMessages] = useState<IndiDeviceMessage[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!indiDeviceName) return
    let alive = true

    const load = () => {
      api.indi
        .deviceMessages(indiDeviceName)
        .then((msgs) => {
          if (alive) {
            setMessages(msgs)
            setError(null)
          }
        })
        .catch((e: Error) => {
          if (alive) setError(e.message)
        })
    }

    load()
    const id = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [indiDeviceName])

  if (!indiDeviceName) {
    return <p className="text-xs text-slate-500 p-4">Not an INDI device.</p>
  }
  if (error) {
    return <p className="text-xs text-status-error p-4">{error}</p>
  }
  if (messages.length === 0) {
    return <p className="text-xs text-slate-500 p-4">No messages from driver.</p>
  }
  return (
    <div className="flex flex-col gap-0">
      {messages.map((m, i) => (
        <div key={i} className="px-4 py-2 border-b border-surface-border last:border-0">
          <p className="text-xs text-slate-500 font-mono mb-0.5">
            {new Date(m.timestamp).toLocaleTimeString()}
          </p>
          <p className="text-xs text-slate-300 break-words">{m.message}</p>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface Props {
  deviceId: string
  onClose: () => void
}

type Tab = 'properties' | 'messages'

export function DevicePropertiesPanel({ deviceId, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('properties')
  const [properties, setProperties] = useState<DeviceProperty[]>([])
  const [error, setError] = useState<string | null>(null)
  const [indiDeviceName, setIndiDeviceName] = useState<string | null>(null)

  // Fetch device config once to get the INDI device name for the messages tab
  useEffect(() => {
    api.devices.getConfig(deviceId).then((cfg) => {
      const name = cfg.params?.device_name
      if (typeof name === 'string') setIndiDeviceName(name)
    }).catch(() => {/* non-INDI device or endpoint unavailable */})
  }, [deviceId])

  useEffect(() => {
    let alive = true

    const load = () => {
      api.devices
        .properties(deviceId)
        .then((ps) => {
          if (alive) {
            setProperties(ps)
            setError(null)
          }
        })
        .catch((e: Error) => {
          if (alive) setError(e.message)
        })
    }

    load()
    const id = setInterval(load, 3000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [deviceId])

  const groups = groupBy(properties, (p) => p.group || 'General')

  return (
    <div className="fixed top-0 right-0 bottom-0 z-50 flex flex-col w-[480px] border-l border-surface-border bg-surface-raised shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border flex-shrink-0">
        <div>
          <p className="text-sm font-semibold text-slate-100">{deviceId}</p>
          <p className="text-xs text-slate-500">
            {indiDeviceName ?? 'Device properties'}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} title="Close panel">
          <X size={14} />
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-surface-border flex-shrink-0">
        {(['properties', 'messages'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={[
              'px-4 py-2 text-xs font-medium capitalize transition-colors',
              tab === t
                ? 'text-slate-100 border-b-2 border-accent -mb-px'
                : 'text-slate-500 hover:text-slate-300',
            ].join(' ')}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'properties' ? (
          error ? (
            <p className="text-xs text-status-error p-4">{error}</p>
          ) : properties.length === 0 ? (
            <p className="text-xs text-slate-500 p-4">Loading properties…</p>
          ) : (
            groups.map(([group, props]) => (
              <div key={group}>
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider px-4 py-2 bg-surface sticky top-0">
                  {group}
                </p>
                <div className="px-4">
                  {props.map((p) => (
                    <PropertyRow key={p.name} prop={p} deviceId={deviceId} />
                  ))}
                </div>
              </div>
            ))
          )
        ) : (
          <MessagesTab indiDeviceName={indiDeviceName} />
        )}
      </div>
    </div>
  )
}
