import { HttpContextToken, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { API_CONFIG } from '../config/api.config';
import { SessionService } from './session.service';

/** La petición lleva la contraseña actual: un 401 puede significar "contraseña incorrecta". */
export const REAUTENTICACION = new HttpContextToken<boolean>(() => false);

/** Detalle del backend para token ausente, inválido o vencido (core/security.py). */
const DETALLE_SIN_SESION = 'No autenticado';

export function esUrlDeApi(url: string, apiUrl: string): boolean {
  // Con barra: "http://api.cl.evil.example" no debe pasar como "http://api.cl".
  return url === apiUrl || url.startsWith(`${apiUrl}/`);
}

/** Adjunta el JWT solo al backend y da por vencida la sesión si este la rechaza. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const sesion = inject(SessionService);
  const { apiUrl } = inject(API_CONFIG);

  const token = sesion.token();
  if (token === null || !esUrlDeApi(req.url, apiUrl)) return next(req);

  return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && error.status === 401) {
        const detalle: unknown = (error.error as { detail?: unknown } | null)?.detail;
        const claveIncorrecta = req.context.get(REAUTENTICACION) && detalle !== DETALLE_SIN_SESION;
        // Una respuesta tardía de un token anterior no debe cerrar la sesión nueva.
        if (!claveIncorrecta && sesion.token() === token) sesion.expirar();
      }
      return throwError(() => error);
    }),
  );
};
