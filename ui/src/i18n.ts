// i18n setup. English is the source language and the fallback.
//
// Core strings live in src/locales/<lng>/<ns>.json (one namespace per page/area, "common" for
// the shell and shared components).
// Each plugin ships its own catalogues in plugins/<id>/ui/locales/<lng>.json and
// they are registered under the namespace <id> — no core file needs editing to
// translate a plugin. Use `useTranslation('<id>')` in plugin components.
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
] as const

type Catalogue = Record<string, unknown>

const coreModules = import.meta.glob('./locales/*/*.json', { eager: true, import: 'default' }) as Record<string, Catalogue>
const pluginModules = import.meta.glob('@plugins/*/ui/locales/*.json', { eager: true, import: 'default' }) as Record<string, Catalogue>

const resources: Record<string, Record<string, Catalogue>> = {}
const add = (lng: string, ns: string, catalogue: Catalogue) => {
  ;(resources[lng] ??= {})[ns] = catalogue
}

for (const [path, catalogue] of Object.entries(coreModules)) {
  const m = path.match(/\/locales\/([^/]+)\/([^/]+)\.json$/)
  if (m) add(m[1], m[2], catalogue)
}
for (const [path, catalogue] of Object.entries(pluginModules)) {
  const m = path.match(/\/([^/]+)\/ui\/locales\/([^/]+)\.json$/)
  if (m) add(m[2], m[1], catalogue)
}

i18n.use(initReactI18next).init({
  resources,
  lng: 'en',
  fallbackLng: 'en',
  defaultNS: 'common',
  interpolation: { escapeValue: false }, // React already escapes
})

/** Switch the UI language and keep <html lang> in sync. Unknown codes fall back to English. */
export function setLanguage(code: string): void {
  const known = SUPPORTED_LANGUAGES.some((l) => l.code === code) ? code : 'en'
  void i18n.changeLanguage(known)
  document.documentElement.lang = known
}

export default i18n
