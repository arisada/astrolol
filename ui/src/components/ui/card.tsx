import { ChevronDown, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLocalStorage } from '@/hooks/useLocalStorage'

export function Card({ title, action, children, className = '' }: {
  title?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  const hasHeader = title != null || action != null
  return (
    <div className={`border border-surface-border rounded-[10px] bg-surface-raised ${className}`}>
      {hasHeader && (
        <div className="flex items-center justify-between">
          {title != null && (
            <h3 className="font-medium text-slate-500 label-caps">{title}</h3>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

/** A sidebar block. With `foldId` its title folds it away, and the choice is remembered. */
export function SidebarSection({ title, action, children, foldId }: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  foldId?: string
}) {
  const { t } = useTranslation()
  const [folded, setFolded] = useLocalStorage<boolean>(`astrolol.fold.${foldId ?? ''}`, false)
  const isFolded = foldId != null && folded
  return (
    <div className="border-b border-surface-border px-4 py-3">
      <div className={`flex items-center justify-between ${isFolded ? '' : 'mb-2'}`}>
        {foldId != null ? (
          <button
            type="button"
            onClick={() => setFolded(!folded)}
            aria-expanded={!folded}
            title={t(folded ? 'fold.expand' : 'fold.collapse')}
            className="flex items-center gap-1 font-medium text-slate-500 label-caps hover:text-slate-300"
          >
            {folded ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
            {title}
          </button>
        ) : (
          <p className="font-medium text-slate-500 label-caps">{title}</p>
        )}
        {action}
      </div>
      {!isFolded && children}
    </div>
  )
}
