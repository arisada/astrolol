// Pick a task target: search the object catalog, pick a favorite, use the mount's
// current pointing, or (advanced) type coordinates.
import { useEffect, useRef, useState } from 'react'
import { Crosshair, Search, Star, Telescope } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { fmtDec, fmtRA } from '@/utils/formatting'
import type { SequencerTargetRef } from '@/api/types'
import { getFavorites, searchObjects, type Favorite, type ObjectMatch } from './api'

type Tab = 'search' | 'favorites' | 'current' | 'coordinates'

const TABS: { id: Tab; label: string; icon: typeof Search }[] = [
  { id: 'search', label: 'Search', icon: Search },
  { id: 'favorites', label: 'Favorites', icon: Star },
  { id: 'current', label: 'Mount pointing', icon: Telescope },
  { id: 'coordinates', label: 'Coordinates', icon: Crosshair },
]

const KIND_LABEL: Record<SequencerTargetRef['kind'], string> = {
  catalog: 'catalog',
  favorite: 'favorite',
  current: 'no slew',
  coordinates: 'coordinates',
}

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, '')

/** "5 35 17", "5:35:17.3", "5h35m17s" or decimal hours → hours. */
export function parseRA(text: string): number | null {
  const parts = text.trim().split(/[^\d.]+/).filter(Boolean).map(Number)
  if (parts.length === 0 || parts.some(Number.isNaN)) return null
  const [h, m = 0, s = 0] = parts
  const hours = h + m / 60 + s / 3600
  return hours >= 0 && hours < 24 ? hours : null
}

/** "-5 23 28", "+41:16:09", "41d16m9s" or decimal degrees → degrees. */
export function parseDec(text: string): number | null {
  const t = text.trim()
  const negative = t.startsWith('-')
  const parts = t.replace(/^[+-]/, '').split(/[^\d.]+/).filter(Boolean).map(Number)
  if (parts.length === 0 || parts.some(Number.isNaN)) return null
  const [d, m = 0, s = 0] = parts
  const deg = (d + m / 60 + s / 3600) * (negative ? -1 : 1)
  return deg >= -90 && deg <= 90 ? deg : null
}

export function TargetSummary({ target }: { target: SequencerTargetRef | null }) {
  if (!target) return <p className="text-sm text-slate-500">No target selected.</p>
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-sm font-medium text-slate-100 truncate">{target.name}</span>
      <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-surface-overlay text-slate-400 shrink-0">
        {KIND_LABEL[target.kind]}
      </span>
      {target.ra != null && target.dec != null && (
        <span className="text-xs font-mono text-slate-500 truncate">
          {fmtRA(target.ra / 15)} {fmtDec(target.dec)}
        </span>
      )}
    </div>
  )
}

export function TargetPicker({ value, onChange }: {
  value: SequencerTargetRef | null
  onChange: (t: SequencerTargetRef) => void
}) {
  const [tab, setTab] = useState<Tab>(value?.kind === 'favorite' ? 'favorites'
    : value?.kind === 'current' ? 'current'
    : value?.kind === 'coordinates' ? 'coordinates' : 'search')

  return (
    <div className="flex flex-col gap-2">
      <div className="rounded border border-surface-border bg-surface px-3 py-2">
        <TargetSummary target={value} />
      </div>
      <div className="flex gap-1 flex-wrap">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded border transition-colors
              ${tab === id
                ? 'border-accent text-accent bg-accent/10'
                : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'}`}
          >
            <Icon size={12} /> {label}
          </button>
        ))}
      </div>
      {tab === 'search' && <SearchTab onChange={onChange} />}
      {tab === 'favorites' && <FavoritesTab onChange={onChange} />}
      {tab === 'current' && <CurrentTab value={value} onChange={onChange} />}
      {tab === 'coordinates' && <CoordinatesTab value={value} onChange={onChange} />}
    </div>
  )
}

function SearchTab({ onChange }: { onChange: (t: SequencerTargetRef) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ObjectMatch[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current)
    if (query.trim().length < 2) { setResults([]); return }
    debounce.current = setTimeout(async () => {
      setLoading(true)
      try {
        setResults(await searchObjects(query.trim()))
        setError(null)
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setLoading(false)
      }
    }, 280)
    return () => { if (debounce.current) clearTimeout(debounce.current) }
  }, [query])

  return (
    <div className="flex flex-col gap-1">
      <Input autoFocus placeholder="M 42, NGC 7000, Heart Nebula, Jupiter…" value={query}
        onChange={(e) => setQuery(e.target.value)} />
      {error && <p className="text-xs text-status-error">{error}</p>}
      {loading && <p className="text-xs text-slate-500">Searching…</p>}
      <ul className="max-h-56 overflow-y-auto divide-y divide-surface-border">
        {results.map((r) => (
          <li key={`${r.source}:${r.name}`}>
            <button
              type="button"
              className="w-full text-left px-2 py-1.5 hover:bg-surface-overlay flex items-center gap-2"
              onClick={() => onChange({
                kind: 'catalog',
                // Keep the name the user searched for when it's one of the object's names
                // ("M 31" rather than the catalog's primary "NGC 224"); resolve by primary name.
                name: [r.name, ...r.aliases].find((n) => norm(n) === norm(query)) ?? r.name,
                catalog_id: r.name,
                ra: r.ra,
                dec: r.dec,
              })}
            >
              <span className="text-sm text-slate-200">{r.name}</span>
              <span className="text-xs text-slate-500 truncate">{r.aliases.slice(0, 3).join(' · ')}</span>
              <span className="ml-auto text-[10px] text-slate-500 shrink-0">{r.type}</span>
            </button>
          </li>
        ))}
      </ul>
      {results.some((r) => r.source === 'solar_system') && (
        <p className="text-xs text-slate-500">Solar-system objects are re-resolved when the task starts.</p>
      )}
    </div>
  )
}

function FavoritesTab({ onChange }: { onChange: (t: SequencerTargetRef) => void }) {
  const [favorites, setFavorites] = useState<Favorite[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getFavorites().then(setFavorites).catch((e: Error) => setError(e.message))
  }, [])
  if (error) return <p className="text-xs text-status-error">Favorites unavailable: {error}</p>
  if (favorites === null) return <p className="text-xs text-slate-500">Loading…</p>
  if (favorites.length === 0) {
    return <p className="text-xs text-slate-500">No favorites yet — add some from the Target page.</p>
  }
  return (
    <ul className="max-h-56 overflow-y-auto divide-y divide-surface-border">
      {favorites.map((f) => (
        <li key={f.id}>
          <button
            type="button"
            className="w-full text-left px-2 py-1.5 hover:bg-surface-overlay flex items-center gap-2"
            onClick={() => onChange({ kind: 'favorite', name: f.name, favorite_id: f.id, ra: f.ra, dec: f.dec })}
          >
            <Star size={12} className="text-amber-400 shrink-0" />
            <span className="text-sm text-slate-200">{f.name}</span>
            {f.object_name && f.object_name !== f.name && (
              <span className="text-xs text-slate-500">{f.object_name}</span>
            )}
            <span className="ml-auto text-[10px] text-slate-500">{f.object_type}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

function CurrentTab({ value, onChange }: {
  value: SequencerTargetRef | null
  onChange: (t: SequencerTargetRef) => void
}) {
  const [name, setName] = useState(value?.kind === 'current' ? value.name : '')
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-500">
        No slew and no centering: the task images wherever the mount points when it starts.
        The name labels the frames (FITS OBJECT, file names).
      </p>
      <div className="flex gap-2">
        <Input placeholder="Name for the frames" value={name} onChange={(e) => setName(e.target.value)} />
        <button
          type="button"
          disabled={!name.trim()}
          onClick={() => onChange({ kind: 'current', name: name.trim() })}
          className="px-3 text-xs rounded border border-accent text-accent disabled:opacity-40"
        >
          Use
        </button>
      </div>
    </div>
  )
}

function CoordinatesTab({ value, onChange }: {
  value: SequencerTargetRef | null
  onChange: (t: SequencerTargetRef) => void
}) {
  const [name, setName] = useState(value?.kind === 'coordinates' ? value.name : '')
  const [ra, setRa] = useState(value?.kind === 'coordinates' && value.ra != null ? fmtRA(value.ra / 15) : '')
  const [dec, setDec] = useState(value?.kind === 'coordinates' && value.dec != null ? fmtDec(value.dec) : '')
  const raH = parseRA(ra)
  const decD = parseDec(dec)
  const ok = name.trim() !== '' && raH !== null && decD !== null
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-500">ICRS (J2000). RA in hours (5 35 17 or 5.588), Dec in degrees (-5 23 28 or -5.39).</p>
      <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
      <div className="grid grid-cols-2 gap-2">
        <Input placeholder="RA  hh mm ss" value={ra} onChange={(e) => setRa(e.target.value)}
          className={ra && raH === null ? 'border-status-error' : ''} />
        <Input placeholder="Dec  ±dd mm ss" value={dec} onChange={(e) => setDec(e.target.value)}
          className={dec && decD === null ? 'border-status-error' : ''} />
      </div>
      <button
        type="button"
        disabled={!ok}
        onClick={() => ok && onChange({ kind: 'coordinates', name: name.trim(), ra: raH! * 15, dec: decD! })}
        className="self-start px-3 py-1 text-xs rounded border border-accent text-accent disabled:opacity-40"
      >
        Use these coordinates
      </button>
    </div>
  )
}
