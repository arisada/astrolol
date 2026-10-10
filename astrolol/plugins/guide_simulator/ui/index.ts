import { Crosshair } from 'lucide-react'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import { GuideSimPage } from './GuideSimPage'
import { GuideSimChip, type GuideSimChipState } from './GuideSimChip'

registerPluginEventHandlers('guide_simulator', {
  'guiding.state_changed': (event: AstrolollEvent): GuideSimChipState | undefined => {
    const e = event as Extract<AstrolollEvent, { type: 'guiding.state_changed' }>
    if (e.guider !== 'simulator') return undefined
    return { guiding: e.guiding, reason: e.reason }
  },
})

export default {
  icon: Crosshair,
  label: 'Guide Simulator',
  Component: GuideSimPage,
  StatusChip: GuideSimChip,
}
