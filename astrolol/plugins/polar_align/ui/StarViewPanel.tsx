import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
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

type Pt = { x: number; y: number }

// A dark outline under every mark, so it reads over both a black sky and a bright star.
const HALO = 'stroke-black'

/** A line with an arrowhead, outlined. Sizes are in image pixels, widths in screen pixels. */
function Arrow({ from, to, cls, fill, dash, head, label, font }: {
  from: Pt; to: Pt; cls: string; fill: string; dash?: string; head: number; label: string; font: number
}) {
  const len = Math.hypot(to.x - from.x, to.y - from.y)
  if (len < head * 0.6) return null
  const ux = (to.x - from.x) / len
  const uy = (to.y - from.y) / len
  const base = { x: to.x - ux * head, y: to.y - uy * head }
  const tri = `${to.x},${to.y} ${base.x - uy * head * 0.55},${base.y + ux * head * 0.55} ${base.x + uy * head * 0.55},${base.y - ux * head * 0.55}`
  const mid = { x: (from.x + base.x) / 2, y: (from.y + base.y) / 2 }
  return (
    <g>
      <line x1={from.x} y1={from.y} x2={base.x} y2={base.y} className={HALO} strokeWidth={7} opacity={0.75} vectorEffect="non-scaling-stroke" />
      <polygon points={tri} className={HALO} strokeWidth={5} strokeLinejoin="round" opacity={0.75} vectorEffect="non-scaling-stroke" />
      <line x1={from.x} y1={from.y} x2={base.x} y2={base.y} className={cls} strokeWidth={3.5} strokeDasharray={dash} vectorEffect="non-scaling-stroke" />
      <polygon points={tri} className={`${fill} ${cls}`} strokeWidth={1} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <text x={mid.x - uy * font * 0.9} y={mid.y + ux * font * 0.9 + font * 0.35} fontSize={font} textAnchor="middle"
        className={`${fill} stroke-black`} strokeWidth={3} paintOrder="stroke" fontWeight={600}>{label}</text>
    </g>
  )
}

/** Four corner ticks around a point: the star that is being followed. */
function Bracket({ at, r, label, font }: { at: Pt; r: number; label: string; font: number }) {
  const c = r * 0.45
  const d = `M${at.x - r},${at.y - r + c} v${-c} h${c} M${at.x + r - c},${at.y - r} h${c} v${c} M${at.x + r},${at.y + r - c} v${c} h${-c} M${at.x - r + c},${at.y + r} h${-c} v${-c}`
  return (
    <g>
      <path d={d} fill="none" className={HALO} strokeWidth={6} opacity={0.75} vectorEffect="non-scaling-stroke" />
      <path d={d} fill="none" className="stroke-emerald-300" strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
      <text x={at.x - r} y={at.y - r - font * 0.35} fontSize={font} className="fill-emerald-300 stroke-black" strokeWidth={3} paintOrder="stroke" fontWeight={600}>
        {label}
      </text>
    </g>
  )
}

/** The star followed, the mark it has to reach and the two knob moves that get it there. */
function Overlay({ info }: { info: StarViewInfo }) {
  const { t } = useTranslation('polar_align')
  if (!info.star || !info.target || !info.az_via) return null
  const [ox, oy] = info.origin
  const star = { x: info.star.x - ox, y: info.star.y - oy }
  const via = { x: info.az_via[0] - ox, y: info.az_via[1] - oy }
  const target = { x: info.target[0] - ox, y: info.target[1] - oy }
  const size = Math.max(info.width, info.height)
  const font = Math.max(4, size / 22)
  const head = Math.max(5, size / 16)
  const ring = info.arrived ? 'stroke-emerald-300' : 'stroke-amber-300'
  // Lines through the star along each knob's direction: they show the axes even when a move is short.
  const extend = (a: Pt, b: Pt) => {
    const len = Math.hypot(b.x - a.x, b.y - a.y)
    if (len < 1e-6) return null
    const k = 2 * size / len
    return { x1: a.x - (b.x - a.x) * k, y1: a.y - (b.y - a.y) * k, x2: a.x + (b.x - a.x) * k, y2: a.y + (b.y - a.y) * k }
  }
  const azAxis = extend(star, via)
  const altAxis = extend(via, target)
  const r = info.tolerance_px
  return (
    <>
      {azAxis && <line {...azAxis} className="stroke-sky-300" strokeWidth={1.5} opacity={0.55} vectorEffect="non-scaling-stroke" />}
      {altAxis && <line {...altAxis} className="stroke-violet-300" strokeWidth={1.5} opacity={0.55} vectorEffect="non-scaling-stroke" strokeDasharray="8 5" />}
      <Arrow from={star} to={via} cls="stroke-sky-300" fill="fill-sky-300" head={head} font={font} label={t('starView.az')} />
      <Arrow from={via} to={target} cls="stroke-violet-300" fill="fill-violet-300" dash="9 6" head={head} font={font} label={t('starView.alt')} />
      {/* The mark: two rings, so it stays visible over a bright star field. */}
      <circle cx={target.x} cy={target.y} r={r} fill="none" className={HALO} strokeWidth={7} opacity={0.75} vectorEffect="non-scaling-stroke" />
      <circle cx={target.x} cy={target.y} r={r} fill="none" className={ring} strokeWidth={3.5} vectorEffect="non-scaling-stroke" />
      <Bracket at={star} r={Math.max(size / 14, 5)} label={t('starView.source')} font={font} />
    </>
  )
}

/** One legend entry: the same mark as in the picture, so no colour has to be remembered. */
function LegendItem({ children, label }: { children: ReactNode; label: string }) {
  return (
    <li className="flex items-center gap-1.5">
      <svg width="22" height="14" viewBox="0 0 22 14" className="shrink-0">{children}</svg>
      {label}
    </li>
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
              stars={[]}>
              <Overlay info={info} />
            </StarImage>
          )}
          {info?.alt_error_arcmin != null && info.az_error_arcmin != null && (
            <KnobArrows altErrorArcmin={info.alt_error_arcmin} azErrorArcmin={info.az_error_arcmin}
              altLabel={t('wizard.altitude')} azLabel={t('wizard.azimuth')} />
          )}
          {info?.weak && <p className="text-xs text-amber-300">{t('starView.weak')}</p>}
          {info?.arrived && <p className="text-xs text-emerald-300">{t('starView.arrived')}</p>}
          {info?.error && state === 'tracking' && <p className="text-xs text-amber-300 break-words">{info.error}</p>}
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <LegendItem label={t('starView.legendStar')}>
              <path d="M3,5 v-3 h3 M16,2 h3 v3 M19,9 v3 h-3 M6,12 h-3 v-3" fill="none" className="stroke-emerald-300" strokeWidth="1.5" />
            </LegendItem>
            <LegendItem label={t('starView.legendAz')}>
              <line x1="1" y1="7" x2="15" y2="7" className="stroke-sky-300" strokeWidth="2" />
              <polygon points="21,7 14,3 14,11" className="fill-sky-300" />
            </LegendItem>
            <LegendItem label={t('starView.legendAlt')}>
              <line x1="1" y1="7" x2="15" y2="7" className="stroke-violet-300" strokeWidth="2" strokeDasharray="3 2" />
              <polygon points="21,7 14,3 14,11" className="fill-violet-300" />
            </LegendItem>
            <LegendItem label={t('starView.legendTarget')}>
              <circle cx="11" cy="7" r="5.5" fill="none" className="stroke-amber-300" strokeWidth="2" />
            </LegendItem>
          </ul>
          <Button size="sm" variant="outline" onClick={stop} disabled={busy} className="w-full">
            <StopCircle size={13} className="mr-1.5" />
            {t('starView.stop')}
          </Button>
        </div>
      )}
    </div>
  )
}
