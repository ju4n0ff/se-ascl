import { Component, inject } from '@angular/core';

import { NotificationService } from '../core/ui/notification.service';

@Component({
  selector: 'app-avisos',
  template: `
    <div class="pila" aria-live="polite">
      @for (aviso of notificaciones.avisos(); track aviso.id) {
        <div class="aviso" [attr.data-tipo]="aviso.tipo">
          <span>{{ aviso.texto }}</span>
          <button type="button" aria-label="Cerrar aviso" (click)="notificaciones.cerrar(aviso.id)">
            ×
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .pila {
      position: fixed;
      right: 1rem;
      bottom: 1rem;
      z-index: 20;
      display: grid;
      gap: 0.5rem;
      max-width: min(26rem, calc(100vw - 2rem));
    }
    .aviso {
      display: flex;
      align-items: start;
      gap: 0.75rem;
      padding: 0.8rem 1rem;
      border-radius: var(--radio);
      background: var(--cafe-profundo);
      color: var(--superficie);
      box-shadow: var(--sombra);
      border-left: 5px solid var(--arena);
    }
    .aviso[data-tipo='exito'] {
      border-left-color: var(--oliva);
    }
    .aviso[data-tipo='error'] {
      border-left-color: var(--acento);
    }
    button {
      min-width: 44px;
      min-height: 44px;
      margin-left: auto;
      border: 0;
      border-radius: var(--radio);
      background: none;
      color: inherit;
      font-size: 1.3rem;
      line-height: 1;
      cursor: pointer;
    }
  `,
})
export class Avisos {
  protected readonly notificaciones = inject(NotificationService);
}
