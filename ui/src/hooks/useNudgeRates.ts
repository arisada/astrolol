import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/client'
import type { DeviceProperty, MountDeviceSettings } from '@/api/types'
import { DEFAULT_NUDGE_RATE, useMountSettings } from './useMountSettings'

/** Nudge speeds in × sidereal, slow to fast, for mounts that do not list their own. */
const NUDGE_SPEEDS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 800]

export interface NudgeRate { label: string; title?: string; rate: string }

/** Rate options from a TELESCOPE_SLEW_RATE switch property. */
const ratesFromProperty = (prop: DeviceProperty): NudgeRate[] =>
  prop.widgets.map((w) => ({ label: String(w.label || w.name), rate: String(w.name) }))

/**
 * The speeds a mount can be nudged at, slowest first (the driver's own list when it has one, else
 * multiples of the sidereal rate), and the one saved for it.
 */
export function useNudgeRates(deviceId: string): {
  rates: NudgeRate[]
  rate: string
  settings: MountDeviceSettings
  saveSettings: (next: MountDeviceSettings) => void
} {
  const { t } = useTranslation('mount')
  const [settings, saveSettings] = useMountSettings(deviceId)
  const [slewRateProp, setSlewRateProp] = useState<DeviceProperty | null>(null)

  useEffect(() => {
    api.devices.properties(deviceId)
      .then((props) => setSlewRateProp(props.find((p) => p.name === 'TELESCOPE_SLEW_RATE') ?? null))
      .catch(() => setSlewRateProp(null))
  }, [deviceId])

  const rates = useMemo<NudgeRate[]>(
    () => slewRateProp
      ? ratesFromProperty(slewRateProp)
      : NUDGE_SPEEDS.map((n) => ({ label: t('nudge.speedX', { n }), title: t('nudge.speedXTitle', { n }), rate: `${n}x` })),
    [slewRateProp, t],
  )
  // The saved speed; a driver list that does not contain it starts at its second-slowest entry.
  const rate = rates.some((r) => r.rate === settings.nudge_rate)
    ? settings.nudge_rate
    : rates[Math.min(1, rates.length - 1)]?.rate ?? DEFAULT_NUDGE_RATE
  return { rates, rate, settings, saveSettings }
}
