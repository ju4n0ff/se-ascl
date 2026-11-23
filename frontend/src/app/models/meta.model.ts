/** Espeja `ClaseInfo`, `ClasesResponse` y `GET /api/health`. */
export interface ClaseInfo {
  indice: number;
  clase_raw: string;
  texto: string;
  es_pregunta: boolean;
}

export interface ClasesResponse {
  total: number;
  clases: ClaseInfo[];
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  service: string;
  database: 'ok' | 'error';
  modelo: { estado: string; num_clases?: number; version_features?: number };
  modelo_estatico: string;
}
