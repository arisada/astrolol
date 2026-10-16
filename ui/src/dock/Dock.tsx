import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, ChevronUp, PanelRightClose, PanelRightOpen, Pencil, Check, Plus, X } from 'lucide-react'
import { useStore } from '@/store'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { getAllDockWidgets, getDockWidget, type DockWidgetDef } from './registry'
import { useDock } from './store'
import './coreWidgets'

const WIDE = '(min-width: 1280px)'

const iconBtn = 'p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-surface-overlay transition-colors disabled:opacity-30 disabled:pointer-events-none'

/** Widgets of plugins that are switched off are not offered (and not shown). */
function useAvailable(): DockWidgetDef[] {
  const infos = useStore((s) => s.pluginInfos)
  return getAllDockWidgets().filter((d) => !d.plugin || infos.some((p) => p.id === d.plugin && p.enabled))
}

function Frame({ def, index, count, collapsed, editing }: {
  def: DockWidgetDef; index: number; count: number; collapsed: boolean; editing: boolean
}) {
  const { t } = useTranslation()
  const dock = useDock()
  const Icon = def.icon
  const title = def.title()
  return (
    <section className="rounded-[10px] border border-surface-border bg-surface-raised">
      <header className="flex items-center gap-1 px-2 py-1.5">
        <button type="button" className={iconBtn} onClick={() => dock.toggleCollapsed(def.id)}
          aria-expanded={!collapsed} aria-label={collapsed ? t('dock.expand') : t('dock.collapse')}>
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </button>
        {Icon && <Icon size={13} className="text-slate-500 shrink-0" />}
        {def.route
          ? <Link to={def.route} className="flex-1 min-w-0 truncate label-caps text-slate-500 hover:text-slate-200">{title}</Link>
          : <h3 className="flex-1 min-w-0 truncate label-caps text-slate-500">{title}</h3>}
        {editing && (
          <>
            <button type="button" className={iconBtn} disabled={index === 0} onClick={() => dock.move(def.id, -1)} aria-label={t('dock.moveUp')}><ChevronUp size={14} /></button>
            <button type="button" className={iconBtn} disabled={index === count - 1} onClick={() => dock.move(def.id, 1)} aria-label={t('dock.moveDown')}><ChevronDown size={14} /></button>
            <button type="button" className={iconBtn} onClick={() => dock.remove(def.id)} aria-label={t('dock.remove')}><X size={14} /></button>
          </>
        )}
      </header>
      {!collapsed && <div className="px-3 pb-3"><def.Component /></div>}
    </section>
  )
}

function Picker({ choices }: { choices: DockWidgetDef[] }) {
  const { t } = useTranslation()
  const add = useDock((s) => s.add)
  return (
    <section className="rounded-[10px] border border-dashed border-surface-border p-2">
      <h3 className="label-caps text-slate-500 px-1 pb-1">{t('dock.add')}</h3>
      {choices.length === 0 && <p className="px-1 text-xs text-slate-500">{t('dock.allPinned')}</p>}
      <ul className="flex flex-col">
        {choices.map((d) => (
          <li key={d.id}>
            <button type="button" onClick={() => add(d.id)}
              className="w-full flex items-center gap-2 rounded px-1 py-1.5 text-left text-sm text-slate-300 hover:bg-surface-overlay">
              <Plus size={14} className="text-accent shrink-0" />
              <span className="truncate">{d.title()}</span>
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
  const available = useAvailable()

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!open || wide) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, wide, setOpen])

  const label = open ? t('dock.close') : t('dock.open')
  // One handle, fixed in the same place whether the dock is open or not (it may cover a widget).
  const handle = (
    <button type="button" onClick={() => setOpen(!open)} aria-label={label} title={label} aria-expanded={open}
      className="fixed right-0 top-1/2 -translate-y-1/2 z-50 flex h-16 w-5 items-center justify-center
                 rounded-l-md border border-r-0 border-surface-border bg-surface-raised text-slate-500
                 hover:text-slate-200 hover:w-6 transition-all">
      {open ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
    </button>
  )

  if (!open) return handle

  const shown = widgets.flatMap((w) => {
    const def = available.find((d) => d.id === w.id) ?? (getDockWidget(w.id)?.plugin ? undefined : getDockWidget(w.id))
    return def ? [{ def, collapsed: w.collapsed }] : []
  })
  const choices = available.filter((d) => !widgets.some((w) => w.id === d.id))

  return (
    <>
    <aside aria-label={t('dock.title')}
      className={`flex flex-col border-l border-surface-border bg-surface ${
        wide ? 'w-80 shrink-0' : 'fixed right-0 top-0 bottom-0 z-40 w-[min(92vw,22rem)] shadow-2xl'}`}>
      <div className="h-9 shrink-0 flex items-center gap-1 border-b border-surface-border px-2">
        <span className="flex-1 label-caps text-slate-500 px-1">{t('dock.title')}</span>
        <button type="button" className={`${iconBtn} ${editing ? 'text-accent' : ''}`} onClick={() => setEditing(!editing)}
          aria-pressed={editing} aria-label={editing ? t('dock.done') : t('dock.edit')} title={editing ? t('dock.done') : t('dock.edit')}>
          {editing ? <Check size={14} /> : <Pencil size={14} />}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {shown.length === 0 && !editing && <p className="p-2 text-xs text-slate-500">{t('dock.empty')}</p>}
        {shown.map(({ def, collapsed }, i) => (
          <Frame key={def.id} def={def} index={i} count={shown.length} collapsed={collapsed} editing={editing} />
        ))}
        {editing && <Picker choices={choices} />}
      </div>
    </aside>
    {handle}
    </>
  )
}
