import { Component, effect, inject, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth/auth.service';
import { SessionService } from './core/auth/session.service';
import { NotificationService } from './core/ui/notification.service';
import { Barra } from './layout/barra';
import { Avisos } from './shared/avisos';
import { PanelAccesibilidad } from './shared/panel-accesibilidad';

const RUTAS_PRIVADAS = /^\/(historial|perfil)\b/;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Barra, Avisos, PanelAccesibilidad],
  template: `
    <a class="saltar" href="#contenido" (click)="irAlContenido($event, main)">Ir al contenido</a>
    <app-barra />
    <main #main id="contenido" tabindex="-1"><router-outlet /></main>
    <nav class="nav-movil" aria-label="Navegación rápida">
      <a routerLink="/" routerLinkActive="activo" [routerLinkActiveOptions]="{ exact: true }"
        >Traducir</a
      >
      <a routerLink="/glosario" routerLinkActive="activo">Glosario</a>
      <a routerLink="/historial" routerLinkActive="activo">Historial</a>
      <a routerLink="/perfil" routerLinkActive="activo">Perfil</a>
    </nav>
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
      <p class="creditos">Hecho con fines educativos · Modelo LSCh v3.2.0 · 89 señas</p>
      <div class="pie-metricas">
        <div class="metricas-bloque">
          <span class="metricas-titulo">ESTADO</span>
          <span>API <b>/salud</b></span>
          <span>MODELO LSCh v3.2.0</span>
          <span>1629 DIM / 30 FPS</span>
        </div>
        <div class="metricas-bloque metricas-derecha">
          <span>DATOS: <b>LOCAL</b> · <b class="privado">PRIVADO</b></span>
          <span>NEURONAL · TENSORFLOW.JS · WEBASSEMBLY</span>
          <span>SEÑACL · octubre 2025</span>
        </div>
      </div>
    </footer>
    <app-avisos />
    <app-panel-accesibilidad />
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      min-height: 100dvh;
      padding-top: 81px;
    }
    main {
      flex: 1;
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      padding: 0 32px;
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
    .nav-movil {
      display: none;
    }
    .pie {
      color: #505652;
      border-top: 1px solid #e7e1d8;
      background: #f6f3ee;
      font-size: 12px;
    }
    .pie-interior {
      display: grid;
      grid-template-columns: minmax(0, 2fr) repeat(2, minmax(0, 1fr));
      gap: 48px;
      min-height: 279px;
      max-width: 1216px;
      margin: 0 auto;
      padding: 40px 0 32px;
    }
    .pie-marca strong {
      font-family: var(--fuente-titulo);
      font-size: 22px;
      font-weight: 700;
      color: #1e4438;
    }
    .pie-marca p {
      margin: 8px 0 0;
      max-width: 32rem;
      color: #505652;
      font-size: 12px;
      line-height: 1.7;
    }
    .pie nav {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;
    }
    .pie h2 {
      margin: 0 0 4px;
      font-family: var(--fuente-mono);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.6px;
      color: #1d2220;
      text-transform: uppercase;
    }
    .pie nav a {
      min-height: 20px;
      display: inline-flex;
      align-items: center;
      color: #505652;
      font-size: 12px;
      text-decoration: none;
    }
    .pie nav a:hover {
      color: #1e4438;
    }
    .creditos {
      max-width: 1216px;
      margin: 0 auto;
      padding-bottom: 24px;
      text-align: left;
      font-family: var(--fuente-mono);
      font-size: 12px;
      color: #7e8580;
    }
    .pie-metricas {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 97px;
      padding: 20px 32px;
      border-top: 1px solid #e7e1d8;
      background: #efebe4;
      font-family: var(--fuente-mono);
      font-size: 12px;
    }
    .metricas-bloque {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      color: #505652;
    }
    .metricas-bloque > span + span::before {
      content: '';
      display: inline-block;
      width: 1px;
      height: 12px;
      margin-right: 8px;
      border-right: 1px solid #d8d2c9;
      vertical-align: -2px;
    }
    .metricas-titulo {
      color: #1d2220;
      font-weight: 700;
    }
    .metricas-bloque b {
      color: #1e4438;
    }
    .metricas-bloque b.privado {
      padding: 2px 6px;
      border-radius: 4px;
      background: #d6ebe2;
      color: #1e4438;
    }
    .metricas-derecha {
      justify-content: flex-end;
      color: #7e8580;
    }
    @media (max-width: 900px) {
      main {
        padding: 0 20px 48px;
      }
    }
    @media (max-width: 760px) {
      :host {
        padding-top: 64px;
      }
      main {
        padding: 0 16px 110px;
      }
      .nav-movil {
        position: fixed;
        z-index: 15;
        left: 0;
        right: 0;
        bottom: 0;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0.25rem;
        padding: 0.45rem 0.5rem calc(0.45rem + env(safe-area-inset-bottom));
        border-top: 1px solid var(--borde);
        background: color-mix(in srgb, var(--superficie) 94%, transparent);
        box-shadow: 0 -10px 30px rgb(18 48 39 / 0.12);
        backdrop-filter: blur(12px);
      }
      .nav-movil a {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 48px;
        border-radius: 14px;
        color: var(--texto-suave);
        font-size: 0.78rem;
        font-weight: 700;
        text-decoration: none;
      }
      .nav-movil a.activo {
        background: var(--verde-claro);
        color: var(--verde-oscuro);
      }
      .pie {
        padding: 0;
      }
      .pie-interior {
        grid-template-columns: 1fr;
        gap: 24px;
        min-height: 0;
        padding: 32px 16px 24px;
      }
      .pie-metricas {
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
        padding: 20px 16px calc(20px + 74px);
      }
      .metricas-derecha {
        justify-content: flex-start;
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
