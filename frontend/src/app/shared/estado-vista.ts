import { Component, input, output } from '@angular/core';

/** Cargando, vacío y error con el mismo aspecto en todas las vistas. */
@Component({
  selector: 'app-estado-vista',
  template: `
    @switch (estado()) {
      @case ('loading') {
        <div class="esqueletos" role="status">
          <span class="solo-lectores">Cargando…</span>
          @for (_ of [1, 2, 3]; track $index) {
            <div class="esqueleto"></div>
          }
        </div>
      }
      @case ('error') {
        <div class="caja" role="alert">
          <p>{{ mensaje() }}</p>
          <button type="button" class="boton" (click)="reintentar.emit()">Reintentar</button>
        </div>
      }
      @case ('empty') {
        <div class="caja" role="status">
          <p>{{ mensaje() }}</p>
          <ng-content />
        </div>
      }
    }
  `,
  styles: `
    .esqueletos {
      display: grid;
      gap: 0.75rem;
    }
    .esqueleto {
      height: 6rem;
      border-radius: var(--radio);
      background: linear-gradient(90deg, #e6ecf4 25%, #f3f6fa 50%, #e6ecf4 75%) 0 0 / 200% 100%;
      animation: brillo 1.4s infinite linear;
    }
    @keyframes brillo {
      to {
        background-position: -200% 0;
      }
    }
    .caja {
      padding: 2.5rem 1.5rem;
      text-align: center;
      border: 1px dashed var(--borde-fuerte);
      border-radius: var(--radio);
      background: var(--blanco);
    }
    .caja p {
      margin: 0 auto 1rem;
      max-width: 34rem;
      font-size: 1.05rem;
    }
  `,
})
export class EstadoVistaPanel {
  readonly estado = input.required<'loading' | 'empty' | 'error' | 'ready'>();
  readonly mensaje = input('');
  readonly reintentar = output<void>();
}
