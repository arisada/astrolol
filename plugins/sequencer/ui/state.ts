// The sequencer's slice of the core store (pluginStates['sequencer']).
// Live updates come from WebSocket snapshot events (see index.ts); the page seeds the
// slice from REST on mount, so it is correct even before the first event arrives.
import { useStore } from '@/store'
import type { SequencerQueueEntry, SequencerStatus } from '@/api/types'

export interface SequencerUiState {
  status: SequencerStatus | null
  entries: SequencerQueueEntry[] | null
}

const EMPTY: SequencerUiState = { status: null, entries: null }

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
