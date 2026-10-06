import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/api/client'
import type { PairedSerialDevice } from '@/api/types'
import { type DiscoveredDevice, forget, pair, rename, scan } from './api'

function PairedRow({ device, onChanged }: { device: PairedSerialDevice; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(device.name)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await rename(device.id, name)
      onChanged()
    } finally {
      setBusy(false)
      setEditing(false)
    }
  }

  const remove = async () => {
    if (!confirm(`Forget "${device.name}"? Any device configured to use it will need re-pairing.`)) return
    setBusy(true)
    try {
      await forget(device.id)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-3 bg-surface border border-surface-border rounded px-3 py-2 text-sm">
      {editing ? (
        <Input value={name} onChange={(e) => setName(e.target.value)} className="flex-1" autoFocus />
      ) : (
        <span className="flex-1 text-slate-200">{device.name}</span>
      )}
      <span className="text-xs text-slate-500 font-mono">{device.mac}</span>
      {editing ? (
        <Button size="sm" variant="outline" disabled={busy} onClick={save}>Save</Button>
      ) : (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(true)}>Rename</Button>
      )}
      <Button size="sm" variant="danger" disabled={busy} onClick={remove}>Forget</Button>
    </div>
  )
}

function ScanPanel({ onPaired }: { onPaired: () => void }) {
  const [devices, setDevices] = useState<DiscoveredDevice[] | null>(null)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pairing, setPairing] = useState<string | null>(null)
  const [pin, setPin] = useState('1234')

  const runScan = async () => {
    setScanning(true)
    setError(null)
    try {
      setDevices(await scan())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setScanning(false)
    }
  }

  const doPair = async (mac: string) => {
    setError(null)
    try {
      await pair(mac, pin)
      setPairing(null)
      onPaired()
      await runScan()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-300 font-medium">Nearby devices</p>
        <Button size="sm" disabled={scanning} onClick={runScan}>
          {scanning ? 'Scanning…' : 'Scan'}
        </Button>
      </div>
      {error && <p className="text-xs text-status-error">{error}</p>}
      {devices === null && !scanning && (
        <p className="text-xs text-slate-500">Scan to find a nearby Bluetooth serial device (e.g. an EQMOD cable replacement).</p>
      )}
      <div className="flex flex-col gap-2">
        {devices?.map((d) => (
          <div key={d.mac} className="flex flex-col gap-2 bg-surface border border-surface-border rounded px-3 py-2">
            <div className="flex items-center gap-3 text-sm">
              <span className="flex-1 text-slate-200">{d.name}</span>
              <span className="text-xs text-slate-500 font-mono">{d.mac}</span>
              {d.rssi != null && <span className="text-xs text-slate-500">{d.rssi} dBm</span>}
              {d.paired ? (
                <span className="text-xs text-emerald-400">paired</span>
              ) : pairing === d.mac ? null : (
                <Button size="sm" variant="outline" onClick={() => setPairing(d.mac)}>Pair</Button>
              )}
            </div>
            {pairing === d.mac && (
              <div className="flex items-center gap-2 pl-1">
                <span className="text-xs text-slate-500">PIN</span>
                <Input
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  inputSize="sm"
                  className="w-24"
                  placeholder="0000"
                />
                <Button size="sm" onClick={() => doPair(d.mac)}>Confirm</Button>
                <Button size="sm" variant="ghost" onClick={() => setPairing(null)}>Cancel</Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function BluetoothSerialPage() {
  const [paired, setPaired] = useState<PairedSerialDevice[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    api.bluetooth
      .paired()
      .then(setPaired)
      .catch((e: Error) => setError(e.message))

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="p-6 max-w-2xl flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-slate-100">Bluetooth Serial</h1>
      <p className="text-xs text-slate-500">
        Pair a classic Bluetooth serial adapter once here — any device that supports a Bluetooth
        connection (e.g. the EQMOD mount driver) can then pick it by name from its own connection
        settings, with no MAC address or channel number to type in.
      </p>
      {error && <p className="text-xs text-status-error">{error}</p>}
      <div className="flex flex-col gap-2">
        <p className="text-sm text-slate-300 font-medium">Paired devices</p>
        {paired !== null && paired.length === 0 && (
          <p className="text-xs text-slate-500">None paired yet.</p>
        )}
        {paired?.map((d) => (
          <PairedRow key={d.id} device={d} onChanged={load} />
        ))}
      </div>
      <ScanPanel onPaired={load} />
    </div>
  )
}
