import { Injectable, InjectionToken, OnDestroy, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';

import { API_CONFIG } from '../core/config/api.config';
import { SessionService } from '../core/auth/session.service';
import {
  CierreConexion,
  ComandoCliente,
  EstadoConexion,
  EstadoSegmentador,
  MensajeServidor,
  ModoCaptura,
  MsgDescartado,
  MsgError,
  MsgPrediccion,
} from '../models/ws.model';
import { BYTES_FRAME, VectorFrame } from './landmarks';

export const FABRICA_WS = new InjectionToken<(url: string) => WebSocket>('FABRICA_WS', {
  providedIn: 'root',
  factory: () => (url: string) => new WebSocket(url),
});

export interface PreferenciasWs {
  modo: ModoCaptura;
  guardar: boolean;
}

export const UMBRAL = 0.55;
export const TOP_K = 3;
/** El backend corta sobre 35 mensajes/s; se deja margen para los comandos. */
export const MAX_FRAMES_POR_SEGUNDO = 28;
const ESPERA_AUTH_MS = 10_000;
const ESPERAS_RECONEXION_MS = [1000, 2000, 4000];
/** Solo una conexión estable recupera el cupo de reintentos (evita bucles abrir-cerrar). */
const CONEXION_ESTABLE_MS = 10_000;
/** Si la red no da abasto se descartan frames en vez de acumular retraso. */
const MAX_BYTES_PENDIENTES = BYTES_FRAME * 8;

const CIERRE_INACTIVIDAD = 1001;
const MENSAJES_CIERRE: Record<number, string> = {
  [CIERRE_INACTIVIDAD]: 'La conexión se cerró por inactividad.',
  1008: 'El servidor cerró la conexión por exceso de uso. Cierra otras pestañas de SeñaCL y reconecta.',
  1009: 'El servidor rechazó un mensaje demasiado grande. Recarga la página.',
  1011: 'El traductor no está disponible en el servidor en este momento.',
};
const MSG_SIN_CONEXION =
  'No pudimos conectar con el traductor. El servidor puede estar iniciando: intenta en un minuto.';

const TIPOS = new Set(['estado', 'prediccion', 'descartado', 'auth', 'error']);

function parsear(datos: unknown): MensajeServidor | null {
  if (typeof datos !== 'string') return null;
  try {
    const msg: unknown = JSON.parse(datos);
    const tipo = (msg as { type?: unknown } | null)?.type;
    return typeof tipo === 'string' && TIPOS.has(tipo) ? (msg as MensajeServidor) : null;
  } catch {
    return null;
  }
}

/**
 * Cliente de `WS /ws/recognize`. El JWT viaja como primer mensaje, nunca en la URL; los
 * frames van en binario (6516 bytes). Se provee por vista: al salir se cierra el socket.
 */
@Injectable()
export class WsRecognitionService implements OnDestroy {
  private readonly config = inject(API_CONFIG);
  private readonly sesion = inject(SessionService);
  private readonly crear = inject(FABRICA_WS);

  private readonly _conexion = signal<EstadoConexion>('DESCONECTADO');
  private readonly _estado = signal<EstadoSegmentador>('ESPERANDO');
  private readonly _frames = signal(0);
  private readonly _autenticado = signal(false);
  private readonly _cierre = signal<CierreConexion | null>(null);

  readonly conexion = this._conexion.asReadonly();
  readonly estado = this._estado.asReadonly();
  readonly frames = this._frames.asReadonly();
  /** El servidor confirmó el JWT en esta conexión. */
  readonly autenticado = this._autenticado.asReadonly();
  /** Motivo del último cierre no pedido por el usuario. */
  readonly cierre = this._cierre.asReadonly();

  readonly prediccion$ = new Subject<MsgPrediccion>();
  readonly descartado$ = new Subject<MsgDescartado>();
  readonly error$ = new Subject<MsgError>();

  private socket: WebSocket | null = null;
  private prefs: PreferenciasWs = { modo: 'auto', guardar: false };
  private listo = false;
  private intentos = 0;
  private abiertoEn = 0;
  private envios: number[] = [];
  private temporizadorAuth: ReturnType<typeof setTimeout> | undefined;
  private temporizadorReconexion: ReturnType<typeof setTimeout> | undefined;

  /** Conexión pedida por el usuario: recupera los reintentos automáticos. */
  conectar(prefs: PreferenciasWs = this.prefs): void {
    this.prefs = { ...prefs };
    this.intentos = 0;
    this.abrir();
  }

  desconectar(): void {
    this.soltar();
    this._cierre.set(null);
    this._conexion.set('DESCONECTADO');
  }

  ngOnDestroy(): void {
    this.desconectar();
  }

  configurar(cambios: Partial<PreferenciasWs>): void {
    this.prefs = { ...this.prefs, ...cambios };
    if (this.listo) this.enviarConfig();
  }

  manualStart(): void {
    if (this.listo) this.comando({ type: 'manual_start' });
  }

  manualStop(): void {
    if (this.listo) this.comando({ type: 'manual_stop' });
  }

  reset(): void {
    if (this.listo) this.comando({ type: 'reset' });
  }

  /** Evita el cierre por inactividad mientras la cámara sigue activa sin enviar frames. */
  mantenerViva(): void {
    if (this.listo) this.comando({ type: 'config' });
  }

  /** Devuelve false si el frame se omitió (sin conexión, tope de frecuencia o red lenta). */
  enviarFrame(vector: VectorFrame): boolean {
    const socket = this.socket;
    if (!this.listo || !socket || vector.byteLength !== BYTES_FRAME) return false;
    if (socket.bufferedAmount > MAX_BYTES_PENDIENTES) return false;
    const ahora = performance.now();
    this.envios = this.envios.filter((t) => ahora - t < 1000);
    if (this.envios.length >= MAX_FRAMES_POR_SEGUNDO) return false;
    this.envios.push(ahora);
    socket.send(vector.buffer);
    return true;
  }

  // ------------------------------------------------------------------ interno
  private abrir(): void {
    this.soltar();
    this._cierre.set(null);
    this._conexion.set('CONECTANDO');
    if (!this.config.configurado) {
      this.fallar(0, 'La dirección del servidor aún no está configurada.');
      return;
    }
    let socket: WebSocket;
    try {
      socket = this.crear(this.config.wsUrl);
    } catch {
      this.fallar(0, MSG_SIN_CONEXION);
      return;
    }
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    this.abiertoEn = 0;
    socket.onopen = () => this.alAbrir(socket);
    socket.onmessage = (ev: MessageEvent<unknown>) => this.alRecibir(socket, ev.data);
    socket.onclose = (ev: CloseEvent) => this.alCerrar(socket, ev.code);
  }

  private alAbrir(socket: WebSocket): void {
    if (socket !== this.socket) return;
    this.abiertoEn = performance.now();
    const token = this.sesion.token();
    if (token === null) {
      this.quedarListo();
      return;
    }
    this.comando({ type: 'auth', token });
    this.temporizadorAuth = setTimeout(() => this.quedarListo(), ESPERA_AUTH_MS);
  }

  private alRecibir(socket: WebSocket, datos: unknown): void {
    if (socket !== this.socket) return;
    const msg = parsear(datos);
    if (!msg) return;
    switch (msg.type) {
      case 'estado':
        this._estado.set(msg.estado);
        this._frames.set(msg.frames_acumulados);
        break;
      case 'auth':
        this._autenticado.set(msg.ok);
        if (this.listo)
          this.enviarConfig(); // la confirmación llegó después de la espera
        else this.quedarListo();
        break;
      case 'prediccion':
        this.prediccion$.next(msg);
        break;
      case 'descartado':
        this.descartado$.next(msg);
        break;
      case 'error':
        if (msg.codigo === 'auth_invalida' && !this.listo) this.quedarListo();
        this.error$.next(msg);
        break;
    }
  }

  private alCerrar(socket: WebSocket, codigo: number): void {
    if (socket !== this.socket) return;
    const estable = this.abiertoEn > 0 && performance.now() - this.abiertoEn >= CONEXION_ESTABLE_MS;
    this.soltar();

    const conocido = MENSAJES_CIERRE[codigo];
    if (conocido) {
      this.fallar(codigo, conocido); // decisión del servidor: solo reconecta el usuario
      return;
    }
    // 1006 y similares: corte de red, o rechazo del handshake (Origin o tope por IP).
    if (estable) this.intentos = 0;
    if (this.intentos < ESPERAS_RECONEXION_MS.length) {
      this._conexion.set('CONECTANDO');
      this.temporizadorReconexion = setTimeout(
        () => this.abrir(),
        ESPERAS_RECONEXION_MS[this.intentos++],
      );
      return;
    }
    this.fallar(codigo, MSG_SIN_CONEXION);
  }

  private quedarListo(): void {
    clearTimeout(this.temporizadorAuth);
    this.listo = true;
    this._conexion.set('CONECTADO');
    this.enviarConfig();
  }

  private enviarConfig(): void {
    this.comando({
      type: 'config',
      modo: this.prefs.modo,
      umbral: UMBRAL,
      top_k: TOP_K,
      // Nunca se pide guardar sin que el servidor haya confirmado la identidad.
      save_history: this.prefs.guardar && this._autenticado(),
    });
  }

  private comando(msg: ComandoCliente): void {
    this.socket?.send(JSON.stringify(msg));
  }

  private fallar(codigo: number, mensaje: string): void {
    this._cierre.set({ codigo, mensaje });
    this._conexion.set('DESCONECTADO');
  }

  private soltar(): void {
    clearTimeout(this.temporizadorAuth);
    clearTimeout(this.temporizadorReconexion);
    const socket = this.socket;
    this.socket = null;
    this.listo = false;
    this.envios = [];
    this._autenticado.set(false);
    this._estado.set('ESPERANDO');
    this._frames.set(0);
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = null;
      socket.close(1000);
    }
  }
}
