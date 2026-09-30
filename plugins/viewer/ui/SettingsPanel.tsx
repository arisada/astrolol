import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import * as api from './api'

function formatBytes(n: number): string {
  const gb = n / 1024 / 1024 / 1024
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${(n / 1024 / 1024).toFixed(0)} MB`
}

export function SettingsPanel({ onLibraryChanged }: { onLibraryChanged: () => void }) {
  const [libraryDir, setLibraryDir] = useState('')
  const [status, setStatus] = useState<api.LibraryStatus | null>(null)
  const [rejected, setRejected] = useState<api.RejectedItem[]>([])
  const [showRejected, setShowRejected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshStatus = () => {
    api.getStatus().then(setStatus).catch(() => {})
  }

  useEffect(() => {
    api.getSettings().then((s) => setLibraryDir(s.library_dir)).catch(() => {})
    refreshStatus()
  }, [])

  useEffect(() => {
    if (!status?.rescanning) return
    const id = setInterval(refreshStatus, 1000)
    return () => clearInterval(id)
  }, [status?.rescanning])

  const saveLibraryDir = async () => {
    setError(null)
    try {
      await api.putSettings({ library_dir: libraryDir })
      refreshStatus()
      onLibraryChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const rescan = async () => {
    setError(null)
    try {
      await api.startRescan()
      refreshStatus()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const cancel = async () => {
    try {
      await api.cancelRescan()
      refreshStatus()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const loadRejected = () => {
    setShowRejected((v) => !v)
    if (!showRejected) api.listRejected().then(setRejected).catch(() => {})
  }

  const unreject = async (item: api.RejectedItem) => {
    try {
      await api.unrejectImage(item.relative_path)
      setRejected((prev) => prev.filter((r) => r.relative_path !== item.relative_path))
      onLibraryChanged()
      refreshStatus()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const emptyRejected = async () => {
    if (!window.confirm(`Permanently delete ${status?.rejected_count ?? 0} rejected file(s)? This cannot be undone.`)) return
    try {
      await api.emptyRejected()
      setRejected([])
      refreshStatus()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="flex flex-col gap-2 p-3 text-xs">
      {error && <p className="text-status-error">{error}</p>}

      <div className="flex flex-col gap-1">
        <span className="text-slate-400">Library directory</span>
        <div className="flex gap-1">
          <Input value={libraryDir} onChange={(e) => setLibraryDir(e.target.value)} className="text-xs" />
          <Button size="sm" onClick={saveLibraryDir}>Save</Button>
        </div>
        <span className="text-slate-500">Changing this re-scans and drops anything outside the new path from the index.</span>
      </div>

      <div className="flex gap-2">
        {status?.rescanning ? (
          <Button size="sm" variant="danger" onClick={cancel} className="flex-1">Cancel rescan</Button>
        ) : (
          <Button size="sm" onClick={rescan} className="flex-1">Rescan library</Button>
        )}
      </div>

      {status && (
        <div className="grid grid-cols-2 gap-y-0.5 border-t border-surface-border pt-2 text-slate-400">
          <span>Indexed frames</span><span className="text-slate-200">{status.image_count}</span>
          <span>Disk free</span><span className="text-slate-200">{formatBytes(status.free_bytes)} / {formatBytes(status.total_bytes)}</span>
        </div>
      )}

      <div className="border-t border-surface-border pt-2">
        <button onClick={loadRejected} className="flex items-center justify-between w-full text-slate-400 hover:text-slate-300">
          <span>Rejected ({status?.rejected_count ?? 0} · {formatBytes(status?.rejected_bytes ?? 0)})</span>
        </button>
        {showRejected && (
          <div className="flex flex-col gap-1 mt-2">
            {rejected.length === 0 && <span className="text-slate-500">Nothing rejected.</span>}
            {rejected.map((r) => (
              <div key={r.relative_path} className="flex items-center justify-between gap-2">
                <span className="truncate text-slate-300">{r.relative_path}</span>
                <button onClick={() => unreject(r)} className="text-slate-500 hover:text-accent shrink-0">Restore</button>
              </div>
            ))}
            {rejected.length > 0 && (
              <Button size="sm" variant="danger" onClick={emptyRejected} className="mt-1">
                <Trash2 size={12} className="mr-1" /> Empty rejected (permanent)
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
