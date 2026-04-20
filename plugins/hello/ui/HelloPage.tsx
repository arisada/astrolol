import { useEffect, useState } from 'react'

export function HelloPage() {
  const [hello, setHello] = useState(false)
  const [status, setStatus] = useState<'idle' | 'saving' | 'error'>('idle')

  useEffect(() => {
    fetch('/plugins/hello/property')
      .then((r) => r.json())
      .then((d) => setHello(d.hello))
      .catch(() => {})
  }, [])

  const toggle = async () => {
    const next = !hello
    setStatus('saving')
    try {
      const r = await fetch('/plugins/hello/property', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hello: next }),
      })
      const d = await r.json()
      setHello(d.hello)
      setStatus('idle')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="p-6 max-w-xl">
      <h1 className="text-lg font-semibold text-slate-100 mb-6">Hello World</h1>
      <div className="bg-surface-raised rounded-lg p-4">
        <div className="flex items-center gap-4">
          <input
            id="hello-checkbox"
            type="checkbox"
            checked={hello}
            onChange={toggle}
            disabled={status === 'saving'}
            className="w-4 h-4 accent-accent cursor-pointer disabled:opacity-50"
          />
          <label htmlFor="hello-checkbox" className="text-sm text-slate-200 cursor-pointer select-none">
            Hello property
          </label>
          {status === 'saving' && <span className="text-xs text-slate-500">Saving…</span>}
          {status === 'error' && <span className="text-xs text-status-error">Failed to save.</span>}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          This checkbox calls <code className="text-slate-400">POST /plugins/hello/property</code> on the backend.
          It demonstrates a self-contained plugin with its own API and UI.
        </p>
      </div>
    </div>
  )
}
