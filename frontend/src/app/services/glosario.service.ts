import { Injectable, computed, inject, signal } from '@angular/core';

import { ErrorMapperService } from '../core/errors/error-mapper.service';
import { ClaseInfo } from '../models/meta.model';
import { EstadoVista } from '../models/vista.model';
import { MetaApiService } from './meta-api.service';

export type FiltroGlosario = 'todas' | 'preguntas' | 'afirmaciones';

/** Sin tildes ni mayúsculas ni signos: "¿Dónde?" coincide con "donde". */
export function normalizarBusqueda(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-̂̄-ͯ]/g, '') // conserva la virgulilla de la ñ
    .normalize('NFC')
    .toLowerCase()
    .replace(/[¿?¡!_]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

@Injectable()
export class GlosarioService {
  private readonly api = inject(MetaApiService);
  private readonly errores = inject(ErrorMapperService);
  private readonly _clases = signal<readonly ClaseInfo[]>([]);
  private readonly _carga = signal<'loading' | 'error' | 'ready'>('loading');
  private readonly _mensajeError = signal('');

  readonly busqueda = signal('');
  readonly filtro = signal<FiltroGlosario>('todas');
  readonly mensajeError = this._mensajeError.asReadonly();
  readonly total = computed(() => this._clases().length);

  readonly visibles = computed(() => {
    const termino = normalizarBusqueda(this.busqueda());
    const filtro = this.filtro();
    return this._clases().filter(
      (c) =>
        (filtro === 'todas' || c.es_pregunta === (filtro === 'preguntas')) &&
        normalizarBusqueda(c.texto).includes(termino),
    );
  });

  readonly estado = computed<EstadoVista>(() => {
    const carga = this._carga();
    return carga === 'ready' && this.visibles().length === 0 ? 'empty' : carga;
  });

  cargar(): void {
    this._carga.set('loading');
    this.api.clases().subscribe({
      next: ({ clases }) => {
        this._clases.set([...clases].sort((a, b) => a.texto.localeCompare(b.texto, 'es')));
        this._carga.set('ready');
      },
      error: (e: unknown) => {
        this._mensajeError.set(this.errores.mapear(e).mensaje);
        this._carga.set('error');
      },
    });
  }
}
