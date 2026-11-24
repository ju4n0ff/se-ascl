import { DOCUMENT } from '@angular/common';
import { Injectable, InjectionToken, inject, signal } from '@angular/core';
import type { Holistic, HolisticConfig } from '@mediapipe/holistic';

import { Punto, ResultadosHolistic, VectorFrame, construirVector } from './landmarks';

export type EstadoMotor = 'sin-cargar' | 'cargando' | 'listo' | 'error';
export type ConstructorHolistic = new (config?: HolisticConfig) => Holistic;

export interface Deteccion {
  /** null si el frame trae valores no finitos: no se envía. */
  vector: VectorFrame | null;
  resultados: ResultadosHolistic;
  manoIzquierda: boolean;
  manoDerecha: boolean;
  hombros: boolean;
}

/** Copiados desde node_modules por angular.json; la versión en la ruta permite caché inmutable. */
export const RUTA_MEDIAPIPE = 'mediapipe/holistic-0.5.1675471629/';

/** Opciones obligatorias de README_ML.md §4: las del entrenamiento. */
export const OPCIONES_HOLISTIC = {
  modelComplexity: 1,
  smoothLandmarks: true,
  enableSegmentation: false,
  refineFaceLandmarks: false, // 468 puntos de rostro, no 478
  minDetectionConfidence: 0.5,
  minTrackingConfidence: 0.5,
  selfieMode: false, // true espejaría los datos y rompería el modelo
} as const;

/**
 * Carga `holistic.js` como script clásico: el paquete no es un módulo ES, publica
 * `window.Holistic`. Reemplazable en los tests.
 */
export const CARGADOR_HOLISTIC = new InjectionToken<() => Promise<ConstructorHolistic>>(
  'CARGADOR_HOLISTIC',
  {
    providedIn: 'root',
    factory: () => {
      const documento = inject(DOCUMENT);
      return () =>
        new Promise<ConstructorHolistic>((resolver, rechazar) => {
          const leer = () =>
            (documento.defaultView as { Holistic?: ConstructorHolistic } | null)?.Holistic;
          const existente = leer();
          if (existente) {
            resolver(existente);
            return;
          }
          const script = documento.createElement('script');
          script.src = `${RUTA_MEDIAPIPE}holistic.js`;
          script.onload = () => {
            const ctor = leer();
            if (ctor) resolver(ctor);
            else rechazar(new Error('holistic.js no publicó Holistic'));
          };
          script.onerror = () => {
            script.remove(); // permite reintentar
            rechazar(new Error('No se pudo descargar holistic.js'));
          };
          documento.head.appendChild(script);
        });
    },
  },
);

const CONEXIONES_MANO: readonly (readonly [number, number])[] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [0, 5],
  [5, 6],
  [6, 7],
  [7, 8],
  [5, 9],
  [9, 10],
  [10, 11],
  [11, 12],
  [9, 13],
  [13, 14],
  [14, 15],
  [15, 16],
  [13, 17],
  [17, 18],
  [18, 19],
  [19, 20],
  [0, 17],
];
const CONEXIONES_BRAZOS: readonly (readonly [number, number])[] = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
];
const HOMBROS = [11, 12] as const;
const VISIBILIDAD_MINIMA = 0.5;

const visible = (p: Punto | undefined): p is Punto =>
  p !== undefined && ((p as { visibility?: number }).visibility ?? 1) > VISIBILIDAD_MINIMA;

const dentro = (p: Punto | undefined): boolean =>
  visible(p) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;

/** Motor de landmarks en el navegador. El video se procesa sin espejar y nunca sale del equipo. */
@Injectable({ providedIn: 'root' })
export class MediaPipeService {
  private readonly cargador = inject(CARGADOR_HOLISTIC);
  private readonly _estado = signal<EstadoMotor>('sin-cargar');
  private holistic: Holistic | null = null;
  private carga: Promise<void> | null = null;
  private ultimo: ResultadosHolistic | null = null;
  private usado = false;

  readonly estado = this._estado.asReadonly();

  /** Carga perezosa e idempotente; si falla se puede volver a llamar. */
  cargar(): Promise<void> {
    this.carga ??= this.inicializar().catch((error: unknown) => {
      this.carga = null;
      this._estado.set('error');
      throw error;
    });
    return this.carga;
  }

  async detectar(video: HTMLVideoElement): Promise<Deteccion | null> {
    if (!this.holistic || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return null;
    const { videoWidth, videoHeight } = video;
    this.ultimo = null;
    this.usado = true;
    await this.holistic.send({ image: video });
    const resultados = this.ultimo as ResultadosHolistic | null;
    if (!resultados) return null;
    const pose = resultados.poseLandmarks;
    return {
      vector: construirVector(resultados, videoWidth, videoHeight),
      resultados,
      manoIzquierda: !!resultados.leftHandLandmarks,
      manoDerecha: !!resultados.rightHandLandmarks,
      hombros: HOMBROS.every((i) => dentro(pose?.[i])),
    };
  }

  /** Olvida el seguimiento anterior. Reconstruye el grafo, así que se omite si está sin usar. */
  reiniciar(): void {
    if (!this.usado) return;
    this.usado = false;
    this.holistic?.reset();
  }

  /** Dibuja brazos y manos. El espejo lo aplica el CSS del contenedor, no este método. */
  dibujar(canvas: HTMLCanvasElement, resultados: ResultadosHolistic | null): void {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!resultados) return;
    ctx.lineWidth = Math.max(2, canvas.width / 240);
    ctx.lineCap = 'round';
    this.trazar(ctx, resultados.poseLandmarks, CONEXIONES_BRAZOS, 'rgba(255,255,255,.75)', true);
    this.trazar(ctx, resultados.leftHandLandmarks, CONEXIONES_MANO, '#B9CE8F');
    this.trazar(ctx, resultados.rightHandLandmarks, CONEXIONES_MANO, '#E7A07C');
  }

  private async inicializar(): Promise<void> {
    this._estado.set('cargando');
    const Holistic = await this.cargador();
    const holistic = new Holistic({ locateFile: (archivo) => `${RUTA_MEDIAPIPE}${archivo}` });
    holistic.setOptions(OPCIONES_HOLISTIC);
    holistic.onResults((r) => {
      this.ultimo = r;
    });
    await holistic.initialize();
    this.holistic = holistic;
    this._estado.set('listo');
  }

  private trazar(
    ctx: CanvasRenderingContext2D,
    puntos: readonly Punto[] | null | undefined,
    conexiones: readonly (readonly [number, number])[],
    color: string,
    soloVisibles = false,
  ): void {
    if (!puntos) return;
    const { width, height } = ctx.canvas;
    ctx.strokeStyle = color;
    ctx.beginPath();
    for (const [a, b] of conexiones) {
      const p = puntos[a];
      const q = puntos[b];
      if (!p || !q || (soloVisibles && !(visible(p) && visible(q)))) continue;
      ctx.moveTo(p.x * width, p.y * height);
      ctx.lineTo(q.x * width, q.y * height);
    }
    ctx.stroke();
  }
}
