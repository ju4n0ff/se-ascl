import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { RecognitionResponse } from '../models/recognition.model';
import { ApiService } from './api.service';
import { N_FLOATS } from './landmarks';

/** Respaldo REST de la traducción en vivo (`POST /api/recognize`, binario). */
@Injectable({ providedIn: 'root' })
export class RecognitionApiService {
  private readonly api = inject(ApiService);

  reconocer(
    frames: readonly Float32Array[],
    opciones: { topK?: number; guardar?: boolean } = {},
  ): Observable<RecognitionResponse> {
    const cuerpo = new Float32Array(frames.length * N_FLOATS);
    frames.forEach((f, i) => cuerpo.set(f, i * N_FLOATS));
    return this.api.post<RecognitionResponse>('api/recognize', cuerpo.buffer, {
      headers: { 'Content-Type': 'application/octet-stream' },
      params: { top_k: opciones.topK ?? 3, save_history: opciones.guardar ?? false },
    });
  }
}
