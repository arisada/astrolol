// Segmented tab switcher: a small raised track with the active tab lifted out of it.
export interface TabItem<T extends string> {
  id: T
  label: string
  icon?: React.ReactNode
}

export function Tabs<T extends string>({ tabs, value, onChange, className = '' }: {
  tabs: readonly TabItem<T>[]
  value: T
  onChange: (id: T) => void
  className?: string
}) {
  return (
    <div role="tablist" className={`inline-flex max-w-full overflow-x-auto gap-0.5 p-0.5 rounded-lg bg-surface-raised border border-surface-border ${className}`}>
      {tabs.map((tb) => (
        <button
          key={tb.id}
          type="button"
          role="tab"
          aria-selected={value === tb.id}
          onClick={() => onChange(tb.id)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md label-caps whitespace-nowrap transition-colors
            ${value === tb.id ? 'bg-surface-overlay text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}
        >
          {tb.icon}
          {tb.label}
        </button>
      ))}
    </div>
  )
}
