import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, ChevronUp, PanelBottomClose, PanelBottomOpen, PanelRightClose, PanelRightOpen, Pencil, Check, Plus, X } from 'lucide-react'
import { useStore } from '@/store'
import type { DockWidgetEntry } from '@/api/types'
import { PORTRAIT_NARROW, useMediaQuery } from '@/hooks/useMediaQuery'
import { getAllDockWidgets, type DockWidgetDef } from './registry'
import { hasWidget } from './layout'
import { useDock } from './store'
import './coreWidgets'

const WIDE = '(min-width: 1280px)'

const iconBtn = 'p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-surface-overlay transition-colors disabled:opacity-30 disabled:pointer-events-none'

/** Widgets of plugins that are switched off are not offered (and not shown). */
function useAvailable(): DockWidgetDef[] {
  const infos = useStore((s) => s.pluginInfos)
  return getAllDockWidgets().filter((d) => !d.plugin || infos.some((p) => p.id === d.plugin && p.enabled))
}

interface Entry { def: DockWidgetDef; device_id: string | null; collapsed: boolean }

const deviceLabel = (def: DockWidgetDef, device: string | null) => (def.perDevice && device ? `${def.title()} · ${device}` : def.title())

function Frame({ entry, index, count, editing }: { entry: Entry; index: number; count: number; editing: boolean }) {
  const { t } = useTranslation()
  const dock = useDock()
  const { def, collapsed } = entry
  const key = { id: def.id, device_id: entry.device_id }
  const Icon = def.icon
  const title = deviceLabel(def, entry.device_id)
  return (
    <section className="rounded-[10px] border border-surface-border bg-surface-raised">
      <header className="flex items-center gap-1 px-2 py-1.5">
        <button type="button" className={iconBtn} onClick={() => dock.toggleCollapsed(key)}
          aria-expanded={!collapsed} aria-label={collapsed ? t('dock.expand') : t('dock.collapse')}>
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </button>
        {Icon && <Icon size={13} className="text-slate-500 shrink-0" />}
        {def.route
          ? <Link to={def.route} className="flex-1 min-w-0 truncate label-caps text-slate-500 hover:text-slate-200">{title}</Link>
          : <h3 className="flex-1 min-w-0 truncate label-caps text-slate-500">{title}</h3>}
        {editing && (
          <>
            <button type="button" className={iconBtn} disabled={index === 0} onClick={() => dock.move(key, -1)} aria-label={t('dock.moveUp')}><ChevronUp size={14} /></button>
            <button type="button" className={iconBtn} disabled={index === count - 1} onClick={() => dock.move(key, 1)} aria-label={t('dock.moveDown')}><ChevronDown size={14} /></button>
            <button type="button" className={iconBtn} onClick={() => dock.remove(key)} aria-label={t('dock.remove')}><X size={14} /></button>
          </>
        )}
      </header>
      {!collapsed && <div className="px-3 pb-3"><def.Component deviceId={entry.device_id ?? undefined} /></div>}
    </section>
  )
}

/** What can still be added: a per-device widget is offered once per connected device. */
function useChoices(available: DockWidgetDef[], pinned: DockWidgetEntry[]) {
  const devices = useStore((s) => s.connectedDevices)
  return available.flatMap((def) => {
    const ids = def.perDevice ? devices.filter((d) => d.kind === def.perDevice).map((d) => d.device_id) : []
    const options: (string | null)[] = ids.length > 0 ? ids : [null]
    return options
      .filter((device_id) => !hasWidget(pinned, { id: def.id, device_id }))
      .map((device_id) => ({ def, device_id }))
  })
}

function Picker({ choices }: { choices: { def: DockWidgetDef; device_id: string | null }[] }) {
  const { t } = useTranslation()
  const add = useDock((s) => s.add)
  return (
    <section className="rounded-[10px] border border-dashed border-surface-border p-2">
      <h3 className="label-caps text-slate-500 px-1 pb-1">{t('dock.add')}</h3>
      {choices.length === 0 && <p className="px-1 text-xs text-slate-500">{t('dock.allPinned')}</p>}
      <ul className="flex flex-col">
        {choices.map(({ def, device_id }) => (
          <li key={`${def.id}@${device_id ?? ''}`}>
            <button type="button" onClick={() => add({ id: def.id, device_id })}
              className="w-full flex items-center gap-2 rounded px-1 py-1.5 text-left text-sm text-slate-300 hover:bg-surface-overlay">
              <Plus size={14} className="text-accent shrink-0" />
              <span className="truncate">{deviceLabel(def, device_id)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The pull-out handle (closed) or the panel (open). Lives in Layout, to the right of the page. */
export function Dock() {
  const { t } = useTranslation()
  const open = useDock((s) => s.open)
  const editing = useDock((s) => s.editing)
  const widgets = useDock((s) => s.widgets)
  const setOpen = useDock((s) => s.setOpen)
  const setEditing = useDock((s) => s.setEditing)
  const load = useDock((s) => s.load)
  const wide = useMediaQuery(WIDE)
  const portrait = useMediaQuery(PORTRAIT_NARROW)   // phone held upright: a sheet at the bottom
  const available = useAvailable()
  const choices = useChoices(available, widgets)

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!open || (wide && !portrait)) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, wide, portrait, setOpen])

  const label = open ? t('dock.close') : t('dock.open')
  // One handle, fixed in the same place whether the dock is open or not (it may cover a widget).
  const handle = (
    <button type="button" onClick={() => setOpen(!open)} aria-label={label} title={label} aria-expanded={open}
      className={`fixed z-50 flex items-center justify-center border border-surface-border bg-surface-raised
                  text-slate-500 hover:text-slate-200 transition-all ${portrait
        ? 'bottom-0 left-1/2 -translate-x-1/2 h-5 w-16 rounded-t-md border-b-0'
        : 'right-0 top-1/2 -translate-y-1/2 h-16 w-5 rounded-l-md border-r-0 hover:w-6'}`}>
      {portrait
        ? (open ? <PanelBottomClose size={14} /> : <PanelBottomOpen size={14} />)
        : (open ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />)}
    </button>
  )

  if (!open) return handle

  const shown = widgets.flatMap((w): Entry[] => {
    const def = available.find((d) => d.id === w.id)
    return def ? [{ def, device_id: w.device_id ?? null, collapsed: w.collapsed }] : []
  })

  return (
    <>
    <aside aria-label={t('dock.title')}
      className={`flex flex-col border-surface-border bg-surface ${
        portrait ? 'fixed inset-x-0 bottom-0 z-40 max-h-[60dvh] border-t shadow-2xl'
          : wide ? 'w-80 shrink-0 border-l'
          : 'fixed right-0 top-0 bottom-0 z-40 w-[min(92vw,22rem)] border-l shadow-2xl'}`}>
      <div className="h-9 shrink-0 flex items-center gap-1 border-b border-surface-border px-2">
        <span className="flex-1 label-caps text-slate-500 px-1">{t('dock.title')}</span>
        <button type="button" className={`${iconBtn} ${editing ? 'text-accent' : ''}`} onClick={() => setEditing(!editing)}
          aria-pressed={editing} aria-label={editing ? t('dock.done') : t('dock.edit')} title={editing ? t('dock.done') : t('dock.edit')}>
          {editing ? <Check size={14} /> : <Pencil size={14} />}
        </button>
      </div>
      <div className={`flex-1 overflow-y-auto p-2 flex flex-col gap-2 ${portrait ? 'pb-7' : ''}`}>
        {shown.length === 0 && !editing && (
          <div className="p-2 flex flex-col items-start gap-2">
            <p className="text-xs text-slate-500">{t('dock.empty')}</p>
            <button type="button" onClick={() => setEditing(true)}
              className="inline-flex items-center gap-1.5 rounded border border-surface-border px-2 py-1 text-xs text-slate-300 hover:bg-surface-overlay">
              <Plus size={13} className="text-accent" /> {t('dock.add')}
            </button>
          </div>
        )}
        {shown.map((entry, i) => (
          <Frame key={`${entry.def.id}@${entry.device_id ?? ''}`} entry={entry} index={i} count={shown.length} editing={editing} />
        ))}
        {editing && <Picker choices={choices} />}
      </div>
    </aside>
    {handle}
    </>
  )
}
