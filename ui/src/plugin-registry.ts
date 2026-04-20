/**
 * Static plugin registry — maps plugin IDs to their frontend metadata.
 *
 * When a new plugin is added, register it here with its route, sidebar icon,
 * label, and page component.  The backend /plugins endpoint gates which entries
 * are actually shown — only enabled plugins appear in the sidebar and routing.
 */
import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Crosshair, ScanSearch, Smile, Telescope } from 'lucide-react'
import { HelloPage } from '@plugins/hello/ui/HelloPage'
import { Lx200Page } from '@plugins/lx200/ui/Lx200Page'
import { Phd2Page } from '@plugins/phd2/ui/Phd2Page'
import { PlatesolvePage } from '@plugins/platesolve/ui/PlatesolvePage'

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
  platesolve: {
    to: '/platesolve',
    icon: ScanSearch,
    label: 'Plate Solving',
    Component: PlatesolvePage,
  },
  lx200: {
    to: '/lx200',
    icon: Telescope,
    label: 'LX200 Server',
    Component: Lx200Page,
  },
}

export function getPluginEntry(id: string): PluginRegistryEntry | undefined {
  return PLUGIN_REGISTRY[id]
}
