/**
 * Static plugin registry — maps plugin IDs to their frontend metadata.
 *
 * When a new plugin is added, register it here with its route, sidebar icon,
 * label, and page component.  The backend /plugins endpoint gates which entries
 * are actually shown — only enabled plugins appear in the sidebar and routing.
 */
import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Crosshair, Smile } from 'lucide-react'
import { HelloPage } from '@plugins/hello/ui/HelloPage'
import { Phd2Page } from '@plugins/phd2/ui/Phd2Page'

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
  phd2: {
    to: '/phd2',
    icon: Crosshair,
    label: 'Guiding',
    Component: Phd2Page,
  },
}

export function getPluginEntry(id: string): PluginRegistryEntry | undefined {
  return PLUGIN_REGISTRY[id]
}
