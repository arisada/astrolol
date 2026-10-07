import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StepperShell, stepperValueClass } from './stepper-shell'

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
