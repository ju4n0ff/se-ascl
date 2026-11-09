import { useCallback, useEffect, useRef, useState } from 'react';

export interface BackendResult {
  predicted_label: string;
  spanish_text: string;
  confidence: number;
  mode: string;
  note?: string;
  error?: string;
}

export interface HandLandmarkPoint {
  x: number;
  y: number;
  z: number;
}

export interface HandPayload {
  landmarks: HandLandmarkPoint[];
  handedness: string;
}

interface UseBackendSocketOptions {
  url?: string;
  enabled?: boolean;
  onResult?: (result: BackendResult) => void;
}

interface UseBackendSocketReturn {
  isConnected: boolean;
  error: string | null;
  sendRecognition: (mode: 'static' | 'dynamic', hands: HandPayload[]) => void;
  reconnect: () => void;
}

const DEFAULT_URL = 'ws://localhost:8000/ws/recognize';

export function useBackendSocket(options: UseBackendSocketOptions = {}): UseBackendSocketReturn {
  const { url = DEFAULT_URL, enabled = true, onResult } = options;
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onResultRef = useRef(onResult);
  const reconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;

  onResultRef.current = onResult;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttempts.current = 0;
        console.log('[WS] Connected to backend');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.error) {
            setError(data.error);
            return;
          }
          onResultRef.current?.(data);
        } catch {
          setError('Respuesta inválida del servidor');
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
          const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 10000);
          reconnectAttempts.current += 1;
          reconnectTimeoutRef.current = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        setError('Error de conexión con el servidor');
      };

      wsRef.current = ws;
    } catch {
      setError('No se pudo conectar al servidor');
    }
  }, [url]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const sendRecognition = useCallback(
    (mode: 'static' | 'dynamic', hands: HandPayload[]) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      wsRef.current.send(JSON.stringify({ mode, hands }));
    },
    []
  );

  const reconnect = useCallback(() => {
    disconnect();
    reconnectAttempts.current = 0;
    connect();
  }, [connect, disconnect]);

  useEffect(() => {
    if (enabled) {
      connect();
    }
    return disconnect;
  }, [enabled, connect, disconnect]);

  return { isConnected, error, sendRecognition, reconnect };
}
