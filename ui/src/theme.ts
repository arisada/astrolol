// Palette switching. The palette is a UserSettings field (like the language); the last value is
// also kept in localStorage so index.html can apply it before first paint.
import { THEMES, type ThemeId } from './themes'

export { THEMES }
export type { ThemeId }

export const DEFAULT_THEME: ThemeId = 'midnight'

export function isTheme(id: unknown): id is ThemeId {
  return THEMES.some((t) => t.id === id)
}

/** Apply a palette. Unknown ids fall back to the default. */
export function setTheme(id: string): void {
  const theme = THEMES.find((t) => t.id === id) ?? THEMES[0]
  document.documentElement.dataset.theme = theme.id
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme.bg1)
  try {
    localStorage.setItem('astrolol.theme', theme.id)
  } catch {
    /* storage blocked: the palette still applies for this session */
  }
}
