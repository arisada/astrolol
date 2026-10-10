import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StepperShell, stepperValueClass } from './stepper-shell'

/** Exposure lengths from 1 ms to 1 h that people actually pick. */
export const EXPOSURE_STEPS = [
  0.001, 0.002, 0.003, 0.004, 0.005, 0.008,
  0.01, 0.013, 0.015, 0.02, 0.025, 0.033, 0.04, 0.05,
  0.067, 0.08, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8,
  1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30,
  45, 60, 90, 120, 180, 240, 300, 360, 480, 600, 900, 1200, 1800, 3600,
]

export function fmtDuration(s: number): string {
  if (s < 1) return `${Math.round(s * 1000)} ms`
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem === 0 ? `${m} m` : `${m} m ${rem} s`
}

export function DurationStepper({ steps, value, onChange, label }: {
  steps: number[]
  value: number
  onChange: (v: number) => void
  label?: string
}) {
  const { t } = useTranslation()
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
    <StepperShell
      label={label ?? t('duration.label')}
      decDisabled={idx === 0}
      incDisabled={idx === steps.length - 1}
      decTitle={t('duration.shorter')}
      incTitle={t('duration.longer')}
      onDec={() => { setEditing(false); onChange(steps[idx - 1]) }}
      onInc={() => { setEditing(false); onChange(steps[idx + 1]) }}
    >
      {editing ? (
        <input
          ref={inputRef}
          type="number" min="0.001" step="any" value={raw}
          onChange={(e) => setRaw(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(false) }}
          className={stepperValueClass}
        />
      ) : (
        <button type="button" onClick={startEdit} title={t('duration.custom')} className={`${stepperValueClass} hover:text-slate-50`}>
          {fmtDuration(value)}
        </button>
      )}
    </StepperShell>
  )
}
