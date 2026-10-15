import type { ReactNode } from 'react'
import type { OverlayStar, StarKind } from '@/api/types'

// Each kind differs by shape and line style as well as colour: the night palettes are red.
export const STAR_KIND_STYLE: Record<StarKind, { stroke: string; text: string; dash?: string; shape: 'square' | 'circle' }> = {
  primary: { stroke: 'stroke-emerald-300', text: 'fill-emerald-300', shape: 'square' },
  companion: { stroke: 'stroke-sky-300', text: 'fill-sky-300', shape: 'square', dash: '6 3' },
  candidate: { stroke: 'stroke-amber-300', text: 'fill-amber-300', shape: 'circle' },
  lost: { stroke: 'stroke-rose-400', text: 'fill-rose-400', shape: 'square', dash: '2 3' },
}

/**
 * A camera frame (a JPEG) with a box around each star and room for more drawing over it.
 *
 * *origin* is the sensor position of the image's top-left pixel; stars arrive in sensor
 * coordinates. *children* are SVG elements drawn in image pixels (the origin already
 * subtracted). *onPick*, when given, makes the image clickable: it receives the sensor
 * position clicked.
 */
export function StarImage({ src, alt, width, height, origin, stars, onPick, children }: {
  src: string
  alt: string
  width: number
  height: number
  origin: [number, number]
  stars: OverlayStar[]
  onPick?: (x: number, y: number) => void
  children?: ReactNode
}) {
  const [ox, oy] = origin
  const font = Math.max(9, width / 55)
  const stroke = Math.max(1, width / 400)
  let chosen = 0
  return (
    // Never taller than most of the screen: a window around the stars can be tall and narrow.
    <div className="relative w-full mx-auto rounded border border-surface-border bg-black overflow-hidden"
      style={{ aspectRatio: `${width} / ${height}`, maxHeight: '60vh', maxWidth: `calc(60vh * ${width / height})` }}>
      <img src={src} alt={alt} className="absolute inset-0 w-full h-full" />
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className={`absolute inset-0 w-full h-full ${onPick ? 'cursor-crosshair' : ''}`}
        preserveAspectRatio="none"
        onClick={onPick ? (e) => {
          const r = e.currentTarget.getBoundingClientRect()
          onPick(ox + ((e.clientX - r.left) / r.width) * width, oy + ((e.clientY - r.top) / r.height) * height)
        } : undefined}
      >
        {stars.map((s, i) => {
          const st = STAR_KIND_STYLE[s.kind]
          const x = s.x - ox
          const y = s.y - oy
          const label = s.kind === 'candidate' ? null : ++chosen
          // Never smaller than a readable mark, whatever the size of the frame.
          const half = Math.max(s.half, width / 90)
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
                <text x={x + half + 3} y={y - half + font} fontSize={font} className={st.text}>{label}</text>
              )}
            </g>
          )
        })}
        {children}
      </svg>
    </div>
  )
}
