import { useTranslation } from 'react-i18next'
import { EventLog } from '@/components/ui/event-log'

const LEVELS = ['warning', 'error']

/** Warnings and errors from anywhere, so a problem shows on every page. */
export function WarningsWidget() {
  const { t } = useTranslation('logs')
  return (
    <div>
      <EventLog levels={LEVELS} className="rounded" style={{ height: "8rem", borderTopWidth: 0 }} />
      <p className="mt-1 text-[11px] text-slate-500">{t('widget.hint')}</p>
    </div>
  )
}
