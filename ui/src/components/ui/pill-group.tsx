export function PillGroup<T extends string | number>({
  options,
  value,
  onChange,
  label,
  formatLabel,
  stretch = false,
}: {
  options: readonly T[]
  value: T
  onChange: (v: T) => void
  label?: string
  formatLabel?: (v: T) => string
  stretch?: boolean
}) {
  return (
    <div className="flex flex-col gap-1">
      {label && <span className="label-caps text-slate-400">{label}</span>}
      <div className={`flex max-w-full overflow-x-auto border border-surface-border rounded-lg bg-surface ${stretch ? 'w-full' : 'w-fit'}`}>
        {options.map((o) => (
          <button
            key={String(o)}
            type="button"
            onClick={() => onChange(o)}
            className={`${stretch ? 'flex-1' : 'px-3'} min-w-[34px] py-1.5 font-mono text-xs capitalize whitespace-nowrap
              border-l border-surface-border first:border-l-0 transition-colors
              ${value === o
                ? 'bg-accent text-accent-fg'
                : 'text-slate-400 hover:bg-surface-overlay hover:text-slate-200'
              }`}
          >
            {formatLabel ? formatLabel(o) : String(o)}
          </button>
        ))}
      </div>
    </div>
  )
}
