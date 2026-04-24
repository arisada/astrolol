import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { PluginInfo } from '@/api/types'
import { useStore } from '@/store'

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

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none
        ${value ? 'bg-accent' : 'bg-slate-600'}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
          ${value ? 'translate-x-6' : 'translate-x-1'}`}
      />
    </button>
  )
}

function TextInput({
  value,
  onChange,
  onBlur,
  disabled,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  onBlur?: () => void
  disabled?: boolean
  className?: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      disabled={disabled}
      className={`bg-surface border border-surface-border rounded px-3 py-1.5 text-sm text-slate-200
        focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40 ${className}`}
    />
  )
}

// Token reference for the save template fields
const TOKEN_REFERENCE = [
  { token: '%D', desc: 'ISO date (YYYY-MM-DD)' },
  { token: '%T', desc: 'Time (HHMMSS)' },
  { token: '%U', desc: 'Home directory' },
  { token: '%O', desc: 'Object name' },
  { token: '%F', desc: 'Frame type (light/dark/flat/bias)' },
  { token: '%C', desc: 'Counter (6-digit, per camera)' },
  { token: '%E', desc: 'Exposure time (seconds)' },
  { token: '%G', desc: 'Gain' },
]

function TokenReference() {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-slate-500 hover:text-slate-300 underline underline-offset-2"
      >
        {open ? 'Hide token reference' : 'Show token reference'}
      </button>
      {open && (
        <table className="mt-2 text-xs w-full border-collapse">
          <tbody>
            {TOKEN_REFERENCE.map(({ token, desc }) => (
              <tr key={token} className="border-t border-slate-700">
                <td className="py-1 pr-4 font-mono text-accent">{token}</td>
                <td className="py-1 text-slate-400">{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function Options() {
  const [indi, setIndi] = useState<IndiSettings>({
    manageServer: true,
    host: 'localhost',
    port: 7624,
  })
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [indiDebugLevel, setIndiDebugLevel] = useState(0)

  // Image saving settings (persisted via backend)
  const [saveDir, setSaveDir] = useState('~/astrolol_pictures/%D')
  const [saveFilename, setSaveFilename] = useState('%F_%C_%Es_%Gg')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  // INDI run dir
  const [indiRunDir, setIndiRunDir] = useState('/tmp/astrolol')

  // INDI local upload mode
  const [indiLocalUpload, setIndiLocalUpload] = useState(false)
  const [indiLocalUploadDir, setIndiLocalUploadDir] = useState('/tmp/astrolol_upload')

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
      })
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
    const updated = pluginInfos.map((p) =>
      p.id === plugin.id ? { ...p, enabled: !p.enabled } : p,
    )
    const enabledIds = updated.filter((p) => p.enabled).map((p) => p.id)
    try {
      const current = await api.settings.get()
      await api.settings.put({ ...current, enabled_plugins: enabledIds })
      setPluginInfos(updated)
      setPluginSaveStatus('saved')
      setRestartNeeded(true)
      setTimeout(() => setPluginSaveStatus('idle'), 2000)
    } catch {
      setPluginSaveStatus('error')
    }
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">Options</h1>

      <Section title="Image Saving">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-sm text-slate-200">Save directory</label>
            <p className="text-xs text-slate-500">Directory template for saved subs. Supports % tokens.</p>
            <TextInput
              value={saveDir}
              onChange={setSaveDir}
              onBlur={persistSaveSettings}
              className="w-full font-mono text-xs"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-sm text-slate-200">Filename template</label>
            <p className="text-xs text-slate-500">Without extension — <code className="text-slate-400">.fits</code> is appended automatically.</p>
            <TextInput
              value={saveFilename}
              onChange={setSaveFilename}
              onBlur={persistSaveSettings}
              className="w-full font-mono text-xs"
            />
          </div>
          <div className="text-xs text-slate-500 bg-surface-overlay border border-surface-border rounded p-2 font-mono break-all">
            Example: <span className="text-slate-300">{saveDir.replace('%D', '2026-04-13').replace('%T', '210530').replace('%U', '~').replace('%O', 'M42').replace('%F', 'light').replace('%C', '000001').replace('%E', '60.0').replace('%G', '100')}/{saveFilename.replace('%D', '2026-04-13').replace('%T', '210530').replace('%U', '~').replace('%O', 'M42').replace('%F', 'light').replace('%C', '000001').replace('%E', '60.0').replace('%G', '100')}.fits</span>
          </div>
          <TokenReference />
          {saveStatus === 'saving' && <p className="text-xs text-slate-500">Saving…</p>}
          {saveStatus === 'saved' && <p className="text-xs text-status-connected">Saved.</p>}
          {saveStatus === 'error' && <p className="text-xs text-status-error">Failed to save settings.</p>}
        </div>
      </Section>

      <Section title="INDI Server">
        <Row
          label="Manage indiserver automatically"
          hint="astrolol will start and stop indiserver as needed"
        >
          <Toggle
            value={indi.manageServer}
            onChange={(v) => setIndi((s) => ({ ...s, manageServer: v }))}
          />
        </Row>
        <Row
          label="Run directory"
          hint="Directory for the INDI FIFO and state file (persisted)"
        >
          <TextInput
            value={indiRunDir}
            onChange={setIndiRunDir}
            onBlur={persistSaveSettings}
            className="w-48 font-mono text-xs"
          />
        </Row>
        <Row
          label="Local image transfer"
          hint="Driver writes FITS directly to disk — eliminates base64 encoding over TCP. Requires restart."
        >
          <Toggle value={indiLocalUpload} onChange={persistIndiLocalUpload} />
        </Row>
        {indiLocalUpload && (
          <Row
            label="Upload directory"
            hint="Shared directory where the driver saves images"
          >
            <TextInput
              value={indiLocalUploadDir}
              onChange={setIndiLocalUploadDir}
              onBlur={persistSaveSettings}
              className="w-48 font-mono text-xs"
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
            {showAdvanced ? 'Hide advanced settings' : 'Show advanced settings'}
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-4 border-t border-slate-700 pt-4">
              <Row
                label="INDI server host"
                hint="Only used when automatic management is disabled"
              >
                <TextInput
                  value={indi.host}
                  onChange={(v) => setIndi((s) => ({ ...s, host: v }))}
                  disabled={indi.manageServer}
                  className="w-40"
                />
              </Row>
              <Row
                label="INDI server port"
                hint="Default: 7624"
              >
                <TextInput
                  value={String(indi.port)}
                  onChange={(v) => {
                    const n = parseInt(v, 10)
                    if (!isNaN(n)) setIndi((s) => ({ ...s, port: n }))
                  }}
                  disabled={indi.manageServer}
                  className="w-24"
                />
              </Row>
              <Row
                label="INDI protocol logging"
                hint="Log XML traffic to console and log file. Resets to Off on restart."
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
                  <option value={0}>Off</option>
                  <option value={1}>Tags only</option>
                  <option value={2}>Full XML</option>
                </select>
              </Row>
            </div>
          )}
        </div>
      </Section>

      {pluginInfos.length > 0 && (
        <Section title="Plugins">
          <div className="space-y-3">
            {pluginInfos.map((plugin) => (
              <Row
                key={plugin.id}
                label={plugin.name}
                hint={plugin.description || undefined}
              >
                <Toggle value={plugin.enabled} onChange={() => togglePlugin(plugin)} />
              </Row>
            ))}
          </div>
          {pluginSaveStatus === 'saved' && (
            <p className="text-xs text-status-connected mt-2">Saved.</p>
          )}
          {pluginSaveStatus === 'error' && (
            <p className="text-xs text-status-error mt-2">Failed to save plugin settings.</p>
          )}
          {restartNeeded && (
            <div className="flex items-center gap-3 mt-2">
              <p className="text-xs text-slate-400">
                {restarting ? 'Restarting…' : 'Restart required for changes to take effect.'}
              </p>
              {!restarting && (
                <button
                  type="button"
                  onClick={restartNow}
                  className="text-xs px-2 py-1 rounded bg-accent text-white hover:bg-accent/80 transition-colors"
                >
                  Restart now
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      <Section title="Server">
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={restartNow}
            disabled={restarting}
            className="px-3 py-1.5 rounded text-sm font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50 transition-colors"
          >
            {restarting ? 'Restarting…' : 'Restart astrolol'}
          </button>
          <button
            type="button"
            onClick={stopIndi}
            disabled={indiStopStatus === 'stopping'}
            className="px-3 py-1.5 rounded text-sm font-medium bg-slate-600 hover:bg-slate-500 text-white disabled:opacity-50 transition-colors"
          >
            {indiStopStatus === 'stopping' ? 'Stopping…' : 'Stop INDI server'}
          </button>
        </div>
        {indiStopStatus === 'stopped' && (
          <p className="text-xs text-status-connected mt-2">INDI server stopped.</p>
        )}
        {indiStopStatus === 'error' && (
          <p className="text-xs text-status-error mt-2">Failed to stop INDI server.</p>
        )}
      </Section>
    </div>
  )
}
