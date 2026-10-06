import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from './button'

/** Frame counts people actually pick for calibration and light sets. */
export const FRAME_COUNT_STEPS = [0, 1, 2, 3, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200]

/**
 * Integer stepper styled like DurationStepper: −/+ jump between `steps`, and the value
 * in the middle is directly editable. The field may be emptied while typing (e.g. to
 * replace the leading digit); leaving it empty restores the last value on blur.
 * A value off the step list steps to its nearest neighbour in each direction.
 */
export function CountStepper({
  value, onChange, steps = FRAME_COUNT_STEPS, min = 0, max, label, disabled = false,
}: {
  value: number
  onChange: (v: number) => void
  steps?: number[]
  min?: number
  max?: number
  label?: string
  disabled?: boolean
}) {
  const [raw, setRaw] = useState(String(value))
  const [focused, setFocused] = useState(false)

  // Follow external changes (arrows, a reset) unless the user is mid-edit.
  useEffect(() => { if (!focused) setRaw(String(value)) }, [value, focused])

  const clamp = (n: number) => Math.max(min, max != null ? Math.min(max, n) : n)
  const lower = [...steps].reverse().find((s) => s < value && s >= min)
  const higher = steps.find((s) => s > value && (max == null || s <= max))

  const step = (to: number | undefined) => {
    if (to == null) return
    setRaw(String(to))
    onChange(to)
  }

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-xs text-slate-400">{label}</span>}
      <div className="flex items-center gap-1">
        <Button size="icon" variant="outline" disabled={disabled || lower == null}
          onClick={() => step(lower)} title="Fewer">
          <ChevronDown size={14} />
        </Button>
        <input
          type="text" inputMode="numeric" value={raw} disabled={disabled}
          onFocus={(e) => { setFocused(true); e.target.select() }}
          onChange={(e) => {
            const text = e.target.value
            if (text !== '' && !/^\d+$/.test(text)) return
            setRaw(text)
            if (text !== '') onChange(clamp(parseInt(text, 10)))
          }}
          onBlur={() => { setFocused(false); setRaw(String(value)) }}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
          className="w-14 text-center text-xs font-mono text-slate-200 bg-surface-overlay border border-surface-border rounded px-2 py-1.5 hover:border-slate-500 focus:border-accent focus:outline-none transition-colors disabled:opacity-50"
        />
        <Button size="icon" variant="outline" disabled={disabled || higher == null}
          onClick={() => step(higher)} title="More">
          <ChevronUp size={14} />
        </Button>
      </div>
    </div>
  )
}
