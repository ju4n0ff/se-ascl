import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../core/auth/auth.service';
import { NotificationService } from '../core/ui/notification.service';
import { BackendStatusService } from '../services/backend-status.service';

@Component({
  selector: 'app-barra',
  imports: [RouterLink, RouterLinkActive],
  template: `
    <header>
      <div class="interior">
        <a routerLink="/" class="marca" aria-label="SeñaCL, inicio">
          <img src="favicon.svg" alt="" width="32" height="32" />
          <span>Seña<b>CL</b></span>
        </a>
        <nav aria-label="Principal">
          <a routerLink="/" routerLinkActive="activo" [routerLinkActiveOptions]="{ exact: true }"
            >Traductor</a
          >
          <a routerLink="/glosario" routerLinkActive="activo">Glosario</a>
          @if (auth.autenticado()) {
            <a routerLink="/historial" routerLinkActive="activo">Historial</a>
            <a routerLink="/perfil" routerLinkActive="activo">{{
              auth.usuario()?.username ?? 'Mi perfil'
            }}</a>
            <button type="button" (click)="salir()">Salir</button>
          } @else {
            <a routerLink="/login" routerLinkActive="activo">Ingresar</a>
            <a routerLink="/registro" class="destacado">Crear cuenta</a>
          }
        </nav>
        <button
          type="button"
          class="salud"
          [attr.data-estado]="backend.estado()"
          [title]="backend.texto() + '. Pulsa para comprobar de nuevo.'"
          (click)="backend.comprobar()"
        >
          <span class="punto" aria-hidden="true"></span>
          <span class="texto" role="status">{{ backend.texto() }}</span>
        </button>
      </div>
    </header>
  `,
  styleUrl: './barra.css',
})
export class Barra {
  protected readonly auth = inject(AuthService);
  protected readonly backend = inject(BackendStatusService);
  private readonly router = inject(Router);
  private readonly avisos = inject(NotificationService);

  constructor() {
    this.backend.comprobar();
  }

  protected salir(): void {
    this.auth.cerrarSesion();
    this.avisos.info('Cerraste tu sesión.');
    void this.router.navigateByUrl('/');
  }
}
