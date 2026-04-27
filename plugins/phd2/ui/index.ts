import { Crosshair } from 'lucide-react'
import { Phd2Page } from './Phd2Page'
import { Phd2Chip } from './Phd2Chip'
import { registerPluginEventHandlers, registerSilentEventTypes } from '@/store'
import { DEFAULT_PHD2_STATE, MAX_GUIDE_STEPS } from './api'
import type { AstrolollEvent } from '@/api/types'
import type { Phd2PluginState, GuidePoint } from './api'

registerPluginEventHandlers('phd2', {
  'phd2.guide_step': (event: AstrolollEvent, cur: unknown): Phd2PluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'phd2.guide_step' }>
    const s = (cur as Phd2PluginState | null) ?? DEFAULT_PHD2_STATE
    const point: GuidePoint = { frame: e.frame, ra: e.ra_dist, dec: e.dec_dist, ts: e.timestamp }
    return { ...s, guidePoints: [...s.guidePoints, point].slice(-MAX_GUIDE_STEPS) }
  },
  'phd2.connected': (_event: AstrolollEvent, cur: unknown): Phd2PluginState => {
    const s = (cur as Phd2PluginState | null) ?? DEFAULT_PHD2_STATE
    return {
      ...s,
      status: {
        connected: true, state: 'Unknown',
        rms_ra: null, rms_dec: null, rms_total: null,
        pixel_scale: null, star_snr: null, is_dithering: false, debug_enabled: false,
      },
    }
  },
  'phd2.disconnected': (): Phd2PluginState => ({
    status: {
      connected: false, state: 'Disconnected',
      rms_ra: null, rms_dec: null, rms_total: null,
      pixel_scale: null, star_snr: null, is_dithering: false, debug_enabled: false,
    },
    guidePoints: [],
  }),
  'phd2.state_changed': (event: AstrolollEvent, cur: unknown) => {
    const e = event as Extract<AstrolollEvent, { type: 'phd2.state_changed' }>
    const s = (cur as Phd2PluginState | null) ?? DEFAULT_PHD2_STATE
    if (!s.status) return undefined
    return { ...s, status: { ...s.status, state: e.state } }
  },
})

// guide_step is high-frequency — route to plugin state but skip the event log
registerSilentEventTypes('phd2.guide_step')

export default {
  icon: Crosshair,
  label: 'Guiding',
  Component: Phd2Page,
  StatusChip: Phd2Chip,
}
