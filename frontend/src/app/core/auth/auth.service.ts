import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, map, tap } from 'rxjs';

import { UserCreate, UserLogin } from '../../models/auth.model';
import { UserResponse, UserUpdate } from '../../models/user.model';
import { AuthApiService } from '../../services/auth-api.service';
import { UsersApiService } from '../../services/users-api.service';
import { SessionService } from './session.service';

/** Casos de uso de la cuenta: coordina las API y la sesión. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly authApi = inject(AuthApiService);
  private readonly usersApi = inject(UsersApiService);
  private readonly sesion = inject(SessionService);
  private readonly _usuario = signal<UserResponse | null>(null);

  readonly autenticado = this.sesion.autenticado;
  /** null sin sesión, también si se cerró por vencimiento o 401. */
  readonly usuario = computed(() => (this.autenticado() ? this._usuario() : null));

  login(datos: UserLogin): Observable<void> {
    return this.authApi.login(datos).pipe(
      tap((t) => {
        this._usuario.set(null);
        this.sesion.iniciar(t.access_token);
      }),
      map(() => undefined),
    );
  }

  registrar(datos: UserCreate): Observable<UserResponse> {
    return this.authApi.registrar(datos);
  }

  cargarPerfil(): Observable<UserResponse> {
    return this.usersApi.yo().pipe(tap((u) => this._usuario.set(u)));
  }

  actualizarPerfil(cambios: UserUpdate): Observable<UserResponse> {
    return this.usersApi.actualizar(cambios).pipe(tap((u) => this._usuario.set(u)));
  }

  eliminarCuenta(): Observable<void> {
    return this.usersApi.eliminar().pipe(tap(() => this.cerrarSesion()));
  }

  cerrarSesion(): void {
    this._usuario.set(null);
    this.sesion.cerrar();
  }
}
