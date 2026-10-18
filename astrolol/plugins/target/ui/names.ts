// Which of an object's many names to show first. "M 31" before "NGC 224", then the other
// catalogues people know (NGC, IC, Caldwell, Sharpless), then everyday names, then the rest.

interface Ranked { label: string; rank: number }

const CATALOGUES: Array<[RegExp, (m: RegExpMatchArray) => string, number]> = [
  [/^(?:m|messier)\s*0*(\d+)$/i, (m) => `M ${m[1]}`, 0],
  [/^ngc\s*0*(\d+\w*)$/i, (m) => `NGC ${m[1]}`, 1],
  [/^ic\s*0*(\d+\w*)$/i, (m) => `IC ${m[1]}`, 2],
  [/^(?:c|caldwell)\s*0*(\d+)$/i, (m) => `C ${m[1]}`, 3],
  [/^(?:sh2|sharpless)[\s-]*0*(\d+)$/i, (m) => `Sh2-${m[1]}`, 4],
]

function rankName(raw: string): Ranked {
  const name = raw.trim()
  for (const [re, label, rank] of CATALOGUES) {
    const m = name.match(re)
    if (m) return { label: label(m), rank }
  }
  // Everyday names ("Andromeda Galaxy") before survey designations ("2MASX J00424433+4116074").
  return { label: name, rank: /\d/.test(name) ? 6 : 5 }
}

/** The name to lead with and the other names, best first, spelled the same way everywhere. */
export function describeNames(name: string, aliases: string[]): { title: string; others: string[] } {
  const seen = new Set<string>()
  const ranked: Ranked[] = []
  for (const raw of [name, ...aliases]) {
    if (!raw.trim()) continue
    const r = rankName(raw)
    const key = r.label.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    ranked.push(r)
  }
  if (ranked.length === 0) return { title: name, others: [] }
  // Stable sort: names of equal rank keep the order they came in (the object's own name first).
  const sorted = ranked.map((r, i) => ({ r, i })).sort((a, b) => a.r.rank - b.r.rank || a.i - b.i).map((x) => x.r)
  const hasMessier = sorted[0].rank === 0
  // Without a Messier number the object's own name leads, whatever its catalogue.
  const first = hasMessier ? sorted[0] : ranked[0]
  return { title: first.label, others: sorted.filter((r) => r !== first).map((r) => r.label) }
}
