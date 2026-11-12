import { Layers } from 'lucide-react'
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import type { NavActivity } from '@/utils/nav-activity'
import { StackedCameraPage } from './StackedCameraPage'
import { StackedCameraChip } from './StackedCameraChip'
import { applyProgress, type StackProgressState } from './progress'

registerPluginEventHandlers('stacked_camera', {
  'stacked_camera.progress': (event: AstrolollEvent, cur: unknown): StackProgressState | null =>
    applyProgress(
      event as Extract<AstrolollEvent, { type: 'stacked_camera.progress' }>,
      cur as StackProgressState | null | undefined,
    ),
})

export default {
  icon: Layers,
  label: 'Stacked camera',
  Component: StackedCameraPage,
  StatusChip: StackedCameraChip,
  navActivity: (cur: unknown): NavActivity => (cur ? 'busy' : null),
}
