import { useCallback, useEffect, useRef, useState } from 'react'
import { MapPin, Star } from 'lucide-react'
import { useStore } from '@/store'
import type { EphemerisResult, FavoriteTarget, TargetSettings } from './api'
import { getEphemeris, getSettings, putSettings, setMountTarget, slewMount } from './api'
import { SearchBox, type ObjectMatch } from './SearchBox'
import { ObjectCard } from './ObjectCard'
import { FavoritesList } from './FavoritesList'

export function TargetPage() {
  const connectedDevices = useStore((s) => s.connectedDevices)
  const mountIds = connectedDevices.filter((d) => d.kind === 'mount').map((d) => d.device_id)
  const mountStatuses = useStore((s) => s.mountStatuses)

  // First connected mount that has a known position
  const activeMountEntry = mountIds
    .map((id) => ({ id, status: mountStatuses[id] }))
    .find((e) => e.status?.ra != null && e.status?.dec != null)

  const [selected, setSelected] = useState<ObjectMatch | null>(null)
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
      showToast('Already in favourites')
      setShowMountSave(false)
      return
    }
    const newFav: FavoriteTarget = {
      id: crypto.randomUUID(),
      name: mountSaveName.trim(),
      ra: raDeg,
      dec: dec!,
      object_name: '',
      object_type: 'Mount Position',
      notes: '',
      added_at: new Date().toISOString(),
    }
    saveSettings({ ...settings, favorites: [...settings.favorites, newFav] })
    showToast(`"${mountSaveName.trim()}" saved to favourites`)
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
            {activeMountEntry && !showMountSave && (
              <button
                onClick={openMountSaveForm}
                className="ml-auto flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-400 transition-colors"
                title="Save current mount position as a favourite"
              >
                <MapPin className="h-3.5 w-3.5" />
                Save mount position
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
                placeholder="Name this position…"
                className="flex-1 text-sm bg-slate-800 border border-slate-600 rounded px-2.5 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <button
                onClick={handleSaveMountPosition}
                disabled={!mountSaveName.trim()}
                className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white transition-colors"
              >
                Save
              </button>
              <button
                onClick={() => setShowMountSave(false)}
                className="text-xs px-2 py-1.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
              >
                Cancel
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
