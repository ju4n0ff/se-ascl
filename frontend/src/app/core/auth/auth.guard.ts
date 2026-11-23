import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { SessionService } from './session.service';

/** Rutas privadas: sin sesión lleva a /login y luego vuelve a donde iba. */
export const authGuard: CanActivateFn = (_ruta, estado) =>
  inject(SessionService).autenticado() ||
  inject(Router).createUrlTree(['/login'], { queryParams: { volver: estado.url } });

/** /login y /registro no tienen sentido con la sesión iniciada. */
export const invitadoGuard: CanActivateFn = () =>
  !inject(SessionService).autenticado() || inject(Router).createUrlTree(['/']);

/** Solo rutas internas: evita redirecciones abiertas desde ?volver=. */
export function destinoSeguro(volver: string | null | undefined): string {
  return volver && /^\/(?![/\\])/.test(volver) ? volver : '/';
}
