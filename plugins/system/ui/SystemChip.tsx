import { useEffect, useState } from 'react'
import { Chip } from '@/components/ui/badge'
import type { NetworkMode, NetworkStatus, SystemStatus } from '@/api/types'
import * as api from './api'

interface SystemChipState {
  mode: NetworkMode
  ssid: string | null
  hotspot_ssid: string | null
  ip: string | null
  temperature: number | null
}

export function SystemChip() {
  const [state, setState] = useState<SystemChipState | null>(null)

  const load = async () => {
    try {
      const [net, sys]: [NetworkStatus, SystemStatus] = await Promise.all([
        api.getNetworkStatus(),
        api.getSystemStatus(),
      ])
      setState({
        mode: net.mode,
        ssid: net.ssid,
        hotspot_ssid: net.hotspot_ssid,
        ip: net.ip_address ?? net.hotspot_ip,
        temperature: sys.temperature_celsius,
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

  // Hotspot mode — most visible: device is sharing its WiFi
  if (state.mode === 'hotspot') {
    const ssid = state.hotspot_ssid ?? 'Hotspot'
    const suffix = state.ip ? ` · ${state.ip}` : ''
    return <Chip label="AP" status={`${ssid}${suffix}`} variant="blue" pulse />
  }

  // WiFi connected — show SSID or IP
  if (state.mode === 'wifi' && (state.ssid || state.ip)) {
    const tempSuffix = state.temperature !== null && state.temperature >= 70
      ? ` · ${state.temperature.toFixed(0)}°C`
      : ''
    const label = state.ssid ?? state.ip ?? 'Wi-Fi'
    return <Chip label="Wi-Fi" status={`${label}${tempSuffix}`} variant="green" />
  }

  // Temperature warning even when offline
  if (state.temperature !== null && state.temperature >= 80) {
    return <Chip label="Temp" status={`${state.temperature.toFixed(0)}°C`} variant="red" pulse />
  }

  // Disconnected — only show if nmcli is available (meaning we're on a Pi)
  if (state.mode === 'disconnected') {
    return <Chip label="Wi-Fi" status="Offline" variant="slate" />
  }

  return null
}
