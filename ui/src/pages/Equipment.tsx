import { useEffect, useState } from 'react'
import { Plug, PlugZap, RefreshCw } from 'lucide-react'
import { api } from '@/api/client'
import type { ConnectedDevice, DeviceConfig, DeviceKind } from '@/api/types'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'

interface ConnectFormState {
  device_id: string
  kind: DeviceKind
  adapter_key: string
  indi_device_name: string
  indi_host: string
  indi_port: string
}

const DEFAULT_FORM: ConnectFormState = {
  device_id: '',
  kind: 'camera',
  adapter_key: '',
  indi_device_name: '',
  indi_host: 'localhost',
  indi_port: '7624',
}

export function Equipment() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)
  const [available, setAvailable] = useState<Record<string, string[]>>({})
  const [form, setForm] = useState<ConnectFormState>(DEFAULT_FORM)
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  const refresh = () => {
    api.devices.connected().then(setConnectedDevices).catch(console.error)
    api.devices.available().then(setAvailable).catch(console.error)
  }

  useEffect(() => { refresh() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const adapterOptions = available[`${form.kind}s`] ?? []

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setConnecting(true)
    const config: DeviceConfig = {
      device_id: form.device_id || undefined,
      kind: form.kind,
      adapter_key: form.adapter_key,
      params: {
        device_name: form.indi_device_name,
        host: form.indi_host,
        port: parseInt(form.indi_port, 10),
      },
    }
    try {
      await api.devices.connect(config)
      refresh()
      setForm(DEFAULT_FORM)
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
                className="flex items-center justify-between bg-surface-raised border border-surface-border rounded px-4 py-3"
              >
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-200">{d.device_id}</span>
                  <span className="text-xs text-slate-500">{d.kind} · {d.adapter_key}</span>
                </div>
                <div className="flex items-center gap-3">
                  <StateBadge state={d.state} />
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDisconnect(d.device_id)}
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

      {/* Connect form */}
      <section>
        <h2 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">
          Connect device
        </h2>
        <form
          onSubmit={handleConnect}
          className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-3"
        >
          <div className="grid grid-cols-2 gap-3">
            {/* Kind */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Type</label>
              <select
                className="rounded bg-surface-overlay border border-surface-border px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as DeviceKind, adapter_key: '' })}
              >
                <option value="camera">Camera</option>
                <option value="mount">Mount</option>
                <option value="focuser">Focuser</option>
              </select>
            </div>

            {/* Adapter */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Adapter</label>
              <select
                className="rounded bg-surface-overlay border border-surface-border px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40"
                value={form.adapter_key}
                onChange={(e) => setForm({ ...form, adapter_key: e.target.value })}
                disabled={adapterOptions.length === 0}
              >
                <option value="">— select —</option>
                {adapterOptions.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Device ID */}
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400">Device ID <span className="text-slate-600">(optional, auto-generated if blank)</span></label>
            <Input
              placeholder="e.g. main_camera"
              value={form.device_id}
              onChange={(e) => setForm({ ...form, device_id: e.target.value })}
            />
          </div>

          {/* INDI params */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-3 flex flex-col gap-1">
              <label className="text-xs text-slate-400">INDI device name</label>
              <Input
                placeholder="e.g. ZWO CCD ASI294MC Pro"
                value={form.indi_device_name}
                onChange={(e) => setForm({ ...form, indi_device_name: e.target.value })}
              />
            </div>
            <div className="col-span-2 flex flex-col gap-1">
              <label className="text-xs text-slate-400">INDI host</label>
              <Input
                value={form.indi_host}
                onChange={(e) => setForm({ ...form, indi_host: e.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-400">Port</label>
              <Input
                value={form.indi_port}
                onChange={(e) => setForm({ ...form, indi_port: e.target.value })}
              />
            </div>
          </div>

          {error && (
            <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
          )}

          <Button
            type="submit"
            disabled={!form.adapter_key || connecting}
            className="self-start"
          >
            <Plug size={14} className="mr-2" />
            {connecting ? 'Connecting…' : 'Connect'}
          </Button>
        </form>
      </section>
    </div>
  )
}
