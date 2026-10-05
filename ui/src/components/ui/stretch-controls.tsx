import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { PillGroup } from '@/components/ui/pill-group'
import { LabeledSlider } from '@/components/ui/labeled-slider'
import type { StretchParams } from '@/utils/stretch'

// Presets only move the background target — the parameter that reads as
// "brighter / darker". The shadows clip stays wherever Advanced left it.
const PRESETS = { soft: 0.15, normal: 0.25, hard: 0.35 } as const
type Preset = keyof typeof PRESETS
const PRESET_NAMES = Object.keys(PRESETS) as Preset[]

function matchingPreset(targetBg: number): Preset | '' {
  return PRESET_NAMES.find((p) => Math.abs(PRESETS[p] - targetBg) < 1e-3) ?? ''
}

export interface ColorParams {
  color: boolean   // render colour frames in colour (false: luminance)
  linked: boolean  // one shared stretch for all channels
}

/**
 * Colour-frame options, shared by the Imaging page and the viewer. Only meaningful
 * for one-shot-colour frames — callers render it when the stats carry channels.
 * The channel-linking choice only exists for the colour auto-stretch.
 */
export function ColorControls({
  value, onChange, showLinked,
}: {
  value: ColorParams
  onChange: (p: ColorParams) => void
  showLinked: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <PillGroup
        label="Colour"
        options={['rgb', 'mono'] as const}
        value={value.color ? 'rgb' : 'mono'}
        formatLabel={(v) => (v === 'rgb' ? 'RGB' : 'Mono')}
        onChange={(v) => onChange({ ...value, color: v === 'rgb' })}
        stretch
      />
      {showLinked && value.color && (
        <PillGroup
          label="Channels"
          options={['unlinked', 'linked'] as const}
          value={value.linked ? 'linked' : 'unlinked'}
          onChange={(v) => onChange({ ...value, linked: v === 'linked' })}
          stretch
        />
      )}
    </div>
  )
}

/**
 * Auto-stretch controls shared by the Imaging page and the viewer: a strength preset
 * plus an Advanced fold with the two underlying parameters. Like LabeledSlider,
 * `onChange` fires on every drag tick (local state only) and `onCommit` once the
 * value is final — presets commit immediately.
 */
export function StretchControls({
  value, onChange, onCommit,
}: {
  value: StretchParams
  onChange: (p: StretchParams) => void
  onCommit: (p: StretchParams) => void
}) {
  const [advanced, setAdvanced] = useState(false)

  return (
    <div className="flex flex-col gap-1.5">
      <PillGroup<Preset | ''>
        label="Stretch"
        options={PRESET_NAMES}
        value={matchingPreset(value.target_bg)}
        onChange={(p) => {
          if (!p) return
          const next = { ...value, target_bg: PRESETS[p] }
          onChange(next)
          onCommit(next)
        }}
        stretch
      />
      <button
        type="button"
        onClick={() => setAdvanced((a) => !a)}
        className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 self-start"
      >
        {advanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Advanced
      </button>
      {advanced && (
        <>
          <LabeledSlider
            label="Background" value={value.target_bg} min={0.05} max={0.5} step={0.01}
            format={(v) => v.toFixed(2)}
            onChange={(v) => onChange({ ...value, target_bg: v })}
            onCommit={(v) => onCommit({ ...value, target_bg: v })}
          />
          <LabeledSlider
            label="Shadows clip" value={value.shadows_sigma} min={-5} max={-0.5} step={0.1}
            format={(v) => `${v.toFixed(1)}σ`}
            onChange={(v) => onChange({ ...value, shadows_sigma: v })}
            onCommit={(v) => onCommit({ ...value, shadows_sigma: v })}
          />
        </>
      )}
    </div>
  )
}
