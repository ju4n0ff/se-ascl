import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ClasesResponse, HealthResponse } from '../models/meta.model';
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
}
