import { useEffect, useRef, useState, useCallback } from 'react'

const WS_URL = import.meta.env.PROD
  ? `wss://${window.location.host}/ws`
  : 'ws://localhost:8000/ws'

export function useWebSocket(onMessage) {
  const ws = useRef(null)
  const [connected, setConnected] = useState(false)
  const reconnectTimer = useRef(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return
    ws.current = new WebSocket(WS_URL)

    ws.current.onopen = () => {
      setConnected(true)
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }

    ws.current.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        onMessageRef.current(msg)
      } catch {}
    }

    ws.current.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.current.onerror = () => {
      ws.current?.close()
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [connect])

  return { connected }
}
