import { useTranslation } from 'react-i18next'
import type { EquipmentItem } from '@/api/types'
import { deviceSource } from '@/utils/device-source'

/** A small tag naming what drives a device item: INDI, INDIGO, or the plugin behind it. */
export function DeviceSourceTag({ item }: { item: EquipmentItem }) {
  const { t, i18n } = useTranslation()
  const source = deviceSource(item)
  if (!source) return null
  const label =
    source.kind === 'plugin' ? i18n.t('manifest.name', { ns: source.plugin, defaultValue: source.plugin })
    : source.kind === 'adapter' ? source.adapter
    : t(`deviceSource.${source.kind}`)
  return (
    <span
      className="shrink-0 text-[10px] leading-4 px-1.5 rounded border border-surface-border text-slate-500 whitespace-nowrap"
      title={t('deviceSource.title', { source: label })}
    >
      {label}
    </span>
  )
}
