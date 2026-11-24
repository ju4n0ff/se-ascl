import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ClasesResponse, HealthResponse, ReferenciaSenaResponse } from '../models/meta.model';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class MetaApiService {
  private readonly api = inject(ApiService);

  salud(): Observable<HealthResponse> {
    return this.api.get<HealthResponse>('api/health');
  }

  clases(): Observable<ClasesResponse> {
    return this.api.get<ClasesResponse>('api/clases');
  }

  referencia(claseRaw: string): Observable<ReferenciaSenaResponse> {
    return this.api.get<ReferenciaSenaResponse>(
      `api/referencias/${encodeURIComponent(claseRaw)}`,
    );
  }
}
