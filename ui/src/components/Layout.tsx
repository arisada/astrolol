import { Outlet } from 'react-router-dom'
import { X } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { useEvents } from '@/hooks/useEvents'
import { useStore } from '@/store'

function ErrorToast() {
  const lastError = useStore((s) => s.lastError)
  const clearLastError = useStore((s) => s.clearLastError)

  if (!lastError) return null

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-start gap-3
                    bg-surface-raised border border-status-error/60 text-slate-200
                    rounded-lg shadow-lg px-4 py-3 max-w-lg w-full mx-4">
      <span className="text-status-error shrink-0 mt-0.5">✕</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-status-error uppercase tracking-wide mb-0.5">
          {lastError.eventType.replace('.', ' ')}
        </p>
        <p className="text-sm text-slate-300 break-words">{lastError.message}</p>
      </div>
      <button
        type="button"
        onClick={clearLastError}
        className="shrink-0 text-slate-500 hover:text-slate-200 transition-colors"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function Layout() {
  useEvents() // connect WebSocket once at the top level

  return (
    <div className="flex h-screen bg-surface text-slate-200 overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      <ErrorToast />
    </div>
  )
}
