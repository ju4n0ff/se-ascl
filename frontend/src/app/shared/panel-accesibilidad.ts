import {
  Component,
  ElementRef,
  HostListener,
  effect,
  inject,
  viewChild,
} from '@angular/core';

import {
  NivelContraste,
  PreferenciasAccesibilidad,
  TemaColor,
} from '../core/ui/preferencias-accesibilidad.service';

@Component({
  selector: 'app-panel-accesibilidad',
  template: `
    <dialog
      #dialogo
      class="panel-accesibilidad"
      aria-labelledby="accesibilidad-titulo"
      (close)="prefs.cerrarPanel()"
    >
      <div class="cabecera">
        <div>
          <h2 id="accesibilidad-titulo">Accesibilidad</h2>
          <p class="suave">Ajusta la lectura y el movimiento a tu manera.</p>
        </div>
        <button type="button" class="cerrar" aria-label="Cerrar panel" (click)="prefs.cerrarPanel()">
          ×
        </button>
      </div>

      <div class="campo">
        <label for="escala-texto">Tamaño de texto</label>
        <select
          id="escala-texto"
          #escala
          [value]="prefs.escala()"
          (change)="prefs.cambiarEscala(escala.value)"
        >
          <option value="normal">Normal</option>
          <option value="grande">Grande</option>
          <option value="extra">Extra grande</option>
        </select>
      </div>

      <fieldset>
        <legend>Contraste</legend>
        <div class="segmentos">
          @for (opcion of contrastes; track opcion.id) {
            <button
              type="button"
              [attr.aria-pressed]="prefs.contraste() === opcion.id"
              (click)="prefs.cambiarContraste(opcion.id)"
            >
              {{ opcion.texto }}
            </button>
          }
        </div>
      </fieldset>

      <fieldset>
        <legend>Apariencia</legend>
        <div class="segmentos">
          @for (opcion of temas; track opcion.id) {
            <button
              type="button"
              [attr.aria-pressed]="prefs.tema() === opcion.id"
              (click)="prefs.cambiarTema(opcion.id)"
            >
              {{ opcion.texto }}
            </button>
          }
        </div>
      </fieldset>

      <div class="interruptores">
        <label class="interruptor">
          <input
            #reducir
            type="checkbox"
            role="switch"
            [checked]="prefs.reducirMovimiento()"
            (change)="prefs.cambiarReducirMovimiento(reducir.checked)"
          />
          Reducir movimiento y animaciones
        </label>
        <label class="interruptor">
          <input
            #subrayar
            type="checkbox"
            role="switch"
            [checked]="prefs.subrayarEnlaces()"
            (change)="prefs.cambiarSubrayarEnlaces(subrayar.checked)"
          />
          Subrayar enlaces
        </label>
        <label class="interruptor">
          <input
            #foco
            type="checkbox"
            role="switch"
            [checked]="prefs.focoVisible()"
            (change)="prefs.cambiarFocoVisible(foco.checked)"
          />
          Foco de teclado reforzado
        </label>
      </div>

      <div class="acciones">
        <button type="button" class="boton secundario" (click)="prefs.restablecer()">
          Restablecer
        </button>
        <button type="button" class="boton" (click)="prefs.cerrarPanel()">Listo</button>
      </div>
      <p class="suave atajo">También puedes abrir este panel con Alt + A.</p>
    </dialog>
  `,
  styles: `
    .panel-accesibilidad {
      width: min(34rem, calc(100vw - 2rem));
      max-height: min(44rem, calc(100dvh - 2rem));
      overflow: auto;
      padding: 1.5rem;
      border: 1px solid var(--arena);
      border-radius: var(--radio-grande);
      background: var(--superficie);
      color: var(--texto);
      box-shadow: var(--sombra);
    }
    .panel-accesibilidad::backdrop {
      background: rgb(var(--cafe-profundo-rgb) / 0.55);
    }
    .cabecera {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
    }
    .cabecera h2 {
      margin: 0;
    }
    .cabecera p {
      margin: 0.25rem 0 1rem;
    }
    .cerrar {
      min-width: 44px;
      min-height: 44px;
      border: 1px solid var(--borde);
      border-radius: 50%;
      background: var(--crema);
      color: var(--cafe);
      font-size: 1.5rem;
      cursor: pointer;
    }
    fieldset {
      margin: 0 0 1rem;
      padding: 0;
      border: 0;
    }
    legend {
      margin-bottom: 0.4rem;
      font-weight: 700;
    }
    .interruptores {
      display: grid;
      gap: 0.6rem;
      padding: 0.9rem;
      border-radius: var(--radio);
      background: var(--crema);
    }
    .interruptor {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      min-height: 44px;
    }
    .interruptor input {
      width: 1.25rem;
      height: 1.25rem;
      accent-color: var(--oliva);
    }
    .acciones {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 0.6rem;
      margin-top: 1.2rem;
    }
    .atajo {
      margin: 0.75rem 0 0;
      font-size: 0.85rem;
    }
  `,
})
export class PanelAccesibilidad {
  protected readonly prefs = inject(PreferenciasAccesibilidad);

  protected readonly contrastes: readonly { id: NivelContraste; texto: string }[] = [
    { id: 'suave', texto: 'Suave' },
    { id: 'alto', texto: 'Alto' },
  ];
  protected readonly temas: readonly { id: TemaColor; texto: string }[] = [
    { id: 'claro', texto: 'Claro' },
    { id: 'oscuro', texto: 'Oscuro cálido' },
  ];

  private readonly dialogo = viewChild<ElementRef<HTMLDialogElement>>('dialogo');

  constructor() {
    effect(() => {
      const elemento = this.dialogo()?.nativeElement;
      if (!elemento) return;
      if (this.prefs.panelAbierto() && !elemento.open) elemento.showModal();
      if (!this.prefs.panelAbierto() && elemento.open) elemento.close();
    });
  }

  @HostListener('document:keydown', ['$event'])
  protected atajo(evento: KeyboardEvent): void {
    if (evento.altKey && evento.key.toLowerCase() === 'a') {
      evento.preventDefault();
      this.prefs.alternarPanel();
    }
  }
}
