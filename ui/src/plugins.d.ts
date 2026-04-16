// Type stubs for plugin UI modules resolved via @plugins/* alias.
// The actual implementation lives in plugins/<name>/ui/*.tsx — Vite handles
// the bundling; this file just satisfies tsc when it encounters these imports.

declare module '@plugins/hello/ui/HelloPage' {
  import type { ComponentType } from 'react'
  export const HelloPage: ComponentType
}
