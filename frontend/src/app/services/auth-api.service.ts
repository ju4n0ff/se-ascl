import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Token, UserCreate, UserLogin } from '../models/auth.model';
import { UserResponse } from '../models/user.model';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly api = inject(ApiService);

  registrar(datos: UserCreate): Observable<UserResponse> {
    return this.api.post<UserResponse>('api/auth/register', datos);
  }

  login(datos: UserLogin): Observable<Token> {
    return this.api.post<Token>('api/auth/login', datos);
  }
}
