import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Crosshair, Download, Trash2, X } from 'lucide-react'
import { api as coreApi } from '@/api/client'
import { useStore } from '@/store'
import { Button } from '@/components/ui/button'
import { LabeledSlider } from '@/components/ui/labeled-slider'
import { HistogramOverlay } from '@/components/ui/histogram'
import { ColorControls, StretchControls } from '@/components/ui/stretch-controls'
import { DEFAULT_STRETCH_PARAMS } from '@/utils/stretch'
import { ZoomableImage } from '@/components/ui/zoomable-image'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import * as api from './api'

interface Stretch {
  mode: 'auto' | 'linear'
  target_bg: number
  shadows: number
  quality: number
  color: boolean
  linked: boolean
}

const DEFAULT_STRETCH: Stretch = {
  mode: 'auto',
  target_bg: DEFAULT_STRETCH_PARAMS.target_bg,
  shadows: DEFAULT_STRETCH_PARAMS.shadows_sigma,
  quality: 85,
  color: true,
  linked: false,
}

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
  const { t } = useTranslation('viewer')
  const [record, setRecord] = useState<api.ImageRecord | null>(null)
  const [stats, setStats] = useState<api.ImageStats | null>(null)
  const [stretch, setStretch] = useState<Stretch>(DEFAULT_STRETCH)
  const [renderStretch, setRenderStretch] = useState<Stretch>(DEFAULT_STRETCH)
  const [error, setError] = useState<string | null>(null)
  const [mountId, setMountId] = useState<string>('')
  const connectedMounts = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))

  // Deliberately doesn't reset stretch/renderStretch here — browsing prev/next through a
  // series re-fetches the record and stats for the new id, but the user's current
  // stretch mode and slider positions should carry over rather than snapping back to
  // defaults on every arrow press.
  useEffect(() => {
    setError(null)
    api.getImage(id).then(setRecord).catch((e) => setError((e as Error).message))
    api.getStats(id).then(setStats).catch(() => {})
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
    if (!window.confirm(t('table.confirmReject', { file: record.path.split('/').pop() }))) return
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
        {error ? <p className="text-status-error text-sm">{error}</p> : <p className="text-slate-400 text-sm">{t('loading')}</p>}
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
            <Button size="icon" variant="ghost" onClick={() => goto('prev')} disabled={!hasPrev} title={t('detail.previous')}><ChevronLeft size={16} /></Button>
            <Button size="icon" variant="ghost" onClick={() => goto('next')} disabled={!hasNext} title={t('detail.next')}><ChevronRight size={16} /></Button>
            <Button size="icon" variant="ghost" onClick={onClose} title={t('detail.close')}><X size={16} /></Button>
          </div>
        </div>
        <ZoomableImage
          className="flex-1"
          src={previewSrc}
          resetKey={record.id}
          empty={<span className="text-slate-500 text-sm">{t('detail.noPreview')}</span>}
        >
          {stats && (
            <div className="absolute bottom-2 right-2 bg-black/60 rounded p-1">
              <HistogramOverlay
                stats={stats}
                linear={renderStretch.mode === 'linear'}
                color={renderStretch.color}
                linked={renderStretch.linked}
                params={{ target_bg: renderStretch.target_bg, shadows_sigma: renderStretch.shadows }}
              />
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
            title={record.ra_deg == null ? t('table.noCoords') : t('detail.setTargetTitle')}
          >
            <Crosshair size={12} className="mr-1" /> {t('detail.setTarget')}
          </Button>
          <Button size="sm" variant="danger" onClick={reject} title={t('detail.rejectTitle')}>
            <Trash2 size={12} />
          </Button>
          <a href={api.fitsDownloadUrl(record.id)} download>
            <Button size="sm" variant="outline" title={t('detail.download')}><Download size={12} /></Button>
          </a>
        </div>

        {connectedMounts.length > 1 && (
          <select value={mountId} onChange={(e) => setMountId(e.target.value)}
            className="rounded bg-surface-overlay border border-surface-border px-2 py-1 text-slate-200">
            <option value="">{t('detail.selectMount')}</option>
            {connectedMounts.map((m) => <option key={m.device_id} value={m.device_id}>{m.driver_name ?? m.device_id}</option>)}
          </select>
        )}

        <div className="grid grid-cols-2 gap-y-1 border-t border-surface-border pt-2">
          <span className="text-slate-500">{t('detail.object')}</span><span className="text-slate-200">{record.object_name || '—'}</span>
          <span className="text-slate-500">{t('detail.frameType')}</span><span className="text-slate-200">{record.frame_type}</span>
          <span className="text-slate-500">{t('detail.captured')}</span>
          <span className="text-slate-200">{record.captured_at.replace('T', ' ').slice(0, 19)}{record.captured_at_estimated && t('detail.estimated')}</span>
          <span className="text-slate-500">{t('detail.exposure')}</span><span className="text-slate-200">{fmt(record.exposure_s, 2, 's')}</span>
          <span className="text-slate-500">{t('detail.gain')}</span><span className="text-slate-200">{record.gain ?? '—'}</span>
          <span className="text-slate-500">{t('detail.binning')}</span><span className="text-slate-200">{record.binning ?? '—'}</span>
          <span className="text-slate-500">{t('detail.filter')}</span><span className="text-slate-200">{record.filter_name || '—'}</span>
          <span className="text-slate-500">{t('detail.camera')}</span><span className="text-slate-200">{record.camera_name || '—'}</span>
          <span className="text-slate-500">{t('detail.telescope')}</span><span className="text-slate-200">{record.telescope_name || '—'}</span>
          <span className="text-slate-500">{t('detail.temp')}</span><span className="text-slate-200">{fmt(record.ccd_temp, 1, '°C')}</span>
          <span className="text-slate-500">{t('detail.size')}</span><span className="text-slate-200">{record.width}×{record.height}</span>
          <span className="text-slate-500">{t('detail.radec')}</span>
          <span className="text-slate-200">
            {record.ra_deg != null ? `${record.ra_deg.toFixed(3)}° / ${record.dec_deg!.toFixed(3)}°` : '—'}
          </span>
          {record.coord_source && (
            <>
              <span className="text-slate-500">{t('detail.coordSource')}</span>
              <span className="text-slate-200" title={
                record.coord_source === 'wcs'
                  ? t('detail.wcs')
                  : t('detail.mountPointing')
              }>
                {record.coord_source}
              </span>
            </>
          )}
          <span className="text-slate-500">{t('detail.quality')}</span>
          <span className="text-slate-200">
            {record.star_count != null ? `${record.star_count}★` : '—'} · {t('detail.hfr')} {fmt(record.hfr, 2)}
          </span>
        </div>

        <div className="flex flex-col gap-2 border-t border-surface-border pt-2">
          <div className="flex gap-1">
            <button
              onClick={() => { setStretch((s) => ({ ...s, mode: 'auto' })); setRenderStretch((s) => ({ ...s, mode: 'auto' })) }}
              className={`flex-1 px-2 py-0.5 rounded border text-xs ${stretch.mode === 'auto' ? 'border-accent text-accent bg-accent/10' : 'border-surface-border text-slate-400'}`}
            >{t('detail.autoStretch')}</button>
            <button
              onClick={() => { setStretch((s) => ({ ...s, mode: 'linear' })); setRenderStretch((s) => ({ ...s, mode: 'linear' })) }}
              className={`flex-1 px-2 py-0.5 rounded border text-xs ${stretch.mode === 'linear' ? 'border-accent text-accent bg-accent/10' : 'border-surface-border text-slate-400'}`}
            >{t('detail.linear')}</button>
          </div>
          {stretch.mode === 'auto' && (
            <StretchControls
              value={{ target_bg: stretch.target_bg, shadows_sigma: stretch.shadows }}
              onChange={(p) => setStretch((s) => ({ ...s, target_bg: p.target_bg, shadows: p.shadows_sigma }))}
              onCommit={(p) => setRenderStretch((s) => ({ ...s, target_bg: p.target_bg, shadows: p.shadows_sigma }))}
            />
          )}
          {!!stats?.channels?.length && (
            <ColorControls
              value={{ color: stretch.color, linked: stretch.linked }}
              onChange={(p) => { setStretch((s) => ({ ...s, ...p })); setRenderStretch((s) => ({ ...s, ...p })) }}
              showLinked={stretch.mode === 'auto'}
            />
          )}
          <LabeledSlider
            label={t('detail.jpegQuality')} value={stretch.quality} min={10} max={100} step={5}
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
