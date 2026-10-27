import { useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import {
  BookOpen,
  Camera,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Compass,
  Crosshair,
  Globe,
  LoaderPinwheel,
  MapPin,
  Copy,
  Minus,
  Plus,
  Repeat,
  Telescope as TelescopeIcon,
  Trash2,
  Wind,
  XCircle,
  Zap,
  Lightbulb,
} from 'lucide-react'
import { api } from '@/api/client'
import type {
  ActivationResult,
  DeviceState,
  EquipmentItem,
  EquipmentItemType,
  Profile,
  ProfileNode,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StateBadge } from '@/components/ui/badge'
import { useStore } from '@/store'
import { useDeviceConfigs } from '@/hooks/useDeviceConfigs'
import { DeviceSourceTag } from '@/components/DeviceSourceTag'
import { itemDeviceStates } from '@/utils/inventory-match'
import { cloneTree, copyName, replaceItemAtPath } from '@/utils/profile-tree'
import { Page } from '@/components/Page'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Equipment tree helpers
// ---------------------------------------------------------------------------

const VALID_CHILD_TYPES: Record<string, Set<string>> = {
  site: new Set(['mount', 'gps']),
  mount: new Set(['ota']),
  ota: new Set(['camera', 'focuser', 'rotator', 'filter_wheel', 'flat_panel', 'ota']),
  focuser: new Set(['filter_wheel', 'camera']),
  filter_wheel: new Set(['camera']),
  rotator: new Set(['focuser', 'filter_wheel', 'camera']),
  camera: new Set(),
  flat_panel: new Set(),
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
  if (type === 'mount') return <Compass size={size} />
  if (type === 'ota') return <TelescopeIcon size={size} />
  if (type === 'camera') return <Camera size={size} />
  if (type === 'filter_wheel') return <LoaderPinwheel size={size} />
  if (type === 'focuser') return <Crosshair size={size} />
  if (type === 'rotator') return <CircleDot size={size} />
  if (type === 'flat_panel') return <Lightbulb size={size} />
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
  noneKey = 'picker.none',
}: {
  inventory: EquipmentItem[]
  allowedTypes: Set<string>
  usedItemIds: Set<string>
  onPick: (item: EquipmentItem) => void
  onClose: () => void
  noneKey?: string
}) {
  const { t } = useTranslation('profiles')
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
        <Trans t={t} i18nKey={noneKey} components={{ br: <br /> }} />
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
            <DeviceSourceTag item={item} />
            {alreadyUsed && (
              <span className="ml-auto pl-2 text-slate-600 text-[10px] whitespace-nowrap">{t('picker.used')}</span>
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
  deviceStates,
  onInsert,
  onReplace,
  onRemove,
}: {
  node: ProfileNode
  path: NodePath
  inventory: EquipmentItem[]
  roots: ProfileNode[]
  depth: number
  deviceStates?: Record<string, DeviceState>
  onInsert: (path: NodePath, item: EquipmentItem) => void
  onReplace: (path: NodePath, item: EquipmentItem) => void
  onRemove: (path: NodePath) => void
}) {
  const { t } = useTranslation('profiles')
  const [showPicker, setShowPicker] = useState(false)
  const [showSwapPicker, setShowSwapPicker] = useState(false)
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
          <span>{item ? itemLabel(item) : <span className="text-slate-600 italic">{t('tree.unknown', { id: node.item_id.slice(0, 8) })}</span>}</span>
          {node.role && (
            <span className="text-slate-600 text-[10px] ml-1">· {node.role}</span>
          )}
          {item && <DeviceSourceTag item={item} />}
          {deviceStates?.[node.item_id] && (
            <span className="ml-1"><StateBadge state={deviceStates[node.item_id]} /></span>
          )}
        </div>

        {/* Attach child button */}
        {validChildren.size > 0 && (
          <div className="relative">
            <button
              className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[10px] text-slate-500
                hover:text-slate-300 px-1.5 py-0.5 rounded border border-transparent hover:border-surface-border"
              onClick={() => setShowPicker((v) => !v)}
              title={t('tree.attach')}
            >
              <Plus size={10} /> {t('tree.child')}
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

        {/* Replace button: another item of the same kind, everything below it stays */}
        {item && (
          <div className="relative">
            <button
              className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-slate-300 p-0.5 rounded"
              onClick={() => setShowSwapPicker((v) => !v)}
              title={t('tree.replace')}
              aria-label={t('tree.replace')}
            >
              <Repeat size={11} />
            </button>
            {showSwapPicker && (
              <ItemPicker
                inventory={inventory.filter((i) => i.id === node.item_id || !used.has(i.id))}
                allowedTypes={new Set([itemType])}
                usedItemIds={new Set([node.item_id])}
                onPick={(other) => { if (other.id !== node.item_id) onReplace(path, other) }}
                onClose={() => setShowSwapPicker(false)}
              />
            )}
          </div>
        )}

        {/* Remove button */}
        <button
          className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-status-error p-0.5 rounded transition-colors"
          onClick={() => onRemove(path)}
          title={t('tree.remove')}
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
          deviceStates={deviceStates}
          onInsert={onInsert}
          onReplace={onReplace}
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
  deviceStates,
  onSave,
}: {
  profile: Profile
  inventory: EquipmentItem[]
  deviceStates?: Record<string, DeviceState>
  onSave: (roots: ProfileNode[]) => Promise<void>
}) {
  const { t } = useTranslation('profiles')
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

  const handleReplace = (path: NodePath, item: EquipmentItem) => {
    const updated = replaceItemAtPath(roots, path, item.id)
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
  // A tree starts at its observing site, and has only one.
  const rootTypes = new Set(['site'])

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-slate-500 label-caps font-medium">{t('tree.title')}</p>
        {saving && <span className="text-[10px] text-slate-600">{t('tree.saving')}</span>}
      </div>

      {roots.length === 0 && !showRootPicker && (
        <p className="text-xs text-slate-600 mb-2">{t('tree.empty')}</p>
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
            deviceStates={deviceStates}
            onInsert={handleInsert}
            onReplace={handleReplace}
            onRemove={handleRemove}
          />
        ))}
      </div>

      {roots.length === 0 && (
        <div className="relative mt-1">
          <button
            className="flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-400 transition-colors"
            onClick={() => setShowRootPicker((v) => !v)}
          >
            <Plus size={11} /> {t('tree.add')}
          </button>
          {showRootPicker && (
            <ItemPicker
              inventory={inventory}
              allowedTypes={rootTypes}
              usedItemIds={used}
              noneKey="picker.noSite"
              onPick={(item) => { handleAddRoot(item); setShowRootPicker(false) }}
              onClose={() => setShowRootPicker(false)}
            />
          )}
        </div>
      )}
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
// ProfileForm — create / edit
// ---------------------------------------------------------------------------

interface ProfileFormProps {
  initial?: Profile
  onSave: (p: Omit<Profile, 'id'> & { id?: string }) => Promise<void>
  onCancel: () => void
}

function ProfileForm({ initial, onSave, onCancel }: ProfileFormProps) {
  const { t } = useTranslation('profiles')
  const [name, setName] = useState(initial?.name ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    if (!name.trim()) { setError(t('form.nameRequired')); return }
    setSaving(true)
    setError(null)
    try {
      await onSave({
        id: initial?.id,
        name,
        roots: initial?.roots ?? [],
      })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <label className="text-xs text-slate-400">
          {t('form.name')} <span className="text-status-error">*</span>
        </label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('form.placeholder')}
          autoFocus
        />
        <p className="text-xs text-slate-600">
          {t('form.hint')}
        </p>
      </div>

      {error && (
        <p className="text-xs text-status-error bg-status-error/10 rounded px-3 py-2">{error}</p>
      )}

      <div className="flex gap-2">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? t('form.saving') : initial ? t('form.save') : t('form.create')}
        </Button>
        <Button variant="ghost" onClick={onCancel}>{t('form.cancel')}</Button>
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
  const { t } = useTranslation('profiles')
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
          {allOk ? t('activation.ok') : t('activation.errors')}
        </div>
        <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 text-xs">
          {t('activation.dismiss')}
        </button>
      </div>
      {result.connected.length > 0 && (
        <div className="text-xs text-slate-400">
          {t('activation.connected', { devices: result.connected.map((d) => `${d.device_id} (${d.role})`).join(', ') })}
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
  deviceStates,
  onActivate,
  onEdit,
  onDuplicate,
  onDelete,
  onTreeSave,
}: {
  profile: Profile
  isActive: boolean
  inventory: EquipmentItem[]
  deviceStates: Record<string, DeviceState>
  onActivate: () => void
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
  onTreeSave: (profileId: string, roots: ProfileNode[]) => Promise<void>
}) {
  const { t } = useTranslation('profiles')
  const [expanded, setExpanded] = useState(isActive)

  const treeCount = (nodes: ProfileNode[]): number =>
    nodes.reduce((n, node) => n + 1 + treeCount(node.children), 0)
  const itemCount = treeCount(profile.roots)
  const summaryParts = [
    itemCount > 0 ? t('card.items', { count: itemCount }) : t('card.emptyTree'),
  ]

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
                {t('card.active')}
              </span>
            )}
          </div>
          {summaryParts.length > 0 && (
            <p className="text-xs text-slate-500">{summaryParts.join(' · ')}</p>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onEdit}>
            {t('card.edit')}
          </Button>
          <Button
            size="sm" className="h-7 text-xs gap-1"
            variant={isActive ? 'ghost' : 'default'}
            onClick={onActivate}
          >
            <Zap size={11} />
            {isActive ? t('card.reload') : t('card.activate')}
          </Button>
          <Button
            size="icon" variant="ghost"
            className="h-7 w-7 text-slate-500 hover:text-slate-300"
            onClick={onDuplicate}
            title={t('card.duplicate')}
            aria-label={t('card.duplicate')}
          >
            <Copy size={13} />
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
        <div className="border-t border-surface-border px-4 py-3">
          <ProfileTreeEditor
            profile={profile}
            inventory={inventory}
            deviceStates={isActive ? deviceStates : undefined}
            onSave={(roots) => onTreeSave(profile.id, roots)}
          />
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
  const { t } = useTranslation('profiles')
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null)
  const [view, setView] = useState<View>('list')
  const [activationResult, setActivationResult] = useState<ActivationResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [inventory, setInventory] = useState<EquipmentItem[]>([])
  // What came up when the active profile was activated: only its tree shows device states.
  const connectedDevices = useStore((s) => s.connectedDevices)
  const deviceConfigs = useDeviceConfigs(connectedDevices)
  const deviceStates = itemDeviceStates(inventory, connectedDevices, deviceConfigs)

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

  const handleDuplicate = async (source: Profile) => {
    const name = copyName(source.name, profiles.map((p) => p.name),
      (n) => (n === 1 ? t('card.copySuffix') : t('card.copySuffixN', { n })))
    await api.profiles.create({ name, roots: cloneTree(source.roots) })
    reload()
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
      <Page width="medium">
        <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('newTitle')}</h1>
        <ProfileForm onSave={handleCreate} onCancel={() => setView('list')} />
      </Page>
    )
  }

  if (typeof view === 'object' && 'edit' in view) {
    return (
      <Page width="medium">
        <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('editTitle')}</h1>
        <ProfileForm initial={view.edit} onSave={handleUpdate} onCancel={() => setView('list')} />
      </Page>
    )
  }

  return (
    <Page width="medium">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">{t('title')}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {t('subtitle')}
          </p>
        </div>
        <Button onClick={() => setView('create')}>
          <Plus size={14} className="mr-2" /> {t('new')}
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
        <p className="text-sm text-slate-500">{t('loading')}</p>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <BookOpen size={32} className="text-slate-600" />
          <p className="text-sm text-slate-400">{t('empty.title')}</p>
          <p className="text-xs text-slate-600">
            {t('empty.hint')}
          </p>
          <Button className="mt-2" onClick={() => setView('create')}>
            <Plus size={14} className="mr-2" /> {t('empty.create')}
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
              deviceStates={deviceStates}
              onActivate={() => handleActivate(p.id)}
              onEdit={() => setView({ edit: p })}
              onDuplicate={() => handleDuplicate(p)}
              onDelete={() => handleDelete(p.id)}
              onTreeSave={handleTreeSave}
            />
          ))}
        </div>
      )}
    </Page>
  )
}
