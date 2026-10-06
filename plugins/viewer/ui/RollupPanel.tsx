import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import * as api from './api'

function formatHours(totalSeconds: number): string {
  return `${(totalSeconds / 3600).toFixed(1)}h`
}

export function RollupPanel() {
  const { t } = useTranslation('viewer')
  const [rows, setRows] = useState<api.RollupRow[]>([])

  useEffect(() => {
    api.getRollup().then(setRows).catch(() => {})
  }, [])

  if (rows.length === 0) return <p className="text-xs text-slate-500 p-3">{t('rollup.none')}</p>

  return (
    <div className="flex flex-col gap-1 p-3 text-xs">
      <table className="w-full">
        <thead>
          <tr className="text-slate-500 border-b border-surface-border">
            <th className="text-left py-1">{t('rollup.object')}</th>
            <th className="text-right py-1">{t('rollup.frames')}</th>
            <th className="text-right py-1">{t('rollup.integration')}</th>
            <th className="text-right py-1">{t('rollup.nights')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.object_name} className="border-b border-surface-border/50">
              <td className="py-1 text-slate-200">{r.object_name}</td>
              <td className="py-1 text-right text-slate-400">{r.frame_count}</td>
              <td className="py-1 text-right text-slate-400">{formatHours(r.total_exposure_s)}</td>
              <td className="py-1 text-right text-slate-400">{r.nights}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
