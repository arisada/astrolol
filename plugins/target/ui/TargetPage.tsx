import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MapPin, Star } from 'lucide-react'
import { useStore } from '@/store'
import type { EphemerisResult, FavoriteTarget, TargetSettings } from './api'
import { getEphemeris, getSettings, putSettings, setMountTarget, slewMount } from './api'
import { SearchBox, type ObjectMatch } from './SearchBox'
import { ObjectCard } from './ObjectCard'
import { FavoritesList } from './FavoritesList'

// crypto.randomUUID() only exists in secure contexts (HTTPS or localhost) — it's
// undefined when astrolol is reached over plain HTTP by hostname/IP (e.g.
// http://astrolol.lan:8000 via mDNS), which throws here and silently aborts
// before the favourite is ever saved. crypto.getRandomValues() has no such
// restriction, so build a UUID v4 from it when randomUUID isn't available.
function makeFavoriteId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function TargetPage() {
  const { t } = useTranslation('target')
  const connectedDevices = useStore((s) => s.connectedDevices)
  const mountIds = connectedDevices.filter((d) => d.kind === 'mount').map((d) => d.device_id)
  const mountStatuses = useStore((s) => s.mountStatuses)

  // First connected mount that has a known position
  const activeMountEntry = mountIds
    .map((id) => ({ id, status: mountStatuses[id] }))
    .find((e) => e.status?.ra != null && e.status?.dec != null)

  const [selected, setSelected] = useState<ObjectMatch | null>(null)
  const [obsDate, setObsDate] = useState<string | null>(null)
  const [ephemeris, setEphemeris] = useState<EphemerisResult | null>(null)
  const [ephLoading, setEphLoading] = useState(false)

  const [settings, setSettings] = useState<TargetSettings>({ favorites: [], min_altitude_deg: 30 })
  const [settingsLoaded, setSettingsLoaded] = useState(false)

  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [showMountSave, setShowMountSave] = useState(false)
  const [mountSaveName, setMountSaveName] = useState('')
  const mountSaveInputRef = useRef<HTMLInputElement>(null)

  function showToast(msg: string, ok = true) {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ msg, ok })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  // Load settings on mount
  useEffect(() => {
    getSettings().then((s) => { setSettings(s); setSettingsLoaded(true) }).catch(() => setSettingsLoaded(true))
  }, [])

  // Fetch ephemeris whenever selection or observation date changes
  useEffect(() => {
    if (!selected) { setEphemeris(null); return }
    let cancelled = false
    setEphLoading(true)
    setEphemeris(null)
    getEphemeris(selected.ra, selected.dec, obsDate ?? undefined)
      .then((data) => { if (!cancelled) setEphemeris(data) })
      .catch(() => { if (!cancelled) showToast(t('toast.ephemerisFailed'), false) })
      .finally(() => { if (!cancelled) setEphLoading(false) })
    return () => { cancelled = true }
  }, [selected, obsDate])

  const handleSelect = useCallback((obj: ObjectMatch) => {
    setSelected(obj)
    setObsDate(null)  // reset to auto-select when switching targets
  }, [])

  async function handleSetTarget(mountId: string) {
    if (!selected) return
    try {
      await setMountTarget(mountId, selected.ra, selected.dec, selected.name)
      showToast(t('toast.targetSet', { name: selected.name }))
    } catch (e) {
      showToast(t('toast.setFailed'), false)
    }
  }

  async function handleSetAndSlew(mountId: string) {
    if (!selected) return
    try {
      await setMountTarget(mountId, selected.ra, selected.dec, selected.name)
      await slewMount(mountId)
      showToast(t('toast.slewing', { name: selected.name }))
    } catch (e) {
      showToast(t('toast.slewFailed'), false)
    }
  }

  async function saveSettings(updated: TargetSettings) {
    setSettings(updated)
    try {
      await putSettings(updated)
    } catch {
      showToast(t('toast.settingsFailed'), false)
    }
  }

  function handleAddToFavorites() {
    if (!selected) return
    // Don't add duplicates (same RA/Dec within 1 arcsec)
    const exists = settings.favorites.some(
      (f) => Math.abs(f.ra - selected.ra) < 0.0003 && Math.abs(f.dec - selected.dec) < 0.0003,
    )
    if (exists) {
      showToast(t('toast.already'))
      return
    }
    const newFav: FavoriteTarget = {
      id: makeFavoriteId(),
      name: selected.name,
      ra: selected.ra,
      dec: selected.dec,
      object_name: selected.name,
      object_type: selected.type,
      notes: '',
      added_at: new Date().toISOString(),
    }
    saveSettings({ ...settings, favorites: [...settings.favorites, newFav] })
    showToast(t('toast.added', { name: selected.name }))
  }

  function openMountSaveForm() {
    if (!activeMountEntry) return
    const { ra, dec } = activeMountEntry.status
    const raDeg = (ra! * 15).toFixed(2)
    const decStr = dec! >= 0 ? `+${dec!.toFixed(2)}` : dec!.toFixed(2)
    setMountSaveName(`${raDeg}° ${decStr}°`)
    setShowMountSave(true)
    setTimeout(() => mountSaveInputRef.current?.focus(), 50)
  }

  function handleSaveMountPosition() {
    if (!activeMountEntry || !mountSaveName.trim()) return
    const { ra, dec } = activeMountEntry.status
    const raDeg = ra! * 15  // decimal hours → ICRS degrees
    const exists = settings.favorites.some(
      (f) => Math.abs(f.ra - raDeg) < 0.0003 && Math.abs(f.dec - dec!) < 0.0003,
    )
    if (exists) {
      showToast(t('toast.already'))
      setShowMountSave(false)
      return
    }
    const newFav: FavoriteTarget = {
      id: makeFavoriteId(),
      name: mountSaveName.trim(),
      ra: raDeg,
      dec: dec!,
      object_name: '',
      object_type: 'Mount Position',
      notes: '',
      added_at: new Date().toISOString(),
    }
    saveSettings({ ...settings, favorites: [...settings.favorites, newFav] })
    showToast(t('toast.saved', { name: mountSaveName.trim() }))
    setShowMountSave(false)
    setMountSaveName('')
  }

  function handleDeleteFavorite(id: string) {
    saveSettings({ ...settings, favorites: settings.favorites.filter((f) => f.id !== id) })
  }

  function handleRecallFavorite(fav: FavoriteTarget) {
    const obj: ObjectMatch = {
      name: fav.name,
      aliases: [fav.name],
      ra: fav.ra,
      dec: fav.dec,
      type: fav.object_type,
      source: 'favorites',
    }
    setSelected(obj)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="relative flex flex-col gap-5 p-5 max-w-2xl mx-auto">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium transition-all ${
          toast.ok
            ? 'bg-emerald-800/90 text-emerald-200 border border-emerald-700/50'
            : 'bg-red-900/90 text-red-200 border border-red-700/50'
        }`}>
          {toast.msg}
        </div>
      )}

      {/* Search */}
      <section>
        <h1 className="text-base font-semibold text-slate-300 mb-3">{t('title')}</h1>
        <SearchBox onSelect={handleSelect} />
      </section>

      {/* Object detail */}
      {selected && (
        <ObjectCard
          object={selected}
          ephemeris={ephemeris}
          loading={ephLoading}
          mountIds={mountIds}
          minAlt={settings.min_altitude_deg}
          obsDate={obsDate}
          onObsDateChange={setObsDate}
          onSetTarget={handleSetTarget}
          onSetAndSlew={handleSetAndSlew}
          onAddToFavorites={handleAddToFavorites}
        />
      )}

      {/* Favourites */}
      {settingsLoaded && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Star className="h-4 w-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-slate-400">
              {t('favorites.title')}
              {settings.favorites.length > 0 && (
                <span className="ml-2 text-xs text-slate-600">({settings.favorites.length})</span>
              )}
            </h2>
            {activeMountEntry && !showMountSave && (
              <button
                onClick={openMountSaveForm}
                className="ml-auto flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-400 transition-colors"
                title={t('favorites.saveMountTitle')}
              >
                <MapPin className="h-3.5 w-3.5" />
                {t('favorites.saveMount')}
              </button>
            )}
          </div>

          {showMountSave && (
            <div className="mb-3 flex items-center gap-2">
              <input
                ref={mountSaveInputRef}
                type="text"
                value={mountSaveName}
                onChange={(e) => setMountSaveName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveMountPosition()
                  if (e.key === 'Escape') setShowMountSave(false)
                }}
                placeholder={t('favorites.namePlaceholder')}
                className="flex-1 text-sm bg-slate-800 border border-slate-600 rounded px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <button
                onClick={handleSaveMountPosition}
                disabled={!mountSaveName.trim()}
                className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white transition-colors"
              >
                {t('favorites.save')}
              </button>
              <button
                onClick={() => setShowMountSave(false)}
                className="text-xs px-2 py-1.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
              >
                {t('favorites.cancel')}
              </button>
            </div>
          )}

          <FavoritesList
            favorites={settings.favorites}
            onRecall={handleRecallFavorite}
            onDelete={handleDeleteFavorite}
          />
        </section>
      )}
    </div>
  )
}
