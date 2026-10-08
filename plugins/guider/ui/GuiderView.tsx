// The guide camera's latest frame, with a box around every star the guider is looking at.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import * as api from './api'

// Each kind differs by shape and line style as well as colour: the night palettes are red.
const KIND_STYLE: Record<api.StarKind, { stroke: string; dash?: string; shape: 'square' | 'circle' }> = {
  primary: { stroke: 'stroke-emerald-300', shape: 'square' },
  companion: { stroke: 'stroke-sky-300', shape: 'square', dash: '6 3' },
  candidate: { stroke: 'stroke-amber-300', shape: 'circle' },
  lost: { stroke: 'stroke-rose-400', shape: 'square', dash: '2 3' },
}
const KIND_TEXT: Record<api.StarKind, string> = {
  primary: 'fill-emerald-300',
  companion: 'fill-sky-300',
  candidate: 'fill-amber-300',
  lost: 'fill-rose-400',
}

export function GuiderView({ poll }: { poll: boolean }) {
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
  const font = Math.max(9, view.width / 55)
  const stroke = Math.max(1, view.width / 400)
  let chosen = 0
  return (
    <div className="flex flex-col gap-2">
      <div className="relative w-full rounded border border-surface-border bg-black overflow-hidden" style={{ aspectRatio: `${view.width} / ${view.height}` }}>
        <img src={src} alt={t('view.alt')} className="absolute inset-0 w-full h-full" />
        <svg viewBox={`0 0 ${view.width} ${view.height}`} className="absolute inset-0 w-full h-full" preserveAspectRatio="none">
          {view.locks.map(([x, y], i) => (
            <path key={`lock-${i}`} d={`M${x - ox - 4},${y - oy} h8 M${x - ox},${y - oy - 4} v8`} className="stroke-slate-100" strokeWidth={stroke} opacity={0.7} vectorEffect="non-scaling-stroke" fill="none" />
          ))}
          {view.stars.map((s, i) => {
            const st = KIND_STYLE[s.kind]
            const x = s.x - ox
            const y = s.y - oy
            const label = s.kind === 'candidate' ? null : ++chosen
            // Never smaller than a readable mark, whatever the size of the frame.
            const half = Math.max(s.half, view.width / 90)
            return (
              <g key={i}>
                {st.shape === 'square' ? (
                  <rect x={x - half} y={y - half} width={2 * half} height={2 * half} fill="none" className={st.stroke} strokeWidth={s.kind === 'primary' ? 2 * stroke : stroke} strokeDasharray={st.dash} vectorEffect="non-scaling-stroke" />
                ) : (
                  <circle cx={x} cy={y} r={half} fill="none" className={st.stroke} strokeWidth={stroke} vectorEffect="non-scaling-stroke" />
                )}
                {s.kind === 'lost' && (
                  <path d={`M${x - half},${y - half} L${x + half},${y + half} M${x + half},${y - half} L${x - half},${y + half}`} className={st.stroke} strokeWidth={stroke} vectorEffect="non-scaling-stroke" fill="none" />
                )}
                {label != null && (
                  <text x={x + half + 3} y={y - half + font} fontSize={font} className={KIND_TEXT[s.kind]}>{label}</text>
                )}
              </g>
            )
          })}
        </svg>
      </div>
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
    </div>
  )
}
