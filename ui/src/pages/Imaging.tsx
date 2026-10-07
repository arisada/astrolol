import { forwardRef, useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Camera, ChevronDown, ChevronUp, Crosshair, Play, Settings, Square, StopCircle, Thermometer,
} from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import type {
  CameraStatus, DitherConfig, FilterWheelStatus, FrameType, ImagerDeviceSettings, OpticalPath,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { CoolingGauge } from '@/components/ui/cooling-gauge'
import { CountStepper } from '@/components/ui/count-stepper'
import { FocuserRuler } from '@/components/ui/focuser-ruler'
import { NumberStepper } from '@/components/ui/number-stepper'
import { Input } from '@/components/ui/input'
import { SidebarSection } from '@/components/ui/card'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { EventLog } from '@/components/ui/event-log'
import { PillGroup } from '@/components/ui/pill-group'
import { DevicePropertiesPanel } from '@/components/DevicePropertiesPanel'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import { LabeledSlider } from '@/components/ui/labeled-slider'
import { HistogramOverlay } from '@/components/ui/histogram'
import { ColorControls, StretchControls } from '@/components/ui/stretch-controls'
import { ZoomableImage, type ZoomableImageHandle } from '@/components/ui/zoomable-image'

// Dither cadence: 0 switches it off; setting one cadence clears the other.
const DITHER_FRAME_STEPS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30]
const DITHER_MINUTE_STEPS = [0, 1, 2, 3, 5, 10, 15, 20, 30, 45, 60]

// Focuser move sizes, 1 to 10000 steps.
const FOCUSER_STEP_SIZES = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]

const DEFAULT_IMAGER_SETTINGS: ImagerDeviceSettings = {
  duration: 5,
  binning: 1,
  frame_type: 'light',
  save_subs: true,
  dither_frames: '',
  dither_minutes: '',
  histo_auto: true,
  target_temp: '',
  jpeg_quality: 85,
  stretch_target_bg: 0.25,
  stretch_shadows_sigma: -2.8,
  preview_color: true,
  stretch_linked: false,
}

// ── Exposure duration helpers ─────────────────────────────────────────────────

const EXPOSURE_STEPS = [
  0.001, 0.002, 0.003, 0.004, 0.005, 0.008,
  0.01, 0.013, 0.015, 0.02, 0.025, 0.033, 0.04, 0.05,
  0.067, 0.08, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8,
  1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30,
  45, 60, 90, 120, 180, 240, 300, 360, 480, 600, 900, 1200, 1800, 3600,
]

// ── Shared sub-components ─────────────────────────────────────────────────────

function Panel({
  title, deviceId, onSettings, children,
}: {
  title: string
  deviceId?: string
  onSettings?: (id: string) => void
  children: React.ReactNode
}) {
  const { t } = useTranslation('imaging')
  const action = deviceId && onSettings ? (
    <button onClick={() => onSettings(deviceId)} title={t('indiProps')}
      className="text-slate-600 hover:text-slate-400 transition-colors">
      <Settings size={12} />
    </button>
  ) : null
  return (
    <SidebarSection title={title} action={action}>
      {children}
    </SidebarSection>
  )
}

function Foldable({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-t border-surface-border pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full text-xs text-slate-400 hover:text-slate-300"
      >
        <span>{label}</span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && <div className="flex flex-col gap-2 mt-2">{children}</div>}
    </div>
  )
}

function TogglePill({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  const { t } = useTranslation('imaging')
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`flex items-center justify-between w-full px-2 py-0.5 text-xs rounded border transition-colors
        ${value
          ? 'border-accent text-accent bg-accent/10'
          : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
        }`}
    >
      <span>{label}</span>
      <span className="text-slate-500">{value ? t('on') : t('off')}</span>
    </button>
  )
}

// ── Image Viewer ──────────────────────────────────────────────────────────────

export type ImageViewerHandle = ZoomableImageHandle

export interface PreviewParams {
  jpeg_quality: number
  stretch_target_bg: number
  stretch_shadows_sigma: number
  preview_color: boolean
  stretch_linked: boolean
}

const ImageViewer = forwardRef<ImageViewerHandle, { deviceId: string | undefined; histoAuto: boolean; previewParams: PreviewParams }>(
function ImageViewer({ deviceId, histoAuto, previewParams }, ref) {
  const { t } = useTranslation('imaging')
  const image = useStore((s) => deviceId ? (s.latestImages[deviceId] ?? null) : null)
  const stats = useStore((s) => deviceId ? (s.imageStats[deviceId] ?? null) : null)
  // Re-rendered on demand from the current stretch/quality settings (not the static
  // preview_path/preview_path_linear a completed exposure carries) so a slider change
  // is reflected immediately without waiting for — or forcing — a new exposure.
  // `v` is only a cache-buster: it ties the URL to this specific exposure (via its
  // already-unique preview_path) so a new capture always fetches fresh pixels even
  // when the stretch settings themselves haven't changed.
  const previewUrl = deviceId && image
    ? `/imager/${deviceId}/preview.jpg?mode=${histoAuto ? 'auto' : 'linear'}`
      + `&target_bg=${previewParams.stretch_target_bg}&shadows=${previewParams.stretch_shadows_sigma}`
      + `&color=${previewParams.preview_color}&linked=${previewParams.stretch_linked}`
      + `&quality=${previewParams.jpeg_quality}&v=${encodeURIComponent(image.previewUrl)}`
    : null

  return (
    <ZoomableImage
      ref={ref}
      className="flex-1"
      src={previewUrl}
      alt={t('latest')}
      resetKey={deviceId}
      empty={
        <div className="text-slate-600 text-sm flex flex-col items-center gap-2">
          <Camera size={32} />
          <span>{t('noImage')}</span>
        </div>
      }
    >
      {/* JSX children are evaluated eagerly by the caller, regardless of whether
          ZoomableImage's own `src ? … : empty` branch ends up rendering them — so
          this whole block must be gated on `image` itself, not just on `src` being
          non-null downstream, or `image!.width` throws (and takes the whole page
          down with it) whenever no exposure has been taken yet. */}
      {image && (
        <>
          {/* Bottom-left: image info + FWHM */}
          <div className="absolute bottom-2 left-2 flex flex-col gap-0.5">
            <div className="text-xs text-slate-400 bg-black/60 px-2 py-1 rounded">
              {image.width}×{image.height} · {image.duration}s
              {stats && stats.star_count > 0 && stats.fwhm != null && (
                <span className="ml-2 text-emerald-400">
                  {t('fwhm', { fwhm: stats.fwhm.toFixed(1), stars: stats.star_count })}
                </span>
              )}
            </div>
          </div>
          {/* Bottom-right: histogram */}
          {stats && (
            <div className="absolute bottom-2 right-2 bg-black/60 rounded p-1">
              <HistogramOverlay
                stats={stats}
                linear={!histoAuto}
                color={previewParams.preview_color}
                linked={previewParams.stretch_linked}
                params={{
                  target_bg: previewParams.stretch_target_bg,
                  shadows_sigma: previewParams.stretch_shadows_sigma,
                }}
              />
            </div>
          )}
        </>
      )}
    </ZoomableImage>
  )
})

// ── Camera Panel ──────────────────────────────────────────────────────────────

const FRAME_TYPES: FrameType[] = ['light', 'dark', 'flat', 'bias']
const BINNINGS = [1, 2, 3, 4]

function CameraPanel({
  deviceId, name, onSettings, onHistoAutoChange, onPreviewParamsChange, onZoomFit, onZoomNative,
}: {
  deviceId: string
  name: string
  onSettings: (id: string) => void
  onHistoAutoChange: (v: boolean) => void
  onPreviewParamsChange: (p: PreviewParams) => void
  onZoomFit: () => void
  onZoomNative: () => void
}) {
  const { t } = useTranslation('imaging')
  const { t: tc } = useTranslation()
  const imagerBusy = useStore((s) => s.imagerBusy)
  const busy = imagerBusy[deviceId] ?? false
  // Colour options only apply to one-shot-colour (Bayer) frames, which carry per-channel stats.
  const isColorFrame = useStore((s) => !!s.imageStats[deviceId]?.channels?.length)

  // Server-persisted settings — loaded on mount, saved on each change
  const [settings, setSettingsState] = useState<ImagerDeviceSettings>(DEFAULT_IMAGER_SETTINGS)
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  const notifyPreviewParams = useCallback((s: ImagerDeviceSettings) => {
    onPreviewParamsChange({
      jpeg_quality: s.jpeg_quality,
      stretch_target_bg: s.stretch_target_bg,
      stretch_shadows_sigma: s.stretch_shadows_sigma,
      preview_color: s.preview_color,
      stretch_linked: s.stretch_linked,
    })
  }, [onPreviewParamsChange])

  const patchSettings = useCallback((patch: Partial<ImagerDeviceSettings>) => {
    const next = { ...settingsRef.current, ...patch }
    setSettingsState(next)
    api.imager.putSettings(deviceId, next).catch(() => {})
    notifyPreviewParams(next)
  }, [deviceId, notifyPreviewParams])

  // Sliders update local state on every drag tick (for a responsive handle) but only
  // PUT to the server once the drag ends — same one-write-per-change intent as the
  // rest of the settings, just deferred past mouseup instead of onChange. The live
  // preview, however, only needs to move on commit too (re-rendering full-resolution
  // on every drag tick would hammer the backend for no benefit), so this doesn't
  // notify the parent — patchSettings (called on commit) does.
  const patchLocal = useCallback((patch: Partial<ImagerDeviceSettings>) => {
    setSettingsState((prev) => ({ ...prev, ...patch }))
  }, [])

  // Gain lives in the driver, not in persisted settings.
  const [gain, setGain] = useState(0)
  const [gainPropName, setGainPropName] = useState<string | null>(null)
  const [gainElemName, setGainElemName] = useState<string | null>(null)
  const [gainMin, setGainMin] = useState(0)
  const [gainMax, setGainMax] = useState(65535)
  const [gainStep, setGainStep] = useState(1)
  const [looping, setLooping] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Camera hardware status (temperature, cooler)
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null>(null)

  useEffect(() => {
    if (!deviceId) return

    // Load persisted settings from server
    api.imager.getSettings(deviceId)
      .then((s) => {
        setSettingsState(s)
        onHistoAutoChange(s.histo_auto)
        notifyPreviewParams(s)
      })
      .catch(() => {})

    // Sync loop state from server on mount so Stop button is always reachable
    api.imager.status(deviceId)
      .then((s) => { if (s.state === 'looping') setLooping(true) })
      .catch(() => {})

    api.devices.properties(deviceId)
      .then((props) => {
        for (const p of props) {
          if (p.type !== 'number') continue
          const w = p.widgets.find((w) => w.name?.toLowerCase() === 'gain' || w.label?.toLowerCase() === 'gain')
          if (w) {
            if (w.min != null) setGainMin(w.min as number)
            if (w.max != null) setGainMax(w.max as number)
            if (w.step != null && (w.step as number) > 0) setGainStep(w.step as number)
            if (typeof w.value === 'number') setGain(w.value)
            setGainPropName(p.name)
            setGainElemName(w.name ?? null)
            break
          }
        }
      })
      .catch(() => {})

    // Poll camera status for temperature
    const poll = () => {
      api.imager.cameraStatus(deviceId)
        .then(setCameraStatus)
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 10_000)
    return () => clearInterval(id)
  }, [deviceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const buildDitherConfig = (): DitherConfig | undefined => {
    const frames = parseInt(settings.dither_frames)
    const minutes = parseFloat(settings.dither_minutes)
    if (!isNaN(frames) && frames > 0) return { every_frames: frames }
    if (!isNaN(minutes) && minutes > 0) return { every_minutes: minutes }
    return undefined
  }

  const commitGain = async (value: number) => {
    if (!gainPropName || !gainElemName) return
    try {
      await api.devices.setProperty(deviceId, gainPropName, { values: { [gainElemName]: value } })
    } catch (e) {
      setError(t('gainError', { error: (e as Error).message }))
    }
  }

  const expose = async () => {
    setError(null)
    try {
      await api.imager.expose(deviceId, {
        duration: settings.duration, gain: gainPropName ? gain : null,
        binning: settings.binning, frame_type: settings.frame_type as FrameType, save: settings.save_subs,
      })
    } catch (e) { setError((e as Error).message) }
  }

  const halt = async () => {
    setError(null)
    try {
      await api.imager.halt(deviceId)
      setLooping(false)
    } catch (e) { setError((e as Error).message) }
  }

  const toggleLoop = async () => {
    setError(null)
    try {
      if (looping) {
        await api.imager.stopLoop(deviceId)
        setLooping(false)
      } else {
        await api.imager.startLoop(deviceId, {
          duration: settings.duration, gain: gainPropName ? gain : null,
          binning: settings.binning, frame_type: settings.frame_type as FrameType, save: settings.save_subs,
          dither: buildDitherConfig() ?? null,
        })
        setLooping(true)
      }
    } catch (e) { setError((e as Error).message) }
  }

  const setCooler = async (enabled: boolean) => {
    const temp = parseFloat(settings.target_temp)
    try {
      await api.imager.setCooler(deviceId, enabled, !isNaN(temp) ? temp : undefined)
      setCameraStatus((s) => s ? { ...s, cooler_on: enabled } : s)
    } catch (e) { setError((e as Error).message) }
  }

  // The set point shown in the stepper: what was typed, else the current sensor temperature.
  const parsedTarget = parseFloat(settings.target_temp)
  const targetTemp = Number.isFinite(parsedTarget) ? parsedTarget : Math.round(cameraStatus?.temperature ?? 0)

  const applyTemp = async () => {
    const temp = targetTemp
    try {
      await api.imager.setCooler(deviceId, cameraStatus?.cooler_on ?? true, temp)
    } catch (e) { setError((e as Error).message) }
  }

  const hasCooler = cameraStatus?.temperature != null

  return (
    <Panel title={name} deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-3">

        {/* Temperature */}
        {hasCooler && (
          <div className="flex flex-col gap-2 pb-2 border-b border-surface-border">
            <div className="mx-auto w-full max-w-[130px]">
              <CoolingGauge
                temperature={cameraStatus!.temperature!}
                setPoint={cameraStatus!.cooler_on && Number.isFinite(parseFloat(settings.target_temp)) ? parseFloat(settings.target_temp) : null}
                power={cameraStatus!.cooler_on ? cameraStatus!.cooler_power : null}
                min={Math.min(-30, Math.floor(cameraStatus!.temperature! / 10) * 10)}
                max={Math.max(20, Math.ceil(cameraStatus!.temperature! / 10) * 10)}
                label={t('cooler.gauge')}
              />
            </div>
            <div className="flex items-center justify-between">
              <Thermometer size={12} className="text-slate-500" />
              <button
                onClick={() => setCooler(!cameraStatus!.cooler_on)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  cameraStatus!.cooler_on
                    ? 'border-accent text-accent bg-accent/10'
                    : 'border-surface-border text-slate-500'
                }`}
              >
                {cameraStatus!.cooler_on ? t('cooler.on') : t('cooler.off')}
              </button>
            </div>
            {cameraStatus!.cooler_on && (
              <div className="flex flex-wrap items-end gap-2">
                <NumberStepper
                  label={t('cooler.target')} unit="°C" value={targetTemp} step={1} min={-60} max={40}
                  onChange={(v) => patchSettings({ target_temp: String(v) })}
                />
                <Button size="sm" variant="outline" onClick={applyTemp}>{t('cooler.set')}</Button>
              </div>
            )}
          </div>
        )}

        {/* Frame type */}
        <PillGroup
          options={FRAME_TYPES}
          formatLabel={(v) => tc(`frameType.${v}`)}
          value={settings.frame_type as FrameType}
          onChange={(v) => patchSettings({ frame_type: v })}
          label={t('frameType')}
        />

        {/* Duration stepper */}
        <DurationStepper steps={EXPOSURE_STEPS} value={settings.duration} onChange={(v) => patchSettings({ duration: v })} />

        {/* Gain */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{t('gain')}</span>
            <span className="text-xs text-slate-600">{gainMin}–{gainMax}</span>
          </div>
          <Input
            type="number" min={gainMin} max={gainMax} step={gainStep} value={gain}
            onChange={(e) => setGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
            onBlur={(e) => commitGain(Math.max(gainMin, Math.min(gainMax, parseInt(e.target.value) || 0)))}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          />
        </div>

        {/* Binning */}
        <PillGroup
          options={BINNINGS}
          value={settings.binning}
          onChange={(v) => patchSettings({ binning: v })}
          label={t('binning')}
          formatLabel={(b) => `${b}×${b}`}
        />

        {/* Save subs + stretch mode */}
        <div className="flex flex-col gap-1.5">
          <TogglePill label={t('saveSubs')} value={settings.save_subs}
            onChange={(v) => patchSettings({ save_subs: v })} />
          <TogglePill label={t('autoStretch')} value={settings.histo_auto}
            onChange={(v) => { patchSettings({ histo_auto: v }); onHistoAutoChange(v) }} />
        </div>

        {/* Preview: JPEG quality + auto-stretch strength */}
        <Foldable label={t('preview.title')}>
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" className="flex-1" onClick={onZoomFit} title={t('preview.fitTitle')}>
              {t('preview.fit')}
            </Button>
            <Button size="sm" variant="outline" className="flex-1" onClick={onZoomNative} title={t('preview.nativeTitle')}>
              {t('preview.native')}
            </Button>
          </div>
          <LabeledSlider
            label={t('preview.quality')} value={settings.jpeg_quality} min={10} max={100} step={5}
            format={(v) => String(v)}
            onChange={(v) => patchLocal({ jpeg_quality: v })}
            onCommit={(v) => patchSettings({ jpeg_quality: v })}
          />
          {settings.histo_auto && (
            <StretchControls
              value={{ target_bg: settings.stretch_target_bg, shadows_sigma: settings.stretch_shadows_sigma }}
              onChange={(p) => patchLocal({ stretch_target_bg: p.target_bg, stretch_shadows_sigma: p.shadows_sigma })}
              onCommit={(p) => patchSettings({ stretch_target_bg: p.target_bg, stretch_shadows_sigma: p.shadows_sigma })}
            />
          )}
          {isColorFrame && (
            <ColorControls
              value={{ color: settings.preview_color, linked: settings.stretch_linked }}
              onChange={(p) => patchSettings({ preview_color: p.color, stretch_linked: p.linked })}
              showLinked={settings.histo_auto}
            />
          )}
        </Foldable>

        {/* Guiding / dither */}
        <div className="border-t border-surface-border pt-2 flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <Crosshair size={12} className="text-slate-500" />
            <span className="text-slate-500 label-caps">{t('dither.title')}</span>
          </div>
          <div className="flex flex-wrap gap-3">
            <CountStepper
              label={t('dither.frames')} steps={DITHER_FRAME_STEPS}
              value={Number.isFinite(parseInt(settings.dither_frames)) ? parseInt(settings.dither_frames) : 0}
              onChange={(v) => patchSettings({ dither_frames: v > 0 ? String(v) : '', dither_minutes: v > 0 ? '' : settings.dither_minutes })}
            />
            <CountStepper
              label={t('dither.minutes')} steps={DITHER_MINUTE_STEPS}
              value={Number.isFinite(parseFloat(settings.dither_minutes)) ? Math.round(parseFloat(settings.dither_minutes)) : 0}
              onChange={(v) => patchSettings({ dither_minutes: v > 0 ? String(v) : '', dither_frames: v > 0 ? '' : settings.dither_frames })}
            />
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <Button size="sm" onClick={expose} disabled={busy}>
            <Camera size={12} className="mr-1" /> {t('expose')}
          </Button>
          <Button size="sm" variant={looping ? 'danger' : 'outline'} onClick={toggleLoop} disabled={!looping && busy}>
            {looping ? <><Square size={12} className="mr-1" /> {t('stop')}</> : <><Play size={12} className="mr-1" /> {t('loop')}</>}
          </Button>
          <Button size="sm" variant="danger" onClick={halt} title={t('haltTitle')}>
            <StopCircle size={12} className="mr-1" /> {t('halt')}
          </Button>
        </div>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Focuser Panel ─────────────────────────────────────────────────────────────

function FocuserPanel({
  deviceId, onSettings,
}: {
  deviceId: string
  onSettings: (id: string) => void
}) {
  const { t } = useTranslation('imaging')
  const focuserStatuses = useStore((s) => s.focuserStatuses)
  const setFocuserStatus = useStore((s) => s.setFocuserStatus)
  const position = focuserStatuses[deviceId]?.position

  const moving = focuserStatuses[deviceId]?.is_moving ?? false
  // Absolute position: follows the focuser until the user types or steps it.
  const [target, setTarget] = useState<number | null>(null)
  const [edited, setEdited] = useState(false)
  const [moveTarget, setMoveTarget] = useState<number | null>(null)
  const [step, setStep] = useState(100)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { if (!edited && position != null) setTarget(position) }, [position, edited])
  useEffect(() => { if (!moving) setMoveTarget(null) }, [moving])

  // Fetch initial position and persisted step on mount
  useEffect(() => {
    api.focuser.status(deviceId)
      .then((s) => setFocuserStatus(deviceId, s))
      .catch(() => {})
    api.focuser.getSettings(deviceId)
      .then((s) => setStep(Math.max(1, s.step)))
      .catch(() => {})
  }, [deviceId, setFocuserStatus])

  // Ruler window: kept still while the position stays inside it, re-centred when it leaves.
  const span = Math.max(500, step * 10)
  const [centre, setCentre] = useState<number | null>(null)
  useEffect(() => {
    if (position == null) return
    setCentre((c) => (c == null || Math.abs(position - c) > span * 0.8 ? position : c))
  }, [position, span])

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }

  const changeStep = (n: number) => {
    setStep(n)
    api.focuser.putSettings(deviceId, { step: n }).catch(() => {})
  }

  return (
    <Panel title={t('focuser.title')} deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline gap-2">
            <span className="text-xs text-slate-400">{t('focuser.position')}</span>
            <span className="text-sm font-mono text-slate-200">{position ?? '—'}</span>
          </div>
          {position != null && centre != null && (
            <FocuserRuler
              position={position}
              target={moveTarget}
              min={Math.max(0, Math.round(centre - span))}
              max={Math.round(centre + span)}
              label={t('focuser.title')}
            />
          )}
        </div>

        <CountStepper label={t('focuser.stepSize')} steps={FOCUSER_STEP_SIZES} min={1} value={step} onChange={changeStep} />
        <div className="flex gap-2">
          <Button size="sm" variant="outline" className="flex-1" onClick={() => act(() => api.focuser.moveBy(deviceId, -step))}>
            <ChevronDown size={14} className="mr-1" /> {t('focuser.in')}
          </Button>
          <Button size="sm" variant="outline" className="flex-1" onClick={() => act(() => api.focuser.moveBy(deviceId, step))}>
            <ChevronUp size={14} className="mr-1" /> {t('focuser.out')}
          </Button>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <NumberStepper
            label={t('focuser.absolute')} min={0} step={step} value={target ?? 0} valueClassName="w-20"
            onChange={(v) => { setTarget(v); setEdited(true) }}
          />
          <Button size="sm" disabled={target == null}
            onClick={() => act(async () => { setMoveTarget(target); setEdited(false); await api.focuser.moveTo(deviceId, target!) })}>
            {t('focuser.go')}
          </Button>
          <Button size="sm" variant="danger" onClick={() => act(() => api.focuser.halt(deviceId))}>
            <StopCircle size={12} className="mr-1" /> {t('focuser.halt')}
          </Button>
        </div>
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Filter Wheel Panel ────────────────────────────────────────────────────────

function FilterWheelPanel({
  deviceId, onSettings,
}: {
  deviceId: string
  onSettings: (id: string) => void
}) {
  const { t } = useTranslation('imaging')
  const filterWheelStatuses = useStore((s) => s.filterWheelStatuses)
  const setFilterWheelStatus = useStore((s) => s.setFilterWheelStatus)
  const status: FilterWheelStatus | undefined = filterWheelStatuses[deviceId]
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.filterWheel.status(deviceId)
      .then((s) => setFilterWheelStatus(deviceId, s))
      .catch(() => {})
  }, [deviceId, setFilterWheelStatus])

  const selectFilter = async (slot: number) => {
    setError(null)
    try {
      await api.filterWheel.select(deviceId, slot)
      setFilterWheelStatus(deviceId, { ...status!, current_slot: slot, is_moving: false })
    } catch (e) { setError((e as Error).message) }
  }

  const names = status?.filter_names ?? []
  const count = status?.filter_count ?? names.length
  const slots = Array.from({ length: count }, (_, i) => i + 1)

  return (
    <Panel title={t('filterWheel.title')} deviceId={deviceId} onSettings={onSettings}>
      <div className="flex flex-col gap-2">
        <select
          value={status?.current_slot ?? ''}
          onChange={(e) => selectFilter(parseInt(e.target.value))}
          className="rounded-lg bg-surface border border-surface-border px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
          disabled={status?.is_moving}
        >
          {slots.map((slot) => (
            <option key={slot} value={slot}>
              {slot}. {names[slot - 1] ?? t('filterWheel.filter', { slot })}
            </option>
          ))}
        </select>
        {status?.is_moving && <p className="text-xs text-slate-500">{t('filterWheel.moving')}</p>}
        {error && <p className="text-xs text-status-error">{error}</p>}
      </div>
    </Panel>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function Imaging() {
  const { t } = useTranslation('imaging')
  const { deviceId } = useParams<{ deviceId?: string }>()
  const connectedDevices = useStore((s) => s.connectedDevices)

  // histoAuto is lifted here so ImageViewer can read it.
  // CameraPanel sets it via onHistoAutoChange when it loads or toggles.
  const [histoAuto, setHistoAuto] = useState(true)

  // Same lift for the stretch/quality settings — ImageViewer needs the live values
  // (not just what's persisted) to build the on-demand preview.jpg URL, and
  // CameraPanel reports them via onPreviewParamsChange on load and on every commit.
  const [previewParams, setPreviewParams] = useState<PreviewParams>({
    jpeg_quality: DEFAULT_IMAGER_SETTINGS.jpeg_quality,
    stretch_target_bg: DEFAULT_IMAGER_SETTINGS.stretch_target_bg,
    stretch_shadows_sigma: DEFAULT_IMAGER_SETTINGS.stretch_shadows_sigma,
    preview_color: DEFAULT_IMAGER_SETTINGS.preview_color,
    stretch_linked: DEFAULT_IMAGER_SETTINGS.stretch_linked,
  })

  // Zoom/pan lives inside ImageViewer; the sidebar's Fit/1x buttons reach it imperatively.
  const viewerRef = useRef<ImageViewerHandle>(null)

  // INDI properties panel state
  const [propertiesDeviceId, setPropertiesDeviceId] = useState<string | null>(null)
  const openProperties = useCallback((id: string) => {
    setPropertiesDeviceId((prev) => (prev === id ? null : id))
  }, [])

  // Per-camera focuser/filter-wheel association resolved from the active profile's
  // equipment tree (which optical path this camera actually sits on) — fetched once per
  // profile activation, since nothing here changes without a (re)activate.
  const [opticalPaths, setOpticalPaths] = useState<OpticalPath[]>([])
  useEffect(() => {
    api.profiles.activeOpticalPaths().then(setOpticalPaths).catch(() => setOpticalPaths([]))
  }, [])

  const camera = deviceId
    ? (connectedDevices.find((d) => d.device_id === deviceId && d.kind === 'camera') ?? null)
    : null

  const opticalPath = camera
    ? (opticalPaths.find((p) => p.camera_device_id === camera.device_id) ?? null)
    : null

  // Find focuser: when the active profile's equipment tree resolved an optical path for
  // this camera, trust it completely — including a null focuser_device_id, which means
  // this camera genuinely has no focuser on its path (e.g. a guide camera sitting
  // directly on an OTA with no focuser/filter wheel below it), not "unknown, keep
  // guessing". Only fall back to the INDI-companion/first-connected heuristics when
  // there's no tree data for this camera at all (legacy profile, or fetch not done yet).
  const focuser = camera
    ? (opticalPath
        ? (connectedDevices.find((d) => d.kind === 'focuser' && d.device_id === opticalPath.focuser_device_id) ?? null)
        : (connectedDevices.find((d) => d.kind === 'focuser' && camera.companions.includes(d.device_id))
            ?? connectedDevices.find((d) => d.kind === 'focuser') ?? null))
    : null

  // Find filter wheel: same rule as the focuser above.
  const filterWheel = camera
    ? (opticalPath
        ? (connectedDevices.find((d) => d.kind === 'filter_wheel' && d.device_id === opticalPath.filter_wheel_device_id) ?? null)
        : (connectedDevices.find((d) => d.kind === 'filter_wheel' && camera.companions.includes(d.device_id))
            ?? connectedDevices.find((d) => d.kind === 'filter_wheel') ?? null))
    : null

  return (
    <>
    <div className="flex h-full">
      {/* Image viewer */}
      <div className="flex-1 flex flex-col min-w-0">
        <ImageViewer ref={viewerRef} deviceId={deviceId} histoAuto={histoAuto} previewParams={previewParams} />
        <EventLog filter={['imager', 'indi', 'phd2']} />
      </div>

      {/* Right sidebar */}
      <CollapsibleSidebar>
        {camera === null ? (
          <div className="p-4 text-xs text-slate-500">{t('noCamera')}</div>
        ) : (
          <>
            <CameraPanel
              key={camera.device_id}
              deviceId={camera.device_id}
              name={camera.driver_name ?? camera.device_id}
              onSettings={openProperties}
              onHistoAutoChange={setHistoAuto}
              onPreviewParamsChange={setPreviewParams}
              onZoomFit={() => viewerRef.current?.fit()}
              onZoomNative={() => viewerRef.current?.oneToOne()}
            />
            {focuser && (
              <FocuserPanel key={focuser.device_id} deviceId={focuser.device_id} onSettings={openProperties} />
            )}
            {filterWheel && (
              <FilterWheelPanel key={filterWheel.device_id} deviceId={filterWheel.device_id} onSettings={openProperties} />
            )}
          </>
        )}
      </CollapsibleSidebar>
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
