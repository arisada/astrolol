// Debounced search-as-you-type box that queries the object_resolver plugin.
// Renders a dropdown of results with type badges.

import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'

export interface ObjectMatch {
  name: string
  aliases: string[]
  ra: number
  dec: number
  type: string
  source: string
}

const TYPE_COLORS: Record<string, string> = {
  Galaxy: 'bg-violet-500/20 text-violet-300',
  'Galaxy Group': 'bg-violet-500/20 text-violet-300',
  'Galaxy Pair': 'bg-violet-500/20 text-violet-300',
  'Galaxy Cluster': 'bg-violet-500/20 text-violet-300',
  'Open Cluster': 'bg-amber-500/20 text-amber-300',
  'Globular Cluster': 'bg-amber-500/20 text-amber-300',
  'Emission Nebula': 'bg-sky-500/20 text-sky-300',
  'Planetary Nebula': 'bg-sky-500/20 text-sky-300',
  'Reflection Nebula': 'bg-sky-500/20 text-sky-300',
  'HII Region': 'bg-sky-500/20 text-sky-300',
  'Supernova Remnant': 'bg-rose-500/20 text-rose-300',
  Star: 'bg-yellow-500/20 text-yellow-300',
}

function typeBadgeClass(type: string): string {
  return TYPE_COLORS[type] ?? 'bg-slate-600/30 text-slate-300'
}

interface Props {
  onSelect: (obj: ObjectMatch) => void
}

export function SearchBox({ onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ObjectMatch[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.trim().length < 2) {
      setResults([])
      setOpen(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await fetch(
          `/plugins/object_resolver/search?q=${encodeURIComponent(query)}&limit=12`,
        )
        if (res.ok) {
          const data: ObjectMatch[] = await res.json()
          setResults(data)
          setOpen(data.length > 0)
          setActiveIdx(-1)
        }
      } finally {
        setLoading(false)
      }
    }, 280)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query])

  function select(obj: ObjectMatch) {
    setQuery(obj.name)
    setOpen(false)
    onSelect(obj)
  }

  function clear() {
    setQuery('')
    setResults([])
    setOpen(false)
    inputRef.current?.focus()
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      select(results[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <div className="relative flex items-center">
        <Search className="absolute left-3 h-4 w-4 text-slate-400 pointer-events-none" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search objects — M42, NGC 891, Andromeda…"
          className="w-full pl-10 pr-9 py-2.5 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/40"
          aria-autocomplete="list"
          aria-expanded={open}
        />
        {(query || loading) && (
          <button
            onMouseDown={(e) => { e.preventDefault(); clear() }}
            className="absolute right-3 p-0.5 rounded text-slate-500 hover:text-slate-300"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && (
        <ul
          ref={listRef}
          className="absolute z-[100] mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 shadow-2xl overflow-hidden"
          role="listbox"
        >
          {results.map((obj, i) => (
            <li
              key={`${obj.name}-${i}`}
              role="option"
              aria-selected={i === activeIdx}
              onMouseDown={(e) => { e.preventDefault(); select(obj) }}
              className={`flex items-center gap-2.5 px-3 py-2 cursor-pointer text-sm ${
                i === activeIdx ? 'bg-slate-700' : 'hover:bg-slate-700/60'
              }`}
            >
              <span className="font-medium text-slate-100 truncate flex-1">{obj.name}</span>
              {obj.aliases.length > 1 && (
                <span className="text-xs text-slate-500 truncate max-w-[5rem]">
                  {obj.aliases.filter((a) => a !== obj.name).slice(0, 2).join(', ')}
                </span>
              )}
              <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded font-medium ${typeBadgeClass(obj.type)}`}>
                {obj.type}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
