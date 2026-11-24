import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../core/auth/auth.service';
import { NotificationService } from '../core/ui/notification.service';
import { PreferenciasAccesibilidad } from '../core/ui/preferencias-accesibilidad.service';
import { BackendStatusService } from '../services/backend-status.service';

@Component({
  selector: 'app-barra',
  imports: [RouterLink, RouterLinkActive],
  template: `
    <header>
      <div class="interior">
        <a routerLink="/" class="marca" aria-label="SeñaCL, inicio" (click)="cerrarMenu()">
          <img src="favicon.svg" alt="" width="34" height="34" />
          <span>Seña<b>CL</b></span>
          <span class="sello" aria-hidden="true">TRADUCTOR LSCH</span>
        </a>

        <button
          type="button"
          class="menu"
          [attr.aria-expanded]="menuAbierto()"
          aria-controls="nav-principal"
          [attr.aria-label]="menuAbierto() ? 'Cerrar menú' : 'Abrir menú'"
          (click)="alternarMenu()"
        >
          <span aria-hidden="true">☰</span>
          <span class="menu-texto">Menú</span>
        </button>

        <nav id="nav-principal" aria-label="Principal" [class.abierto]="menuAbierto()">
          <a
            routerLink="/"
            routerLinkActive="activo"
            [routerLinkActiveOptions]="{ exact: true }"
            (click)="cerrarMenu()"
            >Traducción</a
          >
          <a routerLink="/glosario" routerLinkActive="activo" (click)="cerrarMenu()">Glosario</a>
          <a routerLink="/historial" routerLinkActive="activo" (click)="cerrarMenu()">Historial</a>
          @if (auth.autenticado()) {
            <a routerLink="/perfil" routerLinkActive="activo" (click)="cerrarMenu()"
              >{{ auth.usuario()?.username ?? 'Mi perfil' }}</a
            >
            <button type="button" (click)="salir()">Salir</button>
          }
        </nav>

        <div class="acciones">
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
          <button
            type="button"
            class="accesibilidad"
            aria-label="Abrir panel de accesibilidad, atajo Alt más A"
            (click)="prefs.abrirPanel()"
          >
            <span aria-hidden="true">Aa</span>
            <span class="texto-accesibilidad">Accesibilidad</span>
            <kbd aria-hidden="true">Alt+A</kbd>
          </button>
          @if (auth.autenticado()) {
            <span class="avatar" aria-hidden="true">{{
              (auth.usuario()?.username ?? 'U').charAt(0).toUpperCase()
            }}</span>
          } @else {
            <a routerLink="/login" class="ingresar" (click)="cerrarMenu()">Ingresar</a>
            <a routerLink="/registro" class="registrarse" (click)="cerrarMenu()">Registrarse</a>
          }
        </div>
      </div>
    </header>
  `,
  styleUrl: './barra.css',
})
export class Barra {
  protected readonly auth = inject(AuthService);
  protected readonly backend = inject(BackendStatusService);
  protected readonly prefs = inject(PreferenciasAccesibilidad);
  protected readonly menuAbierto = signal(false);

  private readonly router = inject(Router);
  private readonly avisos = inject(NotificationService);

  constructor() {
    this.backend.comprobar();
  }

  protected alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  protected cerrarMenu(): void {
    this.menuAbierto.set(false);
  }

  protected salir(): void {
    this.auth.cerrarSesion();
    this.avisos.info('Cerraste tu sesión.');
    this.cerrarMenu();
    void this.router.navigateByUrl('/');
  }
}
