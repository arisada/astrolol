// Shared shape for the plugin-state slice fed by registerPluginEventHandlers in
// index.ts and read by FlatWizardPage (full detail) and FlatWizardChip (summary).

export interface FlatWizardLiveTrial {
  cameraId: string
  filterIndex: number
  filterName: string | null
  attempt: number
  duration: number
  meanAdu: number
  fullScaleAdu: number
  ratioPct: number
  saturated: boolean
}

export interface FlatWizardLiveResult {
  cameraId: string
  filterIndex: number
  filterName: string | null
  status: 'solved' | 'failed'
  duration?: number
  error?: string
}

export interface FlatWizardLiveState {
  totalFilters: number
  trials: FlatWizardLiveTrial[]
  liveResults: FlatWizardLiveResult[]
}
