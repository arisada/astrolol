import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Crosshair, Pause, Play, Settings, Square, Target, Wifi, WifiOff } from 'lucide-react'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Card } from '@/components/ui/card'
import { EventLog } from '@/components/ui/event-log'
import { GuideGraph } from '@/components/ui/guide-graph'
import type { Phd2Settings } from '@/api/types'
import * as phd2Api from './api'
import type { Phd2PluginState } from './api'
import { DEFAULT_PHD2_STATE } from './api'

// ── Graph options ──────────────────────────────────────────────────────────────

const GRAPH_SCALES: Array<{ label: string; range: number }> = [
  { label: '±0.5"', range: 1.0 },
  { label: '±1"',   range: 2.0 },
  { label: '±2"',   range: 4.0 },
  { label: '±3"',   range: 6.0 },
]

const SAMPLE_OPTIONS = [50, 100, 200, 500]

// ── Helpers ───────────────────────────────────────────────────────────────────

function lsGet(key: string, fallback: string): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function lsSet(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* ignore */ }
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StateBadge({ state, connected }: { state: string; connected: boolean }) {
  const { t } = useTranslation('phd2')
  const colour = !connected
    ? 'text-slate-500 border-slate-700'
    : state === 'Guiding'
      ? 'text-green-400 border-green-700'
      : state === 'Paused'
        ? 'text-yellow-400 border-yellow-700'
        : state === 'Star loss'
          ? 'text-red-400 border-red-700'
          : 'text-slate-400 border-slate-600'

  return (
    <span className={`text-xs font-mono px-2 py-0.5 rounded border ${colour}`}>
      {connected ? t(`state.${state.toLowerCase().replace(' ', '_')}`, { defaultValue: state }) : t('state.disconnected')}
    </span>
  )
}

// ── Metric row ────────────────────────────────────────────────────────────────

function Metric({ label, value, unit }: { label: string; value: number | null | undefined; unit?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-mono text-slate-200">
        {value != null ? `${value.toFixed(3)}${unit ?? ''}` : '—'}
      </span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

// TODO: audit Connect/Disconnect button style against Equipment page for consistency

export function Phd2Page() {
  const { t } = useTranslation('phd2')
  const allGuidePoints = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null)?.guidePoints ?? [])
  const status         = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null)?.status ?? null)

  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)

  // Connection settings (persisted via backend plugin settings)
  const [phd2Settings, setPhd2Settings] = useState<Phd2Settings>({ host: 'localhost', port: 4400 })
  const [settingsSaving, setSettingsSaving] = useState(false)
  useEffect(() => {
    phd2Api.getSettings()
      .then((s) => setPhd2Settings({ host: s.host ?? 'localhost', port: s.port ?? 4400 }))
      .catch(() => {})
  }, [])
  const savePhd2Settings = async () => {
    setSettingsSaving(true)
    try { await phd2Api.putSettings(phd2Settings) } catch { /* ignore */ } finally { setSettingsSaving(false) }
  }

  // UI preferences persisted via localStorage (graph display only — not server state)
  const [graphRange, setGraphRange] = useState(() =>
    parseFloat(lsGet('phd2_graph_range', '2.0'))
  )
  const [maxSamples, setMaxSamples] = useState(() =>
    parseInt(lsGet('phd2_max_samples', '100'), 10)
  )

  // Debug state: server is the source of truth (returned in status.debug_enabled).
  // Optimistic local copy so the toggle feels instant; reverts on API error.
  // When the server restarts (debug_enabled resets to false), the next status poll
  // updates this automatically — no stale localStorage involved.
  const [debugEnabled, setDebugEnabled] = useState(false)
  useEffect(() => {
    if (status != null) setDebugEnabled(status.debug_enabled)
  }, [status?.debug_enabled])  // eslint-disable-line react-hooks/exhaustive-deps

  // Slice the store's large ring buffer to the user-configured window
  const guidePoints = allGuidePoints.slice(-maxSamples)

  // Poll /phd2/status every 3 s to get RMS values (not emitted via WS)
  useEffect(() => {
    const poll = () => {
      phd2Api.status()
        .then((newStatus) => {
          useStore.setState((s) => {
            const cur = (s.pluginStates['phd2'] as Phd2PluginState | null) ?? DEFAULT_PHD2_STATE
            return { pluginStates: { ...s.pluginStates, phd2: { ...cur, status: newStatus } } }
          })
        })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3_000)
    return () => clearInterval(id)
  }, [])

  const act = async (fn: () => Promise<void>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  const toggleDebug = async () => {
    const next = !debugEnabled
    setDebugEnabled(next)   // optimistic
    try {
      await phd2Api.setDebug(next)
    } catch (e) {
      setDebugEnabled(!next)  // revert on error
      setError((e as Error).message)
    }
  }

  const handleGraphRangeChange = (range: number) => {
    setGraphRange(range)
    lsSet('phd2_graph_range', String(range))
  }

  const handleMaxSamplesChange = (n: number) => {
    setMaxSamples(n)
    lsSet('phd2_max_samples', String(n))
  }

  const guiding    = status?.state === 'Guiding'
  const paused     = status?.state === 'Paused'
  const connected  = status?.connected ?? false
  const dithering  = status?.is_dithering ?? false

  return (
    <div className="flex flex-col h-full">
    <div className="p-4 max-w-2xl mx-auto w-full flex flex-col gap-4 flex-1 overflow-y-auto">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Crosshair size={20} className="text-accent" />
          <h1 className="text-base font-semibold text-slate-200">{t('title')}</h1>
          {status && <StateBadge state={status.state} connected={status.connected} />}
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={connected ? 'danger' : 'outline'}
            onClick={() => act(connected ? phd2Api.disconnect : phd2Api.connect)}
          >
            {connected
              ? <><WifiOff size={12} className="mr-1" /> {t('disconnect')}</>
              : <><Wifi size={12} className="mr-1" /> {t('connect')}</>
            }
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setShowSettings((v) => !v)}
            title={t('settingsTitle')}
            className={showSettings ? 'text-accent' : ''}
          >
            <Settings size={15} />
          </Button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <Card className="p-3 bg-surface-raised flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{t('settings.host')}</span>
            <Input
              inputSize="sm"
              className="!w-36"
              value={phd2Settings.host}
              onChange={(e) => setPhd2Settings((s) => ({ ...s, host: e.target.value }))}
              onBlur={savePhd2Settings}
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{t('settings.port')}</span>
            <Input
              inputSize="sm"
              type="number"
              className="!w-20"
              value={phd2Settings.port}
              onChange={(e) => setPhd2Settings((s) => ({ ...s, port: parseInt(e.target.value) || 4400 }))}
              onBlur={savePhd2Settings}
            />
          </div>
          {settingsSaving && <span className="text-xs text-slate-500">{t('settings.saving')}</span>}
          <div className="border-t border-surface-border" />
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{t('settings.scale')}</span>
            <select
              className="rounded-lg bg-surface border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-accent"
              value={graphRange}
              onChange={(e) => handleGraphRangeChange(parseFloat(e.target.value))}
            >
              {GRAPH_SCALES.map(({ label, range }) => (
                <option key={range} value={range}>{label}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{t('settings.samples')}</span>
            <select
              className="rounded-lg bg-surface border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-accent"
              value={maxSamples}
              onChange={(e) => handleMaxSamplesChange(parseInt(e.target.value, 10))}
            >
              {SAMPLE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">{t('settings.debug')}</p>
              <p className="text-xs text-slate-600">{t('settings.debugHint')}</p>
            </div>
            <ToggleSwitch checked={debugEnabled} onChange={toggleDebug} label={t('settings.debug')} />
          </div>
        </Card>
      )}

      {/* Guide graph — full available width */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised">
        <p className="text-xs text-slate-500 mb-2">{t('graph.title')}</p>
        <GuideGraph points={guidePoints} range={graphRange} rmsTotal={status?.rms_total} />
      </div>

      {/* Metrics */}
      <div className="border border-surface-border rounded p-3 bg-surface-raised flex flex-col gap-1.5">
        <Metric label={t('metrics.rmsRa')}      value={status?.rms_ra}    unit={'"'} />
        <Metric label={t('metrics.rmsDec')}     value={status?.rms_dec}   unit={'"'} />
        <Metric label={t('metrics.rmsAvg')} value={status?.rms_total} unit={'"'} />
        <div className="border-t border-surface-border my-1" />
        <Metric label={t('metrics.snr')} value={status?.star_snr} />
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500">{t('metrics.pixelScale')}</span>
          <span className="text-xs font-mono text-slate-200">
            {status?.pixel_scale != null ? `${status.pixel_scale.toFixed(2)}" /px` : '—'}
          </span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-2">
        <div className="flex gap-2 flex-wrap">
          <Button
            size="sm"
            onClick={() => act(() => phd2Api.guide())}
            disabled={!connected || (guiding && !paused)}
          >
            <Play size={12} className="mr-1" /> {t('controls.guide')}
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(paused ? phd2Api.resume : phd2Api.pause)}
            disabled={!connected || (!guiding && !paused)}
          >
            {paused
              ? <><Play size={12} className="mr-1" /> {t('controls.resume')}</>
              : <><Pause size={12} className="mr-1" /> {t('controls.pause')}</>
            }
          </Button>

          <Button
            size="sm"
            variant="danger"
            onClick={() => act(phd2Api.stop)}
            disabled={!connected || (!guiding && !paused)}
          >
            <Square size={12} className="mr-1" /> {t('controls.stop')}
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => act(() => phd2Api.dither())}
            disabled={!connected || !guiding || dithering}
            title={dithering ? t('controls.ditherBusy') : t('controls.ditherOnce')}
          >
            <Target size={12} className="mr-1" />
            {dithering ? t('controls.dithering') : t('controls.dither')}
          </Button>
        </div>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>

      {!connected && (
        <p className="text-xs text-slate-500">
          {t('notConnected')}
        </p>
      )}
    </div>
    <EventLog filter={['phd2']} />
    </div>
  )
}
