import { HttpContext } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { REAUTENTICACION } from '../core/auth/auth.interceptor';
import { UserResponse, UserUpdate } from '../models/user.model';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class UsersApiService {
  private readonly api = inject(ApiService);

  yo(): Observable<UserResponse> {
    return this.api.get<UserResponse>('api/users/me');
  }

  actualizar(cambios: UserUpdate): Observable<UserResponse> {
    return this.api.patch<UserResponse>('api/users/me', cambios, {
      context: new HttpContext().set(REAUTENTICACION, true),
    });
  }

  eliminar(): Observable<void> {
    return this.api.delete('api/users/me');
  }
}
