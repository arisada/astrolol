import { useEffect, useRef } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useLocalStorage } from '@/hooks/useLocalStorage'

const BREAKPOINT = 768

export function CollapsibleSidebar({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useLocalStorage('ui.sidebar.open', window.innerWidth >= BREAKPOINT)
  const prevWide = useRef(window.innerWidth >= BREAKPOINT)

  useEffect(() => {
    const onResize = () => {
      const wide = window.innerWidth >= BREAKPOINT
      if (wide !== prevWide.current) {
        prevWide.current = wide
        setOpen(wide)
      }
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [setOpen])

  return (
    <aside
      className={`shrink-0 flex flex-col border-l border-surface-border bg-surface-raised ${
        open ? 'w-72' : 'w-8'
      }`}
    >
      {/* Toggle strip — always visible */}
      <div
        className={`h-8 shrink-0 flex items-center border-b border-surface-border ${
          open ? 'justify-end px-2' : 'justify-center'
        }`}
      >
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-surface-overlay transition-colors"
          aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          {open ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {open && <div className="flex-1 overflow-y-auto">{children}</div>}
    </aside>
  )
}
