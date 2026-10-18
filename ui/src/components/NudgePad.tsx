import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { useNudgeRates } from '@/hooks/useNudgeRates'
import { Button } from '@/components/ui/button'
import { ChoiceStepper } from '@/components/ui/choice-stepper'
import { NudgeController } from './nudgeController'

/**
 * Speed stepper and a cross to move a mount by hand: tap a direction for a short nudge, hold it to
 * keep moving, the red button in the middle stops everything. Used on the Mount page and in the dock.
 */
export function NudgePad({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation('mount')
  const status = useStore((s) => s.mountStatuses[deviceId] ?? null)
  const { rates, rate, settings, saveSettings } = useNudgeRates(deviceId)
  const [error, setError] = useState<string | null>(null)

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }, [])

  // One controller per mount; it reads the current speed when a press starts.
  const controller = useMemo(() => new NudgeController({
    start: (direction, nudgeRate, durationMs) => api.mount.startMove(deviceId, direction, nudgeRate, durationMs),
    stop: () => api.mount.stopMove(deviceId),
    onError: (e) => setError((e as Error).message),
  }), [deviceId])

  // Stops a running slew or park, and any nudge, even when the page lost track of it (a lost touch,
  // a reload). Outside a slew only the nudge is stopped, so tracking carries on.
  const slewing = status?.is_slewing ?? false
  const stopAll = useCallback(async () => {
    controller.abort()
    await act(async () => {
      if (slewing) await api.mount.stop(deviceId)
      await api.mount.stopMove(deviceId)
    })
  }, [deviceId, act, slewing, controller])

  // A nudge must not outlive the pad being hidden, folded, closed or left.
  useEffect(() => {
    const onHide = () => controller.abort()
    window.addEventListener('blur', onHide)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.removeEventListener('blur', onHide)
      document.removeEventListener('visibilitychange', onHide)
      controller.abort()
    }
  }, [controller])

  // A button that gets disabled under the finger never reports its release.
  const disabled = !status || status.is_parked
  useEffect(() => { if (disabled) controller.abort() }, [disabled, controller])

  // Pointer capture keeps the release coming to the button wherever the finger or mouse ends up.
  const hold = (dir: string, title: string) => ({
    onPointerDown: (e: React.PointerEvent<HTMLButtonElement>) => {
      if (e.button !== 0) return
      e.currentTarget.setPointerCapture(e.pointerId)
      setError(null)
      controller.pressDown(dir, rate)
    },
    onPointerUp: () => controller.release(),
    onPointerCancel: () => controller.abort(),
    onLostPointerCapture: () => controller.release(),
    onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
    style: { touchAction: 'none' as const },
    disabled,
    title,
    'aria-label': title,
  })

  return (
    <div className="flex flex-col gap-3">
      <ChoiceStepper
        large className="self-center"
        choices={rates.map((r) => ({ value: r.rate, label: r.label, title: r.title }))}
        value={rate}
        onChange={(next) => saveSettings({ ...settings, nudge_rate: next })}
        decTitle={t('nudge.slower')}
        incTitle={t('nudge.faster')}
      />
      <div className="grid grid-cols-3 gap-1 self-center select-none">
        <span />
        <Button size="icon" variant="outline" className="h-12 w-12" {...hold('N', t('nudge.north'))}><ArrowUp size={20} /></Button>
        <span />
        <Button size="icon" variant="outline" className="h-12 w-12" {...hold('W', t('nudge.west'))}><ArrowLeft size={20} /></Button>
        <Button size="icon" variant="danger" className="h-12 w-12" disabled={!status}
          onClick={stopAll} title={t('nudge.stopTitle')} aria-label={t('nudge.stopTitle')}>
          <StopCircle size={20} />
        </Button>
        <Button size="icon" variant="outline" className="h-12 w-12" {...hold('E', t('nudge.east'))}><ArrowRight size={20} /></Button>
        <span />
        <Button size="icon" variant="outline" className="h-12 w-12" {...hold('S', t('nudge.south'))}><ArrowDown size={20} /></Button>
        <span />
      </div>
      {error && <p className="text-xs text-status-error">{error}</p>}
    </div>
  )
}
