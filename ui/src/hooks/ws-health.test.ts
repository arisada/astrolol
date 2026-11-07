import { describe, expect, it } from 'vitest'
import { controlMessage, isStale, mustReconnect, STALE_AFTER_MS, STALE_ON_WAKE_MS } from './ws-health'

describe('ws health', () => {
  it('is stale after more than three heartbeats of silence', () => {
    expect(isStale(0, STALE_AFTER_MS)).toBe(false)
    expect(isStale(0, STALE_AFTER_MS + 1)).toBe(true)
  })

  it('replaces a socket that is closed, or silent for too long', () => {
    expect(mustReconnect(1, 1000, 2000)).toBe(false)
    expect(mustReconnect(0, 1000, 2000)).toBe(false)  // connecting: given time to come up
    expect(mustReconnect(0, 0, STALE_AFTER_MS + 1)).toBe(true)
    expect(mustReconnect(2, 1000, 2000)).toBe(true)   // closing
    expect(mustReconnect(3, 1000, 2000)).toBe(true)   // closed
    expect(mustReconnect(undefined, 1000, 2000)).toBe(true)
  })

  it('is stricter when the tab comes back', () => {
    expect(mustReconnect(1, 0, STALE_ON_WAKE_MS + 1, STALE_ON_WAKE_MS)).toBe(true)
    expect(mustReconnect(1, 0, STALE_ON_WAKE_MS + 1)).toBe(false)
  })

  it('recognises the control messages and nothing else', () => {
    expect(controlMessage('ws.heartbeat')).toBe('ws.heartbeat')
    expect(controlMessage('ws.resync')).toBe('ws.resync')
    expect(controlMessage('sequencer.status')).toBeNull()
  })
})
