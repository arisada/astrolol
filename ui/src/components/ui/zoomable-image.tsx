import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'

const ZOOM_MIN = 1
// Generous cap so "1x" (native resolution) has room — a large preview shown in a small
// window can need well beyond a naive 8x to reach 1 image pixel per screen pixel.
const ZOOM_MAX = 20

export interface ZoomableImageHandle {
  /** Fit the whole image inside the window (zoom 1, no pan). */
  fit: () => void
  /** Zoom so one image pixel maps to one screen pixel. */
  oneToOne: () => void
}

interface ZoomableImageProps {
  src: string | null
  alt?: string
  /** Rendered instead of the image when `src` is null. */
  empty?: React.ReactNode
  /** Extra absolutely-positioned overlays (info box, histogram, …) — the container is
   *  `relative`, so children can position themselves freely on top of the image. */
  children?: React.ReactNode
  className?: string
  /** Reset zoom/pan whenever this key changes (e.g. a new image, or switching subject). */
  resetKey?: unknown
}

/**
 * A pannable/zoomable image viewer: wheel-zoom anchored to the cursor, two-finger
 * pinch-zoom anchored to the finger midpoint (with a smooth hand-off when a finger
 * lifts), mouse/touch drag-to-pan, double-click-to-reset, and an imperative `fit`/
 * `oneToOne` handle for external "Fit"/"1x" controls.
 */
export const ZoomableImage = forwardRef<ZoomableImageHandle, ZoomableImageProps>(
function ZoomableImage({ src, alt = 'Preview', empty, children, className, resetKey }, ref) {
  const containerRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // Mouse-drag anchor — kept in a ref (not state) since window listeners read it live.
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  // Two-finger pinch anchor: fixed at gesture start so zoom/pan stay anchored to the
  // midpoint the fingers started at, plus whatever the midpoint itself travels.
  const pinchRef = useRef<{
    startDist: number; startZoom: number; startMidX: number; startMidY: number; panStartX: number; panStartY: number
  } | null>(null)

  // New subject (new image, or caller-supplied reset key) — reset the view instead of
  // keeping a stale zoom/pan.
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
    setLoaded(false)
  }, [src, resetKey])

  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    setZoom((z) => {
      const nz = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z * factor))
      // Keep the anchor point (cursor, or pinch midpoint) stationary on screen while zooming.
      setPan((p) => ({
        x: cx - (cx - p.x) * (nz / z),
        y: cy - (cy - p.y) * (nz / z),
      }))
      return nz
    })
  }, [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      zoomAt(e.clientX - rect.left - rect.width / 2, e.clientY - rect.top - rect.height / 2, Math.exp(-e.deltaY * 0.0015))
    }

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 2) {
        dragRef.current = null
        const [t0, t1] = [e.touches[0], e.touches[1]]
        pinchRef.current = {
          startDist: Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY),
          startZoom: zoom,
          startMidX: (t0.clientX + t1.clientX) / 2,
          startMidY: (t0.clientY + t1.clientY) / 2,
          panStartX: pan.x,
          panStartY: pan.y,
        }
      } else if (e.touches.length === 1) {
        pinchRef.current = null
        const t = e.touches[0]
        dragRef.current = { startX: t.clientX, startY: t.clientY, panX: pan.x, panY: pan.y }
      }
    }
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length === 2 && pinchRef.current) {
        e.preventDefault()
        const g = pinchRef.current
        const [t0, t1] = [e.touches[0], e.touches[1]]
        const dist = Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY)
        const midX = (t0.clientX + t1.clientX) / 2
        const midY = (t0.clientY + t1.clientY) / 2
        const rect = el.getBoundingClientRect()
        const cx = g.startMidX - rect.left - rect.width / 2
        const cy = g.startMidY - rect.top - rect.height / 2
        const nz = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, g.startZoom * (dist / g.startDist)))
        setZoom(nz)
        setPan({
          x: cx - (cx - g.panStartX) * (nz / g.startZoom) + (midX - g.startMidX),
          y: cy - (cy - g.panStartY) * (nz / g.startZoom) + (midY - g.startMidY),
        })
      } else if (e.touches.length === 1 && dragRef.current) {
        e.preventDefault()
        const d = dragRef.current
        const t = e.touches[0]
        setPan({ x: d.panX + (t.clientX - d.startX), y: d.panY + (t.clientY - d.startY) })
      }
    }
    const onTouchEnd = (e: TouchEvent) => {
      pinchRef.current = null
      dragRef.current = null
      // One finger lifted off a two-finger gesture — resume single-finger panning
      // from here instead of snapping back (re-anchor, don't drop the gesture).
      if (e.touches.length === 1) {
        const t = e.touches[0]
        dragRef.current = { startX: t.clientX, startY: t.clientY, panX: pan.x, panY: pan.y }
      }
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('touchstart', onTouchStart, { passive: false })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: false })
    el.addEventListener('touchcancel', onTouchEnd, { passive: false })
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
      el.removeEventListener('touchcancel', onTouchEnd)
    }
    // pan/zoom are read through refs/functional updaters above except for the touch
    // gesture start snapshots, which intentionally capture the latest committed values.
  }, [zoom, pan, zoomAt])

  const resetZoom = useCallback(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])

  // "1x": one image pixel per screen pixel. img.offsetWidth is the untransformed
  // layout size (CSS transforms never affect it), i.e. exactly the size the image
  // renders at when zoom is 1 — so naturalWidth/offsetWidth is the scale factor
  // needed to reach native resolution from there, at any current zoom level.
  const zoomNative = useCallback(() => {
    const img = imgRef.current
    if (!img || !img.naturalWidth || !img.offsetWidth) return
    const nz = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, img.naturalWidth / img.offsetWidth))
    setZoom(nz)
    setPan({ x: 0, y: 0 })
  }, [])

  useImperativeHandle(ref, () => ({ fit: resetZoom, oneToOne: zoomNative }), [resetZoom, zoomNative])

  // Mouse drag: track the move/up listeners on `window`, not the container, so the drag
  // keeps working once the image is panned into a corner (or the window/zoom has shrunk
  // so the image no longer fits) and dragging further requires the cursor to leave the
  // (fixed-size) viewer — the container never sees that mousemove/mouseup, so a
  // container-scoped listener stops the drag dead there. Unconditional on zoom: even at
  // zoom 1 a stray pan offset (e.g. left over from a zoom-out gesture) must stay draggable.
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y }
    setDragging(true)
    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      setPan({ x: d.panX + (ev.clientX - d.startX), y: d.panY + (ev.clientY - d.startY) })
    }
    const onUp = () => {
      dragRef.current = null
      setDragging(false)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      ref={containerRef}
      className={`bg-black flex items-center justify-center relative min-h-0 overflow-hidden touch-none ${className ?? ''}`}
      onMouseDown={onMouseDown}
      onDoubleClick={resetZoom}
    >
      {src ? (
        <>
          <img
            ref={imgRef}
            src={src}
            alt={alt}
            draggable={false}
            onLoad={() => setLoaded(true)}
            className="max-w-full max-h-full object-contain select-none"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              cursor: dragging ? 'grabbing' : 'grab',
              opacity: loaded ? 1 : 0,
              transition: 'opacity 0.15s ease-in',
            }}
          />
          {!loaded && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="h-8 w-8 rounded-full border-2 border-slate-600 border-t-slate-300 animate-spin" />
            </div>
          )}
          {/* Zoom controls */}
          <div className="absolute top-2 right-2 flex items-center gap-1 bg-black/60 rounded px-1.5 py-1">
            <span className="text-xs text-slate-400 font-mono w-10 text-center">{zoom.toFixed(1)}×</span>
            {zoom > 1 && (
              <button onClick={resetZoom} className="text-xs text-slate-400 hover:text-slate-200 px-1" title="Reset zoom (double-click image)">
                reset
              </button>
            )}
          </div>
          {children}
        </>
      ) : (
        empty ?? null
      )}
    </div>
  )
})
