import { Component, inject, signal } from '@angular/core';
import { take } from 'rxjs';

import { EstadoVistaPanel } from '../../shared/estado-vista';
import { ClaseInfo } from '../../models/meta.model';
import { FiltroGlosario, GlosarioService } from '../../services/glosario.service';
import { ReferenciaSena, ReferenciaSenaService } from '../../services/referencia-sena.service';

interface TarjetaReferencia {
  estado: 'cargando' | 'listo' | 'error';
  datos: ReferenciaSena | null;
  mensaje: string;
}

@Component({
  selector: 'app-glosario',
  imports: [EstadoVistaPanel],
  providers: [GlosarioService],
  template: `
    <h1>Glosario de señas</h1>
    <p class="suave">
      Explora el vocabulario del modelo, filtra por tipo y gira cada tarjeta para ver su referencia.
    </p>

    <div class="buscador tarjeta">
      <label for="buscar-seña">Buscar seña</label>
      <div class="campo-busqueda">
        <span aria-hidden="true">⌕</span>
        <input
          id="buscar-seña"
          #buscar
          type="search"
          autocomplete="off"
          placeholder="Por ejemplo: ¿Dónde está?"
          [value]="glosario.busqueda()"
          (input)="glosario.busqueda.set(buscar.value)"
        />
      </div>
      <div class="segmentos" role="group" aria-label="Filtrar por tipo de seña">
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
        <strong>{{ glosario.visibles().length }}</strong>
        {{ glosario.visibles().length === 1 ? 'seña encontrada' : 'señas encontradas' }} de
        {{ glosario.total() }}.
      </p>
      <div class="malla">
        @for (c of glosario.visibles(); track c.indice) {
          <article
            class="tarjeta-seña"
            [class.girada]="girada() === c.indice"
            [attr.aria-label]="'Seña ' + c.texto"
          >
            <div class="cara frente" [attr.inert]="girada() === c.indice ? '' : null">
              <div class="etiquetas">
                <span class="numero">#{{ c.indice + 1 }}</span>
                <span class="tipo">{{ c.es_pregunta ? 'Pregunta' : 'Afirmación' }}</span>
              </div>
              <h2>{{ c.texto }}</h2>
              <p class="sugerencia">Gira para ver cómo se ejecuta.</p>
              <button
                type="button"
                class="boton"
                [attr.aria-expanded]="girada() === c.indice"
                [attr.aria-controls]="'referencia-' + c.indice"
                (click)="alternar(c)"
              >
                Ver cómo se hace
              </button>
            </div>

            <div
              class="cara dorso"
              id="referencia-{{ c.indice }}"
              [attr.inert]="girada() === c.indice ? null : ''"
              [attr.aria-hidden]="girada() !== c.indice"
            >
              <div class="dorso-cabecera">
                <span class="tipo">{{ c.texto }}</span>
                <button type="button" class="cerrar" aria-label="Volver a la seña" (click)="cerrar()">
                  ×
                </button>
              </div>
              @if (referencia(c.indice); as tarjeta) {
                @switch (tarjeta.estado) {
                  @case ('cargando') {
                    <div class="esqueleto" role="status" aria-label="Cargando referencia">
                      <span></span><span></span><span></span>
                    </div>
                  }
                  @case ('error') {
                    <p class="mensaje-error" role="alert">{{ tarjeta.mensaje }}</p>
                    <button type="button" class="boton secundario" (click)="cargarReferencia(c, true)">
                      Reintentar
                    </button>
                  }
                  @case ('listo') {
                    @if (tarjeta.datos; as datos) {
                      <img
                        [src]="datos.imagenUrl"
                        [alt]="'Ilustración de la seña ' + datos.termino"
                        loading="lazy"
                      />
                      @if (datos.estado === 'pendiente') {
                        <p class="pendiente">Referencia pendiente</p>
                      }
                      <p class="descripcion">{{ datos.descripcion }}</p>
                      <p class="fuente">{{ datos.fuente }}</p>
                      @if (datos.videoUrl) {
                        <video [src]="datos.videoUrl" controls playsinline></video>
                      }
                    }
                  }
                }
              }
            </div>
          </article>
        }
      </div>
    } @else {
      <div class="tarjeta estado">
        <app-estado-vista
          [estado]="glosario.estado()"
          [mensaje]="
            glosario.estado() === 'error'
              ? glosario.mensajeError()
              : 'No encontramos señas con ese texto. Prueba otra palabra.'
          "
          (reintentar)="glosario.cargar()"
        />
      </div>
    }
  `,
  styleUrl: './glosario.css',
})
export class Glosario {
  protected readonly glosario = inject(GlosarioService);
  private readonly referenciasSena = inject(ReferenciaSenaService);

  protected readonly filtros: readonly { id: FiltroGlosario; texto: string }[] = [
    { id: 'todas', texto: 'Todas' },
    { id: 'preguntas', texto: 'Preguntas (¿…?)' },
    { id: 'afirmaciones', texto: 'Afirmaciones' },
  ];

  protected readonly girada = signal<number | null>(null);
  protected readonly referencias = signal<Record<number, TarjetaReferencia>>({});

  constructor() {
    this.glosario.cargar();
  }

  protected referencia(indice: number): TarjetaReferencia | undefined {
    return this.referencias()[indice];
  }

  protected alternar(c: ClaseInfo): void {
    if (this.girada() === c.indice) {
      this.cerrar();
      return;
    }
    this.girada.set(c.indice);
    this.cargarReferencia(c);
  }

  protected cerrar(): void {
    this.girada.set(null);
  }

  protected cargarReferencia(c: ClaseInfo, forzar = false): void {
    const actual = this.referencias()[c.indice];
    if (!forzar && (actual?.estado === 'cargando' || actual?.estado === 'listo')) return;
    this.referencias.update((mapa) => ({
      ...mapa,
      [c.indice]: { estado: 'cargando', datos: null, mensaje: '' },
    }));
    this.referenciasSena
      .obtenerReferenciaSena(c.texto)
      .pipe(take(1))
      .subscribe({
        next: (datos) =>
          this.referencias.update((mapa) => ({
            ...mapa,
            [c.indice]: { estado: 'listo', datos, mensaje: '' },
          })),
        error: () =>
          this.referencias.update((mapa) => ({
            ...mapa,
            [c.indice]: {
              estado: 'error',
              datos: null,
              mensaje: 'No se pudo cargar la referencia. Revisa tu conexión e inténtalo de nuevo.',
            },
          })),
      });
  }
}
