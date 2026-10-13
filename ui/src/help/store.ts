// State of the help panel. A page may say which guide page fits what it currently shows
// (useHelpTopic); otherwise the help button opens the page that explains the current screen.
import { useEffect } from 'react'
import { create } from 'zustand'

interface HelpState {
  /** Topic shown in the panel; null when the panel is closed. */
  topic: string | null
  anchor: string
  /** Topic a page asked for while it is on screen (see useHelpTopic). */
  override: string | null
  /** Pages visited in the panel, for the back button. */
  history: { topic: string; anchor: string }[]
  open: (topic: string, anchor?: string) => void
  navigate: (topic: string, anchor?: string) => void
  back: () => void
  close: () => void
  setOverride: (topic: string | null) => void
}

export const useHelp = create<HelpState>((set) => ({
  topic: null,
  anchor: '',
  override: null,
  history: [],
  open: (topic, anchor = '') => set({ topic, anchor, history: [] }),
  navigate: (topic, anchor = '') =>
    set((s) => ({
      topic,
      anchor,
      history: s.topic ? [...s.history, { topic: s.topic, anchor: s.anchor }] : s.history,
    })),
  back: () =>
    set((s) => {
      const prev = s.history[s.history.length - 1]
      return prev ? { ...prev, history: s.history.slice(0, -1) } : s
    }),
  close: () => set({ topic: null, anchor: '', history: [] }),
  setOverride: (override) => set({ override }),
}))

/**
 * Point the help button at `topic` while the calling page is on screen, e.g. the getting-started
 * guide while there is nothing to show yet. `null` leaves the page's own guide page.
 */
export function useHelpTopic(topic: string | null): void {
  const setOverride = useHelp((s) => s.setOverride)
  useEffect(() => {
    setOverride(topic)
    return () => setOverride(null)
  }, [topic, setOverride])
}
