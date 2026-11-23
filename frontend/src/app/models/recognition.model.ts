/** Espeja `Candidato` y `RecognitionResponse`. */
export interface Candidato {
  clase_raw: string;
  texto: string;
  es_pregunta: boolean;
  confianza: number;
}

export type ModoModelo = 'dynamic' | 'static';

export interface ResultadoReconocimiento {
  aceptada: boolean;
  prediccion: Candidato;
  top_k: Candidato[];
  frames_recibidos: number;
  latencia_ms: number;
  predicted_label: string;
  spanish_text: string;
  confidence: number;
  mode: ModoModelo;
  guardado_en_historial: boolean;
}

export interface RecognitionResponse extends ResultadoReconocimiento {
  timestamp: string;
}
