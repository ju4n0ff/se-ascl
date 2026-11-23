import { Component, inject } from '@angular/core';

import { FiltroGlosario, GlosarioService } from '../../services/glosario.service';
import { EstadoVistaPanel } from '../../shared/estado-vista';

@Component({
  selector: 'app-glosario',
  imports: [EstadoVistaPanel],
  providers: [GlosarioService],
  template: `
    <h1>Glosario de señas</h1>
    <p class="suave">
      Estas son las señas que SeñaCL reconoce hoy.
      @if (glosario.total()) {
        En total son {{ glosario.total() }}.
      }
    </p>
    <div class="filtros">
      <div class="campo">
        <label for="buscar">Buscar seña</label>
        <input
          #buscar
          id="buscar"
          type="search"
          placeholder="Por ejemplo: gracias"
          [value]="glosario.busqueda()"
          (input)="glosario.busqueda.set(buscar.value)"
        />
      </div>
      <div class="segmentos" role="group" aria-label="Filtrar señas">
        @for (f of filtros; track f.id) {
          <button
            type="button"
            [attr.aria-pressed]="glosario.filtro() === f.id"
            (click)="glosario.filtro.set(f.id)"
          >
            {{ f.texto }}
          </button>
        }
      </div>
    </div>
    @if (glosario.estado() === 'ready') {
      <p class="conteo" role="status">
        {{ glosario.visibles().length }}
        {{ glosario.visibles().length === 1 ? 'seña' : 'señas' }}
      </p>
      <ul class="rejilla">
        @for (c of glosario.visibles(); track c.indice) {
          <li [class.pregunta]="c.es_pregunta">{{ c.texto }}</li>
        }
      </ul>
    } @else {
      <app-estado-vista
        [estado]="glosario.estado()"
        [mensaje]="
          glosario.estado() === 'error'
            ? glosario.mensajeError()
            : 'Ninguna seña coincide con tu búsqueda.'
        "
        (reintentar)="glosario.cargar()"
      >
        <button type="button" class="boton secundario" (click)="limpiar()">Ver todas</button>
      </app-estado-vista>
    }
  `,
  styles: `
    .filtros {
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .campo {
      flex: 1 1 18rem;
      margin: 0;
    }
    .conteo {
      color: var(--texto-suave);
    }
    .rejilla {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
      gap: 0.75rem;
    }
    li {
      padding: 0.9rem 1rem;
      border-radius: 10px;
      border: 1px solid var(--borde);
      border-left: 4px solid var(--azul);
      background: var(--blanco);
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    li.pregunta {
      border-left-color: var(--coral);
      background: var(--coral-suave);
    }
  `,
})
export class Glosario {
  protected readonly glosario = inject(GlosarioService);
  protected readonly filtros: readonly { id: FiltroGlosario; texto: string }[] = [
    { id: 'todas', texto: 'Todas' },
    { id: 'preguntas', texto: 'Preguntas (¿…?)' },
    { id: 'afirmaciones', texto: 'Afirmaciones' },
  ];

  constructor() {
    this.glosario.cargar();
  }

  protected limpiar(): void {
    this.glosario.busqueda.set('');
    this.glosario.filtro.set('todas');
  }
}
