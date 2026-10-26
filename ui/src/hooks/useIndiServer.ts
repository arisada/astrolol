import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { IndiServerInfo } from '@/api/types'

// Fixed while the backend runs (it is read from its settings at start), so fetched once.
let cached: Promise<IndiServerInfo> | null = null

/** The server astrolol talks INDI to (indiserver or INDIGO); null until known. */
export function useIndiServer(): IndiServerInfo | null {
  const [info, setInfo] = useState<IndiServerInfo | null>(null)
  useEffect(() => {
    let cancelled = false
    cached ??= api.indi.server().catch((e) => { cached = null; throw e })
    cached.then((i) => { if (!cancelled) setInfo(i) }).catch(() => {})
    return () => { cancelled = true }
  }, [])
  return info
}
