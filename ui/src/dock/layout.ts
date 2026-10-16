// Pure edits of the dock layout (the order of the list is the order on screen).
// An entry is identified by its widget id and, for per-device widgets, the device it shows.
import type { DockWidgetEntry } from '@/api/types'

export interface WidgetKey { id: string; device_id?: string | null }

export const sameWidget = (a: WidgetKey, b: WidgetKey) => a.id === b.id && (a.device_id ?? null) === (b.device_id ?? null)

export const hasWidget = (list: DockWidgetEntry[], key: WidgetKey) => list.some((w) => sameWidget(w, key))

export function addWidget(list: DockWidgetEntry[], key: WidgetKey): DockWidgetEntry[] {
  return hasWidget(list, key) ? list : [...list, { id: key.id, device_id: key.device_id ?? null, collapsed: false }]
}

export const removeWidget = (list: DockWidgetEntry[], key: WidgetKey) => list.filter((w) => !sameWidget(w, key))

export function moveWidget(list: DockWidgetEntry[], key: WidgetKey, delta: -1 | 1): DockWidgetEntry[] {
  const from = list.findIndex((w) => sameWidget(w, key))
  const to = from + delta
  if (from < 0 || to < 0 || to >= list.length) return list
  const next = [...list]
  ;[next[from], next[to]] = [next[to], next[from]]
  return next
}

export const toggleCollapsed = (list: DockWidgetEntry[], key: WidgetKey) =>
  list.map((w) => (sameWidget(w, key) ? { ...w, collapsed: !w.collapsed } : w))
