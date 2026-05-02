import { useCallback, useEffect, useRef, useState } from 'react'
import { Star } from 'lucide-react'
import { useStore } from '@/store'
import type { EphemerisResult, FavoriteTarget, TargetSettings } from './api'
import { getEphemeris, getSettings, putSettings, setMountTarget, slewMount } from './api'
import { SearchBox, type ObjectMatch } from './SearchBox'
import { ObjectCard } from './ObjectCard'
import { FavoritesList } from './FavoritesList'

export function TargetPage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const mountIds = connectedDevices.filter((d) => d.kind === 'mount').map((d) => d.device_id)

  const [selected, setSelected] = useState<ObjectMatch | null>(null)
  const [ephemeris, setEphemeris] = useState<EphemerisResult | null>(null)
  const [ephLoading, setEphLoading] = useState(false)

  const [settings, setSettings] = useState<TargetSettings>({ favorites: [], min_altitude_deg: 30 })
  const [settingsLoaded, setSettingsLoaded] = useState(false)

  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function showToast(msg: string, ok = true) {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToast({ msg, ok })
    toastTimer.current = setTimeout(() => setToast(null), 3000)
  }

  // Load settings on mount
  useEffect(() => {
    getSettings().then((s) => { setSettings(s); setSettingsLoaded(true) }).catch(() => setSettingsLoaded(true))
  }, [])

  // Fetch ephemeris whenever selection changes
  useEffect(() => {
    if (!selected) { setEphemeris(null); return }
    setEphLoading(true)
    setEphemeris(null)
    getEphemeris(selected.ra, selected.dec)
      .then(setEphemeris)
      .catch(() => showToast('Ephemeris computation failed', false))
      .finally(() => setEphLoading(false))
  }, [selected])

  const handleSelect = useCallback((obj: ObjectMatch) => {
    setSelected(obj)
  }, [])

  async function handleSetTarget(mountId: string) {
    if (!selected) return
    try {
      await setMountTarget(mountId, selected.ra, selected.dec, selected.name)
      showToast(`Target set: ${selected.name}`)
    } catch (e) {
      showToast('Failed to set target', false)
    }
  }

  async function handleSetAndSlew(mountId: string) {
    if (!selected) return
    try {
      await setMountTarget(mountId, selected.ra, selected.dec, selected.name)
      await slewMount(mountId)
      showToast(`Slewing to ${selected.name}…`)
    } catch (e) {
      showToast('Slew failed', false)
    }
  }

  async function saveSettings(updated: TargetSettings) {
    setSettings(updated)
    try {
      await putSettings(updated)
    } catch {
      showToast('Failed to save settings', false)
    }
  }

  function handleAddToFavorites() {
    if (!selected) return
    // Don't add duplicates (same RA/Dec within 1 arcsec)
    const exists = settings.favorites.some(
      (f) => Math.abs(f.ra - selected.ra) < 0.0003 && Math.abs(f.dec - selected.dec) < 0.0003,
    )
    if (exists) {
      showToast('Already in favourites')
      return
    }
    const newFav: FavoriteTarget = {
      id: crypto.randomUUID(),
      name: selected.name,
      ra: selected.ra,
      dec: selected.dec,
      object_name: selected.name,
      object_type: selected.type,
      notes: '',
      added_at: new Date().toISOString(),
    }
    saveSettings({ ...settings, favorites: [...settings.favorites, newFav] })
    showToast(`${selected.name} added to favourites`)
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
        <h1 className="text-base font-semibold text-slate-300 mb-3">Target</h1>
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
              Favourites
              {settings.favorites.length > 0 && (
                <span className="ml-2 text-xs text-slate-600">({settings.favorites.length})</span>
              )}
            </h2>
          </div>
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
