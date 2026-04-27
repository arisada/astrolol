import { useStore } from '@/store'

interface AutofocusRunningState {
  runId: string
  step: number
  totalSteps: number
  fwhm: number | null
}

export function AutofocusChip() {
  const af = useStore((s) => s.pluginStates['autofocus'] as AutofocusRunningState | null | undefined)
  if (!af) return null

  const progress = af.totalSteps > 0 ? ` ${af.step}/${af.totalSteps}` : ''
  const fwhm = af.fwhm !== null && af.fwhm > 0 ? ` · ${af.fwhm.toFixed(1)}px` : ''

  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-medium whitespace-nowrap bg-amber-500/20 text-amber-300 border-amber-500/30 animate-pulse">
      <span className="text-slate-400 truncate max-w-[10rem]">Autofocus</span>
      <span className="opacity-40">·</span>
      <span>{`Step${progress}${fwhm}`}</span>
    </span>
  )
}
