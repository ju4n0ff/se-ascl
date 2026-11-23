import { HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { TimeoutError } from 'rxjs';

export type ContextoError = 'general' | 'login' | 'registro' | 'perfil' | 'historial';

export interface ErrorAmigable {
  /** Texto listo para mostrar: nunca JSON, trazas ni inglés técnico. */
  mensaje: string;
  /** Campos rechazados por el servidor (422). */
  campos: string[];
  reintentable: boolean;
}

const NOMBRE_CAMPO: Record<string, string> = {
  username: 'el usuario',
  email: 'el correo',
  password: 'la contraseña',
  new_password: 'la contraseña nueva',
  current_password: 'la contraseña actual',
  spanish_text: 'el texto',
};

const MSG_GENERICO = 'Ocurrió un problema inesperado. Intenta de nuevo en un momento.';

@Injectable({ providedIn: 'root' })
export class ErrorMapperService {
  mapear(error: unknown, contexto: ContextoError = 'general'): ErrorAmigable {
    if (error instanceof TimeoutError) {
      return this.crear('El servidor está tardando demasiado. Intenta de nuevo.', true);
    }
    if (!(error instanceof HttpErrorResponse)) return this.crear(MSG_GENERICO, true);

    switch (error.status) {
      case 0:
        return this.crear(
          'No pudimos conectar con el servidor. Revisa tu conexión a internet o intenta en un minuto.',
          true,
        );
      case 400:
        return this.crear(
          'La solicitud no es válida. Recarga la página e intenta de nuevo.',
          false,
        );
      case 401:
        return this.crear(this.mensaje401(contexto), false);
      case 403:
        return this.crear('No tienes permiso para ver este contenido.', false);
      case 404:
        return this.crear(
          contexto === 'historial'
            ? 'Esta traducción ya no existe en tu historial.'
            : 'No encontramos lo que buscabas.',
          false,
        );
      case 409:
        return this.crear(
          contexto === 'perfil'
            ? 'Ese correo ya está en uso. Prueba con otro.'
            : 'El usuario o correo ya está registrado.',
          false,
        );
      case 413:
        return this.crear('La grabación es demasiado larga. Prueba con una seña más corta.', false);
      case 422:
        return this.mapear422(error);
      case 429:
        return this.crear(this.mensaje429(error), true);
      case 503:
        return this.crear(
          'El servicio no está disponible en este momento. Puede estar iniciando: intenta en un minuto.',
          true,
        );
      case 502:
      case 504:
        return this.crear('El servidor está iniciando. Intenta de nuevo en un minuto.', true);
      default:
        return this.crear(MSG_GENERICO, error.status >= 500);
    }
  }

  private mensaje401(contexto: ContextoError): string {
    if (contexto === 'login') return 'Credenciales inválidas. Revisa tu usuario y contraseña.';
    if (contexto === 'perfil') return 'La contraseña actual no es correcta.';
    return 'Necesitas iniciar sesión para continuar.';
  }

  private mensaje429(error: HttpErrorResponse): string {
    const segundos = Number(error.headers.get('Retry-After'));
    return Number.isFinite(segundos) && segundos > 0
      ? `Demasiados intentos, espera ${Math.ceil(segundos)} segundos.`
      : 'Demasiados intentos, espera unos segundos.';
  }

  /** `detail` puede ser texto o `[{loc, msg, type}]`; solo se usa el nombre del campo. */
  private mapear422(error: HttpErrorResponse): ErrorAmigable {
    const detalle: unknown = (error.error as { detail?: unknown } | null)?.detail;
    const campos = new Set<string>();
    for (const item of Array.isArray(detalle) ? (detalle as unknown[]) : []) {
      const loc: unknown = (item as { loc?: unknown } | null)?.loc;
      if (!Array.isArray(loc)) continue;
      const campo = loc.find(
        (l): l is string => typeof l === 'string' && Object.hasOwn(NOMBRE_CAMPO, l),
      );
      if (campo) campos.add(campo);
    }
    const nombres = [...campos].map((c) => NOMBRE_CAMPO[c]);
    const mensaje = nombres.length
      ? `Revisa ${nombres.join(' y ')}: el formato no es válido.`
      : 'Hay datos con un formato no válido. Revísalos e intenta de nuevo.';
    return { mensaje, campos: [...campos], reintentable: false };
  }

  private crear(mensaje: string, reintentable: boolean): ErrorAmigable {
    return { mensaje, campos: [], reintentable };
  }
}
