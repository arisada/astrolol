// Dock widgets: small self-contained read-outs that can be pinned to the dock sidebar.
// A widget takes no props and reads what it needs from the store, so it renders the same on
// its own page and in the dock. Core pages register theirs here; a plugin lists them under
// `widgets` in its ui/index.ts (plugin-registry.ts adds the `<plugin id>.` prefix).
import type { ComponentType } from 'react'
import type { DeviceKind } from '@/api/types'

/** What a widget gets: the device it was pinned for (per-device widgets only). */
export interface DockWidgetProps { deviceId?: string }

export interface DockWidgetDef {
  /** `<page or plugin>.<name>`, stored in the user's dock layout. */
  id: string
  title: () => string
  icon?: ComponentType<{ size?: number | string; className?: string }>
  /** Page the widget comes from: its title links there. */
  route?: string
  /** Plugin that provides it; the widget is offered only while that plugin is enabled. */
  plugin?: string
  /** Set when the widget shows one device: it can be pinned once per connected device of this kind. */
  perDevice?: DeviceKind
  Component: ComponentType<DockWidgetProps>
}

const WIDGETS = new Map<string, DockWidgetDef>()

export function registerDockWidget(def: DockWidgetDef): void {
  WIDGETS.set(def.id, def)
}

export const getDockWidget = (id: string) => WIDGETS.get(id)
export const getAllDockWidgets = () => [...WIDGETS.values()]
