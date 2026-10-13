import { describe, expect, it } from 'vitest'
import type { ProfileNode } from '@/api/types'
import { cloneTree, copyName, replaceItemAtPath } from './profile-tree'

const n = (item_id: string, children: ProfileNode[] = [], role: string | null = null): ProfileNode => ({
  item_id, role, children,
})

const tree = [n('site', [n('mount', [n('ota-a', [n('cam')]), n('ota-b', [n('guide-cam')], 'guide')])])]

describe('replaceItemAtPath', () => {
  it('swaps a nested item and keeps its children and role', () => {
    const out = replaceItemAtPath(tree, [0, 0, 1], 'ota-c')
    const swapped = out[0].children[0].children[1]
    expect(swapped.item_id).toBe('ota-c')
    expect(swapped.role).toBe('guide')
    expect(swapped.children.map((c) => c.item_id)).toEqual(['guide-cam'])
  })

  it('swaps a root', () => {
    expect(replaceItemAtPath(tree, [0], 'site-2')[0].item_id).toBe('site-2')
  })

  it('leaves the original and the other branches untouched', () => {
    const out = replaceItemAtPath(tree, [0, 0, 1], 'ota-c')
    expect(tree[0].children[0].children[1].item_id).toBe('ota-b')
    expect(out[0].children[0].children[0]).toBe(tree[0].children[0].children[0])
  })
})

describe('copyName', () => {
  const suffix = (k: number) => (k === 1 ? '(copy)' : `(copy ${k})`)

  it('adds a copy suffix', () => {
    expect(copyName('Rig', ['Rig'], suffix)).toBe('Rig (copy)')
  })

  it('numbers further copies', () => {
    expect(copyName('Rig', ['Rig', 'Rig (copy)', 'Rig (copy 2)'], suffix)).toBe('Rig (copy 3)')
  })
})

describe('cloneTree', () => {
  it('copies every level', () => {
    const copy = cloneTree(tree)
    expect(copy).toEqual(tree)
    expect(copy[0]).not.toBe(tree[0])
    expect(copy[0].children[0]).not.toBe(tree[0].children[0])
  })
})
