import { NavLink } from 'react-router-dom'
import { BookOpen, Camera, Cpu, ScrollText, Settings, Telescope, Wifi, WifiOff } from 'lucide-react'
import { useStore } from '@/store'
import { getPluginEntry } from '@/plugin-registry'

export function Sidebar() {
  const wsConnected = useStore((s) => s.wsConnected)
  const hasMounts   = useStore((s) => s.connectedDevices.some((d) => d.kind === 'mount' && d.state === 'connected'))
  const hasError    = useStore((s) => s.lastError !== null)
  const enabledPlugins = useStore((s) => s.pluginInfos.filter((p) => p.enabled))
  const cameras     = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'camera' && d.state === 'connected'))

  const pluginNavItems = enabledPlugins
    .map((p) => {
      const entry = getPluginEntry(p.id)
      if (!entry) return null
      return { to: entry.to, icon: entry.icon, label: entry.label }
    })
    .filter(Boolean) as { to: string; icon: typeof Cpu; label: string; badge?: boolean }[]

  // One sidebar entry per connected camera; fall back to a static entry when none
  const cameraNavItems: { to: string; icon: typeof Camera; label: string; badge?: boolean }[] =
    cameras.length > 0
      ? cameras.map((cam) => ({
          to: `/imaging/${cam.device_id}`,
          icon: Camera,
          label: cam.driver_name ?? cam.device_id,
        }))
      : [{ to: '/imaging', icon: Camera, label: 'Imaging' }]

  const navItems = [
    { to: '/equipment', icon: Cpu,        label: 'Equipment' },
    { to: '/profiles',  icon: BookOpen,   label: 'Profiles'  },
    ...(hasMounts ? [{ to: '/mount', icon: Telescope, label: 'Mount' }] : []),
    ...cameraNavItems,
    ...pluginNavItems,
    { to: '/logs',      icon: ScrollText, label: 'Logs', badge: hasError },
    { to: '/options',   icon: Settings,   label: 'Options'   },
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
        {navItems.map(({ to, icon: Icon, label, badge }) => (
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
            <div className="relative shrink-0">
              <Icon size={18} />
              {badge && (
                <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-status-error" />
              )}
            </div>
            <span className="hidden lg:block truncate">{label}</span>
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
