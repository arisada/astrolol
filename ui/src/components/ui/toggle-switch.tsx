export function ToggleSwitch({ checked, onChange, label, disabled }: {
  checked: boolean
  onChange: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={disabled ? undefined : onChange}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border transition-colors
        focus:outline-none focus-visible:ring-1 focus-visible:ring-accent
        disabled:opacity-40 disabled:cursor-not-allowed
        ${checked ? 'bg-accent/30 border-accent' : 'bg-surface-overlay border-surface-border'} ${!disabled ? 'cursor-pointer' : ''}`}
      aria-label={label}
    >
      <span className={`absolute top-[2px] left-[2px] h-3.5 w-3.5 rounded-full transition-transform
        ${checked ? 'translate-x-4 bg-accent' : 'bg-slate-500'}`}
      />
    </button>
  )
}
