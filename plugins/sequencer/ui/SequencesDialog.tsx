// Named sequences: save the queue as a reusable plan, load one back, and move plans in and
// out of the browser as files.
import { useEffect, useRef, useState } from 'react'
import { Download, FolderOpen, Save, Trash2, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import type { SequencerSequenceDocument, SequencerSequenceInfo } from '@/api/types'
import * as seq from './api'
import { fmtSeconds } from './format'

export function SequencesDialog({ queueSize, hasCompleted, onClose }: {
  queueSize: number
  hasCompleted: boolean
  onClose: () => void
}) {
  const [library, setLibrary] = useState<SequencerSequenceInfo[] | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [skipCompleted, setSkipCompleted] = useState(true)
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [fileTarget, setFileTarget] = useState<'queue' | 'library'>('queue')

  const refresh = () => seq.listSequences().then(setLibrary).catch((e: Error) => setMessage({ text: e.message, error: true }))
  useEffect(() => { void refresh() }, [])

  const report = async (fn: () => Promise<string>) => {
    try {
      setMessage({ text: await fn() })
      await refresh()
    } catch (e) {
      setMessage({ text: (e as Error).message, error: true })
    }
  }

  const save = (overwrite = false): Promise<void> => report(async () => {
    try {
      const info = await seq.saveSequence({
        name: name.trim(), description: description.trim() || null,
        include_completed: !skipCompleted, overwrite,
      })
      return `Saved "${info.name}" (${info.tasks} task${info.tasks > 1 ? 's' : ''})`
    } catch (e) {
      const err = e as seq.ApiError
      if (err.status === 409 && window.confirm(`${err.message}. Replace it?`)) {
        const info = await seq.saveSequence({
          name: name.trim(), description: description.trim() || null,
          include_completed: !skipCompleted, overwrite: true,
        })
        return `Replaced "${info.name}"`
      }
      throw e
    }
  })

  const load = (s: SequencerSequenceInfo) => report(async () => {
    const added = await seq.loadSequence(s.id)
    return `Added ${added.length} task${added.length > 1 ? 's' : ''} from "${s.name}" to the queue`
  })

  const remove = (s: SequencerSequenceInfo) => {
    if (!window.confirm(`Delete the saved sequence "${s.name}"? Tasks already in the queue are not affected.`)) return
    void report(async () => { await seq.deleteSequence(s.id); return `Deleted "${s.name}"` })
  }

  const openFile = (target: 'queue' | 'library') => {
    setFileTarget(target)
    fileInput.current?.click()
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    await report(async () => {
      let doc: SequencerSequenceDocument
      try {
        doc = JSON.parse(await file.text())
      } catch {
        throw new Error(`${file.name} is not a JSON file`)
      }
      if (doc?.format !== 'astrolol-sequence') throw new Error(`${file.name} is not an astrolol sequence file`)
      if (fileTarget === 'queue') {
        const added = await seq.importDocument(doc)
        return `Added ${added.length} task${added.length > 1 ? 's' : ''} from ${file.name} to the queue`
      }
      try {
        const info = await seq.uploadToLibrary(doc)
        return `Saved "${info.name}" in the library`
      } catch (e) {
        const err = e as seq.ApiError
        if (err.status === 409 && window.confirm(`${err.message}. Replace it?`)) {
          const info = await seq.uploadToLibrary(doc, true)
          return `Replaced "${info.name}"`
        }
        throw e
      }
    })
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-16" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[80vh] flex flex-col rounded-lg border border-surface-border bg-surface-raised"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
          <h2 className="text-sm font-semibold text-slate-100">Sequences</h2>
          <Button variant="ghost" size="icon" onClick={onClose} title="Close"><X size={16} /></Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-6">
          <section>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Save the queue as a sequence</h3>
            <p className="text-xs text-slate-500 mb-2">
              Saves the task definitions (targets, cameras, exposures, options), not their progress.
              Loading it later adds fresh copies to the queue.
            </p>
            <div className="flex flex-col gap-2">
              <Input placeholder="Name, e.g. Autumn galaxies LRGB" value={name} onChange={(e) => setName(e.target.value)} />
              <Input placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
              <div className="flex items-center gap-3">
                {hasCompleted && (
                  <>
                    <ToggleSwitch label="Leave out completed tasks" checked={skipCompleted} onChange={() => setSkipCompleted((v) => !v)} />
                    <span className="text-xs text-slate-300">Leave out completed tasks</span>
                  </>
                )}
                <Button size="sm" className="ml-auto" disabled={!name.trim() || queueSize === 0} onClick={() => void save()}>
                  <Save size={13} className="mr-1" /> Save
                </Button>
              </div>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Saved sequences</h3>
            {library === null ? <p className="text-xs text-slate-500">Loading…</p>
              : library.length === 0 ? <p className="text-xs text-slate-500">None yet.</p>
              : (
                <ul className="flex flex-col divide-y divide-surface-border">
                  {library.map((s) => (
                    <li key={s.id} className="flex items-center gap-3 py-2">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-slate-100 truncate">{s.name}</div>
                        <div className="text-xs text-slate-500 truncate">
                          {s.tasks} task{s.tasks > 1 ? 's' : ''} · {s.targets.join(', ')} · {fmtSeconds(s.exposure_s)} of exposure
                          · saved {new Date(s.saved_at).toLocaleDateString()}
                        </div>
                        {s.description && <div className="text-xs text-slate-400 truncate">{s.description}</div>}
                      </div>
                      <Button size="sm" onClick={() => void load(s)} title="Add these tasks to the queue">
                        <FolderOpen size={13} className="mr-1" /> Load
                      </Button>
                      <a href={seq.sequenceDownloadUrl(s.id)} download title="Download as a file"
                        className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-surface-overlay">
                        <Download size={14} />
                      </a>
                      <button type="button" onClick={() => remove(s)} title="Delete"
                        className="p-1.5 rounded text-slate-500 hover:text-status-error hover:bg-surface-overlay">
                        <Trash2 size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
          </section>

          <section>
            <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">Files</h3>
            <div className="flex gap-2 flex-wrap">
              <a href={queueSize ? seq.exportUrl() : undefined} download
                className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-surface-border
                  ${queueSize ? 'text-slate-300 hover:bg-surface-overlay' : 'text-slate-600 pointer-events-none'}`}>
                <Download size={12} /> Download the queue
              </a>
              <Button variant="outline" size="sm" onClick={() => openFile('queue')}>
                <Upload size={12} className="mr-1" /> Add a file to the queue
              </Button>
              <Button variant="outline" size="sm" onClick={() => openFile('library')}>
                <Upload size={12} className="mr-1" /> Add a file to the saved sequences
              </Button>
              <input ref={fileInput} type="file" accept=".json,application/json" className="hidden"
                onChange={(e) => void onFile(e.target.files?.[0])} />
            </div>
          </section>
        </div>

        {message && (
          <p className={`px-5 py-2 border-t border-surface-border text-xs ${message.error ? 'text-status-error' : 'text-emerald-300'}`}>
            {message.text}
          </p>
        )}
      </div>
    </div>
  )
}
