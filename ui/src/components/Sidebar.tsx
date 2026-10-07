import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BookOpen, Camera, ChevronsLeft, ChevronsRight, Cpu, ScrollText, Settings, Telescope } from 'lucide-react'
import { useStore } from '@/store'
import { getPluginEntry } from '@/plugin-registry'
import { useLocalStorage } from '@/hooks/useLocalStorage'

export type NavItem = { to: string; icon: typeof Cpu; label: string; badge?: boolean }

export function useNavItems(): NavItem[] {
  const { t, i18n } = useTranslation()
  const hasMounts   = useStore((s) => s.connectedDevices.some((d) => d.kind === 'mount' && d.state === 'connected'))
  const hasError    = useStore((s) => s.lastError !== null)
  const enabledPlugins = useStore((s) => s.pluginInfos.filter((p) => p.enabled))
  const cameras     = useStore((s) => s.connectedDevices.filter((d) => d.kind === 'camera' && d.state === 'connected'))

  const sortedPlugins = enabledPlugins.slice().sort((a, b) => a.nav_order - b.nav_order)

  function toNavItem(p: typeof sortedPlugins[number]) {
    const entry = getPluginEntry(p.id)
    if (!entry) return null
    // A plugin may translate its sidebar label with a top-level "label" key in its catalogue.
    return { to: entry.to, icon: entry.icon, label: i18n.t('label', { ns: p.id, defaultValue: entry.label }) }
  }

  const pluginsBeforeMount = sortedPlugins
    .filter((p) => p.nav_before === 'mount')
    .map(toNavItem).filter(Boolean) as NavItem[]

  const pluginNavItems = sortedPlugins
    .filter((p) => !p.nav_before)
    .map(toNavItem).filter(Boolean) as NavItem[]

  // One sidebar entry per connected camera; fall back to a static entry when none
  const cameraNavItems: { to: string; icon: typeof Camera; label: string; badge?: boolean }[] =
    cameras.length > 0
      ? cameras.map((cam) => ({
          to: `/imaging/${cam.device_id}`,
          icon: Camera,
          label: cam.driver_name ?? cam.device_id,
        }))
      : [{ to: '/imaging', icon: Camera, label: t('nav.imaging') }]

  const navItems = [
    { to: '/equipment', icon: Cpu,        label: t('nav.equipment') },
    { to: '/profiles',  icon: BookOpen,   label: t('nav.profiles') },
    ...pluginsBeforeMount,
    ...(hasMounts ? [{ to: '/mount', icon: Telescope, label: t('nav.mount') }] : []),
    ...cameraNavItems,
    ...pluginNavItems,
    { to: '/logs',      icon: ScrollText, label: t('nav.logs'), badge: hasError },
    { to: '/options',   icon: Settings,   label: t('nav.options') },
  ]

  return navItems
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors
   ${isActive ? 'bg-surface-overlay text-slate-100' : 'text-slate-400 hover:bg-surface-overlay hover:text-slate-200'}`

/** Landscape navigation: a sidebar that can be folded down to an icon rail. */
export function Sidebar() {
  const { t } = useTranslation()
  const items = useNavItems()
  // Folded by default on narrow screens (a phone on its side), expanded otherwise.
  const [folded, setFolded] = useLocalStorage<boolean>('astrolol.navFolded', window.innerWidth < 900)

  return (
    <aside className={`flex flex-col shrink-0 bg-surface-raised border-r border-surface-border h-full transition-[width]
      ${folded ? 'w-14' : 'w-48'}`}>
      <div className="flex items-center justify-center px-3 py-3.5 border-b border-surface-border">
        <img src="/favicon-32x32.png" alt="astrolol" className="h-6 w-6 shrink-0" />
      </div>

      <nav className="flex flex-col gap-1 p-2 flex-1 min-h-0 overflow-y-auto">
        {items.map(({ to, icon: Icon, label, badge }) => (
          <NavLink key={to} to={to} className={navLinkClass} title={folded ? label : undefined}>
            <div className="relative shrink-0">
              <Icon size={18} />
              {badge && <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-status-error" />}
            </div>
            {!folded && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      <button
        type="button"
        onClick={() => setFolded(!folded)}
        className="flex items-center gap-3 px-4 py-3 border-t border-surface-border text-slate-500 hover:text-slate-200 transition-colors"
        title={folded ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-label={folded ? t('sidebar.expand') : t('sidebar.collapse')}
      >
        {folded ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        {!folded && <span className="text-xs">{t('sidebar.collapse')}</span>}
      </button>
    </aside>
  )
}

/** Portrait navigation: a scrolling row under the status bar, icon with its label beneath. */
export function TopNav() {
  const items = useNavItems()
  return (
    <nav className="flex shrink-0 overflow-x-auto bg-surface-raised border-b border-surface-border">
      {items.map(({ to, icon: Icon, label, badge }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `flex shrink-0 flex-col items-center gap-0.5 px-3 pt-2 pb-1.5 min-w-[64px] max-w-[96px] border-b-2 transition-colors
             ${isActive ? 'border-accent text-slate-100' : 'border-transparent text-slate-400 hover:text-slate-200'}`
          }
        >
          <div className="relative">
            <Icon size={18} />
            {badge && <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-status-error" />}
          </div>
          <span className="label-caps max-w-full truncate">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
