/**
 * DmsInput — degrees°minutes′seconds″ (or hours/minutes/seconds) coordinate entry.
 *
 * One joined block: [N/S] [▲ 41° ▼] [▲ 16′ ▼] [▲ 09.0″ ▼]. Every field has its own up/down buttons
 * (so it works without a keyboard), typed values are settled on blur/Enter, stepping carries into the
 * next field (60′ becomes +1°), and the value can never leave its range — see utils/dms.ts.
 *
 * Takes and emits a decimal value (negative = S / W; hours for RA).
 *
 * mode "lat"  → latitude  ±90°,  direction toggle N / S
 * mode "lon"  → longitude ±180°, direction toggle E / W
 * mode "ra"   → right ascension 0–24 h, h m s units, no direction toggle (wraps at 24 h)
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp } from 'lucide-react'
import {
  type DmsField, type DmsMode, type DmsParts,
  flipSign, fmtSec, fromParts, normalise, pad, parseField, stepParts, toParts,
} from '@/utils/dms'

export interface DmsInputProps {
  value: number
  onChange: (v: number) => void
  mode: DmsMode
}

const FIELDS: DmsField[] = ['deg', 'min', 'sec']
const UNITS: Record<DmsMode, string[]> = {
  lat: ['°', '′', '″'],
  lon: ['°', '′', '″'],
  ra: ['h', 'm', 's'],
}
const SIGNS: Record<DmsMode, [string, string]> = { lat: ['N', 'S'], lon: ['E', 'W'], ra: ['', ''] }

const stepBtn = `flex h-5 items-center justify-center bg-surface-overlay text-slate-400 transition-colors hover:text-slate-100`

export function DmsInput({ value, onChange, mode }: DmsInputProps) {
  const { t } = useTranslation()
  const [parts, setParts] = useState<DmsParts>(() => toParts(value))
  const [editing, setEditing] = useState<{ field: DmsField; text: string } | null>(null)

  // Follow outside changes ("import from connected device"), but not the echo of our own edits.
  useEffect(() => {
    if (Math.abs(fromParts(parts, mode) - value) > 0.05 / 3600) setParts(toParts(value))
  }, [value])  // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (next: DmsParts) => {
    const settled = normalise(next, mode)
    setParts(settled)
    onChange(fromParts(settled, mode))
  }

  const commit = () => {
    if (!editing) return
    setEditing(null)
    apply({ ...parts, [editing.field]: parseField(editing.text, editing.field) })
  }

  const shown = (field: DmsField) =>
    editing?.field === field ? editing.text : field === 'sec' ? fmtSec(parts.sec) : pad(parts[field])
  const width: Record<DmsField, string> = {
    deg: mode === 'lon' ? 'w-[3ch]' : 'w-[2ch]', min: 'w-[2ch]', sec: 'w-[4ch]',
  }

  return (
    <div className="inline-flex max-w-full items-stretch overflow-hidden rounded-lg border border-surface-border bg-surface
      transition-colors focus-within:border-accent">
      {mode !== 'ra' && (
        <button
          type="button"
          onClick={() => apply(flipSign(parts, mode))}
          className="w-9 shrink-0 border-r border-surface-border bg-surface-overlay font-mono text-[13px] font-semibold
            text-slate-200 transition-colors hover:text-accent"
        >
          {SIGNS[mode][parts.negative ? 1 : 0]}
        </button>
      )}
      {FIELDS.map((field, i) => (
        <div key={field} className={`flex flex-col ${i > 0 ? 'border-l border-surface-border' : ''}`}>
          <button type="button" className={stepBtn} aria-label={t('dms.increase', { unit: UNITS[mode][i] })}
            onClick={() => { setEditing(null); apply(stepParts(parts, field, 1, mode)) }}>
            <ChevronUp size={12} />
          </button>
          <label className="flex cursor-text items-baseline justify-center border-y border-surface-border px-1.5 py-1.5 font-mono text-[13px]">
            <input
              type="text" inputMode={field === 'sec' ? 'decimal' : 'numeric'} value={shown(field)}
              onFocus={(e) => { setEditing({ field, text: e.target.value }); e.target.select() }}
              onChange={(e) => {
                const text = e.target.value
                if (field === 'sec' ? /^\d*\.?\d*$/.test(text) : /^\d*$/.test(text)) setEditing({ field, text })
              }}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') setEditing(null)
                if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                  e.preventDefault()
                  setEditing(null)
                  apply(stepParts(parts, field, e.key === 'ArrowUp' ? 1 : -1, mode))
                }
              }}
              className={`${width[field]} bg-transparent p-0 text-right text-slate-200 focus:outline-none`}
            />
            <span className="ml-0.5 select-none text-xs text-slate-500">{UNITS[mode][i]}</span>
          </label>
          <button type="button" className={stepBtn} aria-label={t('dms.decrease', { unit: UNITS[mode][i] })}
            onClick={() => { setEditing(null); apply(stepParts(parts, field, -1, mode)) }}>
            <ChevronDown size={12} />
          </button>
        </div>
      ))}
    </div>
  )
}
