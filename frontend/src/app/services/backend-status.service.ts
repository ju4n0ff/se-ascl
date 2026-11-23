import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';

import { API_CONFIG } from '../core/config/api.config';
import { MetaApiService } from './meta-api.service';

export type EstadoBackend =
  'comprobando' | 'disponible' | 'degradado' | 'sin-conexion' | 'sin-configurar';

const REINTENTO_MS = 20_000;
const MAX_REINTENTOS = 4;

const TEXTOS: Record<EstadoBackend, string> = {
  comprobando: 'Conectando con el servidor…',
  disponible: 'Servidor disponible',
  degradado: 'Servidor con problemas',
  'sin-conexion': 'Servidor sin conexión',
  'sin-configurar': 'Servidor sin configurar',
};

/** Estado del backend para la barra superior. Reintenta pocas veces; luego, a pedido. */
@Injectable({ providedIn: 'root' })
export class BackendStatusService {
  private readonly meta = inject(MetaApiService);
  private readonly config = inject(API_CONFIG);
  private readonly _estado = signal<EstadoBackend>('comprobando');
  private enCurso = false;
  private reintentos = 0;

  readonly estado = this._estado.asReadonly();
  readonly texto = computed(() => TEXTOS[this._estado()]);

  comprobar(): void {
    this.reintentos = 0;
    this.consultar();
  }

  private consultar(): void {
    if (!this.config.configurado) {
      this._estado.set('sin-configurar');
      return;
    }
    if (this.enCurso) return;
    this.enCurso = true;
    this._estado.set('comprobando');
    this.meta.salud().subscribe({
      next: (salud) => this.terminar(salud.status === 'ok' ? 'disponible' : 'degradado'),
      error: (e: unknown) =>
        this.terminar(
          e instanceof HttpErrorResponse && e.status === 503 ? 'degradado' : 'sin-conexion',
        ),
    });
  }

  private terminar(estado: EstadoBackend): void {
    this.enCurso = false;
    this._estado.set(estado);
    if (estado !== 'disponible' && this.reintentos < MAX_REINTENTOS) {
      this.reintentos++;
      setTimeout(() => this.consultar(), REINTENTO_MS);
    }
  }
}
