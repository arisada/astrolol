import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import * as api from './api'

export interface Filters {
  frameTypes: string[]
  objectName: string
  search: string
  dateFrom: string
  dateTo: string
}

export const EMPTY_FILTERS: Filters = { frameTypes: [], objectName: '', search: '', dateFrom: '', dateTo: '' }

const FRAME_TYPES = ['light', 'dark', 'flat', 'bias']

export function FilterSidebar({
  filters, onChange, flat, onFlatChange,
}: {
  filters: Filters
  onChange: (f: Filters) => void
  flat: boolean
  onFlatChange: (v: boolean) => void
}) {
  const { t } = useTranslation('viewer')
  const { t: tc } = useTranslation()
  const [facets, setFacets] = useState<api.Facets | null>(null)

  useEffect(() => {
    api.getFacets().then(setFacets).catch(() => {})
  }, [])

  const toggleFrameType = (ft: string) => {
    const set = new Set(filters.frameTypes)
    if (set.has(ft)) set.delete(ft); else set.add(ft)
    onChange({ ...filters, frameTypes: [...set] })
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-slate-400">{t('filters.frameType')}</span>
        <div className="flex flex-wrap gap-1">
          {FRAME_TYPES.map((ft) => (
            <button
              key={ft}
              onClick={() => toggleFrameType(ft)}
              className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                filters.frameTypes.includes(ft)
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-surface-border text-slate-400 hover:border-slate-500'
              }`}
            >
              {tc(`frameType.${ft}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">{t('filters.object')}</span>
        <Input
          list="viewer-objects"
          value={filters.objectName}
          onChange={(e) => onChange({ ...filters, objectName: e.target.value })}
          placeholder={t('filters.any')}
          className="text-xs"
        />
        <datalist id="viewer-objects">
          {facets?.objects.map((o) => <option key={o} value={o} />)}
        </datalist>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-slate-400">{t('filters.search')}</span>
        <Input
          value={filters.search}
          onChange={(e) => onChange({ ...filters, search: e.target.value })}
          placeholder="…"
          className="text-xs"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-400">{t('filters.from')}</span>
          <Input type="date" value={filters.dateFrom}
            onChange={(e) => onChange({ ...filters, dateFrom: e.target.value })} className="text-xs" />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-400">{t('filters.to')}</span>
          <Input type="date" value={filters.dateTo}
            onChange={(e) => onChange({ ...filters, dateTo: e.target.value })} className="text-xs" />
        </div>
      </div>

      <div className="flex items-center justify-between pt-2 border-t border-surface-border">
        <span className="text-xs text-slate-400">{t('filters.flat')}</span>
        <ToggleSwitch checked={flat} onChange={() => onFlatChange(!flat)} label={t('filters.flat')} />
      </div>

      {(filters.frameTypes.length > 0 || filters.objectName || filters.search || filters.dateFrom || filters.dateTo) && (
        <button
          onClick={() => onChange(EMPTY_FILTERS)}
          className="text-xs text-slate-500 hover:text-slate-300 self-start"
        >
          {t('filters.clear')}
        </button>
      )}
    </div>
  )
}
