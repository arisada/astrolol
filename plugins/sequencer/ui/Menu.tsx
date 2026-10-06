// Minimal popover menu + split button used by the control bar and task cards.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, MoreHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface MenuItem {
  label: string
  hint?: string
  onSelect: () => void
  disabled?: boolean
  danger?: boolean
}

function Popover({ items, onClose, align = 'right' }: {
  items: MenuItem[]
  onClose: () => void
  align?: 'left' | 'right'
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} />
      <div className={`absolute z-30 mt-1 min-w-[12rem] rounded border border-surface-border bg-surface-overlay shadow-lg py-1
        ${align === 'right' ? 'right-0' : 'left-0'}`}>
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            disabled={item.disabled}
            onClick={() => { onClose(); item.onSelect() }}
            className={`w-full text-left px-3 py-1.5 text-xs hover:bg-surface-border disabled:opacity-40 disabled:cursor-not-allowed
              ${item.danger ? 'text-rose-300' : 'text-slate-200'}`}
          >
            <div>{item.label}</div>
            {item.hint && <div className="text-[10px] text-slate-500">{item.hint}</div>}
          </button>
        ))}
      </div>
    </>
  )
}

/** "⋯" button opening a menu. */
export function MoreMenu({ items, title }: { items: MenuItem[]; title?: string }) {
  const { t } = useTranslation('sequencer')
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <Button variant="ghost" size="icon" title={title ?? t('menu.more')} onClick={() => setOpen((o) => !o)}>
        <MoreHorizontal size={14} />
      </Button>
      {open && <Popover items={items} onClose={() => setOpen(false)} />}
    </div>
  )
}

/** Main action on the left, alternatives behind the caret. */
export function SplitButton({ label, icon, onClick, items, variant = 'outline', disabled }: {
  label: string
  icon?: React.ReactNode
  onClick: () => void
  items: MenuItem[]
  variant?: 'default' | 'outline' | 'danger'
  disabled?: boolean
}) {
  const { t } = useTranslation('sequencer')
  const [open, setOpen] = useState(false)
  return (
    <div className="relative inline-flex">
      <Button variant={variant} size="sm" onClick={onClick} disabled={disabled} className="rounded-r-none">
        {icon}{label}
      </Button>
      <Button variant={variant} size="sm" disabled={disabled} className="rounded-l-none border-l-0 px-1"
        onClick={() => setOpen((o) => !o)} title={t('menu.moreOptions')}>
        <ChevronDown size={12} />
      </Button>
      {open && <Popover items={items} onClose={() => setOpen(false)} align="left" />}
    </div>
  )
}
