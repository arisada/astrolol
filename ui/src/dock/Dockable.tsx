import { useTranslation } from 'react-i18next'
import { Check, Plus } from 'lucide-react'
import { useDock } from './store'

/** Wraps a page card that has a dock widget. Outside edit mode it adds nothing visible. */
export function Dockable({ id, children }: { id: string; children: React.ReactNode }) {
  const { t } = useTranslation()
  const editing = useDock((s) => s.open && s.editing)
  const pinned = useDock((s) => s.widgets.some((w) => w.id === id))
  const add = useDock((s) => s.add)
  const remove = useDock((s) => s.remove)
  return (
    <div className="relative">
      {children}
      {editing && (
        <button type="button" onClick={() => (pinned ? remove(id) : add(id))}
          aria-pressed={pinned} aria-label={pinned ? t('dock.unpin') : t('dock.pin')} title={pinned ? t('dock.unpin') : t('dock.pin')}
          className={`absolute -top-2 -right-2 z-10 flex h-6 w-6 items-center justify-center rounded-full border shadow
            ${pinned ? 'border-accent bg-accent text-accent-fg' : 'border-surface-border bg-surface-raised text-accent hover:bg-surface-overlay'}`}>
          {pinned ? <Check size={13} /> : <Plus size={13} />}
        </button>
      )}
    </div>
  )
}
