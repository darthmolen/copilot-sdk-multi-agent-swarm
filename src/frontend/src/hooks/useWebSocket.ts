import { useEffect, useRef, useState, useCallback } from 'react';
import type { SwarmEvent } from '../types/swarm';

const WS_BASE = import.meta.env.VITE_WS_URL ?? `ws://${typeof window !== 'undefined' ? window.location.host : 'localhost:5173'}`;
const MAX_RECONNECT_DELAY = 30_000;
const INITIAL_RECONNECT_DELAY = 1_000;

export function useWebSocket(
  swarmId: string | null,
  onEvent: (event: SwarmEvent) => void,
) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(INITIAL_RECONNECT_DELAY);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shouldReconnect = useRef(true);
  const onEventRef = useRef(onEvent);

  // Keep callback ref fresh without triggering reconnects
  onEventRef.current = onEvent;

  const disconnect = useCallback(() => {
    shouldReconnect.current = false;
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    if (!swarmId) return;

    function connect() {
      const url = `${WS_BASE}/ws/${swarmId}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectDelay.current = INITIAL_RECONNECT_DELAY;
      };

      ws.onmessage = (evt) => {
        try {
          const event: SwarmEvent = JSON.parse(evt.data);
          onEventRef.current(event);
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (!shouldReconnect.current) return;
        // Reconnect with exponential backoff
        reconnectTimer.current = setTimeout(() => {
          reconnectDelay.current = Math.min(
            reconnectDelay.current * 2,
            MAX_RECONNECT_DELAY,
          );
          connect();
        }, reconnectDelay.current);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    shouldReconnect.current = true;
    connect();

    return () => {
      disconnect();
    };
  }, [swarmId, disconnect]);

  return { connected, send, disconnect };
}
