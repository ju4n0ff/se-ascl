import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { SessionService } from '../core/auth/session.service';
import { MsgDescartado, MsgError, MsgPrediccion } from '../models/ws.model';
import { jwtDePrueba } from '../testing/jwt';
import { CameraService } from './camera.service';
import { N_FLOATS } from './landmarks';
import { Deteccion, MediaPipeService } from './mediapipe.service';
import { SpeechService } from './speech.service';
import { TraductorService } from './traductor.service';
import { WsRecognitionService } from './ws-recognition.service';

const prediccion = (texto: string, aceptada = true): MsgPrediccion =>
  ({ type: 'prediccion', aceptada, aviso: null, prediccion: { texto } }) as MsgPrediccion;

describe('TraductorService', () => {
  const ws = {
    conexion: signal('DESCONECTADO'),
    estado: signal('ESPERANDO'),
    frames: signal(0),
    cierre: signal(null),
    prediccion$: new Subject<MsgPrediccion>(),
    descartado$: new Subject<MsgDescartado>(),
    error$: new Subject<MsgError>(),
    conectar: vi.fn(),
    desconectar: vi.fn(),
    configurar: vi.fn(),
    manualStart: vi.fn(),
    manualStop: vi.fn(),
    reset: vi.fn(),
    mantenerViva: vi.fn(),
    enviarFrame: vi.fn(() => true),
  };
  const camara = { iniciar: vi.fn(), detener: vi.fn(), mensajeDe: vi.fn(() => 'Sin permiso') };
  const motor = {
    estado: signal('listo'),
    cargar: vi.fn(),
    reiniciar: vi.fn(),
    detectar: vi.fn(),
    dibujar: vi.fn(),
  };
  const voz = { anunciar: vi.fn(), hablar: vi.fn(), detener: vi.fn() };
  const deteccion = (): Deteccion => ({
    vector: new Float32Array(N_FLOATS),
    resultados: {},
    manoIzquierda: false,
    manoDerecha: true,
    hombros: true,
  });

  let t: TraductorService;
  let cuadros: (() => void)[];
  let video: HTMLVideoElement;
  let lienzo: HTMLCanvasElement;

  /** Entrega un cuadro de video y deja correr las promesas pendientes. */
  const cuadro = async (ms = 50): Promise<void> => {
    vi.advanceTimersByTime(ms);
    cuadros.shift()?.();
    for (let i = 0; i < 12; i++) await Promise.resolve();
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    sessionStorage.clear();
    cuadros = [];
    ws.conexion.set('CONECTADO');
    ws.estado.set('ESPERANDO');
    camara.iniciar.mockResolvedValue(undefined);
    motor.cargar.mockResolvedValue(undefined);
    motor.detectar.mockImplementation(async () => deteccion());
    video = {
      videoWidth: 640,
      videoHeight: 480,
      requestVideoFrameCallback: (f: () => void) => cuadros.push(f),
    } as unknown as HTMLVideoElement;
    lienzo = { width: 0, height: 0 } as HTMLCanvasElement;
    TestBed.configureTestingModule({
      providers: [
        TraductorService,
        { provide: WsRecognitionService, useValue: ws },
        { provide: CameraService, useValue: camara },
        { provide: MediaPipeService, useValue: motor },
        { provide: SpeechService, useValue: voz },
      ],
    });
    t = TestBed.inject(TraductorService);
  });
  afterEach(() => {
    t.detener();
    vi.useRealTimers();
  });

  it('enciende cámara, socket y detector, y transmite en automático', async () => {
    await t.iniciar(video, lienzo);
    expect(t.fase()).toBe('activo');
    expect(ws.conectar).toHaveBeenCalledWith({ modo: 'auto', guardar: false });
    await cuadro();
    expect(ws.enviarFrame).toHaveBeenCalledOnce();
    expect([lienzo.width, lienzo.height]).toEqual([640, 480]);
    expect(t.manos()).toEqual({ izquierda: false, derecha: true });
  });

  it('procesa a lo sumo ~24 FPS aunque la cámara entregue 60', async () => {
    await t.iniciar(video, lienzo);
    for (let i = 0; i < 120; i++) await cuadro(1000 / 60);
    const porSegundo = motor.detectar.mock.calls.length / 2;
    expect(porSegundo).toBeGreaterThanOrEqual(19);
    expect(porSegundo).toBeLessThanOrEqual(26);
  });

  it('en manual solo transmite mientras graba', async () => {
    t.cambiarModo('manual');
    await t.iniciar(video, lienzo);
    await cuadro();
    expect(ws.enviarFrame).not.toHaveBeenCalled();
    t.alternarGrabacion();
    expect(ws.manualStart).toHaveBeenCalledOnce();
    ws.estado.set('GRABANDO');
    await cuadro();
    expect(ws.enviarFrame).toHaveBeenCalledOnce();
    t.alternarGrabacion();
    expect(ws.manualStop).toHaveBeenCalledOnce();
  });

  it('en manual mantiene viva la conexión antes de los 60 s', async () => {
    t.cambiarModo('manual');
    await t.iniciar(video, lienzo);
    await cuadro(26_000);
    expect(ws.mantenerViva).toHaveBeenCalled();
  });

  it('no envía frames inválidos', async () => {
    motor.detectar.mockImplementation(async () => ({ ...deteccion(), vector: null }));
    await t.iniciar(video, lienzo);
    await cuadro();
    expect(ws.enviarFrame).not.toHaveBeenCalled();
  });

  it('permiso denegado: mensaje claro y todo apagado', async () => {
    camara.iniciar.mockRejectedValue(new DOMException('x', 'NotAllowedError'));
    await t.iniciar(video, lienzo);
    expect(t.fase()).toBe('error');
    expect(t.mensajeError()).toBe('Sin permiso');
    expect(ws.conectar).not.toHaveBeenCalled();
    expect(motor.cargar).not.toHaveBeenCalled();
  });

  it('si el detector no carga, libera cámara y socket', async () => {
    motor.cargar.mockRejectedValue(new Error('red'));
    await t.iniciar(video, lienzo);
    expect(t.fase()).toBe('error');
    expect(camara.detener).toHaveBeenCalled();
    expect(ws.desconectar).toHaveBeenCalled();
  });

  it('detener durante la carga no deja nada encendido', async () => {
    let listo!: () => void;
    motor.cargar.mockReturnValue(new Promise<void>((r) => (listo = r)));
    const inicio = t.iniciar(video, lienzo);
    for (let i = 0; i < 5; i++) await Promise.resolve();
    t.detener();
    listo();
    await inicio;
    expect(t.fase()).toBe('inactivo');
    expect(cuadros.length).toBe(0);
  });

  it('detener corta el bucle', async () => {
    await t.iniciar(video, lienzo);
    t.detener();
    await cuadro();
    expect(ws.enviarFrame).not.toHaveBeenCalled();
    expect(camara.detener).toHaveBeenCalled();
  });

  it('lee y acumula solo lo aceptado, sin repetir la seña consecutiva', () => {
    ws.prediccion$.next(prediccion('hola'));
    ws.prediccion$.next(prediccion('hola'));
    ws.prediccion$.next(prediccion('duda', false));
    ws.prediccion$.next(prediccion('¿donde salida?'));
    expect(t.frase()).toBe('hola ¿donde salida?');
    expect(voz.anunciar).toHaveBeenCalledTimes(3);
    expect(t.resultado()!.prediccion.texto).toBe('¿donde salida?');
  });

  it('avisa el ruido de forma transitoria', () => {
    ws.descartado$.next({ type: 'descartado', motivo: 'ruido', frames: 5, min_frames: 12 });
    expect(t.aviso()).toContain('5 cuadros');
    vi.advanceTimersByTime(5000);
    expect(t.aviso()).toBeNull();
  });

  it('guardar exige sesión y se apaga al cerrarla', async () => {
    t.cambiarGuardar(true);
    expect(t.guardar()).toBe(false);
    const sesion = TestBed.inject(SessionService);
    sesion.iniciar(jwtDePrueba());
    TestBed.tick();
    t.cambiarGuardar(true);
    expect(t.guardar()).toBe(true);
    await t.iniciar(video, lienzo);
    ws.conectar.mockClear();
    sesion.cerrar();
    TestBed.tick();
    expect(t.guardar()).toBe(false);
    expect(ws.conectar).toHaveBeenCalledWith({ modo: 'auto', guardar: false });
  });
});
