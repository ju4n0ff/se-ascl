import { Component, effect, inject, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth/auth.service';
import { SessionService } from './core/auth/session.service';
import { NotificationService } from './core/ui/notification.service';
import { Barra } from './layout/barra';
import { Avisos } from './shared/avisos';
import { PanelAccesibilidad } from './shared/panel-accesibilidad';

const RUTAS_PRIVADAS = /^\/(historial|perfil)\b/;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, Barra, Avisos, PanelAccesibilidad],
  template: `
    <a class="saltar" href="#contenido" (click)="irAlContenido($event, main)">Ir al contenido</a>
    <app-barra />
    <main #main id="contenido" tabindex="-1"><router-outlet /></main>
    <footer class="pie">
      <div class="pie-interior">
        <div class="pie-marca">
          <strong>SeñaCL</strong>
          <p>Traductor de Lengua de Señas Chilena a texto y voz. El video se procesa en tu navegador y nunca se envía.</p>
        </div>
        <nav aria-label="Enlaces del pie">
          <h2>Explora</h2>
          <a routerLink="/">Traducción</a>
          <a routerLink="/glosario">Glosario</a>
          <a routerLink="/historial">Historial</a>
        </nav>
        <nav aria-label="Ayuda y privacidad">
          <h2>Ayuda</h2>
          <a routerLink="/informacion" fragment="guia">Guía rápida</a>
          <a routerLink="/informacion" fragment="privacidad">Privacidad</a>
          <a routerLink="/informacion" fragment="terminos">Términos</a>
          <a routerLink="/informacion" fragment="contacto">Contacto</a>
        </nav>
      </div>
      <p class="creditos">Hecho con fines educativos · Modelo LSCh v3 · 89 señas</p>
    </footer>
    <app-avisos />
    <app-panel-accesibilidad />
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      min-height: 100dvh;
    }
    main {
      flex: 1;
      width: 100%;
      max-width: 1180px;
      margin: 0 auto;
      padding: 1.5rem 1rem 3rem;
      outline: none;
    }
    .saltar {
      position: absolute;
      left: -999px;
      top: 0;
      z-index: 30;
      padding: 0.6rem 1rem;
      background: var(--superficie);
      color: var(--cafe-profundo);
    }
    .saltar:focus {
      left: 0;
    }
    .pie {
      padding: 1.75rem 1rem 1rem;
      color: var(--cafe);
      border-top: 1px solid var(--arena);
      background: var(--crema);
    }
    .pie-interior {
      display: grid;
      grid-template-columns: minmax(0, 2fr) repeat(2, minmax(0, 1fr));
      gap: 1.5rem;
      max-width: 1180px;
      margin: 0 auto;
    }
    .pie-marca strong {
      font-size: 1.25rem;
      color: var(--oliva);
    }
    .pie-marca p {
      margin: 0.4rem 0 0;
      max-width: 32rem;
      color: var(--texto-suave);
    }
    .pie nav {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.35rem;
    }
    .pie h2 {
      margin: 0 0 0.3rem;
      font-size: 1rem;
    }
    .pie nav a {
      min-height: 32px;
      display: inline-flex;
      align-items: center;
    }
    .creditos {
      max-width: 1180px;
      margin: 1.5rem auto 0;
      padding-top: 1rem;
      border-top: 1px solid var(--borde);
      text-align: center;
      font-size: 0.85rem;
      color: var(--texto-suave);
    }
    @media (max-width: 640px) {
      .pie-interior {
        grid-template-columns: 1fr;
        gap: 1rem;
      }
    }
  `,
})
export class App {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly avisos = inject(NotificationService);

  constructor() {
    effect(() => {
      if (this.auth.autenticado() && this.auth.usuario() === null) {
        untracked(() => this.auth.cargarPerfil().subscribe({ error: () => undefined }));
      }
    });
    inject(SessionService)
      .expirada$.pipe(takeUntilDestroyed())
      .subscribe(() => {
        this.avisos.error('Tu sesión expiró. Vuelve a iniciar sesión.');
        const url = this.router.url;
        if (RUTAS_PRIVADAS.test(url)) {
          void this.router.navigate(['/login'], { queryParams: { volver: url } });
        }
      });
  }

  /** Sin esto, `<base href="/">` convertiría el ancla en una navegación a la portada. */
  protected irAlContenido(evento: Event, main: HTMLElement): void {
    evento.preventDefault();
    main.focus();
  }
}
