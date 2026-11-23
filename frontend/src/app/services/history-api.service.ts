import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { HistoryEntry, HistoryUpdate } from '../models/history.model';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class HistoryApiService {
  private readonly api = inject(ApiService);

  listar(limit = 50): Observable<HistoryEntry[]> {
    return this.api.get<HistoryEntry[]>('api/history/me', { params: { limit } });
  }

  actualizar(id: number, cambios: HistoryUpdate): Observable<HistoryEntry> {
    return this.api.patch<HistoryEntry>(`api/history/${id}`, cambios);
  }

  eliminar(id: number): Observable<void> {
    return this.api.delete(`api/history/${id}`);
  }
}
