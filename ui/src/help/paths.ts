// Where the user guide lives and how its pages link to each other.
//
// The guide is plain Markdown that also reads well on GitHub, so pages link to each other with
// relative paths between their places in the repository:
//   docs/<lng>/<page>.md                  core pages ("getting-started", "mount"…)
//   docs/<page>.md                        pages in one language only (deployment guide)
//   astrolol/plugins/<id>/docs/<lng>.md   one page per plugin, next to its code
// A page's *topic* is its file name for core pages and the plugin id for plugin pages. The help
// panel shows a topic in the interface language and falls back to English.

export const INDEX_TOPIC = 'README'
export const GETTING_STARTED_TOPIC = 'getting-started'

export interface DocRef {
  topic: string
  /** null for a page that exists in one language only. */
  lng: string | null
}

/** Repository-relative path of a file found by an import.meta.glob key ("../../../docs/en/x.md"). */
export function repoPathFromGlobKey(key: string): string | null {
  const m = key.match(/(?:^|\/)((?:docs|astrolol\/plugins)\/.+)$/)
  return m ? m[1] : null
}

export function docRefFromPath(repoPath: string): DocRef | null {
  let m = repoPath.match(/^docs\/([^/]+)\/([^/]+)\.md$/)
  if (m) return { topic: m[2], lng: m[1] }
  m = repoPath.match(/^docs\/([^/]+)\.md$/)
  if (m) return { topic: m[1], lng: null }
  m = repoPath.match(/^astrolol\/plugins\/([^/]+)\/docs\/([^/]+)\.md$/)
  if (m) return { topic: m[1], lng: m[2] }
  return null
}

/** Join a relative path onto a directory and resolve "." and ".." segments. */
export function joinPath(dir: string, rel: string): string {
  const out = dir ? dir.split('/') : []
  for (const part of rel.split('/')) {
    if (part === '' || part === '.') continue
    if (part === '..') out.pop()
    else out.push(part)
  }
  return out.join('/')
}

export type ResolvedHref =
  | { kind: 'external'; url: string }
  | { kind: 'anchor'; anchor: string }
  | { kind: 'doc'; topic: string; anchor: string }
  | { kind: 'file'; repoPath: string }

/** The Markdown parser percent-encodes link targets ("#propriétés" → "#propri%C3%A9t%C3%A9s"). */
function decode(s: string): string {
  try { return decodeURIComponent(s) } catch { return s }
}

/** What a link written in the page at `fromPath` points to. */
export function resolveHref(fromPath: string, href: string): ResolvedHref {
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('//')) return { kind: 'external', url: href }
  if (href.startsWith('#')) return { kind: 'anchor', anchor: decode(href.slice(1)) }
  const hash = href.indexOf('#')
  const path = decode(hash < 0 ? href : href.slice(0, hash))
  const anchor = decode(hash < 0 ? '' : href.slice(hash + 1))
  const dir = fromPath.includes('/') ? fromPath.slice(0, fromPath.lastIndexOf('/')) : ''
  const repoPath = joinPath(dir, path)
  const ref = docRefFromPath(repoPath)
  return ref ? { kind: 'doc', topic: ref.topic, anchor } : { kind: 'file', repoPath }
}

// Core pages and the guide page that explains each. Plugin pages live at "/<plugin id>" and
// their topic is the plugin id.
const CORE_ROUTE_TOPICS: Record<string, string> = {
  equipment: 'equipment',
  profiles: 'profiles',
  imaging: 'imaging',
  mount: 'mount',
  logs: 'logs',
  options: 'options',
}

/** The guide topic that explains the page at `pathname`. */
export function topicForRoute(pathname: string): string {
  const first = pathname.split('/').filter(Boolean)[0]
  if (!first) return 'imaging'   // "/" shows the Imaging page
  if (first === 'help') return pathname.split('/').filter(Boolean)[1] ?? INDEX_TOPIC
  return CORE_ROUTE_TOPICS[first] ?? first
}
