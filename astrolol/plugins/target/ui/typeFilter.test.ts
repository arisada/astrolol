import { describe, expect, it } from 'vitest'
import { sanitizeSelection, toggleGroup, typesParam } from './typeFilter'

describe('type filter', () => {
  it('sends nothing when nothing is selected', () => {
    expect(typesParam([])).toBe('')
  })

  it('lists the selection in a fixed order', () => {
    expect(typesParam(['nebula', 'galaxy'])).toBe('galaxy,nebula')
  })

  it('toggles a group on and off', () => {
    expect(toggleGroup([], 'star')).toEqual(['star'])
    expect(toggleGroup(['star', 'galaxy'], 'star')).toEqual(['galaxy'])
  })

  it('drops stored values that are not groups', () => {
    expect(sanitizeSelection(['galaxy', 'comet', 3])).toEqual(['galaxy'])
    expect(sanitizeSelection('galaxy')).toEqual([])
    expect(sanitizeSelection(null)).toEqual([])
  })
})
