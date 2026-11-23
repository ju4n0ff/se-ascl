import { DatePipe, PercentPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ErrorMapperService } from '../../core/errors/error-mapper.service';
import { NotificationService } from '../../core/ui/notification.service';
import { TEXTO_MAX, textoHistorial } from '../../core/validation/validators';
import { HistoryEntry } from '../../models/history.model';
import { HistorialService } from '../../services/historial.service';
import { SpeechService } from '../../services/speech.service';
import { EstadoVistaPanel } from '../../shared/estado-vista';

@Component({
  selector: 'app-historial',
  imports: [DatePipe, PercentPipe, ReactiveFormsModule, RouterLink, EstadoVistaPanel],
  providers: [HistorialService],
  templateUrl: './historial.html',
  styleUrl: './historial.css',
})
export class Historial {
  protected readonly historial = inject(HistorialService);
  protected readonly voz = inject(SpeechService);
  private readonly errores = inject(ErrorMapperService);
  private readonly avisos = inject(NotificationService);

  protected readonly maximo = TEXTO_MAX;
  protected readonly editando = signal<number | null>(null);
  protected readonly confirmando = signal<number | null>(null);
  protected readonly errorEdicion = signal('');
  protected readonly form = inject(NonNullableFormBuilder).group({ texto: ['', textoHistorial] });
  protected readonly texto = this.form.controls.texto;

  constructor() {
    this.historial.cargar();
  }

  protected editar(entrada: HistoryEntry): void {
    this.confirmando.set(null);
    this.errorEdicion.set('');
    this.texto.reset(entrada.spanish_text);
    this.editando.set(entrada.id);
  }

  protected cancelarEdicion(): void {
    this.editando.set(null);
  }

  protected guardar(entrada: HistoryEntry): void {
    if (this.texto.invalid || this.historial.ocupada() !== null) return;
    if (this.texto.value.trim() === entrada.spanish_text) {
      this.cancelarEdicion();
      return;
    }
    this.errorEdicion.set('');
    this.historial.actualizarTexto(entrada.id, this.texto.value).subscribe({
      next: () => {
        this.editando.set(null);
        this.avisos.exito('Traducción corregida.');
      },
      error: (e: unknown) => {
        this.errorEdicion.set(this.errores.mapear(e, 'historial').mensaje);
        this.quitarSiNoExiste(e, entrada.id);
      },
    });
  }

  protected eliminar(entrada: HistoryEntry): void {
    this.historial.eliminar(entrada.id).subscribe({
      next: () => {
        this.confirmando.set(null);
        this.avisos.exito('Traducción eliminada de tu historial.');
      },
      error: (e: unknown) => {
        this.confirmando.set(null);
        this.avisos.error(this.errores.mapear(e, 'historial').mensaje);
        this.quitarSiNoExiste(e, entrada.id);
      },
    });
  }

  /** 404: otra pestaña ya la borró; la lista se alinea con el servidor. */
  private quitarSiNoExiste(error: unknown, id: number): void {
    if (!(error instanceof HttpErrorResponse) || error.status !== 404) return;
    if (this.editando() === id) {
      this.editando.set(null);
      this.avisos.error(this.errores.mapear(error, 'historial').mensaje);
    }
    this.historial.quitar(id);
  }
}
