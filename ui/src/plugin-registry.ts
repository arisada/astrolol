// Plugin registry — auto-discovered from each plugin's ui/index.ts.
// Each plugin exports a default object with { icon, label, Component }.
// The plugin ID is derived from the directory name in the path.
// No manual registration is needed when adding a new plugin.
import type { ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'

export interface PluginRegistryEntry {
  to: string
  icon: LucideIcon
  label: string
  Component: ComponentType
  /** Optional status-bar chip rendered while the plugin is active. */
  StatusChip?: ComponentType
}

// Eagerly import all plugin index files.  Vite resolves this glob at build time.
// Side-effects in each index.ts (e.g. registerPluginEventHandlers) run here.
const modules = import.meta.glob('@plugins/*/ui/index.ts', { eager: true }) as Record<
  string,
  { default: { icon: LucideIcon; label: string; Component: ComponentType; StatusChip?: ComponentType } }
>

// Build the registry by extracting the plugin ID from each module path.
// Path shape: "../../plugins/<id>/ui/index.ts" (as seen from this file via the @plugins alias)
const PLUGIN_REGISTRY: Record<string, PluginRegistryEntry> = {}

for (const [path, mod] of Object.entries(modules)) {
  const match = path.match(/\/([^/]+)\/ui\/index\.ts$/)
  if (!match) continue
  const id = match[1]
  const { icon, label, Component, StatusChip } = mod.default
  PLUGIN_REGISTRY[id] = { to: `/${id}`, icon, label, Component, StatusChip }
}

export function getPluginEntry(id: string): PluginRegistryEntry | undefined {
  return PLUGIN_REGISTRY[id]
}

export function getAllPluginEntries(): PluginRegistryEntry[] {
  return Object.values(PLUGIN_REGISTRY)
}
