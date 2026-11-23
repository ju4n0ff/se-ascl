import { Injectable } from '@angular/core';

const RESTRICCIONES: MediaStreamConstraints = {
  audio: false,
  // 640x480 es la resolución de conversor/test_local.py; "ideal" admite otras cámaras.
  video: {
    facingMode: 'user',
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 30 },
  },
};

const MENSAJES: Record<string, string> = {
  NotAllowedError:
    'No tenemos permiso para usar la cámara. Actívalo en el candado de la barra de direcciones y vuelve a intentar.',
  NotFoundError: 'No encontramos ninguna cámara conectada a este equipo.',
  NotReadableError: 'La cámara está siendo usada por otra aplicación. Ciérrala e intenta de nuevo.',
  OverconstrainedError: 'La cámara no es compatible. Prueba con otra.',
  SecurityError: 'El navegador bloqueó la cámara por seguridad. Usa https:// o localhost.',
};

/** Acceso a la cámara. El flujo se muestra en un <video> local y nunca se transmite. */
@Injectable({ providedIn: 'root' })
export class CameraService {
  private flujo: MediaStream | null = null;

  /** `alPerder` avisa si el usuario desconecta la cámara o retira el permiso. */
  async iniciar(video: HTMLVideoElement, alPerder: () => void): Promise<void> {
    if (!globalThis.navigator?.mediaDevices?.getUserMedia) {
      throw new DOMException('sin soporte', 'SecurityError');
    }
    this.detener(video);
    const flujo = await navigator.mediaDevices.getUserMedia(RESTRICCIONES);
    this.flujo = flujo;
    flujo.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (this.flujo === flujo) alPerder();
    });
    video.srcObject = flujo;
    await video.play();
  }

  detener(video: HTMLVideoElement | null): void {
    this.flujo?.getTracks().forEach((t) => t.stop());
    this.flujo = null;
    if (video) video.srcObject = null;
  }

  mensajeDe(error: unknown): string {
    const nombre = error instanceof DOMException ? error.name : '';
    return MENSAJES[nombre] ?? 'No pudimos iniciar la cámara. Intenta de nuevo.';
  }
}
