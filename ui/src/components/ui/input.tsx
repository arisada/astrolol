import { type InputHTMLAttributes, forwardRef } from 'react'

type InputSize = 'sm' | 'md'

const sizeClass: Record<InputSize, string> = {
  md: 'px-2.5 py-2 text-[13px] font-mono',
  sm: 'px-2 py-1 text-xs font-mono',
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { inputSize?: InputSize }>(
  ({ className = '', inputSize = 'md', ...props }, ref) => (
    <input
      ref={ref}
      className={`w-full rounded-lg bg-surface border border-surface-border
        ${sizeClass[inputSize]}
        text-slate-200 placeholder:text-slate-500
        focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent
        disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
