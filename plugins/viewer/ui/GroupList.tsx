import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Crosshair } from 'lucide-react'
import * as api from './api'
import { FrameTable } from './FrameTable'
import type { Filters } from './FilterSidebar'

function formatDuration(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.round((totalSeconds % 3600) / 60)
  if (h > 0) return `${h}h${m > 0 ? `${m.toString().padStart(2, '0')}m` : ''}`
  return `${m}m`
}

function groupLabel(g: api.GroupSummary): string {
  const name = g.object_name || '(unnamed)'
  const parts = [name]
  if (g.filter_name) parts.push(g.filter_name)
  if (g.frame_type !== 'dark' && g.exposure_s != null) parts.push(`${g.exposure_s}s`)
  if (g.binning != null) parts.push(`bin${g.binning}`)
  if (g.gain != null) parts.push(`gain${g.gain}`)
  return parts.join(' · ')
}

// A group is fully described by these field values — expanding it is just /images
// filtered by them, never an opaque group_key/endpoint (see index.py's grouping doc).
function groupFilters(g: api.GroupSummary): api.ImageFilterParams {
  return {
    frame_type: [g.frame_type], object_name: g.object_name || undefined,
    filter_name: g.filter_name || undefined, camera_name: g.camera_name || undefined,
    exposure_s: g.exposure_s ?? undefined, binning: g.binning ?? undefined, gain: g.gain ?? undefined,
    night: g.night,
    sky_cell_ra: !g.object_name ? g.sky_cell_ra ?? undefined : undefined,
    sky_cell_dec: !g.object_name ? g.sky_cell_dec ?? undefined : undefined,
  }
}

export function GroupList({
  filters, onView, onSetTarget,
}: {
  filters: Filters
  onView: (id: string, siblingIds: string[]) => void
  onSetTarget: (image: api.ImageRecord) => void
}) {
  const [groups, setGroups] = useState<api.GroupSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const params: api.GroupFilterParams = {
    frame_type: filters.frameTypes.length ? filters.frameTypes : undefined,
    object_name: filters.objectName || undefined,
    search: filters.search || undefined,
    date_from: filters.dateFrom || undefined,
    date_to: filters.dateTo || undefined,
    page, page_size: 50,
  }

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.listGroups(params)
      .then((res) => { setGroups(res.items); setTotal(res.total) })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters), page])

  const groupKeyOf = (g: api.GroupSummary) =>
    `${g.frame_type}|${g.object_name}|${g.filter_name}|${g.camera_name}|${g.exposure_s}|${g.binning}|${g.gain}|${g.night}`

  return (
    <div className="flex flex-col gap-1 p-3">
      {error && <p className="text-xs text-status-error">{error}</p>}
      {loading && groups.length === 0 && <p className="text-xs text-slate-500">Loading…</p>}
      {!loading && groups.length === 0 && <p className="text-xs text-slate-500">No captures indexed yet.</p>}
      {groups.map((g) => {
        const key = groupKeyOf(g)
        const isOpen = expanded === key
        return (
          <div key={key} className="border border-surface-border rounded">
            <button
              onClick={() => setExpanded(isOpen ? null : key)}
              className="w-full flex items-center gap-2 p-2 text-left hover:bg-surface-overlay/40"
            >
              {isOpen ? <ChevronDown size={14} className="text-slate-500 shrink-0" /> : <ChevronRight size={14} className="text-slate-500 shrink-0" />}
              <img src={api.thumbnailUrl(g.representative_id)} alt="" className="w-12 h-12 object-cover rounded bg-black shrink-0" loading="lazy" />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-slate-200 truncate">{groupLabel(g)}</div>
                <div className="text-xs text-slate-500">
                  {g.night} · {g.count} frames · {formatDuration(g.total_exposure_s)}
                </div>
              </div>
              {g.ra_deg != null && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onSetTarget({ ...emptyRecord, id: g.representative_id, ra_deg: g.ra_deg, dec_deg: g.dec_deg, object_name: g.object_name })
                  }}
                  className="text-slate-500 hover:text-accent p-1 shrink-0"
                  title="Set this group's coordinates as the mount target (does not slew)"
                >
                  <Crosshair size={14} />
                </button>
              )}
            </button>
            {isOpen && (
              <div className="border-t border-surface-border p-2">
                <FrameTable
                  baseFilters={groupFilters(g)}
                  onView={onView}
                  onSetTarget={onSetTarget}
                  onRejected={() => setGroups((prev) => prev.map((x) => (groupKeyOf(x) === key ? { ...x, count: x.count - 1 } : x)))}
                />
              </div>
            )}
          </div>
        )
      })}
      {total > 50 && (
        <div className="flex items-center justify-between pt-2 text-xs text-slate-500">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-30">Prev</button>
          <span>Page {page} of {Math.ceil(total / 50)}</span>
          <button disabled={page * 50 >= total} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-30">Next</button>
        </div>
      )}
    </div>
  )
}

// Minimal placeholder so the group-level "set as target" button can reuse the same
// onSetTarget(image) callback shape as FrameTable's per-frame action.
const emptyRecord: api.ImageRecord = {
  id: '', path: '', size_bytes: 0, mtime: 0, captured_at: '', captured_at_estimated: false,
  frame_type: '', object_name: '', exposure_s: null, gain: null, binning: null, filter_name: '',
  camera_name: '', telescope_name: '', ra_deg: null, dec_deg: null, coord_source: null,
  ccd_temp: null, width: null, height: null, night: '', bg_median: null, star_count: null,
  hfr: null, indexed_at: '',
}
