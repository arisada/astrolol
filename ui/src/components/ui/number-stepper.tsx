import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StepperShell, stepperValueClass } from './stepper-shell'

/**
 * Joined −/+ stepper for a decimal quantity (temperature, focuser position, …). Each press moves by
 * `step`; the value in the middle is editable and settles on blur/Enter, clamped to min..max.
 * Use CountStepper instead when the steps should follow a list of round numbers.
 */
export function NumberStepper({
  value, onChange, step = 1, min, max, decimals = 0, unit, label, disabled = false, valueClassName = 'w-16',
}: {
  value: number
  onChange: (v: number) => void
  step?: number
  min?: number
  max?: number
  /** Decimals shown (typed values keep up to this many). */
  decimals?: number
  unit?: string
  label?: string
  disabled?: boolean
  /** Width of the value field. */
  valueClassName?: string
}) {
  const { t } = useTranslation()
  const [raw, setRaw] = useState(value.toFixed(decimals))
  const [focused, setFocused] = useState(false)
  useEffect(() => { if (!focused) setRaw(value.toFixed(decimals)) }, [value, decimals, focused])

  const clamp = (n: number) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity, n))
  const round = (n: number) => +n.toFixed(Math.max(decimals, 3))
  const set = (n: number) => { const v = round(clamp(n)); setRaw(v.toFixed(decimals)); onChange(v) }

  const commit = () => {
    setFocused(false)
    const n = parseFloat(raw.replace('−', '-'))
    if (Number.isFinite(n)) set(n)
    else setRaw(value.toFixed(decimals))
  }

  return (
    <StepperShell
      label={label}
      decDisabled={disabled || (min != null && value <= min)}
      incDisabled={disabled || (max != null && value >= max)}
      decTitle={t('number.less')}
      incTitle={t('number.more')}
      onDec={() => set(value - step)}
      onInc={() => set(value + step)}
    >
      <span className="flex items-center">
        <input
          type="text" inputMode="decimal" value={raw} disabled={disabled}
          onFocus={(e) => { setFocused(true); e.target.select() }}
          onChange={(e) => { if (/^-?\d*\.?\d*$/.test(e.target.value)) setRaw(e.target.value) }}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          className={`${stepperValueClass} ${valueClassName} ${unit ? 'pr-0 text-right' : ''}`}
        />
        {unit && <span className="select-none pr-2 text-xs text-slate-500">{unit}</span>}
      </span>
    </StepperShell>
  )
}
