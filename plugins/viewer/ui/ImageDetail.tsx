import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Crosshair, Download, Trash2, X } from 'lucide-react'
import { api as coreApi } from '@/api/client'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { LabeledSlider } from '@/components/ui/labeled-slider'
import { HistogramOverlay } from '@/components/ui/histogram'
import { ZoomableImage } from '@/components/ui/zoomable-image'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import * as api from './api'

interface Stretch {
  mode: 'auto' | 'linear'
  black_pct: number
  white_pct: number
  quality: number
}

const DEFAULT_STRETCH: Stretch = { mode: 'auto', black_pct: 50, white_pct: 99, quality: 85 }

function fmt(v: number | null | undefined, digits = 1, suffix = ''): string {
  return v == null ? '—' : `${v.toFixed(digits)}${suffix}`
}

export function ImageDetail({
  id, siblingIds, onClose, onNavigate, onRejected,
}: {
  id: string
  // The exact order the frame was being browsed in (whatever sort/filter was active
  // in the table it was opened from) — prev/next just step through this, rather than
  // re-querying the backend with its own (different) default ordering.
  siblingIds: string[]
  onClose: () => void
  onNavigate: (id: string) => void
  onRejected: () => void
}) {
  const [record, setRecord] = useState<api.ImageRecord | null>(null)
  const [stats, setStats] = useState<api.ImageStats | null>(null)
  const [stretch, setStretch] = useState<Stretch>(DEFAULT_STRETCH)
  const [renderStretch, setRenderStretch] = useState<Stretch>(DEFAULT_STRETCH)
  const [error, setError] = useState<string | null>(null)
  const [mountId, setMountId] = useState<string>('')
  const connectedMounts = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))

  useEffect(() => {
    setError(null)
    api.getImage(id).then(setRecord).catch((e) => setError((e as Error).message))
    api.getStats(id).then(setStats).catch(() => {})
    setStretch(DEFAULT_STRETCH)
    setRenderStretch(DEFAULT_STRETCH)
  }, [id])

  useEffect(() => {
    if (connectedMounts.length === 1) setMountId(connectedMounts[0].device_id)
  }, [connectedMounts])

  const index = siblingIds.indexOf(id)
  const hasPrev = index > 0
  const hasNext = index >= 0 && index < siblingIds.length - 1

  const goto = (direction: 'next' | 'prev') => {
    if (index === -1) return
    const newIndex = direction === 'next' ? index + 1 : index - 1
    if (newIndex < 0 || newIndex >= siblingIds.length) return
    onNavigate(siblingIds[newIndex])
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') goto('next')
      else if (e.key === 'ArrowLeft') goto('prev')
      else if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [goto, onClose])

  const setTarget = async () => {
    if (!record || record.ra_deg == null || record.dec_deg == null || !mountId) return
    try {
      await coreApi.mount.setTarget(mountId, record.ra_deg, record.dec_deg, record.object_name || undefined, 'viewer')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const reject = async () => {
    if (!record) return
    if (!window.confirm(`Reject ${record.path.split('/').pop()}? It moves to _rejected/ and can be undone from Settings.`)) return
    try {
      await api.rejectImage(record.id)
      onRejected()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!record) {
    return (
      <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center">
        {error ? <p className="text-status-error text-sm">{error}</p> : <p className="text-slate-400 text-sm">Loading…</p>}
      </div>
    )
  }

  const previewSrc = api.previewUrl(record.id, renderStretch)

  return (
    <div className="fixed inset-0 bg-black/90 z-50 flex">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between p-2 border-b border-surface-border">
          <span className="text-sm text-slate-300 truncate">{record.path.split('/').pop()}</span>
          <div className="flex items-center gap-1">
            {index >= 0 && (
              <span className="text-xs text-slate-500 font-mono mr-1">{index + 1}/{siblingIds.length}</span>
            )}
            <Button size="icon" variant="ghost" onClick={() => goto('prev')} disabled={!hasPrev} title="Previous (←)"><ChevronLeft size={16} /></Button>
            <Button size="icon" variant="ghost" onClick={() => goto('next')} disabled={!hasNext} title="Next (→)"><ChevronRight size={16} /></Button>
            <Button size="icon" variant="ghost" onClick={onClose} title="Close (Esc)"><X size={16} /></Button>
          </div>
        </div>
        <ZoomableImage
          className="flex-1"
          src={previewSrc}
          resetKey={record.id}
          empty={<span className="text-slate-500 text-sm">No preview</span>}
        >
          {stats && (
            <div className="absolute bottom-2 right-2 bg-black/60 rounded p-1">
              <HistogramOverlay stats={stats} />
            </div>
          )}
        </ZoomableImage>
      </div>

      <CollapsibleSidebar storageKey="ui.viewer_detail_sidebar.open">
      <div className="p-3 flex flex-col gap-3 text-xs">
        {error && <p className="text-status-error">{error}</p>}

        <div className="flex gap-2">
          <Button size="sm" className="flex-1" onClick={setTarget}
            disabled={record.ra_deg == null || !mountId}
            title={record.ra_deg == null ? 'No coordinates recorded for this frame' : 'Sets the mount target — does not slew'}
          >
            <Crosshair size={12} className="mr-1" /> Set as target
          </Button>
          <Button size="sm" variant="danger" onClick={reject} title="Move to _rejected/">
            <Trash2 size={12} />
          </Button>
          <a href={api.fitsDownloadUrl(record.id)} download>
            <Button size="sm" variant="outline" title="Download the original FITS"><Download size={12} /></Button>
          </a>
        </div>

        {connectedMounts.length > 1 && (
          <select value={mountId} onChange={(e) => setMountId(e.target.value)}
            className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200">
            <option value="">Select mount…</option>
            {connectedMounts.map((m) => <option key={m.device_id} value={m.device_id}>{m.driver_name ?? m.device_id}</option>)}
          </select>
        )}

        <div className="grid grid-cols-2 gap-y-1 border-t border-surface-border pt-2">
          <span className="text-slate-500">Object</span><span className="text-slate-200">{record.object_name || '—'}</span>
          <span className="text-slate-500">Frame type</span><span className="text-slate-200">{record.frame_type}</span>
          <span className="text-slate-500">Captured</span>
          <span className="text-slate-200">{record.captured_at.replace('T', ' ').slice(0, 19)}{record.captured_at_estimated && ' (est.)'}</span>
          <span className="text-slate-500">Exposure</span><span className="text-slate-200">{fmt(record.exposure_s, 2, 's')}</span>
          <span className="text-slate-500">Gain</span><span className="text-slate-200">{record.gain ?? '—'}</span>
          <span className="text-slate-500">Binning</span><span className="text-slate-200">{record.binning ?? '—'}</span>
          <span className="text-slate-500">Filter</span><span className="text-slate-200">{record.filter_name || '—'}</span>
          <span className="text-slate-500">Camera</span><span className="text-slate-200">{record.camera_name || '—'}</span>
          <span className="text-slate-500">Telescope</span><span className="text-slate-200">{record.telescope_name || '—'}</span>
          <span className="text-slate-500">Temp</span><span className="text-slate-200">{fmt(record.ccd_temp, 1, '°C')}</span>
          <span className="text-slate-500">Size</span><span className="text-slate-200">{record.width}×{record.height}</span>
          <span className="text-slate-500">RA / Dec</span>
          <span className="text-slate-200">
            {record.ra_deg != null ? `${record.ra_deg.toFixed(3)}° / ${record.dec_deg!.toFixed(3)}°` : '—'}
          </span>
          {record.coord_source && (
            <>
              <span className="text-slate-500">Coord. source</span>
              <span className="text-slate-200" title={
                record.coord_source === 'wcs'
                  ? 'Plate-solved position'
                  : 'The mount\'s reported pointing at capture time — not a measurement'
              }>
                {record.coord_source}
              </span>
            </>
          )}
          <span className="text-slate-500">Quality</span>
          <span className="text-slate-200">
            {record.star_count != null ? `${record.star_count}★` : '—'} · HFR {fmt(record.hfr, 2)}
          </span>
        </div>

        <div className="flex flex-col gap-2 border-t border-surface-border pt-2">
          <div className="flex gap-1">
            <button
              onClick={() => { setStretch((s) => ({ ...s, mode: 'auto' })); setRenderStretch((s) => ({ ...s, mode: 'auto' })) }}
              className={`flex-1 px-2 py-0.5 rounded border text-xs ${stretch.mode === 'auto' ? 'border-accent text-accent bg-accent/10' : 'border-surface-border text-slate-400'}`}
            >Auto stretch</button>
            <button
              onClick={() => { setStretch((s) => ({ ...s, mode: 'linear' })); setRenderStretch((s) => ({ ...s, mode: 'linear' })) }}
              className={`flex-1 px-2 py-0.5 rounded border text-xs ${stretch.mode === 'linear' ? 'border-accent text-accent bg-accent/10' : 'border-surface-border text-slate-400'}`}
            >Linear</button>
          </div>
          {stretch.mode === 'auto' && (
            <>
              <LabeledSlider
                label="Black point" value={stretch.black_pct} min={50} max={90} step={1}
                format={(v) => `${v}th pct`}
                onChange={(v) => setStretch((s) => ({ ...s, black_pct: v }))}
                onCommit={(v) => setRenderStretch((s) => ({ ...s, black_pct: v }))}
              />
              <LabeledSlider
                label="White point" value={stretch.white_pct} min={90} max={100} step={0.1}
                format={(v) => `${v.toFixed(1)}th pct`}
                onChange={(v) => setStretch((s) => ({ ...s, white_pct: v }))}
                onCommit={(v) => setRenderStretch((s) => ({ ...s, white_pct: v }))}
              />
            </>
          )}
          <LabeledSlider
            label="JPEG quality" value={stretch.quality} min={10} max={100} step={5}
            format={(v) => String(v)}
            onChange={(v) => setStretch((s) => ({ ...s, quality: v }))}
            onCommit={(v) => setRenderStretch((s) => ({ ...s, quality: v }))}
          />
        </div>
      </div>
      </CollapsibleSidebar>
    </div>
  )
}
