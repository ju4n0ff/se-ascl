import { ResultadoReconocimiento } from './recognition.model';

/** Contrato de `WS /ws/recognize` (backend/app/routes/ws.py). */
export type ModoCaptura = 'auto' | 'manual';
export type EstadoSegmentador = 'ESPERANDO' | 'GRABANDO';

export interface MsgEstado {
  type: 'estado';
  estado: EstadoSegmentador;
  modo: ModoCaptura;
  frames_acumulados: number;
}

export interface MsgPrediccion extends ResultadoReconocimiento {
  type: 'prediccion';
  origen: ModoCaptura;
  aviso: 'secuencia_corta' | 'tope_manual' | null;
}

export interface MsgDescartado {
  type: 'descartado';
  motivo: string;
  frames: number;
  min_frames: number;
}

export interface MsgAuth {
  type: 'auth';
  ok: boolean;
}

export interface MsgError {
  type: 'error';
  codigo: 'auth_invalida' | 'mensaje_invalido' | 'rate_limit' | 'inferencia';
  detalle: string;
}

export type MensajeServidor = MsgEstado | MsgPrediccion | MsgDescartado | MsgAuth | MsgError;

export interface MsgConfig {
  type: 'config';
  modo?: ModoCaptura;
  umbral?: number;
  top_k?: number;
  save_history?: boolean;
}

export type ComandoCliente =
  MsgConfig | { type: 'auth'; token: string } | { type: 'manual_start' | 'manual_stop' | 'reset' };

/** Estado de la conexión vista por la interfaz. */
export type EstadoConexion = 'DESCONECTADO' | 'CONECTANDO' | 'CONECTADO';

export interface CierreConexion {
  codigo: number;
  mensaje: string;
}
