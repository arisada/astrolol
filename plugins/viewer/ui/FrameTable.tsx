import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2, Crosshair, Eye } from 'lucide-react'
import { Button } from '@/components/ui/button'
import * as api from './api'

type SortKey = 'captured_at' | 'star_count' | 'hfr' | 'size_bytes'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function FrameTable({
  baseFilters, onView, onSetTarget, onRejected, compact = false,
}: {
  baseFilters: api.ImageFilterParams
  // siblingIds is the currently-sorted/displayed order — used for prev/next in the
  // detail view, so navigation there matches whatever order this table is showing
  // right now (not a fresh, sort-ignorant backend query).
  onView: (id: string, siblingIds: string[]) => void
  onSetTarget: (image: api.ImageRecord) => void
  onRejected: (id: string) => void
  compact?: boolean
}) {
  const { t } = useTranslation('viewer')
  const [items, setItems] = useState<api.ImageRecord[]>([])
  const [total, setTotal] = useState(0)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('captured_at')
  const [sortAsc, setSortAsc] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = (cursor?: string) => {
    setLoading(true)
    setError(null)
    const [before_captured_at, before_id] = cursor ? cursor.split('|') : [undefined, undefined]
    api.listImages({ ...baseFilters, before_captured_at, before_id, limit: 100 })
      .then((res) => {
        setItems((prev) => (cursor ? [...prev, ...res.items] : res.items))
        setTotal(res.total)
        setNextCursor(res.next_cursor)
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    setItems([])
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(baseFilters)])

  const sorted = [...items].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity
    const bv = b[sortKey] ?? -Infinity
    const cmp = av < bv ? -1 : av > bv ? 1 : 0
    return sortAsc ? cmp : -cmp
  })

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(false) }
  }

  const reject = async (image: api.ImageRecord) => {
    if (!window.confirm(t('table.confirmReject', { file: image.path.split('/').pop() }))) return
    try {
      await api.rejectImage(image.id)
      setItems((prev) => prev.filter((i) => i.id !== image.id))
      onRejected(image.id)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const siblingIds = sorted.map((i) => i.id)

  return (
    <div className="flex flex-col gap-2">
      {error && <p className="text-xs text-status-error">{error}</p>}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 border-b border-surface-border">
            {!compact && <th className="w-10" />}
            <th className="text-left py-1 cursor-pointer" onClick={() => toggleSort('captured_at')}>{t('table.captured')}</th>
            <th className="text-left py-1">{t('table.file')}</th>
            <th className="text-left py-1 cursor-pointer" onClick={() => toggleSort('size_bytes')}>{t('table.size')}</th>
            <th className="text-left py-1 cursor-pointer" onClick={() => toggleSort('star_count')}>★</th>
            <th className="text-left py-1 cursor-pointer" onClick={() => toggleSort('hfr')}>HFR</th>
            <th className="text-right py-1">{t('table.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((img) => (
            <tr
              key={img.id}
              onClick={() => onView(img.id, siblingIds)}
              className="border-b border-surface-border/50 hover:bg-surface-overlay/40 cursor-pointer"
            >
              {!compact && (
                <td className="py-1">
                  <img src={api.thumbnailUrl(img.id)} alt="" className="w-8 h-8 object-cover rounded bg-black" loading="lazy" />
                </td>
              )}
              <td className="py-1 text-slate-300 whitespace-nowrap">{img.captured_at.replace('T', ' ').slice(0, 19)}</td>
              <td className="py-1 text-slate-400 truncate max-w-[16rem]">{img.path.split('/').pop()}</td>
              <td className="py-1 text-slate-500">{formatBytes(img.size_bytes)}</td>
              <td className="py-1 text-slate-500">{img.star_count ?? '—'}</td>
              <td className="py-1 text-slate-500">{img.hfr != null ? img.hfr.toFixed(2) : '—'}</td>
              <td className="py-1 text-right whitespace-nowrap">
                <button onClick={(e) => { e.stopPropagation(); onView(img.id, siblingIds) }} className="text-slate-500 hover:text-accent p-0.5" title={t('table.view')}>
                  <Eye size={13} />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onSetTarget(img) }}
                  disabled={img.ra_deg == null || img.dec_deg == null}
                  className="text-slate-500 hover:text-accent disabled:opacity-30 disabled:hover:text-slate-500 p-0.5"
                  title={img.ra_deg == null ? t('table.noCoords') : t('table.setTarget')}
                >
                  <Crosshair size={13} />
                </button>
                <button onClick={(e) => { e.stopPropagation(); reject(img) }} className="text-slate-500 hover:text-status-error p-0.5" title={t('table.reject')}>
                  <Trash2 size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && !loading && <p className="text-xs text-slate-500 py-2">{t('table.none')}</p>}
      {nextCursor && (
        <Button size="sm" variant="outline" onClick={() => load(nextCursor)} disabled={loading}>
          {t('table.loadMore', { count: items.length, total })}
        </Button>
      )}
    </div>
  )
}
