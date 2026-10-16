import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import type { DeviceProperty } from '@/api/types'
import { useStore } from '@/store'
import { useMountSettings, DEFAULT_NUDGE_RATE } from '@/hooks/useMountSettings'
import { Button } from '@/components/ui/button'
import { ChoiceStepper } from '@/components/ui/choice-stepper'

/** Nudge speeds in × sidereal, slow to fast, for mounts that do not list their own. */
const NUDGE_SPEEDS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 800]

interface Rate { label: string; title?: string; rate: string }

/** Rate options from a TELESCOPE_SLEW_RATE switch property. */
const ratesFromProperty = (prop: DeviceProperty): Rate[] =>
  prop.widgets.map((w) => ({ label: String(w.label || w.name), rate: String(w.name) }))

/**
 * Speed stepper and a cross to move a mount by hand: hold a direction to move, the red button in
 * the middle stops everything. Used on the Mount page and in the dock.
 */
export function NudgePad({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation('mount')
  const status = useStore((s) => s.mountStatuses[deviceId] ?? null)
  const [settings, saveSettings] = useMountSettings(deviceId)
  const [slewRateProp, setSlewRateProp] = useState<DeviceProperty | null>(null)
  const [error, setError] = useState<string | null>(null)
  const movingRef = useRef(false)

  useEffect(() => {
    api.devices.properties(deviceId)
      .then((props) => setSlewRateProp(props.find((p) => p.name === 'TELESCOPE_SLEW_RATE') ?? null))
      .catch(() => setSlewRateProp(null))
  }, [deviceId])

  // The driver's own list when it has one (INDI), else plain multiples of the sidereal rate.
  const rates = useMemo<Rate[]>(
    () => slewRateProp
      ? ratesFromProperty(slewRateProp)
      : NUDGE_SPEEDS.map((n) => ({ label: t('nudge.speedX', { n }), title: t('nudge.speedXTitle', { n }), rate: `${n}x` })),
    [slewRateProp, t],
  )
  // The saved speed; a driver list that does not contain it starts at its second-slowest entry.
  const rate = rates.some((r) => r.rate === settings.nudge_rate)
    ? settings.nudge_rate
    : rates[Math.min(1, rates.length - 1)]?.rate ?? DEFAULT_NUDGE_RATE

  const act = useCallback(async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message) }
  }, [])

  const start = useCallback(async (direction: string) => {
    if (movingRef.current) return
    movingRef.current = true
    await act(() => api.mount.startMove(deviceId, direction, rate))
  }, [deviceId, rate, act])

  const release = useCallback(async () => {
    if (!movingRef.current) return
    movingRef.current = false
    await act(() => api.mount.stopMove(deviceId))
  }, [deviceId, act])

  // Stops whatever nudge is running, even when the page lost track of it (a lost touch, a reload).
  const stopAll = useCallback(async () => {
    movingRef.current = false
    await act(() => api.mount.stopMove(deviceId))
  }, [deviceId, act])

  // A nudge must not outlive the pad being hidden, folded, closed or left.
  useEffect(() => {
    const onHide = () => { void release() }
    window.addEventListener('blur', onHide)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.removeEventListener('blur', onHide)
      document.removeEventListener('visibilitychange', onHide)
    }
  }, [release])
  useEffect(() => () => {
    if (movingRef.current) { movingRef.current = false; api.mount.stopMove(deviceId).catch(() => {}) }
  }, [deviceId])

  const hold = (dir: string, title: string) => ({
    onMouseDown: () => start(dir),
    onMouseUp: release,
    onMouseLeave: release,
    onTouchStart: (e: React.TouchEvent) => { e.preventDefault(); void start(dir) },
    onTouchEnd: release,
    onTouchCancel: release,
    onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
    disabled: !status || status.is_parked,
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
