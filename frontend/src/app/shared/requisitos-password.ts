import { Component, computed, input } from '@angular/core';

import { REQUISITOS_PASSWORD } from '../core/validation/validators';

@Component({
  selector: 'app-requisitos-password',
  template: `
    <ul aria-label="Requisitos de la contraseña">
      @for (r of requisitos(); track r.id) {
        <li [class.ok]="r.ok">
          <span aria-hidden="true">{{ r.ok ? '✓' : '○' }}</span>
          {{ r.texto }}
          <span class="solo-lectores">{{ r.ok ? '(cumplido)' : '(pendiente)' }}</span>
        </li>
      }
    </ul>
  `,
  styles: `
    ul {
      list-style: none;
      margin: 0.4rem 0 0;
      padding: 0;
      font-size: 0.9rem;
      color: var(--texto-suave);
    }
    li span:first-child {
      display: inline-block;
      width: 1.1rem;
    }
    .ok {
      color: var(--verde);
      font-weight: 600;
    }
  `,
})
export class RequisitosPassword {
  readonly valor = input.required<string>();
  protected readonly requisitos = computed(() =>
    REQUISITOS_PASSWORD.map((r) => ({ id: r.id, texto: r.texto, ok: r.cumple(this.valor()) })),
  );
}
