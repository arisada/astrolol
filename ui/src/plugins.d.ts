// Type stubs for plugin UI modules resolved via the @plugins alias.
// With import.meta.glob auto-discovery, only the index module shape matters.

declare module '@plugins/*/ui/index.ts' {
  import type { ComponentType } from 'react'
  import type { LucideIcon } from 'lucide-react'
  const plugin: { icon: LucideIcon; label: string; Component: ComponentType }
  export default plugin
}
