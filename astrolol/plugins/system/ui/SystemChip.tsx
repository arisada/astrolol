import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Chip } from '@/components/ui/badge'
import type { NetworkMode, NetworkStatus, SystemStatus } from '@/api/types'
import * as api from './api'

interface SystemChipState {
  mode: NetworkMode
  ssid: string | null
  hotspot_ssid: string | null
  ip: string | null
  temperature: number | null
  underpowered: boolean
}

export function SystemChip() {
  const { t } = useTranslation('system')
  const [state, setState] = useState<SystemChipState | null>(null)

  const load = async () => {
    try {
      const [net, sys]: [NetworkStatus, SystemStatus] = await Promise.all([
        api.getNetworkStatus(),
        api.getSystemStatus(),
      ])
      let underpowered = false
      try {
        underpowered = (await api.getThrottleStatus()).underpowered
      } catch {
        // ignore — best-effort
      }
      setState({
        mode: net.mode,
        ssid: net.ssid,
        hotspot_ssid: net.hotspot_ssid,
        ip: net.ip_address ?? net.hotspot_ip,
        temperature: sys.temperature_celsius,
        underpowered,
      })
    } catch {
      // ignore — no network or backend down
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [])

  if (!state) return null

  // Underpowered — most urgent: overrides network/temperature display
  if (state.underpowered) {
    return <Chip label={t('chip.power')} status={t('chip.underpowered')} variant="red" pulse />
  }

  // Hotspot mode — most visible: device is sharing its WiFi
  if (state.mode === 'hotspot') {
    const ssid = state.hotspot_ssid ?? t('chip.hotspot')
    const suffix = state.ip ? ` · ${state.ip}` : ''
    return <Chip label={t('chip.ap')} status={`${ssid}${suffix}`} variant="blue" pulse />
  }

  // WiFi connected — show SSID or IP
  if (state.mode === 'wifi' && (state.ssid || state.ip)) {
    const tempSuffix = state.temperature !== null && state.temperature >= 70
      ? ` · ${state.temperature.toFixed(0)}°C`
      : ''
    const label = state.ssid ?? state.ip ?? t('chip.wifi')
    return <Chip label={t('chip.wifi')} status={`${label}${tempSuffix}`} variant="green" />
  }

  // Temperature warning even when offline
  if (state.temperature !== null && state.temperature >= 80) {
    return <Chip label={t('chip.temp')} status={`${state.temperature.toFixed(0)}°C`} variant="red" pulse />
  }

  // Disconnected — only show if nmcli is available (meaning we're on a Pi)
  if (state.mode === 'disconnected') {
    return <Chip label={t('chip.wifi')} status={t('chip.offline')} variant="slate" />
  }

  return null
}
