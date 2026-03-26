import { useEffect, useState } from 'react'
import { BookOpen, CheckCircle, ChevronDown, ChevronRight, Plus, Trash2, XCircle, Zap } from 'lucide-react'
import { api } from '@/api/client'
import type {
  ActivationResult,
  DeviceRole,
  ObserverLocation,
  Profile,
  ProfileDevice,
  Telescope,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROLE_LABELS: Record<DeviceRole, string> = {
  camera: 'Camera',
  mount: 'Mount',
  focuser: 'Focuser',
}

const KIND_ADAPTER: Record<DeviceRole, string> = {
  camera: 'indi_camera',
  mount: 'indi_mount',
  focuser: 'indi_focuser',
}

function emptyLocation(): ObserverLocation {
  return { name: '', latitude: 0, longitude: 0, altitude: 0 }
}

function emptyTelescope(): Telescope {
  return { name: '', focal_length: 0, aperture: 0 }
}

// ---------------------------------------------------------------------------
// ProfileForm — create / edit
// ---------------------------------------------------------------------------

interface ProfileFormProps {
  initial?: Profile
  onSave: (p: Omit<Profile, 'id'> & { id?: string }) => Promise<void>
  onCancel: () => void
}

function ProfileForm({ initial, onSave, onCancel }: ProfileFormProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [location, setLocation] = useState<ObserverLocation | undefined>(
    initial?.location ?? undefined
  )
  const [telescope, setTelescope] = useState<Telescope | undefined>(
    initial?.telescope ?? undefined
  )
  const [devices, setDevices] = useState<ProfileDevice[]>(initial?.devices ?? [])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    if (!name.trim()) { setError('Name is required.'); return }
    setSaving(true)
    setError(null)
    try {
      await onSave({ id: initial?.id, name, location, telescope, devices })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const updateDevice = (idx: number, patch: Partial<ProfileDevice>) => {
    setDevices((ds) => ds.map((d, i) => (i === idx ? { ...d, ...patch } : d)))
  }

  const addDevice = (role: DeviceRole) => {
    setDevices((ds) => [
      ...ds,
      {
        role,
        config: {
          id: crypto.randomUUID(),
          kind: role,
          adapter_key: KIND_ADAPTER[role],
          params: { device_name: '', executable: '' },
          device_id: role,
        },
      },
    ])
  }

  const removeDevice = (idx: number) => setDevices((ds) => ds.filter((_, i) => i !== idx))

  return (
    <div className="flex flex-col gap-6">
      {/* Name */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">Profile name <span className="text-status-error">*</span></label>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Backyard rig" />
      </div>

      {/* Location */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Observer location</h3>
          {location ? (
            <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setLocation(undefined)}>
              Remove
            </button>
          ) : (
            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setLocation(emptyLocation())}>
              <Plus size={12} className="mr-1" /> Add
            </Button>
          )}
        </div>
        {location && (
          <div className="grid grid-cols-2 gap-3 bg-surface border border-surface-border rounded p-3">
            <div className="col-span-2 flex flex-col gap-1">
              <label className="text-xs text-slate-500">Location name (optional)</label>
              <Input
                value={location.name}
                onChange={(e) => setLocation({ ...location, name: e.target.value })}
                placeholder="e.g. Backyard"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Latitude (°)</label>
              <Input
                type="number" step="0.0001"
                value={location.latitude}
                onChange={(e) => setLocation({ ...location, latitude: parseFloat(e.target.value) || 0 })}
                placeholder="e.g. 48.8566"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Longitude (°)</label>
              <Input
                type="number" step="0.0001"
                value={location.longitude}
                onChange={(e) => setLocation({ ...location, longitude: parseFloat(e.target.value) || 0 })}
                placeholder="e.g. 2.3522"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Altitude (m)</label>
              <Input
                type="number"
                value={location.altitude}
                onChange={(e) => setLocation({ ...location, altitude: parseFloat(e.target.value) || 0 })}
                placeholder="e.g. 35"
              />
            </div>
          </div>
        )}
      </section>

      {/* Telescope */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Telescope</h3>
          {telescope ? (
            <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setTelescope(undefined)}>
              Remove
            </button>
          ) : (
            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setTelescope(emptyTelescope())}>
              <Plus size={12} className="mr-1" /> Add
            </Button>
          )}
        </div>
        {telescope && (
          <div className="grid grid-cols-2 gap-3 bg-surface border border-surface-border rounded p-3">
            <div className="col-span-2 flex flex-col gap-1">
              <label className="text-xs text-slate-500">Telescope name</label>
              <Input
                value={telescope.name}
                onChange={(e) => setTelescope({ ...telescope, name: e.target.value })}
                placeholder="e.g. Celestron EdgeHD 8"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Focal length (mm)</label>
              <Input
                type="number"
                value={telescope.focal_length}
                onChange={(e) => setTelescope({ ...telescope, focal_length: parseFloat(e.target.value) || 0 })}
                placeholder="e.g. 2032"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Aperture (mm)</label>
              <Input
                type="number"
                value={telescope.aperture}
                onChange={(e) => setTelescope({ ...telescope, aperture: parseFloat(e.target.value) || 0 })}
                placeholder="e.g. 203"
              />
            </div>
          </div>
        )}
      </section>

      {/* Devices */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Devices</h3>
          <div className="flex gap-1">
            {(['camera', 'mount', 'focuser'] as DeviceRole[]).map((role) => (
              <Button
                key={role}
                size="sm" variant="ghost"
                className="h-6 text-xs"
                onClick={() => addDevice(role)}
              >
                <Plus size={12} className="mr-1" /> {ROLE_LABELS[role]}
              </Button>
            ))}
          </div>
        </div>
        {devices.length === 0 ? (
          <p className="text-xs text-slate-600">No devices — add a camera, mount, or focuser above.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {devices.map((d, idx) => (
              <div
                key={idx}
                className="grid grid-cols-[auto_1fr_1fr_auto] gap-3 items-end bg-surface border border-surface-border rounded p-3"
              >
                <span className="text-xs font-medium text-slate-400 self-center mt-4">{ROLE_LABELS[d.role]}</span>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">Device ID</label>
                  <Input
                    value={d.config.device_id}
                    onChange={(e) =>
                      updateDevice(idx, { config: { ...d.config, device_id: e.target.value } })
                    }
                    placeholder={`e.g. main_${d.role}`}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">INDI device name</label>
                  <Input
                    value={(d.config.params?.device_name as string) ?? ''}
                    onChange={(e) =>
                      updateDevice(idx, {
                        config: { ...d.config, params: { ...d.config.params, device_name: e.target.value } },
                      })
                    }
                    placeholder="e.g. ZWO CCD ASI294MC Pro"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-slate-500">Driver executable</label>
                  <div className="flex gap-1 items-center">
                    <Input
                      value={(d.config.params?.executable as string) ?? ''}
                      onChange={(e) =>
                        updateDevice(idx, {
                          config: { ...d.config, params: { ...d.config.params, executable: e.target.value } },
                        })
                      }
                      placeholder="e.g. indi_asi_ccd"
                    />
                    <Button
                      size="icon" variant="ghost"
                      className="h-8 w-8 text-slate-500 hover:text-status-error"
                      onClick={() => removeDevice(idx)}
                    >
                      <Trash2 size={13} />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {error && <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>}

      <div className="flex gap-2">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Create profile'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Activation result toast
// ---------------------------------------------------------------------------

function ActivationBanner({ result, onDismiss }: { result: ActivationResult; onDismiss: () => void }) {
  const allOk = result.failed.length === 0
  return (
    <div className={`rounded border px-4 py-3 text-sm flex flex-col gap-2 ${allOk ? 'border-green-700 bg-green-900/20' : 'border-yellow-700 bg-yellow-900/20'}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-medium text-slate-200">
          {allOk ? <CheckCircle size={15} className="text-green-400" /> : <XCircle size={15} className="text-yellow-400" />}
          {allOk ? 'Profile activated' : 'Activated with errors'}
        </div>
        <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 text-xs">Dismiss</button>
      </div>
      {result.connected.length > 0 && (
        <div className="text-xs text-slate-400">
          Connected: {result.connected.map((d) => `${d.device_id} (${d.role})`).join(', ')}
        </div>
      )}
      {result.failed.map((d) => (
        <div key={d.device_id} className="text-xs text-yellow-400">
          {d.device_id} ({d.role}): {d.error}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Profile card
// ---------------------------------------------------------------------------

function ProfileCard({
  profile,
  isActive,
  onActivate,
  onEdit,
  onDelete,
}: {
  profile: Profile
  isActive: boolean
  onActivate: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={`rounded border ${isActive ? 'border-accent bg-accent/5' : 'border-surface-border bg-surface-raised'}`}>
      <div className="flex items-center gap-3 px-4 py-3">
        <button className="text-slate-500 hover:text-slate-300" onClick={() => setExpanded((x) => !x)}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-200">{profile.name}</span>
            {isActive && (
              <span className="text-xs font-medium text-accent border border-accent rounded px-1.5 py-0.5">
                active
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500">
            {[
              profile.telescope?.name,
              profile.location?.name || (profile.location ? `${profile.location.latitude.toFixed(2)}°, ${profile.location.longitude.toFixed(2)}°` : null),
              profile.devices.length > 0 ? `${profile.devices.length} device${profile.devices.length > 1 ? 's' : ''}` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onEdit}>
            Edit
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs gap-1"
            variant={isActive ? 'ghost' : 'default'}
            onClick={onActivate}
          >
            <Zap size={11} />
            {isActive ? 'Reload' : 'Activate'}
          </Button>
          <Button
            size="icon" variant="ghost"
            className="h-7 w-7 text-slate-500 hover:text-status-error"
            onClick={onDelete}
          >
            <Trash2 size={13} />
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-surface-border px-4 py-3 grid grid-cols-2 gap-4 text-xs">
          {profile.telescope && (
            <div>
              <p className="text-slate-500 uppercase tracking-wider mb-1">Telescope</p>
              <p className="text-slate-200">{profile.telescope.name}</p>
              <p className="text-slate-400">f={profile.telescope.focal_length} mm · ⌀{profile.telescope.aperture} mm</p>
            </div>
          )}
          {profile.location && (
            <div>
              <p className="text-slate-500 uppercase tracking-wider mb-1">Location</p>
              {profile.location.name && <p className="text-slate-200">{profile.location.name}</p>}
              <p className="text-slate-400">
                {profile.location.latitude.toFixed(4)}°, {profile.location.longitude.toFixed(4)}° · {profile.location.altitude} m
              </p>
            </div>
          )}
          {profile.devices.length > 0 && (
            <div className="col-span-2">
              <p className="text-slate-500 uppercase tracking-wider mb-1">Devices</p>
              <div className="flex flex-col gap-0.5">
                {profile.devices.map((d, i) => (
                  <span key={i} className="text-slate-300">
                    <span className="text-slate-500">{ROLE_LABELS[d.role]}: </span>
                    {d.config.device_id}
                    {d.config.params?.device_name ? ` (${d.config.params.device_name})` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type View = 'list' | 'create' | { edit: Profile }

export function Profiles() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null)
  const [view, setView] = useState<View>('list')
  const [activationResult, setActivationResult] = useState<ActivationResult | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = () => {
    Promise.all([api.profiles.list(), api.profiles.active()])
      .then(([ps, active]) => {
        setProfiles(ps)
        setActiveProfileId(active?.id ?? null)
        setLoading(false)
      })
      .catch(console.error)
  }

  useEffect(() => { reload() }, [])

  const handleCreate = async (data: Omit<Profile, 'id'> & { id?: string }) => {
    await api.profiles.create(data as Omit<Profile, 'id'>)
    reload()
    setView('list')
  }

  const handleUpdate = async (data: Omit<Profile, 'id'> & { id?: string }) => {
    await api.profiles.update(data as Profile)
    reload()
    setView('list')
  }

  const handleActivate = async (id: string) => {
    const result = await api.profiles.activate(id)
    setActiveProfileId(id)
    setActivationResult(result)
    reload()
  }

  const handleDelete = async (id: string) => {
    await api.profiles.delete(id)
    if (activeProfileId === id) setActiveProfileId(null)
    reload()
  }

  if (view === 'create') {
    return (
      <div className="p-6 max-w-2xl">
        <h1 className="text-lg font-semibold text-slate-100 mb-6">New profile</h1>
        <ProfileForm onSave={handleCreate} onCancel={() => setView('list')} />
      </div>
    )
  }

  if (typeof view === 'object' && 'edit' in view) {
    return (
      <div className="p-6 max-w-2xl">
        <h1 className="text-lg font-semibold text-slate-100 mb-6">Edit profile</h1>
        <ProfileForm initial={view.edit} onSave={handleUpdate} onCancel={() => setView('list')} />
      </div>
    )
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Profiles</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Save your equipment configuration — telescope, location, and devices — for quick re-use.
          </p>
        </div>
        <Button onClick={() => setView('create')}>
          <Plus size={14} className="mr-2" /> New profile
        </Button>
      </div>

      {activationResult && (
        <div className="mb-4">
          <ActivationBanner result={activationResult} onDismiss={() => setActivationResult(null)} />
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <BookOpen size={32} className="text-slate-600" />
          <p className="text-sm text-slate-400">No profiles yet.</p>
          <p className="text-xs text-slate-600">Create a profile to save your equipment setup.</p>
          <Button className="mt-2" onClick={() => setView('create')}>
            <Plus size={14} className="mr-2" /> Create first profile
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {profiles.map((p) => (
            <ProfileCard
              key={p.id}
              profile={p}
              isActive={p.id === activeProfileId}
              onActivate={() => handleActivate(p.id)}
              onEdit={() => setView({ edit: p })}
              onDelete={() => handleDelete(p.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
