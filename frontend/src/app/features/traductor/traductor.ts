import { PercentPipe } from '@angular/common';
import { Component, ElementRef, computed, inject, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { ModoCaptura } from '../../models/ws.model';
import { BackendStatusService } from '../../services/backend-status.service';
import { MediaPipeService } from '../../services/mediapipe.service';
import { SpeechService } from '../../services/speech.service';
import { TraductorService } from '../../services/traductor.service';
import { WsRecognitionService } from '../../services/ws-recognition.service';

const ELEMENTOS_CON_TECLADO = 'input, textarea, select, button, a, [contenteditable]';

@Component({
  selector: 'app-traductor',
  imports: [PercentPipe, RouterLink],
  providers: [WsRecognitionService, TraductorService],
  templateUrl: './traductor.html',
  styleUrl: './traductor.css',
  host: { '(document:keydown.space)': 'alEspacio($event)' },
})
export class Traductor {
  protected readonly t = inject(TraductorService);
  protected readonly auth = inject(AuthService);
  protected readonly voz = inject(SpeechService);
  protected readonly motor = inject(MediaPipeService);
  protected readonly backend = inject(BackendStatusService);

  private readonly video = viewChild.required<ElementRef<HTMLVideoElement>>('video');
  private readonly lienzo = viewChild.required<ElementRef<HTMLCanvasElement>>('lienzo');

  protected readonly modos: readonly { id: ModoCaptura; texto: string }[] = [
    { id: 'auto', texto: 'Automático' },
    { id: 'manual', texto: 'Manual' },
  ];
  protected readonly textoCarga = computed(() =>
    this.motor.estado() === 'cargando'
      ? 'Cargando el detector de señas. La primera vez descarga unos 30 MB…'
      : 'Iniciando la cámara…',
  );

  protected alternarCamara(): void {
    if (this.t.fase() === 'activo' || this.t.fase() === 'cargando') this.t.detener();
    else void this.t.iniciar(this.video().nativeElement, this.lienzo().nativeElement);
  }

  protected alEspacio(evento: Event): void {
    const destino = evento.target as Element | null;
    if (
      (evento as KeyboardEvent).repeat ||
      !this.t.puedeGrabar() ||
      destino?.closest?.(ELEMENTOS_CON_TECLADO)
    ) {
      return; // en un botón o campo, Espacio conserva su función normal
    }
    evento.preventDefault();
    this.t.alternarGrabacion();
  }
}
