// Renders one page of the user guide. Links between guide pages stay inside the help (through
// onNavigate); other links open in a new tab.
import { useEffect, useRef, useState, type ComponentProps } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import { findPage, hasPage, imageUrl } from './content'
import { resolveHref } from './paths'

/** Heading ids get this prefix so they cannot clash with ids used by the app itself. */
const ID_PREFIX = 'help-'

export function DocView({
  topic,
  anchor,
  onNavigate,
  hrefFor,
}: {
  topic: string
  anchor: string
  onNavigate: (topic: string, anchor: string) => void
  /** Address of a guide page, so links can be opened in a new tab too. */
  hrefFor: (topic: string, anchor: string) => string
}) {
  const { t, i18n } = useTranslation()
  const page = findPage(topic, i18n.language)
  const [text, setText] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    setText(null)
    page?.load().then((s) => { if (!cancelled) setText(s) }).catch(() => { if (!cancelled) setText('') })
    return () => { cancelled = true }
  }, [page])

  useEffect(() => {
    if (text === null) return
    const target = anchor ? root.current?.querySelector(`#${CSS.escape(ID_PREFIX + anchor)}`) : null
    if (target) return target.scrollIntoView({ block: 'start' })
    // A new page starts at its top: reset whichever container scrolls it (help drawer or main).
    for (let el = root.current?.parentElement; el; el = el.parentElement) {
      if (el.scrollHeight > el.clientHeight) { el.scrollTop = 0; break }
    }
  }, [text, anchor])

  if (!page) return <p className="text-sm text-slate-400">{t('help.missing')}</p>
  if (text === null) return <p className="text-sm text-slate-500">{t('help.loading')}</p>

  const scrollTo = (id: string) =>
    root.current?.querySelector(`#${CSS.escape(ID_PREFIX + id)}`)?.scrollIntoView({ block: 'start' })

  const components: Components = {
    a: ({ href = '', children }) => {
      const to = resolveHref(page.repoPath, href)
      const cls = 'text-sky-400 underline decoration-sky-400/40 underline-offset-2 hover:decoration-sky-400'
      if (to.kind === 'anchor') {
        return <a href={`#${to.anchor}`} className={cls} onClick={(e) => { e.preventDefault(); scrollTo(to.anchor) }}>{children}</a>
      }
      if (to.kind === 'doc' && hasPage(to.topic)) {
        return (
          <a href={hrefFor(to.topic, to.anchor)} className={cls}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
              e.preventDefault()
              onNavigate(to.topic, to.anchor)
            }}>
            {children}
          </a>
        )
      }
      const url = to.kind === 'external' ? to.url : to.kind === 'file' ? imageUrl(to.repoPath) : undefined
      if (!url) return <span>{children}</span>
      return <a href={url} target="_blank" rel="noreferrer" className={cls}>{children}</a>
    },
    img: ({ src = '', alt }) => {
      const to = resolveHref(page.repoPath, src)
      const url = to.kind === 'external' ? to.url : to.kind === 'file' ? imageUrl(to.repoPath) : undefined
      if (!url) return null
      return <img src={url} alt={alt ?? ''} loading="lazy" className="max-w-full max-h-[32rem] rounded-lg border border-surface-border my-3" />
    },
    h1: (p) => <h1 {...p} className="text-xl font-semibold text-slate-100 mb-3 scroll-mt-4" />,
    h2: (p) => <h2 {...p} className="text-base font-semibold text-slate-100 mt-7 mb-2 scroll-mt-4" />,
    h3: (p) => <h3 {...p} className="text-sm font-semibold text-slate-200 mt-5 mb-1.5 scroll-mt-4" />,
    p: (p) => <p {...p} className="my-2.5" />,
    ul: (p) => <ul {...p} className="list-disc pl-5 my-2.5 space-y-1" />,
    ol: (p) => <ol {...p} className="list-decimal pl-5 my-2.5 space-y-1" />,
    blockquote: (p) => <blockquote {...p} className="border-l-2 border-sky-500/50 pl-3 my-3 text-slate-400" />,
    hr: () => <hr className="my-5 border-surface-border" />,
    table: (p) => (
      <div className="overflow-x-auto my-3">
        <table {...p} className="text-xs border-collapse w-full" />
      </div>
    ),
    th: (p) => <th {...p} className="text-left font-semibold text-slate-200 border-b border-surface-border px-2 py-1.5 align-bottom" />,
    td: (p) => <td {...p} className="border-b border-surface-border/60 px-2 py-1.5 align-top" />,
    pre: (p) => <pre {...p} className="bg-surface-overlay rounded-lg p-3 my-3 overflow-x-auto text-xs leading-relaxed" />,
    code: ({ className, ...p }: ComponentProps<'code'>) =>
      className
        ? <code {...p} className={`${className} font-mono`} />
        : <code {...p} className="font-mono text-[0.85em] bg-surface-overlay rounded px-1 py-0.5" />,
  }

  return (
    <div ref={root} className="text-sm text-slate-300 leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSlug, { prefix: ID_PREFIX }]]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
