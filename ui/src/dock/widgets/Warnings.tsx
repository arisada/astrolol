import { useTranslation } from 'react-i18next'
import { LogList, useLogEntries } from '@/components/ui/log-list'

const LEVELS = ['warning', 'error']

/** Warnings and errors from anywhere, so a problem shows on every page. */
export function WarningsWidget() {
  const { t } = useTranslation('logs')
  const entries = useLogEntries(undefined, LEVELS)
  return (
    <div>
      <LogList entries={entries} className="rounded" style={{ height: '8rem' }} />
      <p className="mt-1 text-[11px] text-slate-500">{t('widget.hint')}</p>
    </div>
  )
}
