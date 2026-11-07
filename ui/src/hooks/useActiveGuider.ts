// Which of the enabled guiding plugins is the one in use (the others refuse to act).
// Kept in the store under pluginStates['guiding']: seeded from REST, then moved by the
// guiding.active_changed event.
import { useEffect } from 'react'
import { api } from '@/api/client'
import type { ActiveGuider, AstrolollEvent } from '@/api/types'
import { registerPluginEventHandlers, registerSilentEventTypes, useStore } from '@/store'

registerSilentEventTypes('guiding.active_changed')
registerPluginEventHandlers('guiding', {
  'guiding.active_changed': (event: AstrolollEvent): ActiveGuider => {
    const e = event as Extract<AstrolollEvent, { type: 'guiding.active_changed' }>
    return { active: e.active, available: e.available }
  },
})

let loading: Promise<void> | null = null

export function refreshActiveGuider(): Promise<void> {
  loading ??= api.guiding.active()
    .then((g) => useStore.setState((s) => ({ pluginStates: { ...s.pluginStates, guiding: g } })))
    .catch(() => undefined)
    .finally(() => { loading = null })
  return loading
}

/** The guider in use; null until known. */
export function useActiveGuider(): ActiveGuider | null {
  const wsConnected = useStore((s) => s.wsConnected)
  useEffect(() => { void refreshActiveGuider() }, [wsConnected])
  return useStore((s) => (s.pluginStates['guiding'] as ActiveGuider | undefined) ?? null)
}

/** True when another guiding plugin is the one in use. Unknown counts as not inactive. */
export function isInactiveGuider(guider: ActiveGuider | null, pluginId: string): boolean {
  return guider !== null && guider.active !== null && guider.active !== pluginId
}

export function useIsInactiveGuider(pluginId: string): boolean {
  return isInactiveGuider(useActiveGuider(), pluginId)
}
