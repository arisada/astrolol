import { useTranslation } from 'react-i18next'
import { NudgeJoystick } from '@/components/NudgeJoystick'
import type { DockWidgetProps } from '../registry'
import { useDevice } from './useDevice'

/** The thumb joystick: one big circle to nudge the mount without looking at the screen. */
export function MountJoystickWidget({ deviceId }: DockWidgetProps) {
  const { t: tc } = useTranslation()
  const id = useDevice('mount', deviceId)
  if (!id) return <p className="text-xs text-slate-500">{tc('dock.noMount')}</p>
  return <NudgeJoystick deviceId={id} />
}
