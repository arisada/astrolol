import type { ProfileNode } from '@/api/types'

export type NodePath = number[]

/** Swap the item at `path` for another one, keeping its role and everything attached below it. */
export function replaceItemAtPath(roots: ProfileNode[], path: NodePath, itemId: string): ProfileNode[] {
  return roots.map((node, i) => {
    if (i !== path[0]) return node
    if (path.length === 1) return { ...node, item_id: itemId }
    return { ...node, children: replaceItemAtPath(node.children, path.slice(1), itemId) }
  })
}

/** Name for a copy of a profile: "Rig (copy)", then "Rig (copy 2)", … */
export function copyName(name: string, existing: string[], suffix: (n: number) => string): string {
  const taken = new Set(existing)
  let n = 1
  while (taken.has(`${name} ${suffix(n)}`)) n++
  return `${name} ${suffix(n)}`
}

/** Deep copy of a tree, so a duplicated profile never shares nodes with its source. */
export function cloneTree(roots: ProfileNode[]): ProfileNode[] {
  return roots.map((n) => ({ ...n, children: cloneTree(n.children) }))
}
