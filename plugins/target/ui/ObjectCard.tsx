// Displays coordinates, ephemeris summary, altitude chart, moon info,
// and action buttons for a selected sky object.

import { useState } from 'react'
import { AlertTriangle, BookmarkPlus, ChevronRight, Crosshair, Moon, Navigation } from 'lucide-react'
import type { ObjectMatch } from './SearchBox'
import type { EphemerisResult } from './api'
import { AltitudeChart } from './AltitudeChart'

interface Props {
  object: ObjectMatch
  ephemeris: EphemerisResult | null
  loading: boolean
  mountIds: string[]        // connected mount device IDs
  minAlt: number
  onSetTarget: (mountId: string) => void
  onSetAndSlew: (mountId: string) => void
  onAddToFavorites: () => void
}

function fmt(degrees: number, isRa = false): string {
  if (isRa) {
    const h = degrees / 15
    const hh = Math.floor(h)
    const mm = Math.floor((h - hh) * 60)
    const ss = ((h - hh - mm / 60) * 3600).toFixed(1)
    return `${hh}h ${mm}m ${ss}s`
  }
  const sign = degrees < 0 ? '−' : '+'
  const abs = Math.abs(degrees)
  const dd = Math.floor(abs)
  const mm = Math.floor((abs - dd) * 60)
  const ss = ((abs - dd - mm / 60) * 3600).toFixed(0)
  return `${sign}${dd}° ${mm}′ ${ss}″`
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

function moonIcon(illumination: number): string {
  if (illumination > 0.85) return '🌕'
  if (illumination > 0.6)  return '🌔'
  if (illumination > 0.35) return '🌓'
  if (illumination > 0.1)  return '🌒'
  return '🌑'
}

export function ObjectCard({
  object, ephemeris, loading, mountIds, minAlt,
  onSetTarget, onSetAndSlew, onAddToFavorites,
}: Props) {
  const [selectedMount, setSelectedMount] = useState<string>(mountIds[0] ?? '')

  const hasMounts = mountIds.length > 0

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between px-4 pt-4 pb-3 border-b border-slate-700/50">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">{object.name}</h2>
          {object.aliases.filter((a) => a !== object.name).length > 0 && (
            <p className="text-xs text-slate-500 mt-0.5">
              {object.aliases.filter((a) => a !== object.name).slice(0, 4).join('  ·  ')}
            </p>
          )}
        </div>
        <span className="text-xs px-2 py-1 rounded bg-slate-700 text-slate-300 font-medium mt-0.5">
          {object.type}
        </span>
      </div>

      {/* Coordinates */}
      <div className="grid grid-cols-2 gap-px bg-slate-700/30 border-b border-slate-700/50">
        <div className="px-4 py-2 bg-slate-800/40">
          <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">RA (J2000)</p>
          <p className="text-sm font-mono text-slate-200">{fmt(object.ra, true)}</p>
          <p className="text-[10px] text-slate-600 mt-0.5">{object.ra.toFixed(4)}°</p>
        </div>
        <div className="px-4 py-2 bg-slate-800/40">
          <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">Dec (J2000)</p>
          <p className="text-sm font-mono text-slate-200">{fmt(object.dec)}</p>
          <p className="text-[10px] text-slate-600 mt-0.5">{object.dec.toFixed(4)}°</p>
        </div>
      </div>

      {/* Ephemeris */}
      <div className="px-4 py-3">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-2">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-slate-600 border-t-indigo-400 rounded-full" />
            Computing ephemeris…
          </div>
        )}

        {!loading && ephemeris?.observer_location_missing && (
          <div className="flex items-center gap-2 text-sm text-amber-400 py-1">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            No observer location set — configure it in the active profile.
          </div>
        )}

        {!loading && ephemeris && !ephemeris.observer_location_missing && (
          <>
            {/* Summary line */}
            <div className="mb-3">
              {ephemeris.circumpolar && (
                <p className="text-sm text-emerald-400 font-medium">Circumpolar — always above horizon</p>
              )}
              {ephemeris.never_rises && (
                <p className="text-sm text-slate-500 font-medium">Never rises from your location</p>
              )}
              {!ephemeris.circumpolar && !ephemeris.never_rises && ephemeris.not_observable_at_night && (
                <p className="text-sm text-amber-400 font-medium">
                  Not visible above {minAlt}° during darkness
                </p>
              )}
              {!ephemeris.circumpolar && !ephemeris.never_rises && !ephemeris.not_observable_at_night && ephemeris.imaging_window_start && (
                <p className="text-sm text-slate-300">
                  <span className="text-indigo-400 font-medium">Best window: </span>
                  {fmtTime(ephemeris.imaging_window_start)} → {fmtTime(ephemeris.imaging_window_end)}
                  {ephemeris.peak_alt != null && (
                    <span className="text-slate-500">
                      {' '}· peaks at <span className="text-slate-300">{ephemeris.peak_alt.toFixed(0)}°</span>
                      {ephemeris.peak_time && <> at {fmtTime(ephemeris.peak_time)}</>}
                    </span>
                  )}
                </p>
              )}
            </div>

            {/* Rise / Transit / Set row */}
            {!ephemeris.circumpolar && !ephemeris.never_rises && (
              <div className="flex gap-1 mb-3">
                {([
                  ['Rise',    ephemeris.rise,    'text-emerald-400'],
                  ['Transit', ephemeris.transit ?? ephemeris.peak_time, 'text-yellow-400'],
                  ['Set',     ephemeris.set,     'text-red-400'],
                ] as [string, string | null, string][]).map(([label, iso, color]) => (
                  <div key={label} className="flex-1 rounded-lg bg-slate-900/50 px-3 py-2 text-center">
                    <p className={`text-[10px] uppercase tracking-wide font-medium mb-1 ${color}`}>{label}</p>
                    <p className="text-sm font-mono text-slate-200 whitespace-nowrap">{fmtTime(iso)}</p>
                  </div>
                ))}
              </div>
            )}

            {/* Altitude chart */}
            {ephemeris.altitude_curve.length > 0 && (
              <div className="mb-3">
                <AltitudeChart ephemeris={ephemeris} minAlt={minAlt} />
              </div>
            )}

            {/* Moon */}
            {ephemeris.moon_illumination != null && (
              <div className={`flex items-center gap-2 text-xs rounded-lg px-3 py-2 mb-3 ${
                ephemeris.moon_separation != null && ephemeris.moon_separation < 15
                  ? 'bg-amber-500/10 border border-amber-500/30 text-amber-300'
                  : 'bg-slate-900/40 text-slate-400'
              }`}>
                <Moon className="h-3.5 w-3.5 shrink-0" />
                <span>
                  {moonIcon(ephemeris.moon_illumination)}{' '}
                  Moon {(ephemeris.moon_illumination * 100).toFixed(0)}% illuminated
                  {ephemeris.moon_separation != null && (
                    <>, {ephemeris.moon_separation.toFixed(0)}° away</>
                  )}
                  {ephemeris.moon_separation != null && ephemeris.moon_separation < 15 && (
                    <span className="font-medium"> — interference likely</span>
                  )}
                </span>
              </div>
            )}
          </>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2 pt-1">
          {mountIds.length > 1 && (
            <select
              value={selectedMount}
              onChange={(e) => setSelectedMount(e.target.value)}
              className="text-xs px-2 py-1.5 rounded-lg bg-slate-700 border border-slate-600 text-slate-300 focus:outline-none"
            >
              {mountIds.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          )}

          <button
            onClick={() => onSetTarget(selectedMount)}
            disabled={!hasMounts}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Crosshair className="h-3.5 w-3.5" />
            Set Target
          </button>

          <button
            onClick={() => onSetAndSlew(selectedMount)}
            disabled={!hasMounts}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Navigation className="h-3.5 w-3.5" />
            Slew to Target
            <ChevronRight className="h-3 w-3 opacity-70" />
          </button>

          <button
            onClick={onAddToFavorites}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-amber-400 hover:text-amber-300 transition-colors"
          >
            <BookmarkPlus className="h-3.5 w-3.5" />
            Add to Favourites
          </button>
        </div>
      </div>
    </div>
  )
}
