import { useRef, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from './button'

export function fmtDuration(s: number): string {
  if (s < 1) return `${Math.round(s * 1000)} ms`
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem === 0 ? `${m} m` : `${m} m ${rem} s`
}

export function DurationStepper({ steps, value, onChange, label = 'Duration' }: {
  steps: number[]
  value: number
  onChange: (v: number) => void
  label?: string
}) {
  const [editing, setEditing] = useState(false)
  const [raw, setRaw] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const idx = steps.reduce(
    (best, v, i) => Math.abs(v - value) < Math.abs(steps[best] - value) ? i : best, 0,
  )

  const startEdit = () => {
    setRaw(String(value))
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  const commitEdit = () => {
    const n = parseFloat(raw)
    if (!isNaN(n) && n > 0) onChange(n)
    setEditing(false)
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="flex items-center gap-1">
        <Button size="icon" variant="outline" disabled={idx === 0}
          onClick={() => { setEditing(false); onChange(steps[idx - 1]) }} title="Shorter">
          <ChevronDown size={14} />
        </Button>
        {editing ? (
          <input
            ref={inputRef}
            type="number" min="0.001" step="any" value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(false) }}
            className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-accent rounded px-2 py-1.5 min-w-[5rem] focus:outline-none"
          />
        ) : (
          <button type="button" onClick={startEdit} title="Click to enter a custom value"
            className="flex-1 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5 min-w-[5rem] hover:border-slate-500 transition-colors">
            {fmtDuration(value)}
          </button>
        )}
        <Button size="icon" variant="outline" disabled={idx === steps.length - 1}
          onClick={() => { setEditing(false); onChange(steps[idx + 1]) }} title="Longer">
          <ChevronUp size={14} />
        </Button>
      </div>
    </div>
  )
}
