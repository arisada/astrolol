import { type InputHTMLAttributes, forwardRef } from 'react'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = '', ...props }, ref) => (
    <input
      ref={ref}
      className={`w-full rounded bg-surface-overlay border border-surface-border px-3 py-1.5
        text-sm text-slate-200 placeholder:text-slate-500
        focus:outline-none focus:ring-1 focus:ring-accent
        disabled:opacity-40 ${className}`}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
