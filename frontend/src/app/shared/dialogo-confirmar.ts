import { Component, ElementRef, effect, input, output, viewChild } from '@angular/core';

/** Modal nativo (<dialog>): foco atrapado y cierre con Escape incluidos. */
@Component({
  selector: 'app-dialogo-confirmar',
  template: `
    <dialog
      #dialogo
      aria-labelledby="dlg-titulo"
      (cancel)="alCancelar($event)"
      (close)="cancelar.emit()"
    >
      <h2 id="dlg-titulo">{{ titulo() }}</h2>
      <ng-content />
      <div class="acciones">
        <button
          type="button"
          class="boton secundario"
          [disabled]="ocupado()"
          (click)="cancelar.emit()"
        >
          Cancelar
        </button>
        <button
          type="button"
          class="boton peligro"
          [disabled]="ocupado() || !habilitado()"
          (click)="confirmar.emit()"
        >
          {{ ocupado() ? 'Procesando…' : accion() }}
        </button>
      </div>
    </dialog>
  `,
  styles: `
    dialog {
      width: min(32rem, calc(100vw - 2rem));
      padding: 1.5rem;
      border: 1px solid var(--arena);
      border-radius: var(--radio-grande);
      background: var(--superficie);
      color: var(--texto);
      box-shadow: var(--sombra);
    }
    dialog::backdrop {
      background: rgb(var(--cafe-profundo-rgb) / 0.6);
    }
    h2 {
      margin-top: 0;
    }
    .acciones {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 0.75rem;
      margin-top: 1.5rem;
    }
  `,
})
export class DialogoConfirmar {
  readonly abierto = input.required<boolean>();
  readonly titulo = input.required<string>();
  readonly accion = input('Confirmar');
  readonly habilitado = input(true);
  readonly ocupado = input(false);
  readonly confirmar = output<void>();
  readonly cancelar = output<void>();

  private readonly dialogo = viewChild.required<ElementRef<HTMLDialogElement>>('dialogo');

  constructor() {
    effect(() => {
      const el = this.dialogo().nativeElement;
      if (this.abierto() && !el.open) el.showModal();
      else if (!this.abierto() && el.open) el.close();
    });
  }

  protected alCancelar(evento: Event): void {
    if (this.ocupado()) evento.preventDefault();
  }
}
