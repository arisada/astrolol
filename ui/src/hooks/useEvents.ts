import { useEffect, useRef } from 'react'
import type { AstrolollEvent } from '@/api/types'
import { useStore } from '@/store'
import { api } from '@/api/client'
import { controlMessage, mustReconnect, STALE_ON_WAKE_MS } from './ws-health'

const RECONNECT_DELAY_MS = 3000
const WATCHDOG_INTERVAL_MS = 5000

export function useEvents() {
  const applyEvent = useStore((s) => s.applyEvent)
  const setWsConnected = useStore((s) => s.setWsConnected)
  const setConnectedDevices = useStore((s) => s.setConnectedDevices)
  const setPluginInfos = useStore((s) => s.setPluginInfos)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // `active` prevents a stale closure (e.g. React 18 StrictMode double-mount)
    // from processing events or scheduling reconnects after cleanup.
    let active = true
    let lastMessageAt = Date.now()

    // Replace a socket that stopped talking without closing. Its handlers are detached first:
    // a dead connection can take minutes to report its close.
    function replace(ws: WebSocket | null) {
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
        try { ws.close() } catch { /* already gone */ }
      }
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      setWsConnected(false)
      connect()
    }

    function connect() {
      if (!active) return
      lastMessageAt = Date.now()
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
        // Re-fetch plugin list — enablement may have changed since we last connected
        // (backend restart, or another tab toggling a plugin)
        api.plugins.list().then(setPluginInfos).catch(console.error)
      }

      ws.onmessage = (msg: MessageEvent<string>) => {
        if (!active) return
        lastMessageAt = Date.now()
        try {
          const event = JSON.parse(msg.data) as AstrolollEvent
          // The server dropped events this client was too slow to read: start over.
          if (controlMessage(event.type) === 'ws.resync') { replace(ws); return }
          if (controlMessage(event.type)) return
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

    const watchdog = setInterval(() => {
      const ws = wsRef.current
      // A socket still connecting is given the same time as a silent one.
      if (mustReconnect(ws?.readyState, lastMessageAt, Date.now())) replace(ws)
    }, WATCHDOG_INTERVAL_MS)

    // Timers are frozen while the tab is in the background, so check the moment it returns.
    const wake = () => {
      if (document.visibilityState === 'hidden') return
      const ws = wsRef.current
      if (mustReconnect(ws?.readyState, lastMessageAt, Date.now(), STALE_ON_WAKE_MS)) replace(ws)
    }
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('online', wake)
    window.addEventListener('pageshow', wake)

    return () => {
      active = false
      clearInterval(watchdog)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('online', wake)
      window.removeEventListener('pageshow', wake)
      reconnectTimer.current && clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [applyEvent, setConnectedDevices, setPluginInfos, setWsConnected])
}
