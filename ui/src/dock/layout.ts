// Pure edits of the dock layout (the order of the list is the order on screen).
import type { DockWidgetEntry } from '@/api/types'

export function addWidget(list: DockWidgetEntry[], id: string): DockWidgetEntry[] {
  return list.some((w) => w.id === id) ? list : [...list, { id, collapsed: false }]
}

export const removeWidget = (list: DockWidgetEntry[], id: string) => list.filter((w) => w.id !== id)

export function moveWidget(list: DockWidgetEntry[], id: string, delta: -1 | 1): DockWidgetEntry[] {
  const from = list.findIndex((w) => w.id === id)
  const to = from + delta
  if (from < 0 || to < 0 || to >= list.length) return list
  const next = [...list]
  ;[next[from], next[to]] = [next[to], next[from]]
  return next
}

export const toggleCollapsed = (list: DockWidgetEntry[], id: string) =>
  list.map((w) => (w.id === id ? { ...w, collapsed: !w.collapsed } : w))
