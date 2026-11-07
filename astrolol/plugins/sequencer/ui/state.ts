// The sequencer's slice of the core store (pluginStates['sequencer']).
// The status is kept live by WebSocket snapshot events (see index.ts). The queue is large, so
// it travels by REST: the page fetches it when it opens and whenever `revision` (the queue
// changed) moves; nothing else needs it.
import { useStore } from '@/store'
import type { SequencerQueueEntry, SequencerStatus } from '@/api/types'

export interface SequencerUiState {
  status: SequencerStatus | null
  entries: SequencerQueueEntry[] | null
  revision: number
}

const EMPTY: SequencerUiState = { status: null, entries: null, revision: 0 }

export function useSequencer(): SequencerUiState {
  return useStore((s) => (s.pluginStates['sequencer'] as SequencerUiState | undefined) ?? EMPTY)
}

export function patchSequencerState(patch: Partial<SequencerUiState>) {
  useStore.setState((s) => ({
    pluginStates: {
      ...s.pluginStates,
      sequencer: { ...((s.pluginStates['sequencer'] as SequencerUiState | undefined) ?? EMPTY), ...patch },
    },
  }))
}
