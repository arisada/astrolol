import { Moon } from 'lucide-react'
import { TargetPage } from './TargetPage'
import { TargetChip } from './TargetChip'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'

interface TargetState {
  name: string | null
  ra: number
  dec: number
}

// Track the most recently set mount target so TargetChip can show it.
registerPluginEventHandlers('target', {
  'mount.target_set': (event: AstrolollEvent): TargetState => {
    const e = event as Extract<AstrolollEvent, { type: 'mount.target_set' }>
    return { name: e.name, ra: e.ra, dec: e.dec }
  },
})

export default {
  icon: Moon,
  label: 'Target',
  Component: TargetPage,
  StatusChip: TargetChip,
}
