import { type ButtonHTMLAttributes, forwardRef } from 'react'

type Variant = 'default' | 'ghost' | 'danger' | 'outline'
type Size = 'sm' | 'md' | 'lg' | 'icon'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

// default: the one primary action; outline: solid secondary; ghost: quiet; danger: destructive, filled.
const variantClass: Record<Variant, string> = {
  default: 'bg-accent border border-accent hover:bg-accent-dim hover:border-accent-dim text-accent-fg font-semibold',
  outline: 'bg-surface-overlay border border-surface-border hover:border-slate-500 text-slate-200',
  ghost: 'border border-transparent hover:bg-surface-overlay text-slate-400 hover:text-slate-200',
  danger: 'bg-status-error border border-status-error hover:brightness-110 text-slate-100 font-semibold',
}

const sizeClass: Record<Size, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3.5 py-2 text-[13px]',
  lg: 'px-5 py-2.5 text-sm',
  icon: 'p-1.5',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'default', size = 'md', className = '', ...props }, ref) => (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center rounded-lg transition-colors
        disabled:opacity-40 disabled:cursor-not-allowed min-h-[36px] min-w-[36px]
        ${variantClass[variant]} ${sizeClass[size]} ${className}`}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
