import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Aperture, Camera, Focus, Lightbulb, Plug, RefreshCw, RotateCw, Server, Telescope, Trash2, X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Page } from '@/components/Page'
import { useStore } from '@/store'
import {
  connectDevice, discover, getConnected, getSettings, putSettings,
  type AddressError, type AlpacaDeviceInfo, type AlpacaServerInfo, type ConnectedAlpacaDevice,
} from './api'
import { connectedAs, formatAddress, sortDevices, suggestDeviceId } from './devices'

const KIND_ICONS: Record<string, LucideIcon> = {
  camera: Camera,
  mount: Telescope,
  focuser: Focus,
  filter_wheel: Aperture,
  rotator: RotateCw,
  flat_panel: Lightbulb,
}

const DEVICE_ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/

function DeviceRow({
  server, device, connected, takenIds, onConnected,
}: {
  server: AlpacaServerInfo
  device: AlpacaDeviceInfo
  connected: ConnectedAlpacaDevice[]
  takenIds: string[]
  onConnected: () => void
}) {
  const { t } = useTranslation('alpaca')
  const { t: te } = useTranslation('equipment')
  const [deviceId, setDeviceId] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const Icon = (device.kind && KIND_ICONS[device.kind]) || Server
  const already = connectedAs(server, device, connected)
  const suggested = suggestDeviceId(device, takenIds)
  const idInvalid = deviceId !== '' && !DEVICE_ID_RE.test(deviceId)

  const connect = async () => {
    setConnecting(true)
    setError(null)
    try {
      await connectDevice(server, device, deviceId || suggested)
      setDeviceId('')
      onConnected()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setConnecting(false)
    }
  }

  return (
    <div className={`flex flex-col gap-1 py-2 border-t border-surface-border first:border-t-0 ${device.kind ? '' : 'opacity-50'}`}>
      <div className="flex items-center gap-3 flex-wrap">
        <Icon size={16} className="text-slate-400 shrink-0" />
        <div className="flex-1 min-w-[10rem]">
          <p className="text-sm text-slate-200">{device.name}</p>
          <p className="text-xs text-slate-500">
            {device.kind ? te(`kind.${device.kind}`) : device.device_type}
            {device.device_number > 0 && ` · ${t('device.number', { n: device.device_number })}`}
          </p>
        </div>
        {!device.kind ? (
          <span className="text-xs text-slate-500">{t('device.unsupported')}</span>
        ) : already ? (
          <span className="text-xs text-status-connected">
            {t('device.connectedAs', { id: already.device_id })}
          </span>
        ) : (
          <div className="flex items-center gap-2">
            <Input
              inputSize="sm"
              value={deviceId}
              placeholder={suggested}
              onChange={(e) => setDeviceId(e.target.value)}
              aria-label={t('device.id')}
              title={t('device.id')}
              className={`!w-56 ${idInvalid ? 'border-status-error' : ''}`}
            />
            <Button type="button" size="sm" variant="outline" disabled={connecting || idInvalid} onClick={connect}>
              <Plug size={14} className="mr-1.5" />
              {connecting ? t('device.connecting') : t('device.connect')}
            </Button>
          </div>
        )}
      </div>
      {idInvalid && <p className="text-xs text-status-error ml-7">{t('device.idInvalid')}</p>}
      {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2 ml-7">{error}</p>}
    </div>
  )
}

function ServerCard({
  server, connected, takenIds, onConnected,
}: {
  server: AlpacaServerInfo
  connected: ConnectedAlpacaDevice[]
  takenIds: string[]
  onConnected: () => void
}) {
  const { t } = useTranslation('alpaca')
  const address = formatAddress(server.host, server.port)
  const details = [server.manufacturer, server.version, server.location].filter(Boolean).join(' · ')
  return (
    <div className="bg-surface-raised border border-surface-border rounded-lg p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-2">
        <p className="text-sm text-slate-100 font-medium">{server.name || address}</p>
        <p className="text-xs text-slate-500 font-mono">{address}</p>
      </div>
      {details && <p className="text-xs text-slate-500 mb-2">{details}</p>}
      {server.devices.length === 0 ? (
        <p className="text-xs text-slate-500">{t('server.noDevices')}</p>
      ) : (
        sortDevices(server.devices).map((d) => (
          <DeviceRow
            key={`${d.device_type}/${d.device_number}`}
            server={server}
            device={d}
            connected={connected}
            takenIds={takenIds}
            onConnected={onConnected}
          />
        ))
      )}
    </div>
  )
}

export function AlpacaPage() {
  const { t } = useTranslation('alpaca')
  const connectedDevices = useStore((s) => s.connectedDevices)
  const [servers, setServers] = useState<AlpacaServerInfo[] | null>(null)
  const [errors, setErrors] = useState<AddressError[]>([])
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const [connected, setConnected] = useState<ConnectedAlpacaDevice[]>([])
  const [addresses, setAddresses] = useState<string[]>([])
  const [newAddress, setNewAddress] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)

  const refreshConnected = useCallback(() => {
    getConnected().then(setConnected).catch(() => {})
  }, [])

  const scan = useCallback(async () => {
    setScanning(true)
    setScanError(null)
    try {
      const result = await discover()
      setServers(result.servers)
      setErrors(result.errors)
    } catch (e) {
      setScanError((e as Error).message)
    } finally {
      setScanning(false)
    }
  }, [])

  useEffect(() => {
    getSettings().then((s) => setAddresses(s.addresses)).catch(() => {})
    scan()
  }, [scan])

  // Devices connected or removed elsewhere (the Equipment page, a profile) show here too.
  useEffect(refreshConnected, [connectedDevices, refreshConnected])

  const saveAddresses = async (next: string[]) => {
    setSaveError(null)
    try {
      setAddresses((await putSettings({ addresses: next })).addresses)
      await scan()
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  const addAddress = () => {
    const address = newAddress.trim()
    if (!address || addresses.includes(address)) return
    setNewAddress('')
    saveAddresses([...addresses, address])
  }

  const takenIds = connectedDevices.map((d) => d.device_id)
  const onConnected = () => refreshConnected()

  return (
    <Page width="medium">
      <div className="flex items-start justify-between gap-4 mb-2">
        <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
        <Button type="button" variant="outline" size="sm" disabled={scanning} onClick={scan}>
          <RefreshCw size={14} className={`mr-1.5 ${scanning ? 'animate-spin' : ''}`} />
          {scanning ? t('scanning') : t('scan')}
        </Button>
      </div>
      <p className="text-sm text-slate-400 mb-6">{t('intro')}</p>

      {scanError && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2 mb-4">{scanError}</p>}

      <div className="flex flex-col gap-4 mb-8">
        {servers === null ? (
          <p className="text-sm text-slate-500">{t('scanning')}</p>
        ) : servers.length === 0 ? (
          <p className="text-sm text-slate-500">{t('none')}</p>
        ) : (
          servers.map((s) => (
            <ServerCard
              key={formatAddress(s.host, s.port)}
              server={s}
              connected={connected}
              takenIds={takenIds}
              onConnected={onConnected}
            />
          ))
        )}
        {errors.map((e) => (
          <p key={e.address} className="text-xs text-status-error">
            {t('unreachable', { address: e.address, error: e.error })}
          </p>
        ))}
      </div>

      <h2 className="label-caps font-semibold text-slate-400 mb-2">{t('addresses.title')}</h2>
      <p className="text-xs text-slate-500 mb-3">{t('addresses.hint')}</p>
      <div className="flex flex-col gap-2 mb-3">
        {addresses.map((a) => (
          <div key={a} className="flex items-center justify-between gap-3 bg-surface border border-surface-border rounded px-3 py-1.5">
            <span className="text-sm font-mono text-slate-300">{a}</span>
            <button
              type="button"
              onClick={() => saveAddresses(addresses.filter((x) => x !== a))}
              className="text-slate-500 hover:text-status-error"
              title={t('addresses.remove')}
              aria-label={t('addresses.remove')}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => { e.preventDefault(); addAddress() }}
      >
        <Input
          inputSize="sm"
          value={newAddress}
          placeholder={t('addresses.placeholder')}
          onChange={(e) => setNewAddress(e.target.value)}
          className="!w-64"
        />
        <Button type="submit" size="sm" variant="outline" disabled={!newAddress.trim()}>
          {t('addresses.add')}
        </Button>
        {newAddress && (
          <button type="button" onClick={() => setNewAddress('')} className="text-slate-500 hover:text-slate-300" aria-label={t('addresses.clear')}>
            <X size={14} />
          </button>
        )}
      </form>
      {saveError && <p className="text-xs text-status-error mt-2">{saveError}</p>}
    </Page>
  )
}
