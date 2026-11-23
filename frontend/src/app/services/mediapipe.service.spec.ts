import { TestBed } from '@angular/core/testing';
import type { HolisticConfig, Options, Results, ResultsListener } from '@mediapipe/holistic';

import { N_MANO, N_POSE, Punto } from './landmarks';
import {
  CARGADOR_HOLISTIC,
  ConstructorHolistic,
  MediaPipeService,
  OPCIONES_HOLISTIC,
} from './mediapipe.service';

const bloque = (n: number, p: Punto): Punto[] => Array.from({ length: n }, () => ({ ...p }));

class HolisticFalso {
  static ultimo: HolisticFalso;
  static proximo: Partial<Results> = {};
  static fallaInicial = false;
  opciones: Options = {};
  imagenes: unknown[] = [];
  reinicios = 0;
  private oyente: ResultsListener = () => undefined;

  constructor(readonly config: HolisticConfig) {
    HolisticFalso.ultimo = this;
  }
  setOptions(o: Options): void {
    this.opciones = o;
  }
  onResults(l: ResultsListener): void {
    this.oyente = l;
  }
  async initialize(): Promise<void> {
    if (HolisticFalso.fallaInicial) throw new Error('sin red');
  }
  reset(): void {
    this.reinicios++;
  }
  async send({ image }: { image: unknown }): Promise<void> {
    this.imagenes.push(image);
    await this.oyente(HolisticFalso.proximo as Results);
  }
}

const video = (extra: object = {}): HTMLVideoElement =>
  ({ readyState: 4, videoWidth: 1280, videoHeight: 720, ...extra }) as HTMLVideoElement;

describe('MediaPipeService', () => {
  let cargas: number;
  let servicio: MediaPipeService;

  beforeEach(() => {
    cargas = 0;
    HolisticFalso.proximo = {};
    HolisticFalso.fallaInicial = false;
    TestBed.configureTestingModule({
      providers: [
        {
          provide: CARGADOR_HOLISTIC,
          useValue: async () => {
            cargas++;
            return HolisticFalso as unknown as ConstructorHolistic;
          },
        },
      ],
    });
    servicio = TestBed.inject(MediaPipeService);
  });

  it('no descarga nada hasta que se pide', async () => {
    expect(servicio.estado()).toBe('sin-cargar');
    expect(cargas).toBe(0);
    expect(await servicio.detectar(video())).toBeNull();
  });

  it('carga una sola vez con las opciones del entrenamiento', async () => {
    await Promise.all([servicio.cargar(), servicio.cargar()]);
    await servicio.cargar();
    expect(cargas).toBe(1);
    expect(servicio.estado()).toBe('listo');
    expect(HolisticFalso.ultimo.opciones).toEqual(OPCIONES_HOLISTIC);
    expect(OPCIONES_HOLISTIC).toMatchObject({
      modelComplexity: 1,
      refineFaceLandmarks: false,
      selfieMode: false,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    expect(HolisticFalso.ultimo.config.locateFile!('a.wasm')).toBe(
      'mediapipe/holistic-0.5.1675471629/a.wasm',
    );
  });

  it('permite reintentar si la carga falla', async () => {
    HolisticFalso.fallaInicial = true;
    await expect(servicio.cargar()).rejects.toThrow();
    expect(servicio.estado()).toBe('error');
    HolisticFalso.fallaInicial = false;
    await servicio.cargar();
    expect(servicio.estado()).toBe('listo');
  });

  it('procesa el <video> original y aplica y isotrópica con sus dimensiones', async () => {
    await servicio.cargar();
    HolisticFalso.proximo = {
      poseLandmarks: bloque(N_POSE, { x: 0.25, y: 0.5, z: 0.1 }),
      rightHandLandmarks: bloque(N_MANO, { x: 0.75, y: 0.8, z: -0.1 }),
    };
    const v = video();
    const d = (await servicio.detectar(v))!;
    expect(HolisticFalso.ultimo.imagenes).toEqual([v]); // sin canvas intermedio que espeje
    expect(d.vector![1]).toBeCloseTo(0.5 * 0.5625, 6);
    expect(d.vector![1566]).toBeCloseTo(0.75, 6);
    expect(d.vector![1567]).toBeCloseTo(0.8 * 0.5625, 6);
    expect(d.vector!.subarray(99, 1566).every((x) => x === 0)).toBe(true);
    expect(d).toMatchObject({ manoIzquierda: false, manoDerecha: true, hombros: true });
  });

  it('no arrastra resultados del frame anterior', async () => {
    await servicio.cargar();
    HolisticFalso.proximo = { leftHandLandmarks: bloque(N_MANO, { x: 0.5, y: 0.5, z: 0 }) };
    expect((await servicio.detectar(video()))!.manoIzquierda).toBe(true);
    HolisticFalso.proximo = {};
    const d = (await servicio.detectar(video()))!;
    expect(d.manoIzquierda).toBe(false);
    expect(d.vector!.every((x) => x === 0)).toBe(true);
  });

  it('entrega vector null si hay NaN', async () => {
    await servicio.cargar();
    HolisticFalso.proximo = { poseLandmarks: bloque(N_POSE, { x: NaN, y: 0, z: 0 }) };
    expect((await servicio.detectar(video()))!.vector).toBeNull();
  });

  it('ignora el video que aún no tiene imagen', async () => {
    await servicio.cargar();
    expect(await servicio.detectar(video({ readyState: 1 }))).toBeNull();
  });

  it('avisa cuando los hombros salen del encuadre', async () => {
    await servicio.cargar();
    HolisticFalso.proximo = { poseLandmarks: bloque(N_POSE, { x: 1.2, y: 0.5, z: 0 }) };
    expect((await servicio.detectar(video()))!.hombros).toBe(false);
  });

  it('reinicia el seguimiento', async () => {
    await servicio.cargar();
    servicio.reiniciar();
    expect(HolisticFalso.ultimo.reinicios).toBe(0); // sin usar: nada que olvidar
    await servicio.detectar(video());
    servicio.reiniciar();
    expect(HolisticFalso.ultimo.reinicios).toBe(1);
  });
});
