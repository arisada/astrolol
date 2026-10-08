import { Crosshair } from 'lucide-react'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import { GuiderPage } from './GuiderPage'
import { GuiderChip } from './GuiderChip'
import type { GuiderChipState } from './api'

registerPluginEventHandlers('guider', {
  'guiding.state_changed': (event: AstrolollEvent): GuiderChipState | undefined => {
    const e = event as Extract<AstrolollEvent, { type: 'guiding.state_changed' }>
    if (e.guider !== 'builtin') return undefined
    return { guiding: e.guiding, reason: e.reason }
  },
})

export default {
  icon: Crosshair,
  label: 'Guider',
  Component: GuiderPage,
  StatusChip: GuiderChip,
}
