import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { fmtRA, fmtDec } from '@/utils/formatting'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Crosshair, RefreshCw, RotateCw, Settings, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type { CoordFrame, DeviceProperty, MountDeviceSettings, OpticalPath, TrackingMode } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DmsInput } from '@/components/ui/dms-input'
import { StateBadge } from '@/components/ui/badge'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Card } from '@/components/ui/card'
import { EquatorialSky } from '@/components/ui/mount-equatorial'
import { HorizontalSky } from '@/components/ui/mount-horizontal'
import { PillGroup } from '@/components/ui/pill-group'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { EventLog } from '@/components/ui/event-log'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_MOVE_RATES = ['guide', 'centering', 'find', 'max']

/** Extract rate options from a TELESCOPE_SLEW_RATE switch property. */
function slewRatesFromProperty(prop: DeviceProperty): { label: string; rate: string }[] {
  return prop.widgets.map((w) => ({ label: String(w.label || w.name), rate: String(w.name) }))
}

const TRACKING_MODES: TrackingMode[] = ['sidereal', 'lunar', 'solar']

// ---------------------------------------------------------------------------
// Pure formatting helpers
// ---------------------------------------------------------------------------

function fmtHA(ha: number | null | undefined): string {
  if (ha == null) return '—'
  const sign = ha >= 0 ? '+' : '−'
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  if (h === 0) return `${sign}${m}m`
  return `${sign}${h}h ${String(m).padStart(2, '0')}m`
}

function fmtMeridianDistance(ha: number, t: TFunction): string {
  const abs = Math.abs(ha)
  const h = Math.floor(abs)
  const m = Math.floor((abs - h) * 60)
  const parts = h > 0 ? `${h}h ${m}m` : `${m}m`
  return t(ha < 0 ? 'meridianDistance.before' : 'meridianDistance.after', { time: parts })
}

// ---------------------------------------------------------------------------
// Helpers for HH:MM ↔ decimal-hours conversion (used for HA threshold)
// ---------------------------------------------------------------------------

function hoursToHHMM(h: number): string {
  const hours = Math.floor(Math.max(0, h))
  const mins  = Math.round((h - hours) * 60)
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

function hhmmToHours(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return (h || 0) + (m || 0) / 60
}

const DEFAULT_MOUNT_SETTINGS: MountDeviceSettings = {
  auto_park_enabled: false,
  auto_park_time: null,
  auto_flip_enabled: false,
  auto_flip_ha_hours: 1.0,
  meridian_limit_deg: 20,
  horizon_min_alt_deg: 0,
  horizon_action: 'stop_tracking',
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Small degrees field: edits freely, commits a clamped value on blur / Enter. */
function DegreesInput({ value, min, max, onCommit }: {
  value: number
  min: number
  max: number
  onCommit: (v: number) => void
}) {
  const [raw, setRaw] = useState<string | null>(null)
  const commit = () => {
    const n = parseFloat(raw ?? '')
    if (!isNaN(n)) onCommit(Math.min(max, Math.max(min, n)))
    setRaw(null)
  }
  return (
    <input
      type="number" min={min} max={max} step="any"
      value={raw ?? String(value)}
      onChange={(e) => setRaw(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setRaw(null) }}
      className="w-16 rounded-lg border border-surface-border bg-surface px-2 py-0.5 text-xs text-slate-200 font-mono
        focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
    />
  )
}

function FrameToggle({ jnow, onChange }: { jnow: boolean; onChange: (jnow: boolean) => void }) {
  const btn = (label: string, active: boolean, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      className={`text-xs px-1.5 py-0.5 rounded transition-colors
        ${active ? 'bg-surface-overlay text-slate-200' : 'text-slate-600 hover:text-slate-400'}`}
    >
      {label}
    </button>
  )
  return (
    <div className="flex items-center gap-0.5 ml-auto">
      {btn('JNow', jnow, () => onChange(true))}
      {btn('J2000', !jnow, () => onChange(false))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main controls component (rendered when a mount is connected)
// ---------------------------------------------------------------------------

function MountControls({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation('mount')
  const status = useStore((s) => s.mountStatuses[deviceId] ?? null)
  const [showIndiPanel, setShowIndiPanel] = useState(false)
  // The observing site this mount is attached to (from the active profile's equipment tree).
  const [opticalPaths, setOpticalPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setOpticalPaths).catch(() => setOpticalPaths([]))
  }, [])
  const [skyView, setSkyView] = useLocalStorage<'equatorial' | 'horizontal'>('astrolol.mountSky', 'equatorial')

  const [slewRa, setSlewRa] = useState(0)
  const [slewDec, setSlewDec] = useState(0)
  const slewEdited = useRef(false)

  const [rateIdx, setRateIdx] = useState(1)
  const [trackingMode, setTrackingMode] = useState<TrackingMode>('sidereal')
  const [positionJnow, setPositionJnow] = useState(true)   // Position section: default JNow
  const [targetJnow, setTargetJnow] = useState(false)      // Target section: default J2000
  const [error, setError] = useState<string | null>(null)
  const movingRef = useRef(false)

  const [mountSettings, setMountSettings] = useState<MountDeviceSettings>(DEFAULT_MOUNT_SETTINGS)
  const [slewRateProp, setSlewRateProp] = useState<DeviceProperty | null>(null)

  // Load mount settings and slew rate property on first render
  useEffect(() => {
    api.mount.getSettings(deviceId)
      .then(setMountSettings)
      .catch(() => {/* use defaults */})
    api.devices.properties(deviceId)
      .then((props) => {
        const prop = props.find((p) => p.name === 'TELESCOPE_SLEW_RATE')
        setSlewRateProp(prop ?? null)
      })
      .catch(() => {/* fall back to defaults */})
  }, [deviceId])

  const moveRates = useMemo(
    () => slewRateProp
      ? slewRatesFromProperty(slewRateProp)
      : DEFAULT_MOVE_RATES.map((rate) => ({ label: t(`rates.${rate}`), rate })),
    [slewRateProp, t],
  )

  const saveMountSettings = useCallback((updated: MountDeviceSettings) => {
    setMountSettings(updated)
    api.mount.putSettings(deviceId, updated).catch(() => {})
  }, [deviceId])

  // Keep target inputs in sync with live position when the user hasn't edited them
  useEffect(() => {
    if (status && !slewEdited.current) {
      setSlewRa(targetJnow ? (status.ra_jnow ?? 0) : (status.ra ?? 0))
      setSlewDec(targetJnow ? (status.dec_jnow ?? 0) : (status.dec ?? 0))
    }
  }, [status, targetJnow])

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }, [])

  const handleMoveStart = useCallback(async (direction: string) => {
    if (movingRef.current) return
    movingRef.current = true
    const rate = moveRates[Math.min(rateIdx, moveRates.length - 1)]?.rate ?? 'centering'
    await act(() => api.mount.startMove(deviceId, direction, rate))
  }, [deviceId, rateIdx, moveRates, act])

  const handleMoveStop = useCallback(async () => {
    if (!movingRef.current) return
    movingRef.current = false
    await act(() => api.mount.stopMove(deviceId))
  }, [deviceId, act])

  const isTracking = status?.is_tracking ?? false
  const isParked   = status?.is_parked   ?? false
  const isSlewing  = status?.is_slewing  ?? false
  const ha         = status?.hour_angle ?? null
  const lst        = status?.lst ?? null
  const site       = opticalPaths.find((p) => p.mount_device_id === deviceId)?.site ?? null
  // The sidereal time is apparent (of date), so pair it with the JNow position.
  const skyRa      = status?.ra_jnow ?? status?.ra ?? null
  const skyDec     = status?.dec_jnow ?? status?.dec ?? null
  // A flip is due when the OTA is on the pier side meant for the other half of the sky
  // (East = looking west, normal for HA >= 0; West = looking east, normal for HA < 0), like
  // MountManager.meridian_flip_due. Flipping from the normal side would raise the counterweight.
  // Without a reported pier side, fall back to "past the meridian, by at most 2 h".
  const pierSide   = status?.pier_side ?? null
  const pierSideLabel = pierSide ? t(`pier.${pierSide}`, { defaultValue: pierSide }) : ''
  const flipDue: boolean | null = ha != null && pierSide != null
    ? pierSide !== ((((ha + 12) % 24 + 24) % 24 - 12) >= 0 ? 'East' : 'West')
    : null
  const canFlip    = ha != null && !isParked && !isSlewing && (flipDue ?? (ha > 0 && ha <= 2.0))

  // Common props for d-pad buttons (hold to move)
  const dpadBtn = (dir: string, title: string) => ({
    onMouseDown: () => handleMoveStart(dir),
    onMouseUp: handleMoveStop,
    onMouseLeave: handleMoveStop,
    onTouchStart: (e: React.TouchEvent) => { e.preventDefault(); handleMoveStart(dir) },
    onTouchEnd: handleMoveStop,
    disabled: !status || isParked,
    title,
  })

  return (
    <div className="h-full flex flex-col">
    <div className="flex-1 overflow-y-auto p-4">
      <div className="max-w-md mx-auto flex flex-col gap-4">

        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-slate-200 font-semibold truncate">{deviceId}</h2>
          <div className="flex items-center gap-2">
            {isSlewing && (
              <span className="text-xs text-yellow-400 animate-pulse">{t('slewing')}</span>
            )}
            {status && <StateBadge state={status.state} />}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowIndiPanel((v) => !v)}
              title={t('indiProps')}
              className={showIndiPanel ? 'text-accent' : ''}
            >
              <Settings size={15} />
            </Button>
          </div>
        </div>
        {showIndiPanel && (
          <DevicePropertiesPanel deviceId={deviceId} onClose={() => setShowIndiPanel(false)} />
        )}

        {/* Live position */}
        <Card title={t('position.title')} action={<FrameToggle jnow={positionJnow} onChange={setPositionJnow} />} className="p-4 flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-x-8 gap-y-1 font-mono text-sm">
            <span className="text-slate-500 text-xs">{t('position.ra')}</span>
            <span className="text-slate-500 text-xs">{t('position.dec')}</span>
            <span className="text-slate-200">{fmtRA(positionJnow ? status?.ra_jnow : status?.ra)}</span>
            <span className="text-slate-200">{fmtDec(positionJnow ? status?.dec_jnow : status?.dec)}</span>
            <span className="text-slate-500 text-xs mt-1">{t('position.alt')}</span>
            <span className="text-slate-500 text-xs mt-1">{t('position.az')}</span>
            <span className="text-slate-300">{status?.alt != null ? `${status.alt.toFixed(1)}°` : '—'}</span>
            <span className="text-slate-300">{status?.az  != null ? `${status.az.toFixed(1)}°`  : '—'}</span>
            <span className="text-slate-500 text-xs mt-1">{t('position.ha')}</span>
            <span className="text-slate-500 text-xs mt-1">{t('position.lst')}</span>
            <span className="text-slate-300">{fmtHA(ha)}</span>
            <span className="text-slate-300">{lst != null ? fmtRA(lst) : '—'}</span>
            <span className="text-slate-500 text-xs mt-1">{t('position.pier')}</span>
            <span className="text-slate-500 text-xs mt-1" />
            <span className="text-slate-300">{status?.pier_side ? t(`pier.${status.pier_side}`, { defaultValue: status.pier_side }) : '—'}</span>
            <span />
          </div>
          {site && lst != null && skyRa != null && skyDec != null && (
            <div className="flex flex-col gap-2 border-t border-surface-border pt-3">
              <div className="md:hidden">
                <PillGroup
                  options={['equatorial', 'horizontal'] as const}
                  value={skyView}
                  onChange={setSkyView}
                  formatLabel={(v) => t(`sky.${v}`)}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className={`${skyView === 'equatorial' ? '' : 'hidden'} md:block`}>
                  <EquatorialSky latitude={site.latitude} lst={lst} ra={skyRa} dec={skyDec} label={t('sky.equatorial')} className="mx-auto w-full max-w-[340px]" />
                </div>
                <div className={`${skyView === 'horizontal' ? '' : 'hidden'} md:block`}>
                  <HorizontalSky latitude={site.latitude} lst={lst} ra={skyRa} dec={skyDec} label={t('sky.horizontal')} className="mx-auto w-full max-w-[340px]" />
                </div>
              </div>
              <p className="flex flex-wrap gap-x-3 font-mono text-[11px] text-slate-500">
                <span><span className="text-accent">{'●'}</span> {t('sky.mount')}</span>
                <span><span className="text-slate-500">{'●'}</span> {t('sky.pole')}</span>
                <span>{'+'} {t('sky.zenith')}</span>
              </p>
            </div>
          )}
        </Card>

        {/* Target */}
        <Card title={t('target.title')} action={<FrameToggle jnow={targetJnow} onChange={setTargetJnow} />} className="p-4 flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 w-8 shrink-0">{t('position.ra')}</span>
              <DmsInput value={slewRa} onChange={(v) => { slewEdited.current = true; setSlewRa(v) }} mode="ra" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 w-8 shrink-0">{t('position.dec')}</span>
              <DmsInput value={slewDec} onChange={(v) => { slewEdited.current = true; setSlewDec(v) }} mode="lat" />
            </div>
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            <Button size="sm" variant="outline" onClick={() => {
              const frame: CoordFrame = targetJnow ? 'jnow' : 'icrs'
              act(() => api.mount.setTarget(deviceId, slewRa * 15, slewDec, undefined, undefined, frame))
            }}>
              <Crosshair size={12} className="mr-1" /> {t('target.set')}
            </Button>
            <Button size="sm" onClick={() => act(async () => {
              const frame: CoordFrame = targetJnow ? 'jnow' : 'icrs'
              await api.mount.setTarget(deviceId, slewRa * 15, slewDec, undefined, undefined, frame)
              await api.mount.slew(deviceId)
            })}>
              {t('target.slew')}
            </Button>
            <Button size="sm" variant="outline" onClick={() => act(() => api.mount.sync(deviceId, slewRa * 15, slewDec))}>
              <RotateCw size={12} className="mr-1" /> {t('target.sync')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => act(() => api.mount.stop(deviceId))}>
              <StopCircle size={12} className="mr-1" /> {t('target.stop')}
            </Button>
            {slewEdited.current && (
              <button
                type="button"
                className="ml-auto text-xs text-slate-500 hover:text-slate-300 transition-colors"
                onClick={() => {
                  slewEdited.current = false
                  const ra = targetJnow ? (status?.ra_jnow ?? 0) : (status?.ra ?? 0)
                  const dec = targetJnow ? (status?.dec_jnow ?? 0) : (status?.dec ?? 0)
                  setSlewRa(ra)
                  setSlewDec(dec)
                }}
              >
                {t('target.live')}
              </button>
            )}
          </div>
        </Card>

        {/* Tracking */}
        <Card title={t('trackingCard.title')} className="p-4 flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <ToggleSwitch
              checked={isTracking}
              label={t('trackingCard.toggle')}
              disabled={isParked}
              onChange={() => act(() => api.mount.setTracking(deviceId, !isTracking, isTracking ? undefined : trackingMode))}
            />
            <span className="text-sm text-slate-300 w-6">{isTracking ? t('trackingCard.on') : t('trackingCard.off')}</span>
            <select
              disabled={isParked}
              className="ml-auto rounded-lg bg-surface border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-accent disabled:opacity-40 disabled:cursor-not-allowed"
              value={trackingMode}
              onChange={(e) => {
                const m = e.target.value as TrackingMode
                setTrackingMode(m)
                act(() => api.mount.setTracking(deviceId, true, m))
              }}
            >
              {TRACKING_MODES.map((mode) => <option key={mode} value={mode}>{t(`tracking.${mode}`)}</option>)}
            </select>
          </div>
          {isParked
            ? <p className="text-xs text-slate-500">{t('trackingCard.unpark')}</p>
            : <p className="text-xs text-slate-600">{t('trackingCard.firmware')}</p>
          }
        </Card>

        {/* Park */}
        <Card title={t('park.title')} className="p-4 flex flex-col gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <Button
              size="sm"
              variant={isParked ? 'default' : 'outline'}
              onClick={() => act(isParked
                ? () => api.mount.unpark(deviceId)
                : () => api.mount.park(deviceId)
              )}
            >
              {isParked ? t('park.unpark') : t('park.park')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={isParked}
              onClick={() => act(() => api.mount.setParkPosition(deviceId))}
              title={t('park.setPositionTitle')}
            >
              {t('park.setPosition')}
            </Button>
            {isParked && <span className="text-xs text-slate-500">{t('park.parked')}</span>}
          </div>
          <label className="flex items-center gap-2 flex-wrap">
            <input
              type="checkbox"
              className="accent-accent"
              checked={mountSettings.auto_park_enabled}
              onChange={(e) => saveMountSettings({ ...mountSettings, auto_park_enabled: e.target.checked })}
            />
            <span className="text-xs text-slate-400">{t('park.auto')}</span>
            <input
              type="time"
              disabled={!mountSettings.auto_park_enabled}
              value={mountSettings.auto_park_time ?? '06:00'}
              onChange={(e) => saveMountSettings({ ...mountSettings, auto_park_time: e.target.value })}
              className="rounded-lg border border-surface-border bg-surface px-2 py-0.5 text-xs text-slate-200 font-mono
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent disabled:opacity-40 disabled:cursor-not-allowed"
            />
            <span className="text-xs text-slate-600">{t('park.localTime')}</span>
          </label>
        </Card>

        {/* Meridian */}
        <Card title={t('meridian.title')} className="p-4 flex flex-col gap-3">
          {ha != null && (
            <p className="text-xs text-slate-500">{fmtMeridianDistance(ha, t)}</p>
          )}
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={!canFlip}
              onClick={() => act(() => api.mount.meridianFlip(deviceId))}
              title={
                canFlip            ? t('meridian.flipTitle') :
                ha == null         ? t('meridian.haUnknown') :
                flipDue === false  ? t('meridian.wrongSide', { side: pierSideLabel }) :
                ha <= 0            ? t('meridian.notCrossed') :
                                     t('meridian.tooFar')
              }
            >
              <RefreshCw size={12} className="mr-1.5" /> {t('meridian.flip')}
            </Button>
            {ha != null && !canFlip && flipDue === false && (
              <span className="text-xs text-slate-600">
                {ha >= 0 ? t('meridian.noFlip', { side: pierSideLabel }) : t('meridian.waiting')}
              </span>
            )}
            {ha != null && !canFlip && flipDue === null && ha <= 0 && (
              <span className="text-xs text-slate-600">{t('meridian.waiting')}</span>
            )}
            {ha != null && !canFlip && flipDue === null && ha > 2.0 && (
              <span className="text-xs text-yellow-700">{t('meridian.slewFirst')}</span>
            )}
          </div>
          <label className="flex items-center gap-2 flex-wrap">
            <input
              type="checkbox"
              className="accent-accent"
              checked={mountSettings.auto_flip_enabled}
              onChange={(e) => saveMountSettings({ ...mountSettings, auto_flip_enabled: e.target.checked })}
            />
            <span className="text-xs text-slate-400">{t('meridian.autoFlip')}</span>
            <input
              type="time"
              disabled={!mountSettings.auto_flip_enabled}
              value={hoursToHHMM(mountSettings.auto_flip_ha_hours)}
              onChange={(e) => saveMountSettings({ ...mountSettings, auto_flip_ha_hours: hhmmToHours(e.target.value) })}
              className="rounded-lg border border-surface-border bg-surface px-2 py-0.5 text-xs text-slate-200 font-mono
                focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent disabled:opacity-40 disabled:cursor-not-allowed"
            />
          </label>
          <div
            className="flex items-center gap-2 flex-wrap"
            title={t('meridian.limitTitle')}
          >
            <span className="text-xs text-slate-400">{t('meridian.limit')}</span>
            <DegreesInput
              value={mountSettings.meridian_limit_deg}
              min={0} max={60}
              onCommit={(v) => saveMountSettings({ ...mountSettings, meridian_limit_deg: v })}
            />
            <span className="text-xs text-slate-600">{t('meridian.limitUnit', { time: hoursToHHMM(mountSettings.meridian_limit_deg / 15) })}</span>
          </div>
          <div
            className="flex items-center gap-2 flex-wrap"
            title={t('meridian.horizonTitle')}
          >
            <span className="text-xs text-slate-400">{t('meridian.horizon')}</span>
            <DegreesInput
              value={mountSettings.horizon_min_alt_deg}
              min={-10} max={60}
              onCommit={(v) => saveMountSettings({ ...mountSettings, horizon_min_alt_deg: v })}
            />
            <span className="text-xs text-slate-600">{t('meridian.horizonUnit')}</span>
            <select
              className="rounded-lg bg-surface border border-surface-border px-2 py-0.5 text-xs text-slate-200 focus:outline-none focus:border-accent"
              value={mountSettings.horizon_action}
              onChange={(e) => saveMountSettings({
                ...mountSettings, horizon_action: e.target.value as MountDeviceSettings['horizon_action'],
              })}
            >
              <option value="stop_tracking">{t('meridian.stopTracking')}</option>
              <option value="park">{t('meridian.park')}</option>
              <option value="none">{t('meridian.nothing')}</option>
            </select>
          </div>
        </Card>

        {/* Nudge */}
        <Card title={t('nudge.title')} className="p-4 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">{t('nudge.rate')}</span>
            <select
              className="rounded-lg bg-surface border border-surface-border px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-accent"
              value={rateIdx}
              onChange={(e) => setRateIdx(parseInt(e.target.value))}
            >
              {moveRates.map((s, i) => <option key={s.rate} value={i}>{s.label}</option>)}
            </select>
            <span className="text-xs text-slate-600 ml-2">{t('nudge.hold')}</span>
          </div>
          {/* D-pad */}
          <div className="flex flex-col items-center gap-1 self-center select-none">
            <Button size="icon" variant="outline" {...dpadBtn('N', t('nudge.north'))} >
              <ArrowUp size={16} />
            </Button>
            <div className="flex gap-8">
              <Button size="icon" variant="outline" {...dpadBtn('W', t('nudge.west'))} >
                <ArrowLeft size={16} />
              </Button>
              <Button size="icon" variant="outline" {...dpadBtn('E', t('nudge.east'))} >
                <ArrowRight size={16} />
              </Button>
            </div>
            <Button size="icon" variant="outline" {...dpadBtn('S', t('nudge.south'))} >
              <ArrowDown size={16} />
            </Button>
          </div>
        </Card>

        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </div>
    <EventLog filter={['mount', 'indi']} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page entry point
// ---------------------------------------------------------------------------

export function Mount() {
  const { t } = useTranslation('mount')
  const mounts = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))

  if (mounts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
        <span className="text-sm">{t('none.title')}</span>
        <span className="text-xs">{t('none.hint')}</span>
      </div>
    )
  }

  return <MountControls deviceId={mounts[0].device_id} />
}
