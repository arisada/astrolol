// What a navigation entry shows next to its icon: something running, or something needing attention.
import type { ConnectedDevice } from '@/api/types'

export type NavActivity = 'busy' | 'alert' | null

const RANK = { busy: 1, alert: 2 } as const

/** The most serious of several activities (alert beats busy beats nothing). */
export function worstActivity(activities: NavActivity[]): NavActivity {
  let worst: NavActivity = null
  for (const a of activities) {
    if (a && (!worst || RANK[a] > RANK[worst])) worst = a
  }
  return worst
}

/** A device in error is an alert; otherwise `busy` decides. */
export function deviceActivity(devices: Pick<ConnectedDevice, 'state'>[], busy: boolean): NavActivity {
  if (devices.some((d) => d.state === 'error')) return 'alert'
  return busy ? 'busy' : null
}
