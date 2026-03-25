import { useEffect, useRef } from 'react'
import type { AstrolollEvent } from '@/api/types'
import { useStore } from '@/store'
import { api } from '@/api/client'

const RECONNECT_DELAY_MS = 3000

export function useEvents() {
  const applyEvent = useStore((s) => s.applyEvent)
  const setWsConnected = useStore((s) => s.setWsConnected)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws/events`)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        // Sync device list on reconnect
        api.devices.connected().then(setConnectedDevices).catch(console.error)
      }

      ws.onmessage = (msg: MessageEvent<string>) => {
        try {
          const event = JSON.parse(msg.data) as AstrolollEvent
          applyEvent(event)
          // Re-fetch connected devices when something connects
          if (event.type === 'device.connected') {
            api.devices.connected().then(setConnectedDevices).catch(console.error)
          }
        } catch (e) {
          console.error('Failed to parse event', e)
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      reconnectTimer.current && clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [applyEvent, setConnectedDevices, setWsConnected])
}
