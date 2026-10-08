import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  BookOpen, Boxes, Camera, ChevronDown, ChevronsLeft, ChevronsRight, Cpu, Stars, ScrollText, Settings,
  SlidersHorizontal, Telescope,
} from 'lucide-react'
import { useStore } from '@/store'
import { getPluginEntry, type NavIcon } from '@/plugin-registry'
import { useLocalStorage } from '@/hooks/useLocalStorage'

export type NavGroupId = 'equipment' | 'astronomy' | 'settings'
export type NavItem = { to: string; icon: NavIcon; label: string; badge?: boolean; group: NavGroupId }

export const NAV_GROUPS: { id: NavGroupId; icon: NavIcon }[] = [
  { id: 'equipment', icon: Boxes },
  { id: 'astronomy', icon: Stars },
  { id: 'settings',  icon: SlidersHorizontal },
]

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
    return {
      to: entry.to, icon: entry.icon, group: p.nav_group ?? 'astronomy',
      label: i18n.t('label', { ns: p.id, defaultValue: entry.label }),
    }
  }

  const pluginsBeforeMount = sortedPlugins
    .filter((p) => p.nav_before === 'mount')
    .map(toNavItem).filter(Boolean) as NavItem[]

  const pluginNavItems = sortedPlugins
    .filter((p) => !p.nav_before)
    .map(toNavItem).filter(Boolean) as NavItem[]

  // One sidebar entry per connected camera; fall back to a static entry when none
  const cameraNavItems: NavItem[] =
    cameras.length > 0
      ? cameras.map((cam) => ({
          to: `/imaging/${cam.device_id}`,
          icon: Camera,
          label: cam.driver_name ?? cam.device_id,
          group: 'astronomy' as const,
        }))
      : [{ to: '/imaging', icon: Camera, label: t('nav.imaging'), group: 'astronomy' as const }]

  const navItems: NavItem[] = [
    { to: '/equipment', icon: Cpu,        label: t('nav.equipment'), group: 'equipment' as const },
    { to: '/profiles',  icon: BookOpen,   label: t('nav.profiles'), group: 'equipment' as const },
    ...pluginsBeforeMount,
    ...(hasMounts ? [{ to: '/mount', icon: Telescope, label: t('nav.mount'), group: 'astronomy' as const }] : []),
    ...cameraNavItems,
    ...pluginNavItems,
    { to: '/logs',      icon: ScrollText, label: t('nav.logs'), badge: hasError, group: 'settings' as const },
    { to: '/options',   icon: Settings,   label: t('nav.options'), group: 'settings' as const },
  ]

  return navItems
}

export interface NavGroup {
  id: NavGroupId
  icon: NavIcon
  label: string
  items: NavItem[]
  /** An item in the group wants attention (e.g. errors in the log). */
  badge: boolean
}

/** The navigation grouped into categories; empty categories are left out. */
export function useNavGroups(): NavGroup[] {
  const { t } = useTranslation()
  const items = useNavItems()
  return NAV_GROUPS
    .map((g) => {
      const mine = items.filter((i) => i.group === g.id)
      return { ...g, label: t(`nav.group.${g.id}`), items: mine, badge: mine.some((i) => i.badge) }
    })
    .filter((g) => g.items.length > 0)
}

const isHere = (pathname: string, to: string) => pathname === to || pathname.startsWith(`${to}/`)

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors
   ${isActive ? 'bg-surface-overlay text-slate-100' : 'text-slate-400 hover:bg-surface-overlay hover:text-slate-200'}`

const Dot = () => <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-status-error" />

/** Which categories are unfolded in the sidebar. Settings starts folded: it is the least used. */
function useOpenGroups(groups: NavGroup[]) {
  const [stored, setStored] = useLocalStorage<Partial<Record<NavGroupId, boolean>>>('astrolol.navGroups', {})
  const { pathname } = useLocation()
  const isOpen = (id: NavGroupId) => stored[id] ?? id !== 'settings'
  const toggle = (id: NavGroupId) => setStored({ ...stored, [id]: !isOpen(id) })

  // Navigating to a page (a link elsewhere, the back button) opens the category it lives in.
  useEffect(() => {
    const g = groups.find((x) => x.items.some((i) => isHere(pathname, i.to)))
    if (g && !isOpen(g.id)) setStored({ ...stored, [g.id]: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  return { isOpen, toggle }
}

/** Landscape navigation: a sidebar that can be folded down to an icon rail. */
export function Sidebar() {
  const { t } = useTranslation()
  const groups = useNavGroups()
  const { pathname } = useLocation()
  const { isOpen, toggle } = useOpenGroups(groups)
  // Folded by default on narrow screens (a phone on its side), expanded otherwise.
  const [folded, setFolded] = useLocalStorage<boolean>('astrolol.navFolded', window.innerWidth < 900)

  return (
    <aside className={`flex flex-col shrink-0 bg-surface-raised border-r border-surface-border h-full transition-[width]
      ${folded ? 'w-14' : 'w-48'}`}>
      <nav className="flex flex-col gap-0.5 p-2 flex-1 min-h-0 overflow-y-auto">
        {/* The logo is the first row of the list, aligned with the icons below it. */}
        <div className="flex items-center gap-3 px-2 py-2 text-sm">
          <div className="flex w-[18px] shrink-0 justify-center">
            <img src="/favicon-32x32.png" alt="" className="h-5 w-5 max-w-none" />
          </div>
          {!folded && <span className="font-semibold tracking-wide text-slate-200">astrolol</span>}
        </div>

        {groups.map((g) => {
          const open = isOpen(g.id)
          const GroupIcon = g.icon
          const here = g.items.some((i) => isHere(pathname, i.to))
          return folded ? (
            // Icon rail: the hairline between categories is their fold button.
            <div key={g.id} className="flex flex-col gap-0.5">
              <button
                type="button"
                onClick={() => toggle(g.id)}
                title={g.label}
                aria-label={g.label}
                aria-expanded={open}
                className="group relative flex h-3.5 items-center justify-center text-slate-600 hover:text-slate-300"
              >
                <span className="absolute inset-x-1 top-1/2 border-t border-surface-border" />
                <span className="relative bg-surface-raised px-1">
                  <ChevronDown size={12} className={`transition-transform ${open ? '' : '-rotate-90'}`} />
                </span>
              </button>
              {open ? g.items.map(({ to, icon: Icon, label, badge }) => (
                <NavLink key={to} to={to} className={navLinkClass} title={label}>
                  <div className="relative shrink-0">
                    <Icon size={18} />
                    {badge && <Dot />}
                  </div>
                </NavLink>
              )) : (
                <button
                  type="button"
                  onClick={() => toggle(g.id)}
                  title={g.label}
                  aria-label={g.label}
                  className={navLinkClass({ isActive: here })}
                >
                  <div className="relative shrink-0">
                    <GroupIcon size={18} />
                    {g.badge && <Dot />}
                  </div>
                  <span className="sr-only">{g.items.length}</span>
                </button>
              )}
            </div>
          ) : (
            <div key={g.id} className="flex flex-col gap-0.5">
              <button
                type="button"
                onClick={() => toggle(g.id)}
                aria-expanded={open}
                className="label-caps relative mt-1 flex items-center gap-2 px-2 py-0.5 text-slate-500 hover:text-slate-300 transition-colors"
              >
                <GroupIcon size={12} className="shrink-0" />
                <span className="truncate">{g.label}</span>
                {!open && g.badge && <span className="w-1.5 h-1.5 rounded-full bg-status-error" />}
                <ChevronDown size={12} className={`ml-auto shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />
              </button>
              {open ? g.items.map(({ to, icon: Icon, label, badge }) => (
                <NavLink key={to} to={to} className={navLinkClass}>
                  <div className="relative shrink-0">
                    <Icon size={18} />
                    {badge && <Dot />}
                  </div>
                  <span className="truncate">{label}</span>
                </NavLink>
              )) : (
                // Folded: the category's pages shrink to a row of icons.
                <div className="flex flex-wrap gap-0.5 px-1">
                  {g.items.map(({ to, icon: Icon, label, badge }) => (
                    <NavLink
                      key={to}
                      to={to}
                      title={label}
                      aria-label={label}
                      className={({ isActive }) =>
                        `relative rounded-md p-1.5 transition-colors ${isActive ? 'bg-surface-overlay text-slate-100' : 'text-slate-400 hover:bg-surface-overlay hover:text-slate-200'}`}
                    >
                      <Icon size={16} />
                      {badge && <Dot />}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </nav>

      <button
        type="button"
        onClick={() => setFolded(!folded)}
        className="flex items-center gap-3 px-4 py-3 border-t border-surface-border text-slate-500 hover:text-slate-200 transition-colors"
        title={folded ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-label={folded ? t('sidebar.expand') : t('sidebar.collapse')}
      >
        {folded ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
      </button>
    </aside>
  )
}

/**
 * Portrait navigation: one scrolling row under the status bar. The category you are in is unfolded
 * (its pages, icon with label beneath); the others are a single icon with a page count.
 */
export function TopNav() {
  const groups = useNavGroups()
  const { pathname } = useLocation()
  const current = groups.find((g) => g.items.some((i) => isHere(pathname, i.to)))?.id
  const [picked, setPicked] = useState<NavGroupId | null>(null)
  // Going to a page in another category (a link, the back button) follows it.
  useEffect(() => { setPicked(null) }, [current])
  const openId = picked ?? current ?? groups[0]?.id

  return (
    <nav className="flex shrink-0 overflow-x-auto bg-surface-raised border-b border-surface-border">
      {groups.map((g) => {
        const GroupIcon = g.icon
        const open = g.id === openId
        return (
          <div key={g.id} className="flex shrink-0">
            <button
              type="button"
              onClick={() => setPicked(g.id)}
              aria-expanded={open}
              aria-label={g.label}
              title={g.label}
              className={`relative flex shrink-0 flex-col items-center justify-center gap-0.5 px-2.5 border-r border-surface-border transition-colors
                ${open ? 'text-accent' : 'text-slate-500 hover:text-slate-300'}`}
            >
              <GroupIcon size={16} />
              <span className="label-caps max-w-[56px] truncate">{open ? g.label : g.items.length}</span>
              {!open && g.badge && <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-status-error" />}
            </button>
            {open && g.items.map(({ to, icon: Icon, label, badge }) => (
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
                  {badge && <Dot />}
                </div>
                <span className="label-caps max-w-full truncate">{label}</span>
              </NavLink>
            ))}
          </div>
        )
      })}
    </nav>
  )
}
