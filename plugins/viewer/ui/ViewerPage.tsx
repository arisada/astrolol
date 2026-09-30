import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useStore } from '@/store'
import { CollapsibleSidebar } from '@/components/ui/collapsible-sidebar'
import { EMPTY_FILTERS, FilterSidebar, type Filters } from './FilterSidebar'
import { GroupList } from './GroupList'
import { FrameTable } from './FrameTable'
import { ImageDetail } from './ImageDetail'
import { SettingsPanel } from './SettingsPanel'
import { RollupPanel } from './RollupPanel'
import { api as coreApi } from '@/api/client'
import type { ImageRecord, ImageFilterParams } from './api'

interface DetailState {
  id: string
  siblingIds: string[]
}

function Section({ label, children, defaultOpen = false }: { label: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-surface-border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-slate-400 uppercase tracking-wider hover:text-slate-300"
      >
        {label}
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && children}
    </div>
  )
}

export function ViewerPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [flat, setFlat] = useState(false)
  const [detail, setDetail] = useState<DetailState | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const connectedMounts = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'mount'))
  const liveIndexCounter = useStore((s) => s.pluginStates['viewer'] as number | undefined)

  const bumpRefresh = () => setRefreshToken((t) => t + 1)

  // A live capture or background rescan changed the index — refresh the current view.
  useEffect(() => { if (liveIndexCounter != null) bumpRefresh() }, [liveIndexCounter])

  const flatFilters: ImageFilterParams = {
    frame_type: filters.frameTypes.length ? filters.frameTypes : undefined,
    object_name: filters.objectName || undefined,
    search: filters.search || undefined,
    date_from: filters.dateFrom || undefined,
    date_to: filters.dateTo || undefined,
  }

  const handleSetTarget = async (image: ImageRecord) => {
    if (image.ra_deg == null || image.dec_deg == null) return
    const mount = connectedMounts[0]
    if (!mount) return
    try {
      await coreApi.mount.setTarget(mount.device_id, image.ra_deg, image.dec_deg, image.object_name || undefined, 'viewer')
    } catch {
      /* surfaced via the detail/table's own error state where relevant */
    }
  }

  return (
    <>
      <div className="flex h-full">
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto" key={refreshToken}>
          {flat ? (
            <div className="p-3">
              <FrameTable
                baseFilters={flatFilters}
                onView={(id, siblingIds) => setDetail({ id, siblingIds })}
                onSetTarget={handleSetTarget}
                onRejected={bumpRefresh}
              />
            </div>
          ) : (
            <GroupList
              filters={filters}
              onView={(id, siblingIds) => setDetail({ id, siblingIds })}
              onSetTarget={handleSetTarget}
            />
          )}
        </div>

        <CollapsibleSidebar>
          <Section label="Filters" defaultOpen>
            <FilterSidebar filters={filters} onChange={setFilters} flat={flat} onFlatChange={setFlat} />
          </Section>
          <Section label="Totals per object">
            <RollupPanel />
          </Section>
          <Section label="Library settings">
            <SettingsPanel onLibraryChanged={bumpRefresh} />
          </Section>
        </CollapsibleSidebar>
      </div>

      {detail && (
        <ImageDetail
          id={detail.id}
          siblingIds={detail.siblingIds}
          onClose={() => setDetail(null)}
          onNavigate={(id) => setDetail({ id, siblingIds: detail.siblingIds })}
          onRejected={() => { setDetail(null); bumpRefresh() }}
        />
      )}
    </>
  )
}
