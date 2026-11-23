import { Injectable, inject, signal } from '@angular/core';
import { Observable, finalize, tap } from 'rxjs';

import { ErrorMapperService } from '../core/errors/error-mapper.service';
import { HistoryEntry } from '../models/history.model';
import { EstadoVista } from '../models/vista.model';
import { HistoryApiService } from './history-api.service';

/** Estado del historial de la vista. La lista siempre refleja lo que confirmó el servidor. */
@Injectable()
export class HistorialService {
  private readonly api = inject(HistoryApiService);
  private readonly errores = inject(ErrorMapperService);
  private readonly _entradas = signal<readonly HistoryEntry[]>([]);
  private readonly _estado = signal<EstadoVista>('loading');
  private readonly _mensajeError = signal('');
  private readonly _ocupada = signal<number | null>(null);

  readonly entradas = this._entradas.asReadonly();
  readonly estado = this._estado.asReadonly();
  readonly mensajeError = this._mensajeError.asReadonly();
  /** Id de la entrada con una operación en curso. */
  readonly ocupada = this._ocupada.asReadonly();

  cargar(): void {
    this._estado.set('loading');
    this.api.listar(50).subscribe({
      next: (lista) => this.publicar(lista),
      error: (e: unknown) => {
        this._mensajeError.set(this.errores.mapear(e, 'historial').mensaje);
        this._estado.set('error');
      },
    });
  }

  actualizarTexto(id: number, texto: string): Observable<HistoryEntry> {
    this._ocupada.set(id);
    return this.api.actualizar(id, { spanish_text: texto.trim() }).pipe(
      tap((nueva) => this._entradas.update((l) => l.map((e) => (e.id === id ? nueva : e)))),
      finalize(() => this._ocupada.set(null)),
    );
  }

  eliminar(id: number): Observable<void> {
    this._ocupada.set(id);
    return this.api.eliminar(id).pipe(
      tap(() => this.quitar(id)),
      finalize(() => this._ocupada.set(null)),
    );
  }

  /** También cuando el servidor responde 404: ya no existe. */
  quitar(id: number): void {
    this.publicar(this._entradas().filter((e) => e.id !== id));
  }

  private publicar(lista: readonly HistoryEntry[]): void {
    this._entradas.set(lista);
    this._estado.set(lista.length ? 'ready' : 'empty');
  }
}
