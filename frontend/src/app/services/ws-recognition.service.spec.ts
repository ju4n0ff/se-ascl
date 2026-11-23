import { TestBed } from '@angular/core/testing';

import { API_CONFIG } from '../core/config/api.config';
import { SessionService } from '../core/auth/session.service';
import { jwtDePrueba } from '../testing/jwt';
import { MsgPrediccion } from '../models/ws.model';
import { N_FLOATS } from './landmarks';
import { FABRICA_WS, MAX_FRAMES_POR_SEGUNDO, WsRecognitionService } from './ws-recognition.service';

class WsFalso {
  static todos: WsFalso[] = [];
  binaryType = '';
  bufferedAmount = 0;
  enviados: (string | ArrayBuffer)[] = [];
  cierres: (number | undefined)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    WsFalso.todos.push(this);
  }
  send(d: string | ArrayBuffer): void {
    this.enviados.push(d);
  }
  close(c?: number): void {
    this.cierres.push(c);
  }
  abrir(): void {
    this.onopen?.();
  }
  recibir(msg: unknown): void {
    this.onmessage?.({ data: typeof msg === 'string' ? msg : JSON.stringify(msg) });
  }
  cortar(code: number): void {
    this.onclose?.({ code });
  }
  get json(): Record<string, unknown>[] {
    return this.enviados
      .filter((e): e is string => typeof e === 'string')
      .map((e) => JSON.parse(e) as Record<string, unknown>);
  }
  static get actual(): WsFalso {
    return WsFalso.todos.at(-1)!;
  }
}

const URL_WS = 'ws://api.test/ws/recognize';

describe('WsRecognitionService', () => {
  let ws: WsRecognitionService;
  let sesion: SessionService;

  beforeEach(() => {
    vi.useFakeTimers();
    sessionStorage.clear();
    WsFalso.todos = [];
    TestBed.configureTestingModule({
      providers: [
        WsRecognitionService,
        {
          provide: API_CONFIG,
          useValue: { apiUrl: 'http://api.test', wsUrl: URL_WS, configurado: true },
        },
        { provide: FABRICA_WS, useValue: (u: string) => new WsFalso(u) as unknown as WebSocket },
      ],
    });
    ws = TestBed.inject(WsRecognitionService);
    sesion = TestBed.inject(SessionService);
  });
  afterEach(() => {
    ws.desconectar();
    vi.useRealTimers();
  });

  const conectar = (): WsFalso => {
    ws.conectar({ modo: 'auto', guardar: false });
    WsFalso.actual.abrir();
    return WsFalso.actual;
  };

  it('sin sesión configura de inmediato, sin auth ni historial', () => {
    ws.conectar({ modo: 'auto', guardar: true });
    expect(ws.conexion()).toBe('CONECTANDO');
    WsFalso.actual.abrir();
    expect(WsFalso.actual.binaryType).toBe('arraybuffer');
    expect(WsFalso.actual.json).toEqual([
      { type: 'config', modo: 'auto', umbral: 0.55, top_k: 3, save_history: false },
    ]);
    expect(ws.conexion()).toBe('CONECTADO');
  });

  it('con sesión autentica en el primer mensaje y nunca en la URL', () => {
    const token = jwtDePrueba();
    sesion.iniciar(token);
    ws.conectar({ modo: 'manual', guardar: true });
    const s = WsFalso.actual;
    s.abrir();
    expect(s.url).toBe(URL_WS);
    expect(s.url).not.toContain(token);
    expect(s.json).toEqual([{ type: 'auth', token }]);
    expect(ws.conexion()).toBe('CONECTANDO');
    expect(ws.enviarFrame(new Float32Array(N_FLOATS))).toBe(false); // espera a auth
    s.recibir({ type: 'auth', ok: true });
    expect(s.json[1]).toEqual({
      type: 'config',
      modo: 'manual',
      umbral: 0.55,
      top_k: 3,
      save_history: true,
    });
    expect(ws.autenticado()).toBe(true);
  });

  it('si el servidor rechaza el token sigue como anónimo y sin guardar', () => {
    sesion.iniciar(jwtDePrueba());
    const errores: string[] = [];
    ws.error$.subscribe((e) => errores.push(e.codigo));
    ws.conectar({ modo: 'auto', guardar: true });
    WsFalso.actual.abrir();
    WsFalso.actual.recibir({ type: 'error', codigo: 'auth_invalida', detalle: 'x' });
    expect(WsFalso.actual.json[1]).toMatchObject({ type: 'config', save_history: false });
    expect(errores).toEqual(['auth_invalida']);
    expect(ws.autenticado()).toBe(false);
  });

  it('activa el guardado si la confirmación llega después de la espera', () => {
    sesion.iniciar(jwtDePrueba());
    ws.conectar({ modo: 'auto', guardar: true });
    const s = WsFalso.actual;
    s.abrir();
    vi.advanceTimersByTime(10_000);
    expect(s.json[1]).toMatchObject({ type: 'config', save_history: false });
    s.recibir({ type: 'auth', ok: true });
    expect(s.json[2]).toMatchObject({ type: 'config', save_history: true });
  });

  it('envía cada frame como ArrayBuffer de 6516 bytes little-endian', () => {
    const s = conectar();
    const v = new Float32Array(N_FLOATS);
    v[0] = 0.5;
    v[1628] = -1.25;
    expect(ws.enviarFrame(v)).toBe(true);
    const buffer = s.enviados.at(-1) as ArrayBuffer;
    expect(buffer.byteLength).toBe(6516);
    const vista = new DataView(buffer);
    expect(vista.getFloat32(0, true)).toBe(0.5);
    expect(vista.getFloat32(1628 * 4, true)).toBe(-1.25);
  });

  it('rechaza vectores de otro tamaño', () => {
    conectar();
    expect(ws.enviarFrame(new Float32Array(1628))).toBe(false);
  });

  it('nunca supera el tope por segundo', () => {
    conectar();
    let enviados = 0;
    for (let ms = 0; ms < 1000; ms += 10) {
      if (ws.enviarFrame(new Float32Array(N_FLOATS))) enviados++;
      vi.advanceTimersByTime(10);
    }
    expect(enviados).toBe(MAX_FRAMES_POR_SEGUNDO);
    expect(MAX_FRAMES_POR_SEGUNDO).toBeLessThan(35);
    vi.advanceTimersByTime(1000);
    expect(ws.enviarFrame(new Float32Array(N_FLOATS))).toBe(true);
  });

  it('descarta frames si la red no da abasto', () => {
    conectar().bufferedAmount = 6516 * 9;
    expect(ws.enviarFrame(new Float32Array(N_FLOATS))).toBe(false);
  });

  it('emite estado, predicción y descartado tipados', () => {
    const s = conectar();
    const recibidas: MsgPrediccion[] = [];
    const ruido: number[] = [];
    ws.prediccion$.subscribe((p) => recibidas.push(p));
    ws.descartado$.subscribe((d) => ruido.push(d.frames));
    s.recibir({ type: 'estado', estado: 'GRABANDO', modo: 'auto', frames_acumulados: 7 });
    expect([ws.estado(), ws.frames()]).toEqual(['GRABANDO', 7]);
    s.recibir({ type: 'descartado', motivo: 'ruido', frames: 5, min_frames: 12 });
    s.recibir({ type: 'prediccion', aceptada: true, prediccion: { texto: 'hola' } });
    expect(ruido).toEqual([5]);
    expect(recibidas[0].prediccion.texto).toBe('hola');
  });

  it.each(['no json', '[]', 'null', '{"type":"otro"}', '{}'])('ignora el mensaje %s', (crudo) => {
    const s = conectar();
    expect(() => s.recibir(crudo)).not.toThrow();
    expect(ws.conexion()).toBe('CONECTADO');
  });

  it('comandos manuales y reset', () => {
    const s = conectar();
    ws.manualStart();
    ws.manualStop();
    ws.reset();
    expect(s.json.slice(1).map((m) => m['type'])).toEqual(['manual_start', 'manual_stop', 'reset']);
  });

  it.each([1001, 1008, 1009, 1011])('cierre %d: informa y no reconecta solo', (codigo) => {
    conectar().cortar(codigo);
    vi.advanceTimersByTime(120_000);
    expect(WsFalso.todos.length).toBe(1);
    expect(ws.conexion()).toBe('DESCONECTADO');
    expect(ws.cierre()!.codigo).toBe(codigo);
    expect(ws.cierre()!.mensaje.length).toBeGreaterThan(10);
  });

  it('1001 permite reconectar a pedido', () => {
    conectar().cortar(1001);
    ws.conectar();
    expect(ws.cierre()).toBeNull();
    WsFalso.actual.abrir();
    expect(ws.conexion()).toBe('CONECTADO');
  });

  it('corte de red: tres reintentos y se detiene', () => {
    conectar().cortar(1006);
    for (const espera of [1000, 2000, 4000]) {
      expect(ws.conexion()).toBe('CONECTANDO');
      vi.advanceTimersByTime(espera);
      WsFalso.actual.cortar(1006); // handshake rechazado
    }
    vi.advanceTimersByTime(120_000);
    expect(WsFalso.todos.length).toBe(4);
    expect(ws.conexion()).toBe('DESCONECTADO');
    expect(ws.cierre()).not.toBeNull();
  });

  it('abrir y cortar en bucle no recupera reintentos; una conexión estable sí', () => {
    conectar().cortar(1006);
    vi.advanceTimersByTime(1000);
    WsFalso.actual.abrir();
    WsFalso.actual.cortar(1006); // inestable: sigue con la segunda espera
    vi.advanceTimersByTime(1000);
    expect(WsFalso.todos.length).toBe(2);
    vi.advanceTimersByTime(1000);
    expect(WsFalso.todos.length).toBe(3);
    WsFalso.actual.abrir();
    vi.advanceTimersByTime(10_000);
    WsFalso.actual.cortar(1006);
    vi.advanceTimersByTime(1000); // vuelve a la primera espera
    expect(WsFalso.todos.length).toBe(4);
  });

  it('desconectar cancela reintentos y no deja mensajes de error', () => {
    const s = conectar();
    ws.desconectar();
    expect(s.cierres).toEqual([1000]);
    expect([ws.conexion(), ws.cierre()]).toEqual(['DESCONECTADO', null]);
    vi.advanceTimersByTime(60_000);
    expect(WsFalso.todos.length).toBe(1);
  });

  it('un socket antiguo no afecta a la conexión nueva', () => {
    const viejo = conectar();
    const alCerrar = viejo.onclose!;
    ws.conectar();
    WsFalso.actual.abrir();
    alCerrar({ code: 1011 });
    expect(ws.conexion()).toBe('CONECTADO');
  });
});

describe('WsRecognitionService sin URL de Render', () => {
  it('no intenta conectar', () => {
    const crear = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        WsRecognitionService,
        { provide: API_CONFIG, useValue: { apiUrl: '', wsUrl: '', configurado: false } },
        { provide: FABRICA_WS, useValue: crear },
      ],
    });
    const ws = TestBed.inject(WsRecognitionService);
    ws.conectar();
    expect(crear).not.toHaveBeenCalled();
    expect(ws.cierre()!.mensaje).toContain('configurada');
  });
});
