import { useEffect, useState } from 'react'

/** Live result of a CSS media query. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const update = () => setMatches(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [query])
  return matches
}

/** A phone (or narrow window) held upright: navigation moves to a top bar. */
export const PORTRAIT_NARROW = '(orientation: portrait) and (max-width: 900px)'
