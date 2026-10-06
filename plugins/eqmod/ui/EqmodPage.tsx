import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { BluetoothDevicePicker } from '@/components/ui/bluetooth-picker'
import { api } from '@/api/client'
import type { MountEquipmentItem } from '@/api/types'
import {
  getDiagnostics, getIndiProxy, getSettings, putSettings,
  type AxisDiagnostics, type EqmodSettings, type IndiProxyStatus, type MountDiagnostics,
} from './api'

const STATUS_FLAGS = ['running', 'tracking_mode', 'fast', 'ccw', 'blocked', 'initialized', 'level_switch']

const MONO = { m: <span className="font-mono text-slate-300" /> }

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-200 text-right">{value}</span>
    </div>
  )
}

function AxisCard({ name, axis }: { name: string; axis: AxisDiagnostics }) {
  const { t } = useTranslation('eqmod')
  return (
    <div className="bg-surface border border-surface-border rounded p-3 text-xs">
      <p className="text-slate-300 font-medium mb-2">{t(axis.reversed ? 'axis.reversed' : 'axis.title', { name })}</p>
      <Row label={t('axis.cpr')} value={axis.cpr.toLocaleString()} />
      <Row label={t('axis.ratio')} value={axis.high_speed_ratio} />
      <Row label={t('axis.counts')} value={axis.position_counts.toLocaleString()} />
      <Row label={t('axis.degrees')} value={axis.position_degrees.toFixed(4)} />
      <Row label={t('axis.period')} value={axis.step_period.toLocaleString()} />
      <Row label={t('axis.extended')} value={axis.extended_status} />
      <div className="flex flex-wrap gap-1 mt-2">
        {STATUS_FLAGS.map((key) => (
          <span
            key={key}
            className={`px-1.5 py-0.5 rounded border ${
              axis.status[key]
                ? 'bg-sky-500/20 text-sky-300 border-sky-500/30'
                : 'bg-slate-700/50 text-slate-500 border-slate-600/40'
            }`}
          >
            {t(`flags.${key}`)}
          </span>
        ))}
      </div>
    </div>
  )
}

function MountCard({ d }: { d: MountDiagnostics }) {
  const { t } = useTranslation('eqmod')
  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <p className="text-sm text-slate-200 font-medium">{d.device_id}</p>
        <p className="text-xs text-slate-500 font-mono">{t('mount.baud', { port: d.port, baud: d.baudrate ?? '?' })}</p>
      </div>
      {d.error ? (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{d.error}</p>
      ) : (
        <>
          <div className="text-xs grid grid-cols-2 gap-x-6">
            <Row label={t('mount.board')} value={d.board_version ?? '—'} />
            <Row label={t('mount.timer')} value={d.timer_freq?.toLocaleString() ?? '—'} />
            <Row label={t('mount.tracking')} value={d.tracking ? d.tracking_mode : t('mount.off')} />
            <Row label={t('mount.nudging')} value={d.nudging.length ? d.nudging.join(', ') : '—'} />
            <Row label={t('mount.guideRate')} value={d.guide_rate != null ? t('mount.guideRateValue', { rate: d.guide_rate }) : '—'} />
            <Row label={t('mount.pulse')} value={d.pulsing.length ? d.pulsing.join(', ') : '—'} />
            <Row
              label={t('mount.meridian')}
              value={d.meridian_limit_deg != null ? t('mount.meridianValue', { deg: d.meridian_limit_deg }) : '—'}
            />
            <Row
              label={t('mount.margin')}
              value={d.ra_axis_margin_deg != null
                ? (d.ra_axis_margin_deg < 0 ? t('mount.beyond', { deg: (-d.ra_axis_margin_deg).toFixed(1) }) : `${d.ra_axis_margin_deg.toFixed(1)}°`)
                : '—'}
            />
            <Row
              label={t('mount.site')}
              value={d.location
                ? `${d.location[0].toFixed(4)}°, ${d.location[1].toFixed(4)}°, ${d.location[2].toFixed(0)} m`
                : t('mount.noSite')}
            />
            <Row label={t('mount.parked')} value={d.parked ? t('mount.yes') : t('mount.no')} />
            <Row
              label={t('mount.park')}
              value={d.park_counts ? d.park_counts.map((c) => c.toLocaleString()).join(' / ') : '—'}
            />
            <Row
              label={t('mount.sync')}
              value={d.sync_offset
                ? t('mount.syncValue', { ra: (d.sync_offset.ra_axis_h * 60).toFixed(2), dec: d.sync_offset.dec_axis_deg.toFixed(3) })
                : t('mount.noSync')}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(d.axes).map(([name, axis]) => (
              <AxisCard key={name} name={name} axis={axis} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SettingsCard() {
  const { t } = useTranslation('eqmod')
  const [settings, setSettings] = useState<EqmodSettings | null>(null)
  const [proxy, setProxy] = useState<IndiProxyStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSettings().then(setSettings).catch((e: Error) => setError(e.message))
    let cancelled = false
    const loadProxy = () => getIndiProxy().then((p) => { if (!cancelled) setProxy(p) }).catch(() => {})
    loadProxy()
    const id = setInterval(loadProxy, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Always save the whole object: a partial PUT would reset the other fields to defaults.
  const save = async () => {
    if (settings === null) return
    setSaving(true)
    setError(null)
    try {
      setSettings(await putSettings(settings))
      setProxy(await getIndiProxy())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const proxyState = !proxy ? '—'
    : !proxy.enabled ? t('settings.proxyState.disabled')
    : !proxy.indi_available ? t('settings.proxyState.unavailable')
    : proxy.loaded ? t('settings.proxyState.loaded')
    : proxy.indiserver_running ? t('settings.proxyState.registered')
    : t('settings.proxyState.pending')

  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-4 text-sm">
      <p className="text-slate-300 font-medium">{t('settings.title')}</p>
      <div className="flex items-center gap-3">
        <span className="text-slate-400 w-40">{t('settings.led')}</span>
        <input
          type="range" min={0} max={100}
          value={settings?.led_brightness ?? 0}
          disabled={settings === null}
          onChange={(e) => settings && setSettings({ ...settings, led_brightness: Number(e.target.value) })}
          className="flex-1"
        />
        <span className="font-mono text-slate-200 w-10 text-right">{settings?.led_brightness ?? '—'}%</span>
      </div>

      <div className="flex flex-col gap-2 border-t border-surface-border pt-4">
        <div className="flex items-center gap-3">
          <ToggleSwitch
            checked={settings?.indi_proxy_enabled ?? false}
            disabled={settings === null}
            onChange={() => settings && setSettings({ ...settings, indi_proxy_enabled: !settings.indi_proxy_enabled })}
            label={t('settings.proxy')}
          />
          <span className="text-slate-300">{t('settings.proxy')}</span>
          <span className="text-xs text-slate-500 ml-auto">{proxyState}</span>
        </div>
        <label className="flex items-center gap-3 text-xs">
          <span className="text-slate-500 w-40">{t('settings.apiUrl')}</span>
          <Input
            value={settings?.indi_proxy_api_url ?? ''}
            disabled={settings === null}
            onChange={(e) => settings && setSettings({ ...settings, indi_proxy_api_url: e.target.value })}
            className="font-mono"
          />
        </label>
        <div className="text-xs text-slate-500 space-y-1">
          <p><Trans t={t} i18nKey="settings.help1" values={{ name: proxy?.device_name ?? 'astrolol Mount Proxy' }} components={MONO} /></p>
          <p><Trans t={t} i18nKey="settings.help2" components={MONO} /></p>
          <p><Trans t={t} i18nKey="settings.help3" components={MONO} /></p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="button" size="sm" disabled={settings === null || saving} onClick={save}>
          {saving ? t('settings.saving') : t('settings.save')}
        </Button>
        {error && <span className="text-xs text-status-error">{error}</span>}
      </div>
    </div>
  )
}

function BluetoothConnectHelper() {
  const { t } = useTranslation('eqmod')
  const [mountItems, setMountItems] = useState<MountEquipmentItem[] | null>(null)
  const [itemId, setItemId] = useState<string | null>(null)
  const [deviceId, setDeviceId] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    api.inventory
      .list()
      .then((items) => {
        const mounts = items.filter(
          (i): i is MountEquipmentItem => i.type === 'mount' && i.adapter_key === 'eqmod',
        )
        setMountItems(mounts)
        setItemId((current) => current ?? mounts[0]?.id ?? null)
      })
      .catch((e: Error) => setError(e.message))

  useEffect(() => {
    load()
  }, [])

  const item = mountItems?.find((i) => i.id === itemId) ?? null

  const apply = async () => {
    if (!item || !deviceId) return
    setStatus('saving')
    setError(null)
    try {
      // Bluetooth and serial are mutually exclusive transports: drop port/baudrate
      // when switching a mount over to a paired Bluetooth device.
      const { port: _port, baudrate: _baudrate, ...rest } = item.connect_params
      await api.inventory.update({
        ...item,
        connect_params: { ...rest, bluetooth_device_id: deviceId },
      })
      setStatus('saved')
      await load()
    } catch (e) {
      setError((e as Error).message)
      setStatus('error')
    }
  }

  return (
    <div className="bg-surface-raised border border-surface-border rounded p-4 flex flex-col gap-2 text-sm">
      <p className="text-slate-300 font-medium">{t('bt.title')}</p>
      <p className="text-xs text-slate-500">
        <Trans t={t} i18nKey="bt.intro" components={MONO} />
      </p>
      {error && <p className="text-xs text-status-error">{error}</p>}
      {mountItems !== null && mountItems.length === 0 && (
        <p className="text-xs text-slate-500">
          <Trans t={t} i18nKey="bt.noMount" components={MONO} />
        </p>
      )}
      {mountItems !== null && mountItems.length > 0 && (
        <div className="flex flex-col gap-2">
          {mountItems.length > 1 && (
            <select
              value={itemId ?? ''}
              onChange={(e) => setItemId(e.target.value)}
              className="w-full rounded bg-surface-overlay border border-surface-border px-3 py-1.5 text-sm text-slate-200"
            >
              {mountItems.map((i) => (
                <option key={i.id} value={i.id}>{i.name}</option>
              ))}
            </select>
          )}
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <BluetoothDevicePicker value={deviceId} onChange={setDeviceId} />
            </div>
            <Button size="sm" disabled={!deviceId || status === 'saving'} onClick={apply}>
              {status === 'saving' ? t('bt.applying') : t('bt.apply')}
            </Button>
          </div>
          {item && (
            <p className="text-xs text-slate-500">
              <Trans t={t} i18nKey="bt.appliesTo" values={{ name: item.name }} components={MONO} />
              {typeof item.connect_params.bluetooth_device_id === 'string' && (
                <Trans t={t} i18nKey="bt.currently" values={{ id: item.connect_params.bluetooth_device_id }} components={MONO} />
              )}
              .
            </p>
          )}
          {status === 'saved' && (
            <p className="text-xs text-emerald-400">
              {t('bt.saved')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function EqmodPage() {
  const { t } = useTranslation('eqmod')
  const [mounts, setMounts] = useState<MountDiagnostics[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      getDiagnostics()
        .then((d) => { if (!cancelled) { setMounts(d); setError(null) } })
        .catch((e: Error) => { if (!cancelled) setError(e.message) })
    load()
    const id = setInterval(load, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return (
    <div className="p-6 max-w-4xl flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-slate-100">{t('page.title')}</h1>
      {error && <p className="text-xs text-status-error">{error}</p>}
      {mounts !== null && mounts.length === 0 && (
        <div className="text-sm text-slate-500 space-y-1">
          <p>{t('page.none')}</p>
          <p className="text-xs">
            <Trans t={t} i18nKey="page.howto" values={{ params: '{"port": "/dev/ttyUSB0"}' }} components={MONO} />
          </p>
        </div>
      )}
      {mounts?.map((d) => <MountCard key={d.device_id} d={d} />)}
      <BluetoothConnectHelper />
      <SettingsCard />
    </div>
  )
}
