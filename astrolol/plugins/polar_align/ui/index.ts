import { Compass } from 'lucide-react'
import { PolarAlignPage } from './PolarAlignPage'
import { PolarAlignChip } from './PolarAlignChip'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'

interface PolarAlignRunningState {
  status: 'running' | 'converging'
  pointIndex: number | null
  altErrorArcmin: number | null
  azErrorArcmin: number | null
}

registerPluginEventHandlers('polar_align', {
  'polar_align.wizard_started': (): PolarAlignRunningState => ({
    status: 'running', pointIndex: null, altErrorArcmin: null, azErrorArcmin: null,
  }),
  'polar_align.point_started': (event, cur) => {
    const e = event as Extract<AstrolollEvent, { type: 'polar_align.point_started' }>
    const current = cur as PolarAlignRunningState | null | undefined
    return current ? { ...current, pointIndex: e.index } : undefined
  },
  'polar_align.fit_completed': (event) => {
    const e = event as Extract<AstrolollEvent, { type: 'polar_align.fit_completed' }>
    return {
      status: 'converging', pointIndex: null,
      altErrorArcmin: e.alt_error_arcmin, azErrorArcmin: e.az_error_arcmin,
    } satisfies PolarAlignRunningState
  },
  'polar_align.error_updated': (event, cur) => {
    const e = event as Extract<AstrolollEvent, { type: 'polar_align.error_updated' }>
    const current = cur as PolarAlignRunningState | null | undefined
    return {
      status: 'converging', pointIndex: current?.pointIndex ?? null,
      altErrorArcmin: e.alt_error_arcmin, azErrorArcmin: e.az_error_arcmin,
    } satisfies PolarAlignRunningState
  },
  'polar_align.wizard_completed': () => null,
  'polar_align.wizard_failed': () => null,
  'polar_align.wizard_cancelled': () => null,
})

export default {
  icon: Compass,
  label: 'Polar Align',
  Component: PolarAlignPage,
  StatusChip: PolarAlignChip,
}
