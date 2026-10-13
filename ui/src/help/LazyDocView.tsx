// The Markdown renderer is only downloaded the first time help is opened.
import { lazy, Suspense, type ComponentProps } from 'react'
import type { DocView } from './DocView'

const DocViewImpl = lazy(() => import('./DocView').then((m) => ({ default: m.DocView })))

export function LazyDocView(props: ComponentProps<typeof DocView>) {
  return (
    <Suspense fallback={null}>
      <DocViewImpl {...props} />
    </Suspense>
  )
}
