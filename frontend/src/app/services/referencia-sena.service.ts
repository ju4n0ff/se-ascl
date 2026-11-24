import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, of, tap } from 'rxjs';

import { environment } from '../../environments/environment';
import { ReferenciaSenaResponse } from '../models/meta.model';
import { normalizarBusqueda } from './glosario.service';
import { MetaApiService } from './meta-api.service';

export interface ReferenciaSena {
  termino: string;
  estado: 'disponible' | 'pendiente';
  imagenUrl: string;
  videoUrl: string | null;
  descripcion: string;
  fuente: string;
}

/**
 * Entrega la referencia visual de una seña. El backend aún no publica ese recurso, así que
 * con `referenciasHabilitadas: false` devuelve una ficha honesta de "pendiente" con una
 * ilustración local; al habilitarlo usa `GET /api/referencias/{clase}` y cae a la ficha si falla.
 */
@Injectable({ providedIn: 'root' })
export class ReferenciaSenaService {
  private readonly api = inject(MetaApiService);
  private readonly cache = new Map<string, ReferenciaSena>();

  obtenerReferenciaSena(termino: string): Observable<ReferenciaSena> {
    const clave = normalizarBusqueda(termino);
    const guardada = this.cache.get(clave);
    if (guardada) return of(guardada);

    const resultado = environment.referenciasHabilitadas
      ? this.api.referencia(clave).pipe(
          map((respuesta) => this.desdeApi(termino, respuesta)),
          catchError(() => of(this.pendiente(termino))),
        )
      : of(this.pendiente(termino));

    return resultado.pipe(
      tap((referencia) => this.cache.set(clave, referencia)),
    );
  }

  private desdeApi(termino: string, respuesta: ReferenciaSenaResponse): ReferenciaSena {
    return {
      termino,
      estado: 'disponible',
      imagenUrl: respuesta.imagen_url,
      videoUrl: respuesta.video_url ?? null,
      descripcion:
        respuesta.descripcion ?? `Observa la ejecución de «${termino}» y repite el gesto frente al espejo.`,
      fuente: respuesta.fuente ?? 'Referencia del proyecto',
    };
  }

  private pendiente(termino: string): ReferenciaSena {
    return {
      termino,
      estado: 'pendiente',
      imagenUrl: 'referencias/mano.svg',
      videoUrl: null,
      descripcion: `Aún no hay grabación de referencia para «${termino}». Mientras tanto, abre el traductor y practica el gesto viendo tu espejo.`,
      fuente: 'Ilustración de referencia',
    };
  }
}
