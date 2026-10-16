import { StepperShell } from './stepper-shell'

export interface Choice { value: string; label: string; /** Longer wording for the tooltip and screen readers. */ title?: string }

/**
 * −/+ through an ordered list of choices, the current one named in the middle: for settings
 * that are really a ladder (speeds, binning) and need a thumb-sized control on a phone.
 * A value that is not in the list shows `fallbackLabel` and steps to the nearest end.
 */
export function ChoiceStepper({
  choices, value, onChange, label, decTitle, incTitle, disabled = false, fallbackLabel = '—', large = false, className,
}: {
  choices: Choice[]
  value: string
  onChange: (value: string) => void
  label?: string
  decTitle: string
  incTitle: string
  disabled?: boolean
  fallbackLabel?: string
  /** Thumb-sized buttons, and a value field as wide as two of them. */
  large?: boolean
  className?: string
}) {
  const index = choices.findIndex((c) => c.value === value)
  const go = (to: number) => { const c = choices[to]; if (c) onChange(c.value) }
  return (
    <StepperShell
      label={label} large={large} className={className}
      decTitle={decTitle} incTitle={incTitle}
      decDisabled={disabled || choices.length === 0 || index === 0}
      incDisabled={disabled || choices.length === 0 || index === choices.length - 1}
      onDec={() => go(index < 0 ? choices.length - 1 : index - 1)}
      onInc={() => go(index < 0 ? 0 : index + 1)}
    >
      <output title={index >= 0 ? (choices[index].title ?? choices[index].label) : undefined} aria-live="polite"
        className={`${large ? 'w-14 px-1' : 'w-36 px-2'} min-w-0 truncate py-2 text-center font-mono text-[13px] leading-[1.9] text-slate-200`}>
        {index >= 0 ? choices[index].label : fallbackLabel}
      </output>
    </StepperShell>
  )
}
