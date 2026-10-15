import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Crosshair, StopCircle } from 'lucide-react'
import * as polarAlignApi from './api'
import { KnobArrows } from './KnobArrows'
import { Button } from '@/components/ui/button'
import { DurationStepper } from '@/components/ui/duration-stepper'
import { StarImage } from '@/components/ui/star-image'
import type { StarViewInfo } from '@/api/types'

const EXPOSURE_STEPS = [0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5, 8]
const POLL_MS = 400

/** The star, the mark it has to reach and the two knob moves that get it there. */
function Overlay({ info }: { info: StarViewInfo }) {
  const { t } = useTranslation('polar_align')
  if (!info.star || !info.target || !info.az_via) return null
  const [ox, oy] = info.origin
  const star = { x: info.star.x - ox, y: info.star.y - oy }
  const via = { x: info.az_via[0] - ox, y: info.az_via[1] - oy }
  const target = { x: info.target[0] - ox, y: info.target[1] - oy }
  const size = Math.max(info.width, info.height)
  const font = Math.max(10, size / 40)
  const ring = info.arrived ? 'stroke-emerald-300' : 'stroke-amber-300'
  const long = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(b.x - a.x, b.y - a.y) > 3
  // Faint lines through the star along each knob's direction, so the axes read even when a move is short.
  const extend = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const len = Math.hypot(b.x - a.x, b.y - a.y)
    if (len < 1e-6) return null
    const k = size / len
    return { x1: a.x - (b.x - a.x) * k, y1: a.y - (b.y - a.y) * k, x2: a.x + (b.x - a.x) * k, y2: a.y + (b.y - a.y) * k }
  }
  const azAxis = extend(star, via)
  const altAxis = extend(via, target)
  return (
    <>
      <defs>
        <marker id="pa-az-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="fill-sky-300" />
        </marker>
        <marker id="pa-alt-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="fill-violet-300" />
        </marker>
      </defs>
      {azAxis && <line {...azAxis} className="stroke-sky-300" strokeWidth={1} opacity={0.25} vectorEffect="non-scaling-stroke" />}
      {altAxis && <line {...altAxis} className="stroke-violet-300" strokeWidth={1} opacity={0.25} vectorEffect="non-scaling-stroke" strokeDasharray="6 4" />}
      {long(star, via) && (
        <>
          <line x1={star.x} y1={star.y} x2={via.x} y2={via.y} className="stroke-sky-300" strokeWidth={2} vectorEffect="non-scaling-stroke" markerEnd="url(#pa-az-head)" />
          <text x={(star.x + via.x) / 2 + 4} y={(star.y + via.y) / 2 - 4} fontSize={font} className="fill-sky-300">{t('starView.az')}</text>
        </>
      )}
      {long(via, target) && (
        <>
          <line x1={via.x} y1={via.y} x2={target.x} y2={target.y} className="stroke-violet-300" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" markerEnd="url(#pa-alt-head)" />
          <text x={(via.x + target.x) / 2 + 4} y={(via.y + target.y) / 2 - 4} fontSize={font} className="fill-violet-300">{t('starView.alt')}</text>
        </>
      )}
      {/* The mark: two rings, so it stays visible over a bright star field. */}
      <circle cx={target.x} cy={target.y} r={info.tolerance_px} fill="none" className="stroke-black" strokeWidth={5} opacity={0.6} vectorEffect="non-scaling-stroke" />
      <circle cx={target.x} cy={target.y} r={info.tolerance_px} fill="none" className={ring} strokeWidth={3} vectorEffect="non-scaling-stroke" />
      <path d={`M${target.x - info.tolerance_px * 1.6},${target.y} h${info.tolerance_px * 0.9} M${target.x + info.tolerance_px * 0.7},${target.y} h${info.tolerance_px * 0.9} M${target.x},${target.y - info.tolerance_px * 1.6} v${info.tolerance_px * 0.9} M${target.x},${target.y + info.tolerance_px * 0.7} v${info.tolerance_px * 0.9}`} className={ring} strokeWidth={1.5} vectorEffect="non-scaling-stroke" fill="none" />
    </>
  )
}

/** Live alternative to rechecks: follows one star on the camera and shows where it has to go. */
export function StarViewPanel({ disabled, onActiveChange }: { disabled: boolean; onActiveChange: (active: boolean) => void }) {
  const { t } = useTranslation('polar_align')
  const [exposure, setExposure] = useState(1)
  const [info, setInfo] = useState<StarViewInfo | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const state = info?.state ?? 'idle'
  const running = state === 'starting' || state === 'tracking' || state === 'lost'

  useEffect(() => { onActiveChange(running) }, [running, onActiveChange])

  useEffect(() => {
    let alive = true
    const load = () => polarAlignApi.getStarView().then((v) => alive && setInfo(v)).catch(() => {})
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  // Swap the picture only once the new one has loaded, so it never flashes empty.
  useEffect(() => {
    if (!info || info.width === 0) return
    const url = polarAlignApi.starViewFrameUrl(info.version)
    const img = new Image()
    img.onload = () => setSrc(url)
    img.src = url
  }, [info?.version, info?.width]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    setBusy(true)
    setError(null)
    setSrc(null)
    try {
      setInfo(await polarAlignApi.startStarView({ exposure_s: exposure }))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('starView.startFailed'))
    } finally {
      setBusy(false)
    }
  }, [exposure, t])

  const stop = useCallback(async () => {
    setBusy(true)
    try {
      await polarAlignApi.stopStarView()
      setInfo(await polarAlignApi.getStarView())
    } catch (e) {
      setError(e instanceof Error ? e.message : t('starView.stopFailed'))
    } finally {
      setBusy(false)
    }
  }, [t])

  return (
    <div className="rounded border border-surface-border bg-surface-overlay/30 p-2.5 space-y-2">
      <p className="text-xs text-slate-400">{t('starView.title')}</p>

      {!running && (
        <>
          <p className="text-[10px] text-slate-600">{t('starView.hint')}</p>
          <div className="flex items-end gap-2">
            <DurationStepper label={t('starView.exposure')} steps={EXPOSURE_STEPS} value={exposure} onChange={setExposure} />
            <Button size="sm" onClick={start} disabled={busy || disabled} className="flex-1">
              <Crosshair size={13} className="mr-1.5" />
              {t('starView.start')}
            </Button>
          </div>
        </>
      )}

      {state === 'failed' && info?.error && <p className="text-xs text-red-400 break-words">{info.error}</p>}
      {error && <p className="text-xs text-red-400 break-words">{error}</p>}

      {running && (
        <div className="space-y-2">
          {state === 'starting' && <p className="text-xs text-slate-500">{t('starView.starting')}</p>}
          {state === 'lost' && <p className="text-xs text-amber-300">{t('starView.lost')}</p>}
          {info && info.width > 0 && src && (
            <StarImage src={src} alt={t('starView.alt_text')} width={info.width} height={info.height} origin={info.origin}
              stars={info.star ? [info.star] : []}>
              <Overlay info={info} />
            </StarImage>
          )}
          {info?.alt_error_arcmin != null && info.az_error_arcmin != null && (
            <KnobArrows altErrorArcmin={info.alt_error_arcmin} azErrorArcmin={info.az_error_arcmin}
              altLabel={t('wizard.altitude')} azLabel={t('wizard.azimuth')} />
          )}
          {info?.arrived && <p className="text-xs text-emerald-300">{t('starView.arrived')}</p>}
          {info?.error && state === 'tracking' && <p className="text-xs text-amber-300 break-words">{info.error}</p>}
          <p className="text-[10px] text-slate-600">{t('starView.legend')}</p>
          <Button size="sm" variant="outline" onClick={stop} disabled={busy} className="w-full">
            <StopCircle size={13} className="mr-1.5" />
            {t('starView.stop')}
          </Button>
        </div>
      )}
    </div>
  )
}
