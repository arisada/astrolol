// Visibility of the mount's current target tonight, for the dock.
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { AltitudeChart } from './AltitudeChart'
import { getEphemeris, getSettings, type EphemerisResult } from './api'

interface TargetState { name: string | null; ra: number; dec: number }

const fmtTime = (iso: string | null, lng: string) =>
  iso ? new Date(iso).toLocaleTimeString(lng, { hour: '2-digit', minute: '2-digit', hour12: false }) : '—'

export function TargetVisibilityWidget() {
  const { t, i18n } = useTranslation('target')
  const live = useStore((s) => s.pluginStates['target'] as TargetState | null | undefined)
  const mountId = useStore((s) => s.connectedDevices.find((d) => d.kind === 'mount')?.device_id)
  // The event only arrives when a target is set: after a reload, ask the mount.
  const [seeded, setSeeded] = useState<TargetState | null>(null)
  useEffect(() => {
    if (live || !mountId) return
    api.mount.getTarget(mountId).then((m) => setSeeded({ name: m.name, ra: m.ra, dec: m.dec })).catch(() => {})
  }, [live, mountId])
  const target = live ?? seeded

  const [minAlt, setMinAlt] = useState(0)
  useEffect(() => { getSettings().then((s) => setMinAlt(s.min_altitude_deg)).catch(() => {}) }, [])

  const [eph, setEph] = useState<EphemerisResult | null>(null)
  useEffect(() => {
    if (!target) { setEph(null); return }
    let alive = true
    getEphemeris(target.ra, target.dec).then((e) => { if (alive) setEph(e) }).catch(() => {})
    return () => { alive = false }
  }, [target?.ra, target?.dec])  // eslint-disable-line react-hooks/exhaustive-deps

  if (!target) return <p className="text-xs text-slate-500">{t('widget.none')}</p>
  const lng = i18n.language
  return (
    <div className="flex flex-col gap-2">
      <p className="truncate text-sm text-slate-200">{target.name ?? `${(target.ra / 15).toFixed(2)}h ${target.dec.toFixed(1)}°`}</p>
      {!eph && <p className="text-xs text-slate-500">{t('card.computing')}</p>}
      {eph?.observer_location_missing && <p className="text-xs text-amber-400">{t('card.noLocation')}</p>}
      {eph && !eph.observer_location_missing && (
        <>
          <p className="text-xs text-slate-300">
            {eph.circumpolar ? t('card.circumpolar')
              : eph.never_rises ? t('card.neverRises')
              : eph.not_observable_at_night ? t('card.notVisible', { alt: minAlt })
              : eph.imaging_window_start
                ? `${fmtTime(eph.imaging_window_start, lng)} → ${fmtTime(eph.imaging_window_end, lng)}${eph.peak_alt != null ? ` · ${t('widget.peak', { alt: eph.peak_alt.toFixed(0) })}` : ''}`
                : ''}
          </p>
          {eph.altitude_curve.length > 0 && <AltitudeChart ephemeris={eph} minAlt={minAlt} />}
        </>
      )}
    </div>
  )
}
