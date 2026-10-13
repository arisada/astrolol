// The help drawer, opened from the status bar, and the button that opens it.
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { Trans, useTranslation } from 'react-i18next'
import { ArrowLeft, BookOpen, CircleHelp, ExternalLink, X } from 'lucide-react'
import { LazyDocView as DocView } from './LazyDocView'
import { hasPage } from './content'
import { GETTING_STARTED_TOPIC, INDEX_TOPIC, topicForRoute } from './paths'
import { useHelp } from './store'

export const helpHref = (topic: string, anchor = '') => `/help/${topic}${anchor ? `#${anchor}` : ''}`

const iconButton = 'p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-surface-overlay transition-colors'

export function HelpButton() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const openTopic = useHelp((s) => s.topic)
  const override = useHelp((s) => s.override)
  const open = useHelp((s) => s.open)
  const close = useHelp((s) => s.close)

  const onClick = () => {
    if (openTopic) return close()
    const topic = override ?? topicForRoute(pathname)
    open(hasPage(topic) ? topic : INDEX_TOPIC)
  }

  return (
    <button type="button" onClick={onClick} title={t('help.open')} aria-label={t('help.open')}
      className={`pl-2.5 shrink-0 transition-colors ${openTopic ? 'text-slate-100' : 'text-slate-500 hover:text-slate-200'}`}>
      <CircleHelp size={14} />
    </button>
  )
}

/** "New here? Read Getting started", for pages that have nothing to show yet. */
export function GettingStartedHint() {
  const { t } = useTranslation()
  const open = useHelp((s) => s.open)
  return (
    <p className="text-sm text-slate-500">
      <Trans t={t} i18nKey="help.gettingStarted" components={{
        link: (
          <a href={helpHref(GETTING_STARTED_TOPIC)} className="text-sky-400 underline underline-offset-2"
            onClick={(e) => { e.preventDefault(); open(GETTING_STARTED_TOPIC) }} />
        ),
      }} />
    </p>
  )
}

export function HelpPanel() {
  const { t } = useTranslation()
  const { topic, anchor, history, navigate, back, close } = useHelp()

  useEffect(() => {
    if (!topic) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [topic, close])

  if (!topic) return null

  return (
    <aside aria-label={t('help.title')} className="fixed top-8 bottom-0 right-0 z-40 w-full sm:w-[36rem] flex flex-col
                      bg-surface-raised border-l border-surface-border shadow-2xl">
      <div className="flex items-center gap-1 px-3 h-10 shrink-0 border-b border-surface-border">
        {history.length > 0 && (
          <button type="button" onClick={back} className={iconButton} title={t('help.back')} aria-label={t('help.back')}>
            <ArrowLeft size={15} />
          </button>
        )}
        <span className="label-caps text-xs text-slate-400 pl-1">{t('help.title')}</span>
        <div className="flex-1" />
        <button type="button" onClick={() => { if (topic !== INDEX_TOPIC) navigate(INDEX_TOPIC) }}
          className={iconButton} title={t('help.contents')} aria-label={t('help.contents')}>
          <BookOpen size={15} />
        </button>
        <a href={helpHref(topic, anchor)} target="_blank" rel="noreferrer" className={iconButton}
          title={t('help.newTab')} aria-label={t('help.newTab')}>
          <ExternalLink size={15} />
        </a>
        <button type="button" onClick={close} className={iconButton} title={t('help.close')} aria-label={t('help.close')}>
          <X size={15} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <DocView topic={topic} anchor={anchor} onNavigate={(tp, a) => navigate(tp, a)} hrefFor={helpHref} />
      </div>
    </aside>
  )
}
