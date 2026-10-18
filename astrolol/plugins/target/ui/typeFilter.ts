// The kinds of object the search can be narrowed to (the object_resolver's type groups).

export const TYPE_GROUPS = ['galaxy', 'cluster', 'nebula', 'star', 'solar_system', 'other'] as const
export type TypeGroup = (typeof TYPE_GROUPS)[number]

/** The `types` query parameter for a selection; none selected means no filter at all. */
export function typesParam(selected: readonly TypeGroup[]): string {
  return TYPE_GROUPS.filter((g) => selected.includes(g)).join(',')
}

/** A stored selection cleaned of anything that is no longer a group. */
export function sanitizeSelection(stored: unknown): TypeGroup[] {
  if (!Array.isArray(stored)) return []
  return TYPE_GROUPS.filter((g) => stored.includes(g))
}

export function toggleGroup(selected: readonly TypeGroup[], group: TypeGroup): TypeGroup[] {
  return selected.includes(group) ? selected.filter((g) => g !== group) : [...selected, group]
}
