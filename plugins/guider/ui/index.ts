import { Crosshair } from 'lucide-react'
import { registerPluginEventHandlers, registerSilentEventTypes } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import { GuiderPage } from './GuiderPage'
import { GuiderChip } from './GuiderChip'
import { DEFAULT_GUIDER_STATE, MAX_STEPS, type GuiderPluginState } from './api'

const current = (cur: unknown) => (cur as GuiderPluginState | null) ?? DEFAULT_GUIDER_STATE

registerPluginEventHandlers('guider', {
  'guiding.state_changed': (event: AstrolollEvent, cur: unknown): GuiderPluginState | undefined => {
    const e = event as Extract<AstrolollEvent, { type: 'guiding.state_changed' }>
    if (e.guider !== 'builtin') return undefined
    return { ...current(cur), guiding: e.guiding, reason: e.reason }
  },
  'guider.step': (event: AstrolollEvent, cur: unknown): GuiderPluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'guider.step' }>
    const s = current(cur)
    const sample = { ra: e.ra_dist, dec: e.dec_dist, ts: e.timestamp }
    return { ...s, guiding: true, reason: null, steps: [...s.steps, sample].slice(-MAX_STEPS) }
  },
})

// One guide step per frame: keep them for the graph, out of the event log.
registerSilentEventTypes('guider.step')

export default {
  icon: Crosshair,
  label: 'Guider',
  Component: GuiderPage,
  StatusChip: GuiderChip,
}
