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
      {label && <span className="text-xs text-slate-400">{label}</span>}
      <div className="flex gap-1 flex-wrap">
        {options.map((o) => (
          <button
            key={String(o)}
            type="button"
            onClick={() => onChange(o)}
            className={`${stretch ? 'flex-1' : 'px-2'} py-0.5 text-xs rounded border capitalize transition-colors
              ${value === o
                ? 'border-accent text-accent bg-accent/10'
                : 'border-surface-border text-slate-400 hover:border-slate-500 hover:text-slate-300'
              }`}
          >
            {formatLabel ? formatLabel(o) : String(o)}
          </button>
        ))}
      </div>
    </div>
  )
}
