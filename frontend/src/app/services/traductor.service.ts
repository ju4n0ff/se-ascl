import { DestroyRef, Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { SessionService } from '../core/auth/session.service';
import { ModoCaptura, MsgPrediccion } from '../models/ws.model';
import { CameraService } from './camera.service';
import { MediaPipeService } from './mediapipe.service';
import { SpeechService } from './speech.service';
import { WsRecognitionService } from './ws-recognition.service';

export type FaseTraductor = 'inactivo' | 'cargando' | 'activo' | 'error';
export type EtiquetaEstado = 'ESPERANDO' | 'GRABANDO' | 'CONECTANDO' | 'DESCONECTADO';

/** 24 FPS: dentro de 20–25 y bajo el tope de 35 mensajes/s del backend. */
export const FPS_MAXIMO = 24;
const INTERVALO_MS = 1000 / FPS_MAXIMO;
const REFRESCO_FPS_MS = 500;
const LATIDO_MS = 25_000;
const DURACION_AVISO_MS = 4000;

/**
 * Caso de uso "traducir en vivo": une cámara, MediaPipe, WebSocket y voz. Se provee en la
 * vista del traductor; al destruirla libera la cámara y cierra el socket. Los frames viven
 * solo en memoria.
 */
@Injectable()
export class TraductorService {
  private readonly camara = inject(CameraService);
  private readonly motor = inject(MediaPipeService);
  private readonly voz = inject(SpeechService);
  private readonly sesion = inject(SessionService);
  readonly ws = inject(WsRecognitionService);

  private readonly _fase = signal<FaseTraductor>('inactivo');
  private readonly _mensajeError = signal<string | null>(null);
  private readonly _modo = signal<ModoCaptura>('auto');
  private readonly _guardar = signal(false);
  private readonly _resultado = signal<MsgPrediccion | null>(null);
  private readonly _frase = signal<readonly string[]>([]);
  private readonly _recientes = signal<readonly string[]>([]);
  private readonly _aviso = signal<string | null>(null);
  private readonly _fps = signal(0);
  private readonly _manos = signal({ izquierda: false, derecha: false });
  private readonly _hombros = signal(true);

  readonly fase = this._fase.asReadonly();
  readonly mensajeError = this._mensajeError.asReadonly();
  readonly modo = this._modo.asReadonly();
  readonly guardar = computed(() => this._guardar() && this.sesion.autenticado());
  readonly resultado = this._resultado.asReadonly();
  readonly frase = computed(() => this._frase().join(' '));
  readonly recientes = this._recientes.asReadonly();
  readonly aviso = this._aviso.asReadonly();
  readonly fps = this._fps.asReadonly();
  readonly manos = this._manos.asReadonly();
  /** Falso si los hombros salen del encuadre: la normalización del modelo los necesita. */
  readonly encuadreOk = this._hombros.asReadonly();
  readonly esqueleto = signal(true);
  readonly grabando = computed(() => this.ws.estado() === 'GRABANDO');
  readonly puedeGrabar = computed(
    () =>
      this._fase() === 'activo' && this._modo() === 'manual' && this.ws.conexion() === 'CONECTADO',
  );
  readonly etiqueta = computed<EtiquetaEstado>(() => {
    const conexion = this.ws.conexion();
    return conexion === 'CONECTADO' ? this.ws.estado() : conexion;
  });

  private video: HTMLVideoElement | null = null;
  private lienzo: HTMLCanvasElement | null = null;
  /** Cambia en cada inicio o detención: invalida los bucles y esperas anteriores. */
  private epoca = 0;
  private ultimoEnvio = 0;
  private temporizadorAviso: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    this.ws.prediccion$.pipe(takeUntilDestroyed()).subscribe((p) => this.alPredecir(p));
    this.ws.descartado$
      .pipe(takeUntilDestroyed())
      .subscribe((d) =>
        this.avisar(`Movimiento muy corto (${d.frames} cuadros): se descartó como ruido.`),
      );
    this.ws.error$.pipe(takeUntilDestroyed()).subscribe((e) => {
      if (e.codigo === 'inferencia') this.avisar('No pudimos analizar esa seña. Repítela.');
      if (e.codigo === 'auth_invalida') {
        this.avisar('No pudimos validar tu sesión: las traducciones no se guardarán.');
      }
    });
    // Entrar o salir de la cuenta cambia la identidad de la conexión.
    let anterior = this.sesion.token();
    effect(() => {
      const token = this.sesion.token();
      if (token === anterior) return;
      anterior = token;
      untracked(() => {
        if (token === null) this._guardar.set(false);
        if (this._fase() === 'activo') this.reconectar();
      });
    });
    inject(DestroyRef).onDestroy(() => this.detener());
  }

  async iniciar(video: HTMLVideoElement, lienzo: HTMLCanvasElement): Promise<void> {
    if (this._fase() === 'cargando' || this._fase() === 'activo') return;
    const epoca = ++this.epoca;
    this.video = video;
    this.lienzo = lienzo;
    this._mensajeError.set(null);
    this._fase.set('cargando');
    try {
      await this.camara.iniciar(video, () => this.fallar('Se perdió la conexión con la cámara.'));
    } catch (error) {
      if (epoca === this.epoca) this.fallar(this.camara.mensajeDe(error));
      return;
    }
    if (epoca !== this.epoca) {
      this.camara.detener(video);
      return;
    }
    this.ws.conectar({ modo: this._modo(), guardar: this.guardar() });
    try {
      await this.motor.cargar();
      this.motor.reiniciar();
    } catch {
      if (epoca === this.epoca) {
        this.fallar(
          'No pudimos cargar el detector de señas. Revisa tu conexión e intenta de nuevo.',
        );
      }
      return;
    }
    if (epoca !== this.epoca) return;
    this._fase.set('activo');
    void this.bucle(epoca);
  }

  detener(): void {
    this.liberar();
    this._mensajeError.set(null);
    this._fase.set('inactivo');
  }

  reconectar(): void {
    this.ws.conectar({ modo: this._modo(), guardar: this.guardar() });
  }

  cambiarModo(modo: ModoCaptura): void {
    this._modo.set(modo);
    this.ws.configurar({ modo });
  }

  cambiarGuardar(guardar: boolean): void {
    this._guardar.set(guardar && this.sesion.autenticado());
    this.ws.configurar({ guardar: this.guardar() });
  }

  alternarGrabacion(): void {
    if (!this.puedeGrabar()) return;
    if (this.grabando()) this.ws.manualStop();
    else this.ws.manualStart();
  }

  /** Descarta lo acumulado en el servidor y limpia el resultado en pantalla. */
  reiniciar(): void {
    this.ws.reset();
    this._resultado.set(null);
  }

  leerFrase(): void {
    this.voz.hablar(this.frase());
  }

  limpiarFrase(): void {
    this._frase.set([]);
    this._recientes.set([]);
  }

  async copiarFrase(): Promise<void> {
    const texto = this.frase();
    if (!texto) return;
    try {
      await navigator.clipboard.writeText(texto);
      this.avisar('Frase copiada al portapapeles.');
    } catch {
      this.avisar('No se pudo copiar. Selecciona el texto y cópialo manualmente.');
    }
  }

  // ------------------------------------------------------------------ interno
  private async bucle(epoca: number): Promise<void> {
    let proximo = performance.now();
    let cuadros = 0;
    let marca = performance.now();
    while (epoca === this.epoca && this.video) {
      await this.siguienteCuadro(this.video);
      if (epoca !== this.epoca) return;
      const ahora = performance.now();
      // Tolerancia de 4 ms: los cuadros de la cámara no llegan exactos.
      if (ahora < proximo - 4) continue;
      proximo = Math.max(proximo + INTERVALO_MS, ahora);
      try {
        await this.procesar(this.video, epoca);
      } catch {
        if (epoca === this.epoca) {
          this.fallar('El detector de señas se detuvo. Vuelve a iniciar la cámara.');
        }
        return;
      }
      cuadros++;
      const transcurrido = performance.now() - marca;
      if (transcurrido >= REFRESCO_FPS_MS) {
        this._fps.set(Math.round((cuadros * 1000) / transcurrido));
        cuadros = 0;
        marca = performance.now();
      }
    }
  }

  private async procesar(video: HTMLVideoElement, epoca: number): Promise<void> {
    const deteccion = await this.motor.detectar(video);
    if (!deteccion || epoca !== this.epoca) return;

    const manos = this._manos();
    if (manos.izquierda !== deteccion.manoIzquierda || manos.derecha !== deteccion.manoDerecha) {
      this._manos.set({ izquierda: deteccion.manoIzquierda, derecha: deteccion.manoDerecha });
    }
    this._hombros.set(deteccion.hombros);
    if (this.lienzo) {
      if (this.lienzo.width !== video.videoWidth || this.lienzo.height !== video.videoHeight) {
        this.lienzo.width = video.videoWidth;
        this.lienzo.height = video.videoHeight;
      }
      this.motor.dibujar(this.lienzo, this.esqueleto() ? deteccion.resultados : null);
    }

    // En manual solo se transmite mientras se graba.
    const ahora = performance.now();
    if (this._modo() === 'auto' || this.grabando()) {
      if (deteccion.vector && this.ws.enviarFrame(deteccion.vector)) this.ultimoEnvio = ahora;
    } else if (ahora - this.ultimoEnvio > LATIDO_MS) {
      this.ultimoEnvio = ahora;
      this.ws.mantenerViva();
    }
  }

  private siguienteCuadro(video: HTMLVideoElement): Promise<void> {
    return new Promise((resolver) => {
      if ('requestVideoFrameCallback' in video) video.requestVideoFrameCallback(() => resolver());
      else requestAnimationFrame(() => resolver());
    });
  }

  private alPredecir(p: MsgPrediccion): void {
    this._resultado.set(p);
    if (p.aviso === 'secuencia_corta') {
      this.avisar('La grabación fue muy corta: el resultado puede ser impreciso.');
    } else if (p.aviso === 'tope_manual') {
      this.avisar('Se alcanzó el máximo de grabación y se tradujo lo capturado.');
    }
    if (!p.aceptada) return;
    const { texto } = p.prediccion;
    // Como test_local.py: no se repite la misma seña consecutiva.
    this._frase.update((f) => (f.at(-1) === texto ? f : [...f, texto]));
    this._recientes.update((r) => [...r.filter((t) => t !== texto), texto].slice(-3));
    this.voz.anunciar(texto);
  }

  private avisar(texto: string): void {
    this._aviso.set(texto);
    clearTimeout(this.temporizadorAviso);
    this.temporizadorAviso = setTimeout(() => this._aviso.set(null), DURACION_AVISO_MS);
  }

  private fallar(mensaje: string): void {
    this.liberar();
    this._mensajeError.set(mensaje);
    this._fase.set('error');
  }

  private liberar(): void {
    this.epoca++;
    this.camara.detener(this.video);
    this.ws.desconectar();
    this.voz.detener();
    if (this.lienzo) this.motor.dibujar(this.lienzo, null);
    this.video = null;
    this.lienzo = null;
    this._fps.set(0);
    this._manos.set({ izquierda: false, derecha: false });
    this._hombros.set(true);
  }
}
