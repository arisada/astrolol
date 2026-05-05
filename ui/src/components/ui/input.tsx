import { type InputHTMLAttributes, forwardRef } from 'react'

type InputSize = 'sm' | 'md'

const sizeClass: Record<InputSize, string> = {
  md: 'px-3 py-1.5 text-sm',
  sm: 'px-2 py-1 text-xs font-mono',
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { inputSize?: InputSize }>(
  ({ className = '', inputSize = 'md', ...props }, ref) => (
    <input
      ref={ref}
      className={`w-full rounded bg-surface-overlay border border-surface-border
        ${sizeClass[inputSize]}
        text-slate-200 placeholder:text-slate-500
        focus:outline-none focus:ring-1 focus:ring-accent
        disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
