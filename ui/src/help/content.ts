// The user guide, bundled into the UI at build time so it works without Internet and always
// matches the installed version. Page text is loaded when a page is first opened; images are
// emitted as assets and only downloaded when shown. See paths.ts for the layout.
import { docRefFromPath, repoPathFromGlobKey } from './paths'

type Loader = () => Promise<string>

const pageModules = {
  ...import.meta.glob('../../../docs/*.md', { query: '?raw', import: 'default' }),
  ...import.meta.glob('../../../docs/*/*.md', { query: '?raw', import: 'default' }),
  ...import.meta.glob('@plugins/*/docs/*.md', { query: '?raw', import: 'default' }),
} as Record<string, Loader>

const imageModules = {
  ...import.meta.glob('../../../docs/images/*.{png,jpg,jpeg,svg}', { eager: true, query: '?url', import: 'default' }),
  ...import.meta.glob('@plugins/*/docs/*.{png,jpg,jpeg,svg}', { eager: true, query: '?url', import: 'default' }),
} as Record<string, string>

export interface DocPage {
  repoPath: string
  load: Loader
}

// topic → language ('' for a page in one language only) → page
const pages = new Map<string, Map<string, DocPage>>()
for (const [key, load] of Object.entries(pageModules)) {
  const repoPath = repoPathFromGlobKey(key)
  const ref = repoPath ? docRefFromPath(repoPath) : null
  if (!repoPath || !ref) continue
  if (!pages.has(ref.topic)) pages.set(ref.topic, new Map())
  pages.get(ref.topic)!.set(ref.lng ?? '', { repoPath, load })
}

const images = new Map<string, string>()
for (const [key, url] of Object.entries(imageModules)) {
  const repoPath = repoPathFromGlobKey(key)
  if (repoPath) images.set(repoPath, url)
}

/** The page for `topic` in `lng`, else in English, else its only version. */
export function findPage(topic: string, lng: string): DocPage | null {
  const byLng = pages.get(topic)
  if (!byLng) return null
  return byLng.get(lng) ?? byLng.get('en') ?? byLng.get('') ?? null
}

export function hasPage(topic: string): boolean {
  return pages.has(topic)
}

export function imageUrl(repoPath: string): string | undefined {
  return images.get(repoPath)
}
