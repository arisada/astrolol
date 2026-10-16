import { Crosshair } from 'lucide-react'
import { registerPluginEventHandlers, registerSilentEventTypes } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import type { NavActivity } from '@/utils/nav-activity'
import { GuiderPage } from './GuiderPage'
import { GuiderChip } from './GuiderChip'
import { GuiderGraphWidget, GuiderStatusWidget, GuiderTargetWidget } from './GuiderWidgets'
import i18n from '@/i18n'
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
    const sample = { ra: e.ra_dist, dec: e.dec_dist, ts: e.timestamp, raCorr: e.ra_corr, decCorr: e.dec_corr }
    return { ...s, guiding: true, reason: null, steps: [...s.steps, sample].slice(-MAX_STEPS), snr: e.star_snr, stars: e.stars_found }
  },
})

// One guide step per frame: keep them for the graph, out of the event log.
registerSilentEventTypes('guider.step')

export default {
  icon: Crosshair,
  label: 'Guider',
  Component: GuiderPage,
  StatusChip: GuiderChip,
  widgets: [
    { id: 'status', title: () => i18n.t('widget.status', { ns: 'guider' }), icon: Crosshair, Component: GuiderStatusWidget },
    { id: 'target', title: () => i18n.t('widget.target', { ns: 'guider' }), icon: Crosshair, Component: GuiderTargetWidget },
    { id: 'graph', title: () => i18n.t('widget.graph', { ns: 'guider' }), icon: Crosshair, Component: GuiderGraphWidget },
  ],
  // Guiding is busy; having lost the star (anything but a deliberate stop) needs attention.
  navActivity: (cur: unknown): NavActivity => {
    const s = cur as GuiderPluginState | null | undefined
    if (!s || s.guiding === null) return null
    if (s.guiding) return 'busy'
    return s.reason === 'stopped' || s.reason === 'disconnected' ? null : 'alert'
  },
}
