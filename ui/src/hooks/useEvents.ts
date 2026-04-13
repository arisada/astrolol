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
    // `active` prevents a stale closure (e.g. React 18 StrictMode double-mount)
    // from processing events or scheduling reconnects after cleanup.
    let active = true

    function connect() {
      if (!active) return
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws/events`)
      wsRef.current = ws

      ws.onopen = () => {
        if (!active) { ws.close(); return }
        setWsConnected(true)
        // Replay server-side ring buffer so the log survives page reloads
        fetch('/events/history')
          .then((r) => r.json())
          .then((events: AstrolollEvent[]) => { if (active) events.forEach(applyEvent) })
          .catch(console.error)
        // Sync device list
        api.devices.connected().then(setConnectedDevices).catch(console.error)
      }

      ws.onmessage = (msg: MessageEvent<string>) => {
        if (!active) return
        try {
          const event = JSON.parse(msg.data) as AstrolollEvent
          applyEvent(event)
          if (event.type === 'device.connected') {
            api.devices.connected().then(setConnectedDevices).catch(console.error)
          }
        } catch (e) {
          console.error('Failed to parse event', e)
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
        if (active) {
          reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }

      ws.onerror = () => { ws.close() }
    }

    connect()

    return () => {
      active = false
      reconnectTimer.current && clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [applyEvent, setConnectedDevices, setWsConnected])
}
