import { Crosshair } from 'lucide-react'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import type { NavActivity } from '@/utils/nav-activity'
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
  // Guiding is busy; having lost the star (anything but a deliberate stop) needs attention.
  navActivity: (cur: unknown): NavActivity => {
    const s = cur as GuideSimChipState | null | undefined
    if (!s) return null
    if (s.guiding) return 'busy'
    return s.reason === 'stopped' || s.reason === 'disconnected' ? null : 'alert'
  },
}
