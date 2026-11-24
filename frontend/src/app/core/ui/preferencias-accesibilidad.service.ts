import { Injectable, effect, inject, signal } from '@angular/core';

import { PreferenciasGuardadas, SessionService } from '../auth/session.service';

export type EscalaTexto = 'normal' | 'grande' | 'extra';
export type NivelContraste = 'suave' | 'alto';
export type TemaColor = 'claro' | 'oscuro';

export interface PreferenciasAccesibilidadEstado {
  escala: EscalaTexto;
  contraste: NivelContraste;
  tema: TemaColor;
  reducirMovimiento: boolean;
  subrayarEnlaces: boolean;
  focoVisible: boolean;
}

const VALORES_ESCALA: readonly EscalaTexto[] = ['normal', 'grande', 'extra'];

@Injectable({ providedIn: 'root' })
export class PreferenciasAccesibilidad {
  private readonly sesion = inject(SessionService);

  private readonly _escala = signal<EscalaTexto>('normal');
  private readonly _contraste = signal<NivelContraste>('suave');
  private readonly _tema = signal<TemaColor>('claro');
  private readonly _reducirMovimiento = signal(false);
  private readonly _subrayarEnlaces = signal(false);
  private readonly _focoVisible = signal(true);

  readonly escala = this._escala.asReadonly();
  readonly contraste = this._contraste.asReadonly();
  readonly tema = this._tema.asReadonly();
  readonly reducirMovimiento = this._reducirMovimiento.asReadonly();
  readonly subrayarEnlaces = this._subrayarEnlaces.asReadonly();
  readonly focoVisible = this._focoVisible.asReadonly();
  readonly panelAbierto = signal(false);

  constructor() {
    this.restaurar(this.sesion.leerPreferencias());
    effect(() => {
      const estado = this.estado();
      this.aplicar(estado);
      this.sesion.guardarPreferencias(estado);
    });
  }

  cambiarEscala(valor: string): void {
    if (VALORES_ESCALA.includes(valor as EscalaTexto)) this._escala.set(valor as EscalaTexto);
  }

  cambiarContraste(valor: NivelContraste): void {
    this._contraste.set(valor);
  }

  cambiarTema(valor: TemaColor): void {
    this._tema.set(valor);
  }

  alternarTema(): void {
    this._tema.update((tema) => (tema === 'claro' ? 'oscuro' : 'claro'));
  }

  cambiarReducirMovimiento(valor: boolean): void {
    this._reducirMovimiento.set(valor);
  }

  cambiarSubrayarEnlaces(valor: boolean): void {
    this._subrayarEnlaces.set(valor);
  }

  cambiarFocoVisible(valor: boolean): void {
    this._focoVisible.set(valor);
  }

  restablecer(): void {
    this.restaurar({});
  }

  abrirPanel(): void {
    this.panelAbierto.set(true);
  }

  cerrarPanel(): void {
    this.panelAbierto.set(false);
  }

  alternarPanel(): void {
    this.panelAbierto.update((abierto) => !abierto);
  }

  private estado(): PreferenciasAccesibilidadEstado {
    return {
      escala: this.escala(),
      contraste: this.contraste(),
      tema: this.tema(),
      reducirMovimiento: this.reducirMovimiento(),
      subrayarEnlaces: this.subrayarEnlaces(),
      focoVisible: this.focoVisible(),
    };
  }

  private restaurar(guardadas: PreferenciasGuardadas): void {
    if (VALORES_ESCALA.includes(guardadas.escala as EscalaTexto)) {
      this._escala.set(guardadas.escala as EscalaTexto);
    }
    if (guardadas.contraste === 'suave' || guardadas.contraste === 'alto') {
      this._contraste.set(guardadas.contraste);
    }
    if (guardadas.tema === 'claro' || guardadas.tema === 'oscuro') {
      this._tema.set(guardadas.tema);
    }
    this._reducirMovimiento.set(guardadas.reducirMovimiento === true);
    this._subrayarEnlaces.set(guardadas.subrayarEnlaces === true);
    this._focoVisible.set(guardadas.focoVisible !== false);
  }

  private aplicar(estado: PreferenciasAccesibilidadEstado): void {
    if (typeof document === 'undefined') return;
    const datos = document.documentElement.dataset;
    datos['texto'] = estado.escala;
    datos['contraste'] = estado.contraste;
    datos['tema'] = estado.tema;
    datos['movimiento'] = estado.reducirMovimiento ? 'reducir' : 'normal';
    datos['subrayar'] = String(estado.subrayarEnlaces);
    datos['foco'] = estado.focoVisible ? 'mejorado' : 'basico';
  }
}
