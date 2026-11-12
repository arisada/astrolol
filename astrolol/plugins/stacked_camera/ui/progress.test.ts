import { describe, expect, it } from 'vitest'
import type { AstrolollEvent } from '@/api/types'
import { applyProgress } from './progress'

type Progress = Extract<AstrolollEvent, { type: 'stacked_camera.progress' }>

const event = (over: Partial<Progress>): Progress => ({
  id: 'e', timestamp: '2026-11-12T21:00:00Z', type: 'stacked_camera.progress',
  device_id: 'cam_stack', active: true, subs_done: 1, subs_total: 3, exposure_done: 2, exposure_total: 6,
  ...over,
} as Progress)

describe('applyProgress', () => {
  it('records the exposure of a device', () => {
    expect(applyProgress(event({}), null)).toEqual({
      cam_stack: { subsDone: 1, subsTotal: 3, exposureDone: 2, exposureTotal: 6 },
    })
  })

  it('replaces the previous state of the same device and keeps the others', () => {
    const first = applyProgress(event({ device_id: 'a' }), null)
    const both = applyProgress(event({ device_id: 'b', subs_done: 2 }), first)
    const later = applyProgress(event({ device_id: 'a', subs_done: 3 }), both)
    expect(later?.a.subsDone).toBe(3)
    expect(later?.b.subsDone).toBe(2)
  })

  it('removes a device whose exposure is over', () => {
    const both = applyProgress(event({ device_id: 'b' }), applyProgress(event({ device_id: 'a' }), null))
    expect(Object.keys(applyProgress(event({ device_id: 'a', active: false }), both) ?? {})).toEqual(['b'])
  })

  it('is null once nothing is exposing, so the status bar clears', () => {
    const one = applyProgress(event({}), null)
    expect(applyProgress(event({ active: false }), one)).toBeNull()
  })

  it('does not modify the state it was given', () => {
    const one = applyProgress(event({}), null)
    const copy = JSON.parse(JSON.stringify(one))
    applyProgress(event({ device_id: 'other' }), one)
    expect(one).toEqual(copy)
  })
})
