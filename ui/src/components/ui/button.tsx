import { type ButtonHTMLAttributes, forwardRef } from 'react'

type Variant = 'default' | 'ghost' | 'danger' | 'outline'
type Size = 'sm' | 'md' | 'lg' | 'icon'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

const variantClass: Record<Variant, string> = {
  default: 'bg-accent hover:bg-accent-dim text-white',
  ghost: 'hover:bg-surface-overlay text-slate-300',
  danger: 'bg-red-700 hover:bg-red-600 text-white',
  outline: 'border border-surface-border hover:bg-surface-overlay text-slate-300',
}

const sizeClass: Record<Size, string> = {
  sm: 'px-2 py-1 text-xs',
  md: 'px-3 py-1.5 text-sm',
  lg: 'px-4 py-2 text-sm',
  icon: 'p-1.5',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'default', size = 'md', className = '', ...props }, ref) => (
    <button
      ref={ref}
      className={`inline-flex items-center justify-center rounded font-medium transition-colors
        disabled:opacity-40 disabled:cursor-not-allowed min-h-[36px] min-w-[36px]
        ${variantClass[variant]} ${sizeClass[size]} ${className}`}
      {...props}
    />
  ),
)
Button.displayName = 'Button'
