import { create } from 'zustand'
import { api } from '@/api/client'
import type { DockWidgetEntry } from '@/api/types'
import { addWidget, moveWidget, removeWidget, toggleCollapsed } from './layout'

const OPEN_KEY = 'astrolol.dock.open'

function readOpen(): boolean {
  try { return localStorage.getItem(OPEN_KEY) === '1' } catch { return false }
}

interface DockState {
  /** Per browser: a phone and a laptop want different things on screen. */
  open: boolean
  /** Edit mode: pages show "+" on their widgets, the dock shows reorder/remove. */
  editing: boolean
  /** Which widgets, in which order: follows the user (UserSettings.dock). */
  widgets: DockWidgetEntry[]
  setOpen: (open: boolean) => void
  setEditing: (editing: boolean) => void
  load: () => Promise<void>
  add: (id: string) => void
  remove: (id: string) => void
  move: (id: string, delta: -1 | 1) => void
  toggleCollapsed: (id: string) => void
}

// Saves are chained so two quick edits cannot overtake each other.
let saving: Promise<unknown> = Promise.resolve()

export const useDock = create<DockState>((set, get) => {
  const edit = (fn: (list: DockWidgetEntry[]) => DockWidgetEntry[]) => {
    const widgets = fn(get().widgets)
    if (widgets === get().widgets) return
    set({ widgets })
    // Re-read the settings so only the dock is replaced. A viewer cannot save: the layout then
    // lasts until the page is reloaded.
    saving = saving
      .then(() => api.settings.get())
      .then((s) => api.settings.put({ ...s, dock: { widgets: get().widgets } }))
      .catch(() => {})
  }
  return {
    open: readOpen(),
    editing: false,
    widgets: [],
    setOpen: (open) => {
      try { localStorage.setItem(OPEN_KEY, open ? '1' : '0') } catch { /* private window */ }
      set({ open, editing: open ? get().editing : false })
    },
    setEditing: (editing) => set({ editing }),
    load: async () => {
      try {
        const s = await api.settings.get()
        set({ widgets: s.dock?.widgets ?? [] })
      } catch { /* keep what we have */ }
    },
    add: (id) => edit((l) => addWidget(l, id)),
    remove: (id) => edit((l) => removeWidget(l, id)),
    move: (id, delta) => edit((l) => moveWidget(l, id, delta)),
    toggleCollapsed: (id) => edit((l) => toggleCollapsed(l, id)),
  }
})
