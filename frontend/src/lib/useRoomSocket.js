import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";

/**
 * useRoomSocket — keeps a websocket open and aggregates server events into a single state.
 * Returns { state, lastEvent, sendPing }.
 */
export function useRoomSocket(code, playerId, onEvent) {
  const [state, setState] = useState(null);
  const [lastEvent, setLastEvent] = useState(null);
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  useEffect(() => {
    if (!code) return undefined;
    let alive = true;

    const connect = () => {
      const ws = new WebSocket(wsUrl(code, playerId));
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "state") setState(msg.payload);
          setLastEvent(msg);
          if (onEvent) onEvent(msg);
        } catch (e) {
          /* noop */
        }
      };
      ws.onclose = () => {
        if (!alive) return;
        // try to reconnect
        reconnectRef.current = setTimeout(connect, 1200);
      };
      ws.onerror = () => {
        try { ws.close(); } catch (e) { /* ignore */ }
      };
    };
    connect();

    return () => {
      alive = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) {
        try { wsRef.current.close(); } catch (e) { /* ignore */ }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, playerId]);

  return { state, lastEvent };
}
