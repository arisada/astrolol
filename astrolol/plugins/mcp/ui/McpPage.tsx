import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '@/components/ui/card'
import * as api from './api'
import type { McpInfo } from './api'
import { Page } from '@/components/Page'

function CopyBlock({ text }: { text: string }) {
  const { t } = useTranslation('mcp')
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard needs a secure page; the text is selectable as a fallback.
    }
  }

  return (
    <div className="flex items-start gap-2">
      <code className="flex-1 min-w-0 break-all rounded bg-surface-overlay px-2 py-1.5 text-xs text-slate-300 select-all">
        {text}
      </code>
      <button
        onClick={copy}
        className="px-2.5 py-1 rounded bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors flex-none"
      >
        {copied ? t('copied') : t('copy')}
      </button>
    </div>
  )
}

function firstSentence(text: string): string {
  const end = text.search(/[.!?](\s|$)/)
  return end === -1 ? text : text.slice(0, end + 1)
}

export function McpPage() {
  const { t } = useTranslation('mcp')
  const [info, setInfo] = useState<McpInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getInfo().then(setInfo).catch(() => setError(t('unreachable')))
  }, [])

  const command = info
    ? `claude mcp add --transport http astrolol ${info.endpoint}` +
      (info.auth_required ? ' --header "Authorization: Bearer <token>"' : '')
    : ''

  return (
    <Page width="medium" className="space-y-4">
      <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
      <p className="text-xs text-slate-500">{t('intro')}</p>

      {error && (
        <div className="rounded-lg border border-surface-border border-l-2 border-l-rose-400 bg-surface-raised px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}

      {info && (
        <>
          <Card title={t('connect')} className="p-4 space-y-3">
            <div>
              <p className="text-xs text-slate-400 mb-1">{t('address')}</p>
              <CopyBlock text={info.endpoint} />
            </div>
            <div>
              <p className="text-xs text-slate-400 mb-1">{t('claudeCode')}</p>
              <CopyBlock text={command} />
            </div>
            {info.auth_required && <p className="text-xs text-slate-500">{t('tokenHint')}</p>}
          </Card>

          <Card title={t('skill')} className="p-4 space-y-2">
            <p className="text-xs text-slate-500">{t('skillHint')}</p>
            <a
              href={api.skillUrl}
              download="SKILL.md"
              className="inline-block px-3 py-1.5 rounded-lg bg-surface-overlay hover:bg-surface-border text-slate-300 text-xs font-medium transition-colors"
            >
              {t('skillDownload')}
            </a>
          </Card>

          <Card title={t('tools', { count: info.tools.length })} className="p-4">
            <ul className="space-y-1.5">
              {info.tools.map((tool) => (
                <li key={tool.name} className="text-xs">
                  <span className="font-mono text-slate-200">{tool.name}</span>
                  {tool.read_only && (
                    <span className="ml-2 rounded border border-surface-border px-1 text-[10px] text-slate-400">
                      {t('readOnly')}
                    </span>
                  )}
                  <span className="block text-slate-500">{firstSentence(tool.description)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </Page>
  )
}
