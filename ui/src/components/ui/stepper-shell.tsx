// Shared frame of the joined −/+ steppers: [ − | value | + ] in one bordered block.
const stepBtn = `w-9 shrink-0 bg-surface-overlay text-slate-400 text-base leading-none transition-colors
  hover:text-slate-100 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-400`

export function StepperShell({ label, onDec, onInc, decDisabled, incDisabled, decTitle, incTitle, children }: {
  label?: string
  onDec: () => void
  onInc: () => void
  decDisabled?: boolean
  incDisabled?: boolean
  decTitle: string
  incTitle: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      {label && <span className="label-caps text-slate-400">{label}</span>}
      <div className="inline-flex w-fit max-w-full items-stretch overflow-hidden rounded-lg border border-surface-border bg-surface
        transition-colors focus-within:border-accent">
        <button type="button" className={`${stepBtn} border-r border-surface-border`} disabled={decDisabled}
          onClick={onDec} title={decTitle} aria-label={decTitle}>{'−'}</button>
        {children}
        <button type="button" className={`${stepBtn} border-l border-surface-border`} disabled={incDisabled}
          onClick={onInc} title={incTitle} aria-label={incTitle}>{'+'}</button>
      </div>
    </div>
  )
}

export const stepperValueClass =
  'w-20 min-w-0 bg-transparent px-2 py-1.5 text-center font-mono text-[13px] text-slate-200 focus:outline-none disabled:opacity-50'
