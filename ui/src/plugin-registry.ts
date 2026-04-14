/**
 * Static plugin registry — maps plugin IDs to their frontend metadata.
 *
 * When a new plugin is added, register it here with its route, sidebar icon,
 * label, and page component.  The backend /plugins endpoint gates which entries
 * are actually shown — only enabled plugins appear in the sidebar and routing.
 */
import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Smile } from 'lucide-react'
import { HelloPage } from '@plugins/hello/ui/HelloPage'

export interface PluginRegistryEntry {
  to: string
  icon: LucideIcon
  label: string
  Component: ComponentType
}

const PLUGIN_REGISTRY: Record<string, PluginRegistryEntry> = {
  hello: {
    to: '/hello',
    icon: Smile,
    label: 'Hello',
    Component: HelloPage,
  },
}

export function getPluginEntry(id: string): PluginRegistryEntry | undefined {
  return PLUGIN_REGISTRY[id]
}
