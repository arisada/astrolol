import { useState } from 'react'

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
      <div className="bg-surface-1 rounded-lg p-4 space-y-4">
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
  disabled,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={`bg-surface-0 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200
        focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40 ${className}`}
    />
  )
}

export function Options() {
  const [indi, setIndi] = useState<IndiSettings>({
    manageServer: true,
    host: 'localhost',
    port: 7624,
  })
  const [showAdvanced, setShowAdvanced] = useState(false)

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">Options</h1>

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
            </div>
          )}
        </div>
      </Section>

      <p className="text-xs text-slate-600 mt-4">
        Note: settings shown here are UI previews only — a backend settings API is not yet
        implemented. To configure the server, set <code className="text-slate-500">ASTROLOL_*</code> environment
        variables before starting astrolol.
      </p>
    </div>
  )
}
