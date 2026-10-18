import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StopCircle } from 'lucide-react'
import { api } from '@/api/client'
import { useStore } from '@/store'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { useNudgeRates } from '@/hooks/useNudgeRates'
import { Button } from '@/components/ui/button'
import { ChoiceStepper } from '@/components/ui/choice-stepper'
import { PillGroup } from '@/components/ui/pill-group'
import { ToggleSwitch } from '@/components/ui/toggle-switch'
import { edgeDirections, NORTH_UP, readJoystick, ROTATIONS, type Orientation, type Rotation } from './joystick'
import { JoystickController } from './joystickController'

/** Full speed is reached this far from where the thumb landed, as a share of the circle's width. */
const REACH = 0.42

interface Touch { id: number; x: number; y: number; dx: number; dy: number }

/**
 * A big circle to move the mount with one thumb, without looking: touch anywhere, then push the
 * way the stars should move; the further from where the thumb landed, the faster. Back to the
 * landing point, or lifting, stops. The orientation says how the eyepiece shows the sky.
 */
export function NudgeJoystick({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation('mount')
  const status = useStore((s) => s.mountStatuses[deviceId] ?? null)
  const { rates, rate, settings, saveSettings } = useNudgeRates(deviceId)
  const [orientation, setOrientation] = useLocalStorage<Orientation>('astrolol.joystick.orientation', NORTH_UP)
  const [touch, setTouch] = useState<Touch | null>(null)
  const [error, setError] = useState<string | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const pointerRef = useRef<{ id: number; x: number; y: number } | null>(null)
  const speedRef = useRef<number | null>(null)
  const sentRef = useRef('')

  // The fastest allowed speed is the one picked in the stepper; the slower ones fill the travel below it.
  const top = Math.max(0, rates.findIndex((r) => r.rate === rate))
  const speedCount = top + 1

  const controller = useMemo(() => new JoystickController({
    start: (direction, nudgeRate, durationMs) => api.mount.startMove(deviceId, direction, nudgeRate, durationMs),
    stop: () => api.mount.stopMove(deviceId),
    onError: (e) => setError((e as Error).message),
  }), [deviceId])

  const disabled = !status || status.is_parked
  const slewing = status?.is_slewing ?? false

  const finish = useCallback((abort: boolean) => {
    if (!pointerRef.current) return
    pointerRef.current = null
    speedRef.current = null
    sentRef.current = ''
    setTouch(null)
    if (abort) controller.abort()
    else controller.end()
  }, [controller])

  // A nudge must not outlive the pad being hidden, folded, closed or left; and a phone must not
  // dim its screen under a thumb.
  useEffect(() => {
    const onHide = () => finish(true)
    window.addEventListener('blur', onHide)
    document.addEventListener('visibilitychange', onHide)
    let lock: WakeLockSentinel | null = null
    navigator.wakeLock?.request('screen').then((l) => { lock = l }).catch(() => {})
    return () => {
      window.removeEventListener('blur', onHide)
      document.removeEventListener('visibilitychange', onHide)
      lock?.release().catch(() => {})
      finish(true)
      controller.abort()
    }
  }, [controller, finish])
  useEffect(() => { if (disabled) finish(true) }, [disabled, finish])

  const stopAll = useCallback(async () => {
    finish(true)
    setError(null)
    try {
      if (slewing) await api.mount.stop(deviceId)
      await api.mount.stopMove(deviceId)
    } catch (e) { setError((e as Error).message) }
  }, [deviceId, slewing, finish])

  const follow = useCallback((clientX: number, clientY: number) => {
    const box = boxRef.current
    const pointer = pointerRef.current
    if (!box || !pointer) return
    const rect = box.getBoundingClientRect()
    const dx = clientX - pointer.x
    const dy = clientY - pointer.y
    setTouch({ id: pointer.id, x: pointer.x - rect.left, y: pointer.y - rect.top, dx, dy })
    const reading = readJoystick(dx, dy, rect.width * REACH, orientation, speedCount, speedRef.current)
    if (reading.speed !== speedRef.current) navigator.vibrate?.(8)   // a tick per speed step, where supported
    speedRef.current = reading.speed
    const moves = reading.speed === null
      ? []
      : reading.directions.map((direction) => ({ direction, rate: rates[reading.speed as number].rate }))
    const key = moves.map((m) => `${m.direction}${m.rate}`).join()
    if (key !== sentRef.current) {
      sentRef.current = key
      controller.update(moves)
    }
  }, [controller, orientation, rates, speedCount])

  const edges = edgeDirections(orientation)
  const label = (d: keyof typeof edges) => t(`nudge.initial.${edges[d]}`)
  const dotPos = touch ? { left: `${touch.x + touch.dx}px`, top: `${touch.y + touch.dy}px` } : null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PillGroup
          options={ROTATIONS}
          value={orientation.rotation}
          onChange={(rotation: Rotation) => setOrientation({ ...orientation, rotation })}
          formatLabel={(r) => `${r}°`}
          label={t('joystick.rotation')}
        />
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <ToggleSwitch
            checked={orientation.mirror}
            onChange={() => setOrientation({ ...orientation, mirror: !orientation.mirror })}
            label={t('joystick.mirror')}
          />
          {t('joystick.mirror')}
        </label>
      </div>

      <div
        ref={boxRef}
        className={`relative mx-auto aspect-square select-none rounded-full border border-surface-border bg-surface
          ${disabled ? 'opacity-40' : ''}`}
        style={{ width: 'min(100%, 62vh)', touchAction: 'none' }}
        onContextMenu={(e) => e.preventDefault()}
        onPointerDown={(e) => {
          if (disabled || pointerRef.current || e.button !== 0) return   // one thumb at a time
          e.currentTarget.setPointerCapture(e.pointerId)
          pointerRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY }
          setError(null)
          follow(e.clientX, e.clientY)
        }}
        onPointerMove={(e) => { if (pointerRef.current?.id === e.pointerId) follow(e.clientX, e.clientY) }}
        onPointerUp={(e) => { if (pointerRef.current?.id === e.pointerId) finish(false) }}
        onPointerCancel={(e) => { if (pointerRef.current?.id === e.pointerId) finish(true) }}
        onLostPointerCapture={(e) => { if (pointerRef.current?.id === e.pointerId) finish(false) }}
      >
        <span className="pointer-events-none absolute left-1/2 top-2 -translate-x-1/2 font-mono text-sm text-slate-400">{label('top')}</span>
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-sm text-slate-400">{label('right')}</span>
        <span className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 font-mono text-sm text-slate-400">{label('bottom')}</span>
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 font-mono text-sm text-slate-400">{label('left')}</span>
        {touch && dotPos && (
          <>
            <span
              className="pointer-events-none absolute h-10 w-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-600"
              style={{ left: `${touch.x}px`, top: `${touch.y}px` }}
            />
            <span
              className="pointer-events-none absolute h-8 w-8 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/60"
              style={dotPos}
            />
          </>
        )}
        {!touch && (
          <span className="pointer-events-none absolute inset-0 flex items-center justify-center px-12 text-center text-xs text-slate-500">
            {disabled ? t('joystick.unavailable') : t('joystick.hint')}
          </span>
        )}
      </div>

      <div className="flex items-end justify-between gap-3">
        <ChoiceStepper
          large
          choices={rates.map((r) => ({ value: r.rate, label: r.label, title: r.title }))}
          value={rate}
          onChange={(next) => saveSettings({ ...settings, nudge_rate: next })}
          decTitle={t('nudge.slower')}
          incTitle={t('nudge.faster')}
        />
        <Button size="icon" variant="danger" className="h-12 w-12" disabled={!status}
          onClick={stopAll} title={t('nudge.stopTitle')} aria-label={t('nudge.stopTitle')}>
          <StopCircle size={20} />
        </Button>
      </div>
      {error && <p className="text-xs text-status-error">{error}</p>}
    </div>
  )
}
