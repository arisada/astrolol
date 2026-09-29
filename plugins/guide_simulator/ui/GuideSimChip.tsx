import { Chip } from '@/components/ui/badge'
import { useStore } from '@/store'

export interface GuideSimChipState {
  guiding: boolean
  reason: string | null
}

export function GuideSimChip() {
  const s = useStore((st) => st.pluginStates['guide_simulator'] as GuideSimChipState | undefined)
  if (!s) return null
  if (s.guiding) return <Chip label="Guide sim" status="guiding" variant="green" />
  if (s.reason === 'stopped' || s.reason === 'disconnected') return null
  return <Chip label="Guide sim" status={(s.reason ?? 'lost').replace('_', ' ')} variant="amber" pulse />
}
