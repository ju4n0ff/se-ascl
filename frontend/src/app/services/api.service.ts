import { HttpClient, HttpContext, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, timeout } from 'rxjs';

import { API_CONFIG } from '../core/config/api.config';

export interface OpcionesApi {
  params?: Record<string, string | number | boolean>;
  headers?: Record<string, string>;
  context?: HttpContext;
}

/** Render (plan gratuito) puede tardar cerca de un minuto en despertar. */
const TIMEOUT_MS = 75_000;

/** Única puerta a HttpClient. Las rutas van siempre sin barra final (404 en producción). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(API_CONFIG);

  get<T>(ruta: string, opciones: OpcionesApi = {}): Observable<T> {
    return this.http.get<T>(this.url(ruta), this.preparar(opciones)).pipe(timeout(TIMEOUT_MS));
  }

  post<T>(ruta: string, cuerpo: unknown, opciones: OpcionesApi = {}): Observable<T> {
    return this.http
      .post<T>(this.url(ruta), cuerpo, this.preparar(opciones))
      .pipe(timeout(TIMEOUT_MS));
  }

  patch<T>(ruta: string, cuerpo: unknown, opciones: OpcionesApi = {}): Observable<T> {
    return this.http
      .patch<T>(this.url(ruta), cuerpo, this.preparar(opciones))
      .pipe(timeout(TIMEOUT_MS));
  }

  delete(ruta: string, opciones: OpcionesApi = {}): Observable<void> {
    return this.http
      .delete<void>(this.url(ruta), this.preparar(opciones))
      .pipe(timeout(TIMEOUT_MS));
  }

  private url(ruta: string): string {
    return `${this.config.apiUrl}/${ruta.replace(/^\/+|\/+$/g, '')}`;
  }

  private preparar(o: OpcionesApi) {
    return {
      params: new HttpParams({ fromObject: o.params ?? {} }),
      headers: new HttpHeaders(o.headers ?? {}),
      context: o.context ?? new HttpContext(),
    };
  }
}
