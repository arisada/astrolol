import { NavLink } from 'react-router-dom'
import { BookOpen, Camera, Cpu, Settings, Telescope, Wifi, WifiOff } from 'lucide-react'
import { useStore } from '@/store'

const optionsItem = { to: '/options', icon: Settings, label: 'Options' }

export function Sidebar() {
  const wsConnected = useStore((s) => s.wsConnected)
  const hasMounts   = useStore((s) => s.connectedDevices.some((d) => d.kind === 'mount'))

  const navItems = [
    { to: '/equipment', icon: Cpu,      label: 'Equipment' },
    { to: '/profiles',  icon: BookOpen, label: 'Profiles'  },
    ...(hasMounts ? [{ to: '/mount', icon: Telescope, label: 'Mount' }] : []),
    { to: '/imaging',   icon: Camera,   label: 'Imaging'   },
    optionsItem,
  ]

  return (
    <aside className="flex flex-col w-14 lg:w-48 shrink-0 bg-surface-raised border-r border-surface-border h-screen">
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 py-4 border-b border-surface-border">
        <span className="text-accent font-bold text-lg">✦</span>
        <span className="hidden lg:block text-slate-200 font-semibold text-sm tracking-wide">astrolol</span>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-2 py-2.5 rounded text-sm transition-colors
               ${isActive
                ? 'bg-surface-overlay text-slate-100'
                : 'text-slate-400 hover:bg-surface-overlay hover:text-slate-200'}`
            }
          >
            <Icon size={18} className="shrink-0" />
            <span className="hidden lg:block">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* WS status */}
      <div className="flex items-center gap-2 p-3 border-t border-surface-border">
        {wsConnected
          ? <Wifi size={14} className="text-status-connected shrink-0" />
          : <WifiOff size={14} className="text-status-error shrink-0" />}
        <span className="hidden lg:block text-xs text-slate-500">
          {wsConnected ? 'live' : 'reconnecting…'}
        </span>
      </div>
    </aside>
  )
}
