// The guide camera's latest frame, with a box around every star the guider is looking at.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import * as api from './api'
import { STAR_KIND_STYLE as KIND_STYLE, StarImage } from '@/components/ui/star-image'

/** *onPick*, when given, makes the image clickable: it receives the sensor position clicked. */
export function GuiderView({ poll, onPick }: { poll: boolean; onPick?: (x: number, y: number) => void }) {
  const { t } = useTranslation('guider')
  const [view, setView] = useState<api.ViewInfo | null>(null)
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => api.getView().then((v) => alive && setView(v)).catch(() => {})
    load()
    if (!poll) return () => { alive = false }
    const timer = setInterval(load, 1000)
    return () => { alive = false; clearInterval(timer) }
  }, [poll])

  // Swap the picture only once the new one has loaded, so it never flashes empty.
  useEffect(() => {
    if (!view || view.width === 0) return
    const url = api.frameUrl(view.version)
    const img = new Image()
    img.onload = () => setSrc(url)
    img.src = url
  }, [view?.version, view?.width]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!view || view.width === 0 || !src) {
    return (
      <div className="flex items-center justify-center aspect-[5/4] rounded border border-surface-border bg-surface text-xs text-slate-600 px-4 text-center">
        {t('view.none')}
      </div>
    )
  }

  const [ox, oy] = view.origin
  const kindLabel: Record<api.StarKind, string> = {
    primary: t('view.kind_primary'),
    companion: t('view.kind_companion'),
    candidate: t('view.kind_candidate'),
    lost: t('view.kind_lost'),
  }
  return (
    <div className="flex flex-col gap-2">
      <StarImage src={src} alt={t('view.alt')} width={view.width} height={view.height} origin={view.origin}
        stars={view.stars} onPick={onPick}>
        {view.locks.map(([x, y], i) => (
          <path key={`lock-${i}`} d={`M${x - ox - 4},${y - oy} h8 M${x - ox},${y - oy - 4} v8`} className="stroke-slate-100" strokeWidth={Math.max(1, view.width / 400)} opacity={0.7} vectorEffect="non-scaling-stroke" fill="none" />
        ))}
      </StarImage>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        {(['primary', 'companion', 'candidate', 'lost'] as const).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12">
              {KIND_STYLE[k].shape === 'square'
                ? <rect x="1.5" y="1.5" width="9" height="9" fill="none" className={KIND_STYLE[k].stroke} strokeWidth={k === 'primary' ? 2 : 1} strokeDasharray={KIND_STYLE[k].dash} />
                : <circle cx="6" cy="6" r="4.5" fill="none" className={KIND_STYLE[k].stroke} strokeWidth="1" />}
            </svg>
            {kindLabel[k]}
          </li>
        ))}
      </ul>
      {onPick && <p className="text-[11px] text-slate-500">{t('view.pickHint')}</p>}
      <FrameInfo view={view} kindLabel={kindLabel} />
    </div>
  )
}

const n = (v: number | null | undefined, digits = 1) => (v == null ? '—' : v.toFixed(digits))

/** The frame's numbers, and a line per star with its size, brightness and signal-to-noise. */
function FrameInfo({ view, kindLabel }: { view: api.ViewInfo; kindLabel: Record<api.StarKind, string> }) {
  const { t } = useTranslation('guider')
  const f = view.stats
  const scale = view.pixel_scale
  const size = (px: number | null) => (px == null ? '—' : scale ? `${n(px * scale)}″` : `${n(px)} px`)
  let chosen = 0
  const rows = view.stars.map((s) => ({ s, label: s.kind === 'candidate' ? null : ++chosen }))
  return (
    <div className="flex flex-col gap-2 text-[11px] text-slate-400">
      {f && (
        <p className="font-mono">
          {t('frame.summary', {
            seq: f.seq, exposure: n(f.exposure, 2), rate: f.period ? n(1 / f.period) : '—',
            background: n(f.background, 0), noise: n(f.noise, 1), brightest: n(f.brightest, 0),
          })}
        </p>
      )}
      {rows.length > 0 && (
        <table className="w-full font-mono">
          <thead>
            <tr className="text-slate-500 text-left">
              <th className="font-normal pr-2">{t('frame.star')}</th>
              <th className="font-normal pr-2">{t('frame.hfd')}</th>
              <th className="font-normal pr-2">{t('frame.fwhm')}</th>
              <th className="font-normal pr-2">{t('frame.snr')}</th>
              <th className="font-normal pr-2">{t('frame.peak')}</th>
              <th className="font-normal" />
            </tr>
          </thead>
          <tbody>
            {rows.map(({ s, label }, i) => (
              <tr key={i} className={s.kind === 'lost' ? 'text-rose-300' : ''}>
                <td className="pr-2">{label == null ? kindLabel[s.kind] : `${label} ${kindLabel[s.kind]}`}</td>
                <td className="pr-2">{size(s.hfd)}</td>
                <td className="pr-2">{size(s.fwhm)}</td>
                <td className="pr-2">{n(s.snr, 0)}</td>
                <td className="pr-2">{n(s.peak, 0)}</td>
                <td className="text-amber-300">
                  {s.saturated ? t('frame.saturated') : s.state && s.state !== 'ok' && s.state !== 'lost' ? t(`frame.states.${s.state}`) : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
