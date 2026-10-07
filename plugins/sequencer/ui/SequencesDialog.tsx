// Named sequences: save the queue as a reusable plan, load one back, and move plans in and
// out of the browser as files.
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t, i18n } = useTranslation('sequencer')
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
      return t('sequences.saved', { name: info.name, tasks: t('sequences.tasks', { count: info.tasks }) })
    } catch (e) {
      const err = e as seq.ApiError
      if (err.status === 409 && window.confirm(t('sequences.confirmReplace', { message: err.message }))) {
        const info = await seq.saveSequence({
          name: name.trim(), description: description.trim() || null,
          include_completed: !skipCompleted, overwrite: true,
        })
        return t('sequences.replaced', { name: info.name })
      }
      throw e
    }
  })

  const load = (s: SequencerSequenceInfo) => report(async () => {
    const added = await seq.loadSequence(s.id)
    return t('sequences.added', { tasks: t('sequences.tasks', { count: added.length }), name: s.name })
  })

  const remove = (s: SequencerSequenceInfo) => {
    if (!window.confirm(t('sequences.confirmDelete', { name: s.name }))) return
    void report(async () => { await seq.deleteSequence(s.id); return t('sequences.deleted', { name: s.name }) })
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
        throw new Error(t('sequences.notJson', { file: file.name }))
      }
      if (doc?.format !== 'astrolol-sequence') throw new Error(t('sequences.notSequence', { file: file.name }))
      if (fileTarget === 'queue') {
        const added = await seq.importDocument(doc)
        return t('sequences.addedFile', { tasks: t('sequences.tasks', { count: added.length }), file: file.name })
      }
      try {
        const info = await seq.uploadToLibrary(doc)
        return t('sequences.savedLibrary', { name: info.name })
      } catch (e) {
        const err = e as seq.ApiError
        if (err.status === 409 && window.confirm(t('sequences.confirmReplace', { message: err.message }))) {
          const info = await seq.uploadToLibrary(doc, true)
          return t('sequences.replaced', { name: info.name })
        }
        throw e
      }
    })
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/55 pt-16" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[80vh] flex flex-col rounded-[10px] border border-surface-border bg-surface-raised"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
          <h2 className="text-sm font-semibold text-slate-100">{t('sequences.title')}</h2>
          <Button variant="ghost" size="icon" onClick={onClose} title={t('sequences.close')}><X size={16} /></Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-6">
          <section>
            <h3 className="font-medium text-slate-500 label-caps mb-2">{t('sequences.saveTitle')}</h3>
            <p className="text-xs text-slate-500 mb-2">
              {t('sequences.saveHint')}
            </p>
            <div className="flex flex-col gap-2">
              <Input placeholder={t('sequences.namePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} />
              <Input placeholder={t('sequences.descPlaceholder')} value={description} onChange={(e) => setDescription(e.target.value)} />
              <div className="flex items-center gap-3">
                {hasCompleted && (
                  <>
                    <ToggleSwitch label={t('sequences.leaveOut')} checked={skipCompleted} onChange={() => setSkipCompleted((v) => !v)} />
                    <span className="text-xs text-slate-300">{t('sequences.leaveOut')}</span>
                  </>
                )}
                <Button size="sm" className="ml-auto" disabled={!name.trim() || queueSize === 0} onClick={() => void save()}>
                  <Save size={13} className="mr-1" /> {t('sequences.save')}
                </Button>
              </div>
            </div>
          </section>

          <section>
            <h3 className="font-medium text-slate-500 label-caps mb-2">{t('sequences.library')}</h3>
            {library === null ? <p className="text-xs text-slate-500">{t('sequences.loading')}</p>
              : library.length === 0 ? <p className="text-xs text-slate-500">{t('sequences.none')}</p>
              : (
                <ul className="flex flex-col divide-y divide-surface-border">
                  {library.map((s) => (
                    <li key={s.id} className="flex items-center gap-3 py-2">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-slate-100 truncate">{s.name}</div>
                        <div className="text-xs text-slate-500 truncate">
                          {t('sequences.summary', { tasks: t('sequences.tasks', { count: s.tasks }), targets: s.targets.join(', '), time: fmtSeconds(s.exposure_s) })}
                          {' · '}{t('sequences.savedOn', { date: new Date(s.saved_at).toLocaleDateString(i18n.language) })}
                        </div>
                        {s.description && <div className="text-xs text-slate-400 truncate">{s.description}</div>}
                      </div>
                      <Button size="sm" onClick={() => void load(s)} title={t('sequences.loadTitle')}>
                        <FolderOpen size={13} className="mr-1" /> {t('sequences.load')}
                      </Button>
                      <a href={seq.sequenceDownloadUrl(s.id)} download title={t('sequences.download')}
                        className="p-1.5 rounded text-slate-400 hover:text-slate-100 hover:bg-surface-overlay">
                        <Download size={14} />
                      </a>
                      <button type="button" onClick={() => remove(s)} title={t('sequences.delete')}
                        className="p-1.5 rounded text-slate-500 hover:text-status-error hover:bg-surface-overlay">
                        <Trash2 size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
          </section>

          <section>
            <h3 className="font-medium text-slate-500 label-caps mb-2">{t('sequences.files')}</h3>
            <div className="flex gap-2 flex-wrap">
              <a href={queueSize ? seq.exportUrl() : undefined} download
                className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-surface-border
                  ${queueSize ? 'text-slate-300 hover:bg-surface-overlay' : 'text-slate-600 pointer-events-none'}`}>
                <Download size={12} /> {t('sequences.downloadQueue')}
              </a>
              <Button variant="outline" size="sm" onClick={() => openFile('queue')}>
                <Upload size={12} className="mr-1" /> {t('sequences.addQueue')}
              </Button>
              <Button variant="outline" size="sm" onClick={() => openFile('library')}>
                <Upload size={12} className="mr-1" /> {t('sequences.addLibrary')}
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
