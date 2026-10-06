import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { PluginInfo } from '@/api/types'
import { useStore } from '@/store'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { Input } from '@/components/ui/input'
import { PillGroup } from '@/components/ui/pill-group'
import { SUPPORTED_LANGUAGES, setLanguage } from '@/i18n'

interface IndiSettings {
  manageServer: boolean
  host: string
  port: number
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
        {title}
      </h2>
      <div className="bg-surface-raised rounded-lg p-4 space-y-4">
        {children}
      </div>
    </div>
  )
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-200">{label}</p>
        {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  )
}

// Token reference for the save template fields
const TOKEN_KEYS = ['D', 'T', 'U', 'O', 'F', 'N', 'C', 'f', 'E', 'G']

function TokenReference() {
  const { t } = useTranslation('options')
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-slate-500 hover:text-slate-300 underline underline-offset-2"
      >
        {open ? t('tokenRef.hide') : t('tokenRef.show')}
      </button>
      {open && (
        <table className="mt-2 text-xs w-full border-collapse">
          <tbody>
            {TOKEN_KEYS.map((k) => (
              <tr key={k} className="border-t border-slate-700">
                <td className="py-1 pr-4 font-mono text-accent">%{k}</td>
                <td className="py-1 text-slate-400">{t(`tokens.${k}`)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function Options() {
  const { t, i18n } = useTranslation('options')
  const [indi, setIndi] = useState<IndiSettings>({
    manageServer: true,
    host: 'localhost',
    port: 7624,
  })
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [indiDebugLevel, setIndiDebugLevel] = useState(0)

  // Image saving settings (persisted via backend)
  const [saveDir, setSaveDir] = useState('~/astrolol_pictures/%D')
  const [saveFilename, setSaveFilename] = useState('%F_%N_%Es_%Gg')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  // INDI run dir
  const [indiRunDir, setIndiRunDir] = useState('/tmp/astrolol')

  // INDI local upload mode
  const [indiLocalUpload, setIndiLocalUpload] = useState(false)
  const [indiLocalUploadDir, setIndiLocalUploadDir] = useState('/tmp/astrolol_upload')

  // Low memory mode
  const [lowMemoryMode, setLowMemoryMode] = useState(false)

  // Stop INDI status
  const [indiStopStatus, setIndiStopStatus] = useState<'idle' | 'stopping' | 'stopped' | 'error'>('idle')

  // Plugin enable/disable
  const pluginInfos = useStore((s) => s.pluginInfos)
  const setPluginInfos = useStore((s) => s.setPluginInfos)
  const [pluginSaveStatus, setPluginSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle')
  const [restartNeeded, setRestartNeeded] = useState(false)
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    api.settings.get()
      .then((s) => {
        setSaveDir(s.save_dir_template)
        setSaveFilename(s.save_filename_template)
        setIndiRunDir(s.indi_run_dir)
        setIndiLocalUpload(s.indi_local_upload ?? false)
        setIndiLocalUploadDir(s.indi_local_upload_dir ?? '/tmp/astrolol_upload')
        setLowMemoryMode(s.low_memory_mode ?? false)
      })
      .catch(() => { /* backend may not be running */ })
  }, [])

  const persistSaveSettings = async () => {
    setSaveStatus('saving')
    try {
      const current = await api.settings.get()
      await api.settings.put({
        ...current,
        save_dir_template: saveDir,
        save_filename_template: saveFilename,
        indi_run_dir: indiRunDir,
        indi_local_upload: indiLocalUpload,
        indi_local_upload_dir: indiLocalUploadDir,
        low_memory_mode: lowMemoryMode,
      })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  const persistLanguage = async (code: string) => {
    setLanguage(code)
    setSaveStatus('saving')
    try {
      const current = await api.settings.get()
      await api.settings.put({ ...current, language: code })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  const persistLowMemoryMode = async (v: boolean) => {
    setLowMemoryMode(v)
    setSaveStatus('saving')
    try {
      const current = await api.settings.get()
      await api.settings.put({ ...current, low_memory_mode: v })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  const persistIndiLocalUpload = async (v: boolean) => {
    setIndiLocalUpload(v)
    setSaveStatus('saving')
    try {
      const current = await api.settings.get()
      await api.settings.put({ ...current, indi_local_upload: v, indi_local_upload_dir: indiLocalUploadDir })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  const restartNow = async () => {
    setRestarting(true)
    try {
      await fetch('/admin/restart', { method: 'POST' })
    } catch {
      // expected — process may die before responding
    }
    // Poll /health until the server is back up, then reload
    const poll = async () => {
      try {
        const r = await fetch('/health')
        if (r.ok) { window.location.reload(); return }
      } catch { /* still down */ }
      setTimeout(poll, 800)
    }
    setTimeout(poll, 1200)
  }

  const stopIndi = async () => {
    setIndiStopStatus('stopping')
    try {
      await api.admin.indiStop()
      setIndiStopStatus('stopped')
      setTimeout(() => setIndiStopStatus('idle'), 3000)
    } catch {
      setIndiStopStatus('error')
      setTimeout(() => setIndiStopStatus('idle'), 3000)
    }
  }

  const togglePlugin = async (plugin: PluginInfo) => {
    const enabledIds = pluginInfos
      .map((p) => (p.id === plugin.id ? { ...p, enabled: !p.enabled } : p))
      .filter((p) => p.enabled)
      .map((p) => p.id)
    try {
      const current = await api.settings.get()
      await api.settings.put({ ...current, enabled_plugins: enabledIds })
      // Re-fetch rather than patch optimistically: a hot-reloadable plugin may
      // already be live, while others still need a restart — GET /plugins is
      // the source of truth for both.
      const fresh = await api.plugins.list()
      setPluginInfos(fresh)
      setPluginSaveStatus('saved')
      setRestartNeeded(fresh.some((p) => p.pending_restart))
      setTimeout(() => setPluginSaveStatus('idle'), 2000)
    } catch {
      setPluginSaveStatus('error')
    }
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">{t('title')}</h1>

      <Section title={t('language.title')}>
        <Row label={t('language.label')}>
          <PillGroup
            options={SUPPORTED_LANGUAGES.map((l) => l.code)}
            value={i18n.resolvedLanguage as string}
            onChange={persistLanguage}
            formatLabel={(code) => SUPPORTED_LANGUAGES.find((l) => l.code === code)?.label ?? code}
          />
        </Row>
      </Section>

      <Section title={t('saving.title')}>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-sm text-slate-200">{t('saving.dir')}</label>
            <p className="text-xs text-slate-500">{t('saving.dirHint')}</p>
            <Input
              inputSize="sm"
              value={saveDir}
              onChange={(e) => setSaveDir(e.target.value)}
              onBlur={persistSaveSettings}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-sm text-slate-200">{t('saving.filename')}</label>
            <p className="text-xs text-slate-500"><Trans t={t} i18nKey="saving.filenameHint" components={{ code: <code className="text-slate-400" /> }} /></p>
            <Input
              inputSize="sm"
              value={saveFilename}
              onChange={(e) => setSaveFilename(e.target.value)}
              onBlur={persistSaveSettings}
            />
          </div>
          <div className="text-xs text-slate-500 bg-surface-overlay border border-surface-border rounded p-2 font-mono break-all">
            {t('saving.example')} <span className="text-slate-300">{saveDir.replace('%D', '2026-04-13').replace('%T', '210530').replace('%U', '~').replace('%O', 'M42').replace('%F', 'light').replace('%N', '000001').replace('%C', 'zwo_asi294').replace('%f', 'L').replace('%E', '60.0').replace('%G', '100')}/{saveFilename.replace('%D', '2026-04-13').replace('%T', '210530').replace('%U', '~').replace('%O', 'M42').replace('%F', 'light').replace('%N', '000001').replace('%C', 'zwo_asi294').replace('%f', 'L').replace('%E', '60.0').replace('%G', '100')}.fits</span>
          </div>
          <TokenReference />
          {saveStatus === 'saving' && <p className="text-xs text-slate-500">{t('saving.saving')}</p>}
          {saveStatus === 'saved' && <p className="text-xs text-status-connected">{t('saving.saved')}</p>}
          {saveStatus === 'error' && <p className="text-xs text-status-error">{t('saving.error')}</p>}
        </div>
      </Section>

      <Section title={t('indi.title')}>
        <Row
          label={t('indi.manage')}
          hint={t('indi.manageHint')}
        >
          <ToggleSwitch
            checked={indi.manageServer}
            onChange={() => setIndi((s) => ({ ...s, manageServer: !s.manageServer }))}
            label={t('indi.manage')}
          />
        </Row>
        <Row
          label={t('indi.runDir')}
          hint={t('indi.runDirHint')}
        >
          <Input
            inputSize="sm"
            value={indiRunDir}
            onChange={(e) => setIndiRunDir(e.target.value)}
            onBlur={persistSaveSettings}
            className="!w-48"
          />
        </Row>
        <Row
          label={t('indi.localUpload')}
          hint={t('indi.localUploadHint')}
        >
          <ToggleSwitch checked={indiLocalUpload} onChange={() => persistIndiLocalUpload(!indiLocalUpload)} label={t('indi.localUpload')} />
        </Row>
        {indiLocalUpload && (
          <Row
            label={t('indi.uploadDir')}
            hint={t('indi.uploadDirHint')}
          >
            <Input
              inputSize="sm"
              value={indiLocalUploadDir}
              onChange={(e) => setIndiLocalUploadDir(e.target.value)}
              onBlur={persistSaveSettings}
              className="!w-48"
            />
          </Row>
        )}

        {/* Advanced — hidden by default */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-xs text-slate-500 hover:text-slate-300 underline underline-offset-2"
          >
            {showAdvanced ? t('indi.hideAdvanced') : t('indi.showAdvanced')}
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-4 border-t border-slate-700 pt-4">
              <Row
                label={t('indi.host')}
                hint={t('indi.hostHint')}
              >
                <Input
                  value={indi.host}
                  onChange={(e) => setIndi((s) => ({ ...s, host: e.target.value }))}
                  disabled={indi.manageServer}
                  className="!w-40"
                />
              </Row>
              <Row
                label={t('indi.port')}
                hint={t('indi.portHint')}
              >
                <Input
                  type="number"
                  value={String(indi.port)}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10)
                    if (!isNaN(n)) setIndi((s) => ({ ...s, port: n }))
                  }}
                  disabled={indi.manageServer}
                  className="!w-24"
                />
              </Row>
              <Row
                label={t('indi.logging')}
                hint={t('indi.loggingHint')}
              >
                <select
                  value={indiDebugLevel}
                  onChange={(e) => {
                    const level = parseInt(e.target.value, 10)
                    setIndiDebugLevel(level)
                    api.indi.setDebugLevel(level).catch(() => {})
                  }}
                  className="bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  <option value={0}>{t('indi.logOff')}</option>
                  <option value={1}>{t('indi.logTags')}</option>
                  <option value={2}>{t('indi.logFull')}</option>
                </select>
              </Row>
              <Row
                label={t('indi.lowMemory')}
                hint={t('indi.lowMemoryHint')}
              >
                <ToggleSwitch checked={lowMemoryMode} onChange={() => persistLowMemoryMode(!lowMemoryMode)} label={t('indi.lowMemory')} />
              </Row>
            </div>
          )}
        </div>
      </Section>

      {pluginInfos.length > 0 && (
        <Section title={t('plugins.title')}>
          <div className="space-y-3">
            {pluginInfos.map((plugin) => (
              <Row
                key={plugin.id}
                label={i18n.t('manifest.name', { ns: plugin.id, defaultValue: plugin.name })}
                hint={
                  plugin.pending_restart
                    ? t('plugins.restartPending')
                    : i18n.t('manifest.description', { ns: plugin.id, defaultValue: plugin.description }) || undefined
                }
              >
                <ToggleSwitch checked={plugin.enabled} onChange={() => togglePlugin(plugin)} label={i18n.t('manifest.name', { ns: plugin.id, defaultValue: plugin.name })} />
              </Row>
            ))}
          </div>
          {pluginSaveStatus === 'saved' && (
            <p className="text-xs text-status-connected mt-2">{t('plugins.saved')}</p>
          )}
          {pluginSaveStatus === 'error' && (
            <p className="text-xs text-status-error mt-2">{t('plugins.saveError')}</p>
          )}
          {restartNeeded && (
            <div className="flex items-center gap-3 mt-2">
              <p className="text-xs text-slate-400">
                {restarting ? t('plugins.restarting') : t('plugins.restartNeeded')}
              </p>
              {!restarting && (
                <button
                  type="button"
                  onClick={restartNow}
                  className="text-xs px-2 py-1 rounded bg-accent text-white hover:bg-accent/80 transition-colors"
                >
                  {t('plugins.restartNow')}
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      <Section title={t('server.title')}>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={restartNow}
            disabled={restarting}
            className="px-3 py-1.5 rounded text-sm font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50 transition-colors"
          >
            {restarting ? t('server.restarting') : t('server.restart')}
          </button>
          <button
            type="button"
            onClick={stopIndi}
            disabled={indiStopStatus === 'stopping'}
            className="px-3 py-1.5 rounded text-sm font-medium bg-slate-600 hover:bg-slate-500 text-white disabled:opacity-50 transition-colors"
          >
            {indiStopStatus === 'stopping' ? t('server.stopping') : t('server.stopIndi')}
          </button>
        </div>
        {indiStopStatus === 'stopped' && (
          <p className="text-xs text-status-connected mt-2">{t('server.indiStopped')}</p>
        )}
        {indiStopStatus === 'error' && (
          <p className="text-xs text-status-error mt-2">{t('server.indiStopFailed')}</p>
        )}
      </Section>
    </div>
  )
}
