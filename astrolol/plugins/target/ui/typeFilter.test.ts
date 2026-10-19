import { describe, expect, it } from 'vitest'
import { sanitizeSelection, TONIGHT_KINDS, tonightTypes, toggleGroup, TYPE_GROUPS, typesParam } from './typeFilter'

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

  it('offers a Tonight kind for every group', () => {
    const covered = new Set(TONIGHT_KINDS.flatMap((k) => tonightTypes(k).split(',')))
    expect(TYPE_GROUPS.every((g) => covered.has(g))).toBe(true)
    expect(tonightTypes('other')).toBe('other')
    expect(tonightTypes('galaxy')).toBe('galaxy')
  })
})
