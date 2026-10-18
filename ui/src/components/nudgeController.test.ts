import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HOLD_MS, LEASE_MS, NudgeController, RENEW_MS, TAP_MS, type NudgeIo } from './nudgeController'

function rig(opts: { startDelay?: number; failStart?: boolean } = {}) {
  const calls: string[] = []
  const errors: unknown[] = []
  const io: NudgeIo = {
    start: async (d, r, ms) => {
      calls.push(`start ${d} ${r} ${ms}`)
      if (opts.startDelay) await new Promise((res) => setTimeout(res, opts.startDelay))
      if (opts.failStart) throw new Error('refused')
      calls.push(`started ${d}`)
    },
    stop: async () => { calls.push('stop') },
    onError: (e) => { errors.push(e) },
  }
  return { calls, errors, ctl: new NudgeController(io) }
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('NudgeController', () => {
  it('a quick press moves for a fixed time and never sends a stop', async () => {
    const { ctl, calls } = rig()
    ctl.pressDown('N', '8x')
    await vi.advanceTimersByTimeAsync(HOLD_MS - 50)
    ctl.release()
    await vi.advanceTimersByTimeAsync(5000)
    expect(calls).toEqual([`start N 8x ${TAP_MS}`, 'started N'])
  })

  it('a long press moves while held and stops on release', async () => {
    const { ctl, calls } = rig()
    ctl.pressDown('E', '16x')
    await vi.advanceTimersByTimeAsync(HOLD_MS + 10)
    expect(calls[0]).toBe(`start E 16x ${LEASE_MS}`)
    ctl.release()
    await vi.advanceTimersByTimeAsync(10)
    expect(calls[calls.length - 1]).toBe('stop')
  })

  it('renews the lease while held and stops renewing after release', async () => {
    const { ctl, calls } = rig()
    ctl.pressDown('W', '1x')
    await vi.advanceTimersByTimeAsync(HOLD_MS + RENEW_MS * 3 + 10)
    const starts = calls.filter((c) => c.startsWith('start ')).length
    expect(starts).toBe(4)
    ctl.release()
    await vi.advanceTimersByTimeAsync(RENEW_MS * 5)
    expect(calls.filter((c) => c.startsWith('start ')).length).toBe(starts)
  })

  it('never lets a stop overtake a slow start', async () => {
    const { ctl, calls } = rig({ startDelay: 400 })
    ctl.pressDown('S', '4x')
    await vi.advanceTimersByTimeAsync(HOLD_MS + 10)   // start in flight
    ctl.release()
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls.indexOf('stop')).toBeGreaterThan(calls.indexOf('started S'))
  })

  it('does not pile renewals up behind a slow request', async () => {
    const { ctl, calls } = rig({ startDelay: 3000 })
    ctl.pressDown('N', '1x')
    await vi.advanceTimersByTimeAsync(HOLD_MS + RENEW_MS * 4)
    expect(calls.filter((c) => c.startsWith('start ')).length).toBe(1)
    ctl.release()
  })

  it('ignores a second press while one is down', async () => {
    const { ctl, calls } = rig()
    ctl.pressDown('N', '1x')
    ctl.pressDown('E', '1x')
    ctl.release()
    await vi.advanceTimersByTimeAsync(10)
    expect(calls).toEqual([`start N 1x ${TAP_MS}`, 'started N'])
  })

  it('abort before the hold does nothing; abort while holding stops', async () => {
    const a = rig()
    a.ctl.pressDown('N', '1x')
    a.ctl.abort()
    await vi.advanceTimersByTimeAsync(HOLD_MS * 4)
    expect(a.calls).toEqual([])

    const b = rig()
    b.ctl.pressDown('N', '1x')
    await vi.advanceTimersByTimeAsync(HOLD_MS + 10)
    b.ctl.abort()
    await vi.advanceTimersByTimeAsync(10)
    expect(b.calls[b.calls.length - 1]).toBe('stop')
  })

  it('reports a refused start and keeps working', async () => {
    const { ctl, errors, calls } = rig({ failStart: true })
    ctl.pressDown('N', '1x')
    ctl.release()
    await vi.advanceTimersByTimeAsync(10)
    expect(errors).toHaveLength(1)
    ctl.pressDown('S', '1x')
    ctl.release()
    await vi.advanceTimersByTimeAsync(10)
    expect(calls.filter((c) => c.startsWith('start ')).length).toBe(2)
  })
})
