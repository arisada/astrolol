import { ScanSearch } from 'lucide-react'
import { PlatesolvePage } from './PlatesolvePage'
import { PlatesolveChip } from './PlatesolveChip'
import { registerPluginEventHandlers } from '@/store'
import { DEFAULT_PLATESOLVE_STATE } from './api'
import type { AstrolollEvent } from '@/api/types'
import type { PlateSolvePluginState, SolveResult } from './api'

registerPluginEventHandlers('platesolve', {
  'platesolve.started': (event: AstrolollEvent, cur: unknown): PlateSolvePluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'platesolve.started' }>
    const s = (cur as PlateSolvePluginState | null) ?? DEFAULT_PLATESOLVE_STATE
    const existing = s.jobs[e.solve_id]
    return {
      ...s,
      jobs: {
        ...s.jobs,
        [e.solve_id]: {
          ...existing,
          id: e.solve_id,
          status: 'pending' as const,
          request: existing?.request ?? { fits_path: e.fits_path },
          created_at: existing?.created_at ?? e.timestamp,
        },
      },
    }
  },
  'platesolve.completed': (event: AstrolollEvent, cur: unknown): PlateSolvePluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'platesolve.completed' }>
    const s = (cur as PlateSolvePluginState | null) ?? DEFAULT_PLATESOLVE_STATE
    const existing = s.jobs[e.solve_id]
    if (!existing) return s
    const result: SolveResult = {
      ra: e.ra, dec: e.dec, rotation: e.rotation,
      pixel_scale: e.pixel_scale, field_w: e.field_w, field_h: e.field_h,
      duration_ms: e.duration_ms,
    }
    return { ...s, jobs: { ...s.jobs, [e.solve_id]: { ...existing, status: 'completed', result, completed_at: e.timestamp } } }
  },
  'platesolve.failed': (event: AstrolollEvent, cur: unknown): PlateSolvePluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'platesolve.failed' }>
    const s = (cur as PlateSolvePluginState | null) ?? DEFAULT_PLATESOLVE_STATE
    const existing = s.jobs[e.solve_id]
    if (!existing) return s
    return { ...s, jobs: { ...s.jobs, [e.solve_id]: { ...existing, status: 'failed', error: e.reason, completed_at: e.timestamp } } }
  },
  'platesolve.cancelled': (event: AstrolollEvent, cur: unknown): PlateSolvePluginState => {
    const e = event as Extract<AstrolollEvent, { type: 'platesolve.cancelled' }>
    const s = (cur as PlateSolvePluginState | null) ?? DEFAULT_PLATESOLVE_STATE
    const existing = s.jobs[e.solve_id]
    if (!existing) return s
    return { ...s, jobs: { ...s.jobs, [e.solve_id]: { ...existing, status: 'cancelled', completed_at: e.timestamp } } }
  },
})

export default {
  icon: ScanSearch,
  label: 'Plate Solving',
  Component: PlatesolvePage,
  StatusChip: PlatesolveChip,
}
