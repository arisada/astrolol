export function LabeledSlider({
  label, value, min, max, step, format, onChange, onCommit,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  onChange: (v: number) => void
  onCommit: (v: number) => void
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-500 font-mono">{format(value)}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        onMouseUp={(e) => onCommit(parseFloat((e.target as HTMLInputElement).value))}
        onTouchEnd={(e) => onCommit(parseFloat((e.target as HTMLInputElement).value))}
        className="range-thin w-full"
        style={{ ['--v' as string]: `${((value - min) / (max - min)) * 100}%` }}
      />
    </div>
  )
}
