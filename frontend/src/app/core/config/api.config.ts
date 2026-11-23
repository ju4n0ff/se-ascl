import { InjectionToken } from '@angular/core';

import { environment } from '../../../environments/environment';

export interface ApiConfig {
  apiUrl: string;
  wsUrl: string;
  /** false mientras environment.prod.ts conserve el marcador de Render. */
  configurado: boolean;
}

const sinBarraFinal = (url: string): string => url.replace(/\/+$/, '');

export function crearApiConfig(env: { apiUrl: string; wsUrl: string }): ApiConfig {
  return {
    // En producción el backend responde 404 a rutas con barra final o doble barra.
    apiUrl: sinBarraFinal(env.apiUrl),
    wsUrl: sinBarraFinal(env.wsUrl),
    configurado: !env.apiUrl.includes('REPLACE_WITH_RENDER_SERVICE'),
  };
}

export const API_CONFIG = new InjectionToken<ApiConfig>('API_CONFIG', {
  providedIn: 'root',
  factory: () => crearApiConfig(environment),
});
