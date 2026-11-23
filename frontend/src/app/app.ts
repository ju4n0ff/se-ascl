import { Component, effect, inject, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth/auth.service';
import { SessionService } from './core/auth/session.service';
import { NotificationService } from './core/ui/notification.service';
import { Barra } from './layout/barra';
import { Avisos } from './shared/avisos';

const RUTAS_PRIVADAS = /^\/(historial|perfil)\b/;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, Barra, Avisos],
  template: `
    <a class="saltar" href="#contenido" (click)="irAlContenido($event, main)">Ir al contenido</a>
    <app-barra />
    <main #main id="contenido" tabindex="-1"><router-outlet /></main>
    <footer class="pie">
      SeñaCL · Traductor de Lengua de Señas Chilena. El video se procesa en tu navegador y nunca se
      envía.
    </footer>
    <app-avisos />
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
      background: var(--blanco);
    }
    .saltar:focus {
      left: 0;
    }
    .pie {
      padding: 1.25rem 1rem;
      text-align: center;
      font-size: 0.875rem;
      color: var(--texto-suave);
      border-top: 1px solid var(--borde);
      background: var(--blanco);
    }
  `,
})
export class App {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly avisos = inject(NotificationService);

  constructor() {
    // Tras iniciar sesión o recargar la página: recupera el perfil para la barra.
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
