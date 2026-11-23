import { Injectable, computed, signal } from '@angular/core';
import { Subject } from 'rxjs';

const CLAVE = 'senacl.token';
/** setTimeout desborda con más de 2^31-1 ms. */
const MAX_TIMEOUT_MS = 2_147_483_647;

/** Expiración del JWT en ms. Se lee solo para UX: la validez la decide el backend. */
export function expiracionMs(token: string): number | null {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload: unknown = JSON.parse(atob(base64));
    const exp = (payload as { exp?: unknown }).exp;
    return typeof exp === 'number' ? exp * 1000 : null;
  } catch {
    return null;
  }
}

/**
 * Único dueño del JWT. `sessionStorage`: sobrevive a recargar la página y desaparece al
 * cerrar la pestaña (ver frontend/README.md, "Decisión: dónde vive el JWT").
 */
@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly _token = signal<string | null>(null);
  private temporizador: ReturnType<typeof setTimeout> | undefined;

  readonly token = this._token.asReadonly();
  readonly autenticado = computed(() => this._token() !== null);
  /** La sesión terminó sin que el usuario lo pidiera (vencimiento o rechazo del backend). */
  readonly expirada$ = new Subject<void>();

  constructor() {
    const guardado = this.leer();
    if (guardado) this.iniciar(guardado);
  }

  iniciar(token: string): void {
    const expira = expiracionMs(token);
    if (expira === null || expira <= Date.now()) {
      this.cerrar();
      return;
    }
    this._token.set(token);
    this.escribir(token);
    clearTimeout(this.temporizador);
    this.temporizador = setTimeout(
      () => this.expirar(),
      Math.min(expira - Date.now(), MAX_TIMEOUT_MS),
    );
  }

  cerrar(): void {
    clearTimeout(this.temporizador);
    this._token.set(null);
    this.escribir(null);
  }

  expirar(): void {
    if (this._token() === null) return;
    this.cerrar();
    this.expirada$.next();
  }

  // El almacenamiento puede estar bloqueado (modo privado): la sesión sigue en memoria.
  private leer(): string | null {
    try {
      return sessionStorage.getItem(CLAVE);
    } catch {
      return null;
    }
  }

  private escribir(token: string | null): void {
    try {
      if (token === null) sessionStorage.removeItem(CLAVE);
      else sessionStorage.setItem(CLAVE, token);
    } catch {
      /* sin almacenamiento disponible */
    }
  }
}
