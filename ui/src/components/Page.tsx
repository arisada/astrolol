import type { ReactNode } from 'react'

export type PageWidth = 'narrow' | 'medium' | 'wide'

const MAX_WIDTH: Record<PageWidth, string> = {
  narrow: 'max-w-md',    // 28 rem: a single column of controls (Mount)
  medium: 'max-w-2xl',   // 42 rem: forms and settings, most pages
  wide: 'max-w-5xl',     // 64 rem: pages with side-by-side panels (Guider, Sequencer)
}

/**
 * The frame of a page that reads as a column: one scroll container, a centred column of one of three
 * widths, and the same padding everywhere. The column shrinks with the window, so the page fits a
 * phone and the room left beside the dock. Pages built as split panes (a viewer with a sidebar) fill
 * the screen themselves instead. `className` styles the column (flex, gap, spacing).
 */
export function Page({ width = 'medium', className = '', children }: {
  width?: PageWidth
  className?: string
  children: ReactNode
}) {
  return (
    <div className="h-full min-h-0 flex-1 overflow-y-auto">
      <div className={`mx-auto w-full ${MAX_WIDTH[width]} p-4 md:p-6 ${className}`}>{children}</div>
    </div>
  )
}
