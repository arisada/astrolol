/**
 * DmsInput — degrees°minutes'seconds" coordinate input.
 *
 * Accepts a decimal float (negative = S / W) and lets the user edit in DMS
 * format.  Fires onChange with the new decimal value on every field change.
 *
 * mode "lat"  → latitude  ±90°,  direction toggle N / S
 * mode "lon"  → longitude ±180°, direction toggle E / W
 * mode "ra"   → right ascension 0–24 h, H M S labels, no direction toggle
 *
 * Reusable wherever DMS / HMS entry is needed (profiles, mount page, etc.).
 */
import { useEffect, useRef, useState } from 'react'
import { Input } from './input'

// ---------------------------------------------------------------------------
// Pure conversion helpers
// ---------------------------------------------------------------------------

function decimalToDms(decimal: number): { deg: number; min: number; sec: number; negative: boolean } {
  const negative = decimal < 0
  const abs = Math.abs(decimal)
  const deg = Math.floor(abs)
  const minFull = (abs - deg) * 60
  const min = Math.floor(minFull)
  const sec = parseFloat(((minFull - min) * 60).toFixed(2))
  return { deg, min, sec, negative }
}

function dmsToDecimal(deg: number, min: number, sec: number, negative: boolean): number {
  const abs = Math.abs(deg) + min / 60 + sec / 3600
  return negative ? -abs : abs
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface DmsInputProps {
  value: number
  onChange: (v: number) => void
  mode: 'lat' | 'lon' | 'ra'
}

export function DmsInput({ value, onChange, mode }: DmsInputProps) {
  const { deg: initDeg, min: initMin, sec: initSec, negative: initNeg } = decimalToDms(value)
  const [deg, setDeg] = useState(initDeg)
  const [min, setMin] = useState(initMin)
  const [sec, setSec] = useState(initSec)
  const [negative, setNegative] = useState(initNeg)

  // When `value` changes from outside (e.g. "import from connected"), re-sync
  // local state.  Skip when the change was triggered by the user editing a
  // field (emit=true path below) to avoid clobbering mid-edit state.
  const skipSync = useRef(false)
  useEffect(() => {
    if (skipSync.current) { skipSync.current = false; return }
    const { deg: d, min: m, sec: s, negative: n } = decimalToDms(value)
    setDeg(d); setMin(m); setSec(s); setNegative(n)
  }, [value])

  function emit(d: number, m: number, s: number, n: boolean) {
    skipSync.current = true
    onChange(dmsToDecimal(d, m, s, n))
  }

  const isRa = mode === 'ra'
  const maxDeg = isRa ? 23 : mode === 'lat' ? 90 : 180
  const posLabel = mode === 'lat' ? 'N' : 'E'
  const negLabel = mode === 'lat' ? 'S' : 'W'

  return (
    <div className="flex items-center gap-1">
      <Input
        type="number" min={0} max={maxDeg} step={1}
        className="w-14 text-center px-1"
        value={deg}
        onChange={(e) => {
          const v = Math.min(maxDeg, Math.max(0, parseInt(e.target.value) || 0))
          setDeg(v); emit(v, min, sec, negative)
        }}
      />
      <span className="text-slate-500 text-xs select-none">{isRa ? 'h' : '°'}</span>
      <Input
        type="number" min={0} max={59} step={1}
        className="w-12 text-center px-1"
        value={min}
        onChange={(e) => {
          const v = Math.min(59, Math.max(0, parseInt(e.target.value) || 0))
          setMin(v); emit(deg, v, sec, negative)
        }}
      />
      <span className="text-slate-500 text-xs select-none">{isRa ? 'm' : "'"}</span>
      <Input
        type="number" min={0} max={59.99} step={0.1}
        className="w-16 text-center px-1"
        value={sec}
        onChange={(e) => {
          const v = Math.min(59.99, Math.max(0, parseFloat(e.target.value) || 0))
          setSec(v); emit(deg, min, v, negative)
        }}
      />
      <span className="text-slate-500 text-xs select-none">{isRa ? 's' : '"'}</span>
      {!isRa && (
        <button
          type="button"
          onClick={() => { const n = !negative; setNegative(n); emit(deg, min, sec, n) }}
          className="min-w-[2rem] px-1.5 py-1 rounded border border-surface-border bg-surface-overlay text-xs font-medium text-slate-300 hover:border-accent hover:text-accent transition-colors"
        >
          {negative ? negLabel : posLabel}
        </button>
      )}
    </div>
  )
}
