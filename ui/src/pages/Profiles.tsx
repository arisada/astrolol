import { useEffect, useRef, useState } from 'react'
import {
  BookOpen,
  Camera,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Crosshair,
  Filter as FilterIcon,
  Focus,
  Globe,
  MapPin,
  Minus,
  Plus,
  Telescope as TelescopeIcon,
  Trash2,
  Wind,
  XCircle,
  Zap,
} from 'lucide-react'
import { api } from '@/api/client'
import type {
  ActivationResult,
  ConnectedDevice,
  DeviceRole,
  DriverEntry,
  EquipmentItem,
  EquipmentItemType,
  ObserverLocation,
  Profile,
  ProfileDevice,
  ProfileNode,
  Telescope,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { DmsInput } from '@/components/ui/dms-input'
import { Input } from '@/components/ui/input'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROLE_LABELS: Record<DeviceRole, string> = {
  camera: 'Camera',
  mount: 'Mount',
  focuser: 'Focuser',
  filter_wheel: 'Filter Wheel',
  rotator: 'Rotator',
  indi: 'INDI Device',
}

const KIND_ADAPTER: Record<DeviceRole, string> = {
  camera: 'indi_camera',
  mount: 'indi_mount',
  focuser: 'indi_focuser',
  filter_wheel: 'indi_filter_wheel',
  rotator: 'indi_rotator',
  indi: 'indi_raw',
}

function emptyLocation(): ObserverLocation {
  return { name: '', latitude: 0, longitude: 0, altitude: 0 }
}

function emptyTelescope(): Telescope {
  return { name: '', focal_length: 0, aperture: 0 }
}

/** Format a decimal coordinate as a compact DMS string for display. */
function fmtDms(decimal: number, mode: 'lat' | 'lon'): string {
  const neg = decimal < 0
  const abs = Math.abs(decimal)
  const deg = Math.floor(abs)
  const minFull = (abs - deg) * 60
  const min = Math.floor(minFull)
  const sec = Math.round((minFull - min) * 60)
  const dir = mode === 'lat' ? (neg ? 'S' : 'N') : (neg ? 'W' : 'E')
  return `${deg}°${String(min).padStart(2, '0')}'${String(sec).padStart(2, '0')}" ${dir}`
}

function fRatio(t: Telescope): string | null {
  if (t.aperture <= 0) return null
  return `f/${(t.focal_length / t.aperture).toFixed(1)}`
}

// ---------------------------------------------------------------------------
// Equipment tree helpers
// ---------------------------------------------------------------------------

const VALID_CHILD_TYPES: Record<string, Set<string>> = {
  site: new Set(['mount', 'gps']),
  mount: new Set(['ota']),
  ota: new Set(['camera', 'focuser', 'rotator', 'filter_wheel', 'ota']),
  focuser: new Set(['filter_wheel', 'camera']),
  filter_wheel: new Set(['camera']),
  rotator: new Set(['focuser', 'filter_wheel', 'camera']),
  camera: new Set(),
  gps: new Set(),
}

type NodePath = number[]

function removeAtPath(roots: ProfileNode[], path: NodePath): ProfileNode[] {
  if (path.length === 1) return roots.filter((_, i) => i !== path[0])
  return roots.map((node, i) =>
    i === path[0]
      ? { ...node, children: removeAtPath(node.children, path.slice(1)) }
      : node,
  )
}

/** Collect all item_ids currently in the tree to highlight already-used items. */
function usedIds(roots: ProfileNode[]): Set<string> {
  const ids = new Set<string>()
  function walk(nodes: ProfileNode[]) {
    for (const n of nodes) { ids.add(n.item_id); walk(n.children) }
  }
  walk(roots)
  return ids
}

function ItemTypeIcon({ type, size = 13 }: { type: EquipmentItemType; size?: number }) {
  if (type === 'site') return <MapPin size={size} />
  if (type === 'mount') return <TelescopeIcon size={size} />
  if (type === 'ota') return <Crosshair size={size} />
  if (type === 'camera') return <Camera size={size} />
  if (type === 'filter_wheel') return <FilterIcon size={size} />
  if (type === 'focuser') return <Focus size={size} />
  if (type === 'rotator') return <CircleDot size={size} />
  if (type === 'gps') return <Globe size={size} />
  return <Wind size={size} />
}

function itemLabel(item: EquipmentItem): string {
  if (item.type === 'ota') return `${item.name}  f/${(item.focal_length / item.aperture).toFixed(1)}`
  return item.name
}

// ---------------------------------------------------------------------------
// Item picker dropdown
// ---------------------------------------------------------------------------

function ItemPicker({
  inventory,
  allowedTypes,
  usedItemIds,
  onPick,
  onClose,
}: {
  inventory: EquipmentItem[]
  allowedTypes: Set<string>
  usedItemIds: Set<string>
  onPick: (item: EquipmentItem) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const candidates = inventory.filter((i) => allowedTypes.has(i.type))

  if (candidates.length === 0) {
    return (
      <div ref={ref} className="absolute z-20 mt-1 bg-surface border border-surface-border rounded shadow-lg p-3 text-xs text-slate-500 min-w-48">
        No matching items in inventory.<br />
        Add them in Equipment → Inventory first.
      </div>
    )
  }

  return (
    <div ref={ref} className="absolute z-20 mt-1 bg-surface border border-surface-border rounded shadow-lg min-w-52 max-h-64 overflow-y-auto">
      {candidates.map((item) => {
        const alreadyUsed = usedItemIds.has(item.id)
        return (
          <button
            key={item.id}
            className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-surface-raised transition-colors"
            onClick={() => { onPick(item); onClose() }}
          >
            <span className="text-slate-500 shrink-0">
              <ItemTypeIcon type={item.type as EquipmentItemType} />
            </span>
            <span className={alreadyUsed ? 'text-slate-500' : 'text-slate-200'}>
              {itemLabel(item)}
            </span>
            {alreadyUsed && (
              <span className="ml-auto text-slate-600 text-[10px]">already in tree</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// TreeNodeRow — recursive node renderer
// ---------------------------------------------------------------------------

function TreeNodeRow({
  node,
  path,
  inventory,
  roots,
  depth,
  onInsert,
  onRemove,
}: {
  node: ProfileNode
  path: NodePath
  inventory: EquipmentItem[]
  roots: ProfileNode[]
  depth: number
  onInsert: (path: NodePath, item: EquipmentItem) => void
  onRemove: (path: NodePath) => void
}) {
  const [showPicker, setShowPicker] = useState(false)
  const item = inventory.find((i) => i.id === node.item_id)
  const itemType = (item?.type ?? 'camera') as EquipmentItemType
  const validChildren = VALID_CHILD_TYPES[itemType] ?? new Set<string>()
  const used = usedIds(roots)

  return (
    <div>
      <div className="flex items-center gap-1 group py-0.5">
        {/* Indent guide */}
        {depth > 0 && (
          <div
            className="shrink-0 border-l border-b border-slate-700/50 rounded-bl"
            style={{ width: 12, height: 12, marginLeft: depth * 16 - 4, marginRight: 2, alignSelf: 'flex-start', marginTop: 8 }}
          />
        )}

        {/* Item chip */}
        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-surface border border-surface-border text-xs text-slate-300">
          <span className="text-slate-500"><ItemTypeIcon type={itemType} /></span>
          <span>{item ? itemLabel(item) : <span className="text-slate-600 italic">Unknown ({node.item_id.slice(0, 8)})</span>}</span>
          {node.role && (
            <span className="text-slate-600 text-[10px] ml-1">· {node.role}</span>
          )}
        </div>

        {/* Attach child button */}
        {validChildren.size > 0 && (
          <div className="relative">
            <button
              className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[10px] text-slate-500
                hover:text-slate-300 px-1.5 py-0.5 rounded border border-transparent hover:border-surface-border"
              onClick={() => setShowPicker((v) => !v)}
              title="Attach child item"
            >
              <Plus size={10} /> child
            </button>
            {showPicker && (
              <ItemPicker
                inventory={inventory}
                allowedTypes={validChildren}
                usedItemIds={used}
                onPick={(child) => onInsert(path, child)}
                onClose={() => setShowPicker(false)}
              />
            )}
          </div>
        )}

        {/* Remove button */}
        <button
          className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-status-error p-0.5 rounded transition-colors"
          onClick={() => onRemove(path)}
          title="Remove from tree"
        >
          <Minus size={11} />
        </button>
      </div>

      {/* Children */}
      {node.children.map((child, i) => (
        <TreeNodeRow
          key={`${child.item_id}-${i}`}
          node={child}
          path={[...path, i]}
          inventory={inventory}
          roots={roots}
          depth={depth + 1}
          onInsert={onInsert}
          onRemove={onRemove}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ProfileTreeEditor
// ---------------------------------------------------------------------------

function ProfileTreeEditor({
  profile,
  inventory,
  onSave,
}: {
  profile: Profile
  inventory: EquipmentItem[]
  onSave: (roots: ProfileNode[]) => Promise<void>
}) {
  const [roots, setRoots] = useState<ProfileNode[]>(profile.roots)
  const [showRootPicker, setShowRootPicker] = useState(false)
  const [saving, setSaving] = useState(false)

  // Keep local state in sync when profile changes from parent
  useEffect(() => { setRoots(profile.roots) }, [profile.roots])

  const save = async (newRoots: ProfileNode[]) => {
    setSaving(true)
    try { await onSave(newRoots) } finally { setSaving(false) }
  }

  const handleInsert = (parentPath: NodePath, item: EquipmentItem) => {
    const child: ProfileNode = { item_id: item.id, role: null, children: [] }
    // parentPath points to the parent node; append child to its children list
    const updated = roots.map((node, i) =>
      i === parentPath[0]
        ? appendChildAtPath(node, parentPath.slice(1), child)
        : node,
    )
    setRoots(updated)
    save(updated)
  }

  const handleRemove = (path: NodePath) => {
    const updated = removeAtPath(roots, path)
    setRoots(updated)
    save(updated)
  }

  const handleAddRoot = (item: EquipmentItem) => {
    const newNode: ProfileNode = { item_id: item.id, role: null, children: [] }
    const updated = [...roots, newNode]
    setRoots(updated)
    save(updated)
  }

  const used = usedIds(roots)
  const allTypes = new Set(['site', 'mount', 'ota', 'camera', 'filter_wheel', 'focuser', 'rotator', 'gps'])

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-slate-500 uppercase tracking-wider text-[10px] font-medium">Equipment tree</p>
        {saving && <span className="text-[10px] text-slate-600">Saving…</span>}
      </div>

      {roots.length === 0 && !showRootPicker && (
        <p className="text-xs text-slate-600 mb-2">No equipment tree configured.</p>
      )}

      <div className="flex flex-col">
        {roots.map((node, i) => (
          <TreeNodeRow
            key={`${node.item_id}-${i}`}
            node={node}
            path={[i]}
            inventory={inventory}
            roots={roots}
            depth={0}
            onInsert={handleInsert}
            onRemove={handleRemove}
          />
        ))}
      </div>

      <div className="relative mt-1">
        <button
          className="flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-400 transition-colors"
          onClick={() => setShowRootPicker((v) => !v)}
        >
          <Plus size={11} /> Add to tree
        </button>
        {showRootPicker && (
          <ItemPicker
            inventory={inventory}
            allowedTypes={allTypes}
            usedItemIds={used}
            onPick={(item) => { handleAddRoot(item); setShowRootPicker(false) }}
            onClose={() => setShowRootPicker(false)}
          />
        )}
      </div>
    </div>
  )
}

/** Recursively append a child at the correct nested path. */
function appendChildAtPath(node: ProfileNode, remainingPath: NodePath, child: ProfileNode): ProfileNode {
  if (remainingPath.length === 0) {
    return { ...node, children: [...node.children, child] }
  }
  return {
    ...node,
    children: node.children.map((c, i) =>
      i === remainingPath[0] ? appendChildAtPath(c, remainingPath.slice(1), child) : c,
    ),
  }
}

// ---------------------------------------------------------------------------
// DriverCombobox — searchable INDI driver picker
// ---------------------------------------------------------------------------

interface DriverComboboxProps {
  role: DeviceRole
  onSelect: (d: DriverEntry) => void
}

function DriverCombobox({ role, onSelect }: DriverComboboxProps) {
  const [query, setQuery] = useState('')
  const [drivers, setDrivers] = useState<DriverEntry[]>([])
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.indi.drivers(role).then(setDrivers).catch(() => {})
  }, [role])

  const filtered = query.trim()
    ? drivers.filter(
        (d) =>
          d.label.toLowerCase().includes(query.toLowerCase()) ||
          d.manufacturer.toLowerCase().includes(query.toLowerCase()),
      )
    : drivers

  return (
    <div ref={containerRef} className="relative">
      <Input
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        placeholder="Search driver catalog…"
      />
      {open && filtered.length > 0 && (
        <ul className="absolute z-20 w-full mt-0.5 max-h-48 overflow-auto bg-surface-raised border border-surface-border rounded shadow-lg">
          {filtered.slice(0, 40).map((d) => (
            <li key={`${d.executable}:${d.device_name}`}>
              <button
                type="button"
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-accent/10 flex items-baseline gap-2"
                onMouseDown={(e) => {
                  // prevent input blur before click fires
                  e.preventDefault()
                  onSelect(d)
                  setQuery(d.label)
                  setOpen(false)
                }}
              >
                <span className="text-slate-200">{d.label}</span>
                <span className="text-slate-500 text-[11px]">{d.manufacturer}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
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
    initial?.location ?? undefined,
  )
  const [telescope, setTelescope] = useState<Telescope | undefined>(
    initial?.telescope ?? undefined,
  )
  const [devices, setDevices] = useState<ProfileDevice[]>(initial?.devices ?? [])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState<ConnectedDevice[]>([])

  useEffect(() => {
    api.devices.connected().then(setConnected).catch(() => {})
  }, [])

  const handleSave = async () => {
    if (!name.trim()) { setError('Name is required.'); return }
    setSaving(true)
    setError(null)
    try {
      await onSave({ id: initial?.id, name, location, telescope, devices, roots: initial?.roots ?? [] })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const updateDevice = (idx: number, patch: Partial<ProfileDevice>) =>
    setDevices((ds) => ds.map((d, i) => (i === idx ? { ...d, ...patch } : d)))

  const addDevice = (role: DeviceRole) =>
    setDevices((ds) => [
      ...ds,
      {
        role,
        config: {
          device_id: role,
          kind: role,
          adapter_key: KIND_ADAPTER[role],
          params: { device_name: '', executable: '' },
        },
      },
    ])

  const removeDevice = (idx: number) => setDevices((ds) => ds.filter((_, i) => i !== idx))

  const importConnected = async (idx: number, c: ConnectedDevice) => {
    try {
      const cfg = await api.devices.getConfig(c.device_id)
      updateDevice(idx, { config: cfg })
    } catch {
      // Fallback if endpoint not available: fill what we know
      updateDevice(idx, {
        config: { ...devices[idx].config, device_id: c.device_id, adapter_key: c.adapter_key },
      })
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Name */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">
          Profile name <span className="text-status-error">*</span>
        </label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Backyard rig"
        />
      </div>

      {/* Location */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Observer location
          </h3>
          {location ? (
            <button
              className="text-xs text-slate-500 hover:text-slate-300"
              onClick={() => setLocation(undefined)}
            >
              Remove
            </button>
          ) : (
            <Button
              size="sm" variant="ghost" className="h-6 text-xs"
              onClick={() => setLocation(emptyLocation())}
            >
              <Plus size={12} className="mr-1" /> Add
            </Button>
          )}
        </div>
        {location && (
          <div className="flex flex-col gap-3 bg-surface border border-surface-border rounded p-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Location name (optional)</label>
              <Input
                value={location.name}
                onChange={(e) => setLocation({ ...location, name: e.target.value })}
                placeholder="e.g. Backyard"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Latitude</label>
              <DmsInput
                value={location.latitude}
                onChange={(v) => setLocation({ ...location, latitude: v })}
                mode="lat"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Longitude</label>
              <DmsInput
                value={location.longitude}
                onChange={(v) => setLocation({ ...location, longitude: v })}
                mode="lon"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Altitude (m)</label>
              <Input
                type="number"
                value={location.altitude}
                onChange={(e) =>
                  setLocation({ ...location, altitude: parseFloat(e.target.value) || 0 })
                }
                placeholder="e.g. 35"
                className="w-32"
              />
            </div>
          </div>
        )}
      </section>

      {/* Telescope */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Telescope
          </h3>
          {telescope ? (
            <button
              className="text-xs text-slate-500 hover:text-slate-300"
              onClick={() => setTelescope(undefined)}
            >
              Remove
            </button>
          ) : (
            <Button
              size="sm" variant="ghost" className="h-6 text-xs"
              onClick={() => setTelescope(emptyTelescope())}
            >
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
                onChange={(e) =>
                  setTelescope({ ...telescope, focal_length: parseFloat(e.target.value) || 0 })
                }
                placeholder="e.g. 2032"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-slate-500">Aperture (mm)</label>
              <Input
                type="number"
                value={telescope.aperture}
                onChange={(e) =>
                  setTelescope({ ...telescope, aperture: parseFloat(e.target.value) || 0 })
                }
                placeholder="e.g. 203"
              />
            </div>
            {telescope.aperture > 0 && (
              <p className="col-span-2 text-xs text-slate-500">
                f/{(telescope.focal_length / telescope.aperture).toFixed(1)}
              </p>
            )}
          </div>
        )}
      </section>

      {/* Devices */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">
            Devices
          </h3>
          <div className="flex gap-1">
            {(['camera', 'mount', 'focuser'] as DeviceRole[]).map((role) => (
              <Button
                key={role}
                size="sm" variant="ghost" className="h-6 text-xs"
                onClick={() => addDevice(role)}
              >
                <Plus size={12} className="mr-1" /> {ROLE_LABELS[role]}
              </Button>
            ))}
          </div>
        </div>

        {devices.length === 0 ? (
          <p className="text-xs text-slate-600">
            No devices — add a camera, mount, or focuser above.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {devices.map((d, idx) => {
              const matchingConnected = connected.filter((c) => c.kind === d.role)
              return (
                <div
                  key={idx}
                  className="flex flex-col gap-2 bg-surface border border-surface-border rounded p-3"
                >
                  {/* Role + driver picker + delete */}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-400 w-14 shrink-0">
                      {ROLE_LABELS[d.role]}
                    </span>
                    <div className="flex-1">
                      <DriverCombobox
                        role={d.role}
                        onSelect={(driver) =>
                          updateDevice(idx, {
                            config: {
                              ...d.config,
                              params: {
                                ...d.config.params,
                                device_name: driver.device_name,
                                executable: driver.executable,
                              },
                            },
                          })
                        }
                      />
                    </div>
                    <Button
                      size="icon" variant="ghost"
                      className="h-8 w-8 text-slate-500 hover:text-status-error shrink-0"
                      onClick={() => removeDevice(idx)}
                    >
                      <Trash2 size={13} />
                    </Button>
                  </div>

                  {/* Import from already-connected devices */}
                  {matchingConnected.length > 0 && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] text-slate-600">From connected:</span>
                      {matchingConnected.map((c) => (
                        <button
                          key={c.device_id}
                          type="button"
                          onClick={() => importConnected(idx, c)}
                          className="text-[11px] px-2 py-0.5 rounded border border-surface-border hover:border-accent text-slate-400 hover:text-slate-200 transition-colors"
                        >
                          {c.device_id}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Editable fields */}
                  <div className="grid grid-cols-3 gap-2">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-slate-500">Device ID</label>
                      <Input
                        value={d.config.device_id ?? ''}
                        onChange={(e) =>
                          updateDevice(idx, {
                            config: { ...d.config, device_id: e.target.value },
                          })
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
                            config: {
                              ...d.config,
                              params: { ...d.config.params, device_name: e.target.value },
                            },
                          })
                        }
                        placeholder="e.g. ZWO CCD ASI294MC Pro"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-slate-500">Driver executable</label>
                      <Input
                        value={(d.config.params?.executable as string) ?? ''}
                        onChange={(e) =>
                          updateDevice(idx, {
                            config: {
                              ...d.config,
                              params: { ...d.config.params, executable: e.target.value },
                            },
                          })
                        }
                        placeholder="e.g. indi_asi_ccd"
                      />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
      )}

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

function ActivationBanner({
  result,
  onDismiss,
}: {
  result: ActivationResult
  onDismiss: () => void
}) {
  const allOk = result.failed.length === 0
  return (
    <div
      className={`rounded border px-4 py-3 text-sm flex flex-col gap-2 ${
        allOk ? 'border-green-700 bg-green-900/20' : 'border-yellow-700 bg-yellow-900/20'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-medium text-slate-200">
          {allOk ? (
            <CheckCircle size={15} className="text-green-400" />
          ) : (
            <XCircle size={15} className="text-yellow-400" />
          )}
          {allOk ? 'Profile activated' : 'Activated with errors'}
        </div>
        <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 text-xs">
          Dismiss
        </button>
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
  inventory,
  onActivate,
  onEdit,
  onDelete,
  onTreeSave,
}: {
  profile: Profile
  isActive: boolean
  inventory: EquipmentItem[]
  onActivate: () => void
  onEdit: () => void
  onDelete: () => void
  onTreeSave: (profileId: string, roots: ProfileNode[]) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const ratio = profile.telescope ? fRatio(profile.telescope) : null

  const summaryParts = [
    profile.telescope?.name
      ? `${profile.telescope.name}${ratio ? ` (${ratio})` : ''}`
      : null,
    profile.location?.name ||
      (profile.location
        ? `${fmtDms(profile.location.latitude, 'lat')}, ${fmtDms(profile.location.longitude, 'lon')}`
        : null),
    profile.devices.length > 0
      ? `${profile.devices.length} device${profile.devices.length > 1 ? 's' : ''}`
      : null,
  ].filter(Boolean)

  return (
    <div
      className={`rounded border ${
        isActive ? 'border-accent bg-accent/5' : 'border-surface-border bg-surface-raised'
      }`}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          className="text-slate-500 hover:text-slate-300"
          onClick={() => setExpanded((x) => !x)}
        >
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
          {summaryParts.length > 0 && (
            <p className="text-xs text-slate-500">{summaryParts.join(' · ')}</p>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onEdit}>
            Edit
          </Button>
          <Button
            size="sm" className="h-7 text-xs gap-1"
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
              <p className="text-slate-400">
                {profile.telescope.focal_length} mm · ⌀{profile.telescope.aperture} mm
                {ratio && <> · {ratio}</>}
              </p>
            </div>
          )}
          {profile.location && (
            <div>
              <p className="text-slate-500 uppercase tracking-wider mb-1">Location</p>
              {profile.location.name && (
                <p className="text-slate-200">{profile.location.name}</p>
              )}
              <p className="text-slate-400">
                {fmtDms(profile.location.latitude, 'lat')}
                {', '}
                {fmtDms(profile.location.longitude, 'lon')}
                {' · '}
                {profile.location.altitude} m
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
                    {d.config.params?.device_name
                      ? ` (${d.config.params.device_name})`
                      : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
          {/* Equipment tree */}
          <div className="col-span-2 border-t border-surface-border pt-3">
            <ProfileTreeEditor
              profile={profile}
              inventory={inventory}
              onSave={(roots) => onTreeSave(profile.id, roots)}
            />
          </div>
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
  const [inventory, setInventory] = useState<EquipmentItem[]>([])

  const reload = () => {
    Promise.all([api.profiles.list(), api.profiles.active(), api.inventory.list()])
      .then(([ps, active, inv]) => {
        setProfiles(ps)
        setActiveProfileId(active?.id ?? null)
        setInventory(inv)
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

  const handleTreeSave = async (profileId: string, roots: ProfileNode[]) => {
    const profile = profiles.find((p) => p.id === profileId)
    if (!profile) return
    const updated = { ...profile, roots }
    await api.profiles.update(updated)
    setProfiles((ps) => ps.map((p) => (p.id === profileId ? updated : p)))
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
            Save your equipment configuration — telescope, location, and devices — for quick
            re-use.
          </p>
        </div>
        <Button onClick={() => setView('create')}>
          <Plus size={14} className="mr-2" /> New profile
        </Button>
      </div>

      {activationResult && (
        <div className="mb-4">
          <ActivationBanner
            result={activationResult}
            onDismiss={() => setActivationResult(null)}
          />
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <BookOpen size={32} className="text-slate-600" />
          <p className="text-sm text-slate-400">No profiles yet.</p>
          <p className="text-xs text-slate-600">
            Create a profile to save your equipment setup.
          </p>
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
              inventory={inventory}
              onActivate={() => handleActivate(p.id)}
              onEdit={() => setView({ edit: p })}
              onDelete={() => handleDelete(p.id)}
              onTreeSave={handleTreeSave}
            />
          ))}
        </div>
      )}
    </div>
  )
}
