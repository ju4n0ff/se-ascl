import { Injectable, signal } from '@angular/core';

const PREFERENCIAS = ['es-cl', 'es-es'];

const normalizar = (lang: string): string => lang.replace('_', '-').toLowerCase();

/** es-CL, luego es-ES, luego cualquier español. */
export function elegirVoz(voces: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  for (const lang of PREFERENCIAS) {
    const voz = voces.find((v) => normalizar(v.lang) === lang);
    if (voz) return voz;
  }
  return voces.find((v) => /^es(-|$)/.test(normalizar(v.lang))) ?? null;
}

@Injectable({ providedIn: 'root' })
export class SpeechService {
  private readonly sintesis: SpeechSynthesis | null = globalThis.speechSynthesis ?? null;
  private readonly _activo = signal(this.sintesis !== null);
  private ultimo = '';

  readonly disponible = this.sintesis !== null;
  /** Lectura automática de las traducciones aceptadas. */
  readonly activo = this._activo.asReadonly();

  alternar(): void {
    this._activo.update((a) => this.disponible && !a);
    if (!this._activo()) this.detener();
  }

  /** Lectura automática: respeta el interruptor. */
  anunciar(texto: string): void {
    this.ultimo = texto;
    if (this._activo()) this.hablar(texto);
  }

  /** Lectura pedida por el usuario: suena aunque el audio automático esté apagado. */
  hablar(texto: string): void {
    if (!this.sintesis || !texto.trim()) return;
    this.sintesis.cancel();
    const locucion = new SpeechSynthesisUtterance(texto);
    // Las voces se cargan en diferido en algunos navegadores: se eligen al hablar.
    const voz = elegirVoz(this.sintesis.getVoices());
    if (voz) locucion.voice = voz;
    locucion.lang = voz?.lang ?? 'es-CL';
    this.sintesis.speak(locucion);
  }

  repetir(): void {
    this.hablar(this.ultimo);
  }

  detener(): void {
    this.sintesis?.cancel();
  }
}
