import { ListVideo } from 'lucide-react'
import { registerPluginEventHandlers, registerSilentEventTypes } from '@/store'
import type { AstrolollEvent } from '@/api/types'
import { SequencerPage } from './SequencerPage'
import { SequencerChip } from './SequencerChip'
import type { SequencerUiState } from './state'

const EMPTY: SequencerUiState = { status: null, entries: null }

// Snapshots replace the whole slice; they are silent (not in the log panel). The
// fine-grained events are silent too: the backend's "sequencer" log lines already tell
// the same story in readable form.
registerSilentEventTypes(
  'sequencer.status', 'sequencer.queue_changed',
  'sequencer.session_started', 'sequencer.session_finished',
  'sequencer.task_started', 'sequencer.task_finished',
  'sequencer.step_started', 'sequencer.step_finished', 'sequencer.step_skipped', 'sequencer.step_failed',
  'sequencer.frame_saved', 'sequencer.frame_discarded',
  'sequencer.interruption', 'sequencer.resumed',
  'sequencer.task_stalled', 'sequencer.stall_attempt', 'sequencer.task_unstalled',
)

registerPluginEventHandlers('sequencer', {
  'sequencer.status': (event: AstrolollEvent, cur: unknown): SequencerUiState => {
    const e = event as Extract<AstrolollEvent, { type: 'sequencer.status' }>
    return { ...((cur as SequencerUiState | null) ?? EMPTY), status: e.status }
  },
  'sequencer.queue_changed': (event: AstrolollEvent, cur: unknown): SequencerUiState => {
    const e = event as Extract<AstrolollEvent, { type: 'sequencer.queue_changed' }>
    return { ...((cur as SequencerUiState | null) ?? EMPTY), entries: e.entries }
  },
})

export default {
  icon: ListVideo,
  label: 'Sequencer',
  Component: SequencerPage,
  StatusChip: SequencerChip,
}
