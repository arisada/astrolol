// Favourites panel: list saved targets, recall on click, delete, inline name editing.

import { useState } from 'react'
import { BookmarkX, ChevronRight, Star } from 'lucide-react'
import type { FavoriteTarget } from './api'
import type { ObjectMatch } from './SearchBox'

interface Props {
  favorites: FavoriteTarget[]
  onRecall: (fav: FavoriteTarget) => void
  onDelete: (id: string) => void
}

function fmtCoord(ra: number, dec: number): string {
  const raNorm = (ra / 15).toFixed(2)
  const sign = dec >= 0 ? '+' : ''
  return `${raNorm}h  ${sign}${dec.toFixed(2)}°`
}

const TYPE_DOT: Record<string, string> = {
  Galaxy: 'bg-violet-400',
  'Open Cluster': 'bg-amber-400',
  'Globular Cluster': 'bg-amber-400',
  'Emission Nebula': 'bg-sky-400',
  'Planetary Nebula': 'bg-sky-400',
  'Reflection Nebula': 'bg-sky-400',
  'HII Region': 'bg-sky-400',
  Star: 'bg-yellow-400',
  'Mount Position': 'bg-emerald-400',
}

function typeDot(type: string): string {
  return TYPE_DOT[type] ?? 'bg-slate-500'
}

export function FavoritesList({ favorites, onRecall, onDelete }: Props) {
  if (favorites.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-slate-600 text-sm gap-2">
        <Star className="h-6 w-6 opacity-40" />
        <span>No favourites yet — search for an object and save it.</span>
      </div>
    )
  }

  return (
    <ul className="space-y-1">
      {favorites.map((fav) => (
        <li key={fav.id} className="group flex items-center gap-2 rounded-lg px-3 py-2.5 hover:bg-slate-700/50 transition-colors">
          {/* Type dot */}
          <span className={`shrink-0 w-2 h-2 rounded-full ${typeDot(fav.object_type)}`} />

          {/* Main content — click to recall */}
          <button
            onClick={() => onRecall(fav)}
            className="flex-1 text-left min-w-0"
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-200 truncate">{fav.name}</span>
              {fav.object_name && fav.object_name !== fav.name && (
                <span className="text-xs text-slate-500 truncate">{fav.object_name}</span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] font-mono text-slate-500">{fmtCoord(fav.ra, fav.dec)}</span>
              {fav.object_type && (
                <span className="text-[10px] text-slate-600">{fav.object_type}</span>
              )}
            </div>
            {fav.notes && (
              <p className="text-[10px] text-slate-600 truncate mt-0.5 italic">{fav.notes}</p>
            )}
          </button>

          {/* Recall arrow */}
          <ChevronRight className="h-3.5 w-3.5 text-slate-600 group-hover:text-indigo-400 transition-colors shrink-0" />

          {/* Delete */}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(fav.id) }}
            className="shrink-0 p-1 rounded text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
            title="Remove from favourites"
          >
            <BookmarkX className="h-3.5 w-3.5" />
          </button>
        </li>
      ))}
    </ul>
  )
}
