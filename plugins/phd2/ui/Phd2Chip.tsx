import { useStore } from '@/store'
import { Chip } from '@/components/StatusBar'
import type { Phd2PluginState } from './api'

export function Phd2Chip() {
  const phd2 = useStore((s) => (s.pluginStates['phd2'] as Phd2PluginState | null | undefined)?.status)
  if (!phd2?.connected) return null

  const state = phd2.state ?? ''
  const rms = phd2.rms_total

  if (state === 'Guiding') {
    const rmsStr = rms !== null ? ` ${rms.toFixed(2)}"` : ''
    return <Chip label="PHD2" status={`Guiding${rmsStr}`} variant="green" />
  }
  if (state === 'Calibrating') {
    return <Chip label="PHD2" status="Calibrating" variant="amber" pulse />
  }
  if (phd2.is_dithering) {
    return <Chip label="PHD2" status="Dithering" variant="amber" pulse />
  }
  if (state && state !== 'Stopped' && state !== 'Disconnected' && state !== 'Unknown') {
    return <Chip label="PHD2" status={state} variant="slate" />
  }
  return <Chip label="PHD2" status="Connected" variant="slate" />
}
