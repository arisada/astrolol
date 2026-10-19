// "Tonight" tab: well-known objects of one kind that get high enough during the dark hours,
// highest first, with the ones too close to the Moon at the bottom.

import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Moon, RefreshCw } from 'lucide-react'
import { getTonight, type TonightItem, type TonightResult } from './api'
import { typeKey } from './FavoritesList'
import { describeNames } from './names'
import type { ObjectMatch } from './SearchBox'
import { firstNearMoon, fmtMag, fmtSize, timing } from './tonight'
import { TONIGHT_KINDS, tonightTypes, type TonightKind } from './typeFilter'
import { useLocalStorage } from '@/hooks/useLocalStorage'

interface Props {
  onSelect: (obj: ObjectMatch) => void
}

export function TonightList({ onSelect }: Props) {
  const { t, i18n } = useTranslation('target')
  const [stored, setKind] = useLocalStorage<string>('astrolol.target.tonight', 'galaxy')
  const kind: TonightKind = (TONIGHT_KINDS as readonly string[]).includes(stored) ? (stored as TonightKind) : 'galaxy'
  const [result, setResult] = useState<TonightResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getTonight(tonightTypes(kind))
      .then((r) => { if (!cancelled) setResult(r) })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [kind])
  useEffect(() => load(), [load])

  const time = (iso: string) =>
    new Date(iso).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit', hour12: false })
  const items = result?.items ?? []
  const moonStart = firstNearMoon(items)

  function pick(item: TonightItem) {
    onSelect({
      name: item.name, aliases: item.aliases, ra: item.ra, dec: item.dec, type: item.type, source: item.source,
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label={t('tonight.kind')}>
        {TONIGHT_KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            onClick={() => setKind(k)}
            className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
              kind === k
                ? 'border-indigo-500 bg-indigo-500/20 text-indigo-200'
                : 'border-slate-700 text-slate-400 hover:bg-slate-800'
            }`}
          >
            {t(`tonight.kinds.${k}`)}
          </button>
        ))}
        <button
          type="button"
          onClick={load}
          title={t('tonight.refresh')}
          aria-label={t('tonight.refresh')}
          className="ml-auto rounded p-1.5 text-slate-500 hover:text-slate-300"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {result && !result.observer_location_missing && !result.no_darkness && result.window_start && result.window_end && (
        <p className="text-xs text-slate-500">
          {t('tonight.window', {
            from: time(result.window_start), to: time(result.window_end), alt: result.min_altitude_deg,
          })}
        </p>
      )}
      {error && <p className="text-xs text-status-error">{error}</p>}
      {result?.observer_location_missing && <p className="text-sm text-slate-500">{t('tonight.noLocation')}</p>}
      {result?.no_darkness && <p className="text-sm text-slate-500">{t('tonight.noDarkness')}</p>}
      {result && !result.observer_location_missing && !result.no_darkness && items.length === 0 && (
        <p className="text-sm text-slate-500">{t('tonight.empty', { alt: result.min_altitude_deg })}</p>
      )}
      {!result && loading && <p className="text-sm text-slate-500">{t('tonight.loading')}</p>}

      <ul className="space-y-1">
        {items.map((item, i) => {
          const names = describeNames(item.name, item.aliases)
          const when = timing(item)
          const details = [
            t(`types.${typeKey(item.type)}`, { defaultValue: item.type }),
            fmtMag(item.mag) && t('tonight.mag', { mag: fmtMag(item.mag) }),
            fmtSize(item.size_arcmin),
          ].filter(Boolean).join(' · ')
          return (
            <li key={`${item.name}-${i}`}>
              {i === moonStart && (
                <p className="flex items-center gap-1.5 px-3 pb-1 pt-3 text-xs text-slate-500">
                  <Moon className="h-3.5 w-3.5" />{t('tonight.nearMoonHeading')}
                </p>
              )}
              <button
                type="button"
                onClick={() => pick(item)}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-slate-700/50"
              >
                <span className="w-12 shrink-0 text-right font-mono text-sm text-slate-200">
                  {when.state === 'up' ? `${Math.round(item.alt_now)}°` : '—'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-2">
                    <span className="truncate text-sm font-medium text-slate-200">{names.title}</span>
                    {names.others.length > 0 && (
                      <span className="truncate text-xs text-slate-500">{names.others.slice(0, 2).join(' · ')}</span>
                    )}
                  </span>
                  <span className="block truncate text-[11px] text-slate-500">{details}</span>
                </span>
                <span className="shrink-0 text-right text-[11px] leading-snug text-slate-400">
                  <span className="block">
                    {when.rises
                      ? t('tonight.rises', { time: time(when.rises), alt: result?.min_altitude_deg })
                      : t('tonight.peak', { time: time(item.peak_time), alt: Math.round(item.peak_alt) })}
                  </span>
                  {when.sets && <span className="block">{t('tonight.sets', { time: time(when.sets) })}</span>}
                  {item.near_moon && item.moon_separation !== null && (
                    <span className="block">{t('tonight.moonSeparation', { deg: Math.round(item.moon_separation) })}</span>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
