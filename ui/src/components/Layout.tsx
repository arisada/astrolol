import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useEvents } from '@/hooks/useEvents'

export function Layout() {
  useEvents() // connect WebSocket once at the top level

  return (
    <div className="flex h-screen bg-surface text-slate-200 overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
