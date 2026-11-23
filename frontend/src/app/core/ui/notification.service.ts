import { Injectable, signal } from '@angular/core';

export type TipoAviso = 'exito' | 'error' | 'info';

export interface Aviso {
  id: number;
  tipo: TipoAviso;
  texto: string;
}

const DURACION_MS: Record<TipoAviso, number> = { exito: 4000, info: 5000, error: 8000 };

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly _avisos = signal<Aviso[]>([]);
  private siguienteId = 0;

  readonly avisos = this._avisos.asReadonly();

  exito(texto: string): void {
    this.mostrar('exito', texto);
  }

  error(texto: string): void {
    this.mostrar('error', texto);
  }

  info(texto: string): void {
    this.mostrar('info', texto);
  }

  cerrar(id: number): void {
    this._avisos.update((lista) => lista.filter((a) => a.id !== id));
  }

  private mostrar(tipo: TipoAviso, texto: string): void {
    const id = ++this.siguienteId;
    // Sin repetir el mismo texto ni acumular más de tres.
    this._avisos.update((lista) => [
      ...lista.filter((a) => a.texto !== texto).slice(-2),
      { id, tipo, texto },
    ]);
    setTimeout(() => this.cerrar(id), DURACION_MS[tipo]);
  }
}
