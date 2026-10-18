import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JoystickController } from './joystickController'
import { LEASE_MS, RENEW_MS, TAP_MS, type NudgeIo } from './nudgeController'

function rig(opts: { startDelay?: number; failFor?: string } = {}) {
  const calls: string[] = []
  const errors: unknown[] = []
  const io: NudgeIo = {
    start: async (d, r, ms) => {
      calls.push(`start ${d} ${r} ${ms}`)
      if (opts.startDelay) await new Promise((res) => setTimeout(res, opts.startDelay))
      if (opts.failFor === d) throw new Error('refused')
    },
    stop: async () => { calls.push('stop') },
    onError: (e) => { errors.push(e) },
  }
  return { calls, errors, ctl: new JoystickController(io) }
}
const flush = (ms = 10) => vi.advanceTimersByTimeAsync(ms)

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('JoystickController', () => {
  it('moves while the thumb is out and stops when it lifts', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'N', rate: '8x' }])
    await flush(TAP_MS + 100)
    ctl.end()
    await flush()
    expect(calls).toEqual([`start N 8x ${LEASE_MS}`, 'stop'])
  })

  it('a flick still moves for the fixed tap time, then stops by itself', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'E', rate: '8x' }])
    await flush(50)
    ctl.end()
    await flush(TAP_MS * 2)
    expect(calls[0]).toBe(`start E 8x ${LEASE_MS}`)
    expect(calls[1]).toMatch(/^start E 8x \d+$/)
    const ms = Number(calls[1].split(' ')[3])
    expect(ms).toBeGreaterThanOrEqual(50)
    expect(ms).toBeLessThanOrEqual(TAP_MS)
    expect(calls).not.toContain('stop')
  })

  it('changing speed restarts the move at the new rate, without a stop', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'N', rate: '1x' }])
    await flush()
    ctl.update([{ direction: 'N', rate: '16x' }])
    await flush()
    expect(calls).toEqual([`start N 1x ${LEASE_MS}`, `start N 16x ${LEASE_MS}`])
  })

  it('adding a second axis only starts that axis', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'N', rate: '4x' }])
    await flush()
    ctl.update([{ direction: 'N', rate: '4x' }, { direction: 'E', rate: '4x' }])
    await flush()
    expect(calls).toEqual([`start N 4x ${LEASE_MS}`, `start E 4x ${LEASE_MS}`])
  })

  it('dropping one axis stops everything and restarts the other', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'N', rate: '4x' }, { direction: 'E', rate: '4x' }])
    await flush()
    calls.length = 0
    ctl.update([{ direction: 'N', rate: '4x' }])
    await flush()
    expect(calls).toEqual(['stop', `start N 4x ${LEASE_MS}`])
  })

  it('renews the lease while held and stops renewing after the end', async () => {
    const { ctl, calls } = rig()
    ctl.update([{ direction: 'S', rate: '2x' }])
    await flush(RENEW_MS * 3 + 50)
    expect(calls.filter((c) => c.startsWith('start')).length).toBe(4)
    ctl.end()
    await flush(RENEW_MS * 5)
    expect(calls.filter((c) => c.startsWith('start')).length).toBe(4)
    expect(calls[calls.length - 1]).toBe('stop')
  })

  it('answers a burst of updates with the latest wish, not each one', async () => {
    const { ctl, calls } = rig({ startDelay: 100 })
    for (const r of ['1x', '2x', '4x', '8x', '16x']) ctl.update([{ direction: 'N', rate: r }])
    await flush(400)
    expect(calls).toEqual([`start N 1x ${LEASE_MS}`, `start N 16x ${LEASE_MS}`])
  })

  it('a stop never overtakes a start still in flight', async () => {
    const { ctl, calls } = rig({ startDelay: 300 })
    ctl.update([{ direction: 'W', rate: '4x' }])
    await flush(50)
    ctl.abort()
    await flush(1000)
    expect(calls).toEqual([`start W 4x ${LEASE_MS}`, 'stop'])
  })

  it('gives up on a refused move and reports it', async () => {
    const { ctl, calls, errors } = rig({ failFor: 'N' })
    ctl.update([{ direction: 'N', rate: '4x' }])
    await flush(RENEW_MS * 3)
    expect(errors).toHaveLength(1)
    expect(calls.filter((c) => c.startsWith('start')).length).toBe(1)
  })

  it('abort with nothing moving sends nothing', async () => {
    const { ctl, calls } = rig()
    ctl.abort()
    await flush()
    expect(calls).toEqual([])
  })
})
