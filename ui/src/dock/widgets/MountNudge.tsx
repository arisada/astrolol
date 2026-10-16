import { useTranslation } from 'react-i18next'
import { NudgePad } from '@/components/NudgePad'
import type { DockWidgetProps } from '../registry'
import { useDevice } from './useDevice'

/** The Mount page's nudge pad: speed, directions and a stop button. */
export function MountNudgeWidget({ deviceId }: DockWidgetProps) {
  const { t: tc } = useTranslation()
  const id = useDevice('mount', deviceId)
  if (!id) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>
  return <NudgePad deviceId={id} />
}
