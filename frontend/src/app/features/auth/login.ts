import { Component, inject, input, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { destinoSeguro } from '../../core/auth/auth.guard';
import { AuthService } from '../../core/auth/auth.service';
import { ErrorMapperService } from '../../core/errors/error-mapper.service';
import { PASSWORD_MAX } from '../../core/validation/validators';

@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <section class="tarjeta angosta">
      <h1>Iniciar sesión</h1>
      <p class="suave">Con una cuenta puedes guardar y corregir tus traducciones.</p>
      <form [formGroup]="form" (ngSubmit)="enviar()" novalidate>
        <div class="campo">
          <label for="username">Usuario</label>
          <input
            id="username"
            formControlName="username"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
          />
          @if (form.controls.username.touched && form.controls.username.invalid) {
            <p class="error-campo">Escribe tu usuario (hasta 50 caracteres).</p>
          }
        </div>
        <div class="campo">
          <label for="password">Contraseña</label>
          <input
            id="password"
            type="password"
            formControlName="password"
            autocomplete="current-password"
          />
          @if (form.controls.password.touched && form.controls.password.invalid) {
            <p class="error-campo">Escribe tu contraseña.</p>
          }
        </div>
        @if (error()) {
          <p class="alerta" role="alert">{{ error() }}</p>
        }
        <button class="boton ancho" type="submit" [disabled]="enviando()">
          {{ enviando() ? 'Ingresando…' : 'Ingresar' }}
        </button>
      </form>
      <p class="centro">
        ¿No tienes cuenta?
        <a routerLink="/registro" queryParamsHandling="preserve">Crear cuenta</a>
      </p>
    </section>
  `,
})
export class Login {
  /** Ruta de retorno (?volver=) que dejó el guard. */
  readonly volver = input<string>();

  private readonly auth = inject(AuthService);
  private readonly errores = inject(ErrorMapperService);
  private readonly router = inject(Router);
  private readonly fb = inject(NonNullableFormBuilder);

  protected readonly form = this.fb.group({
    username: ['', [Validators.required, Validators.maxLength(50)]],
    password: ['', [Validators.required, Validators.maxLength(PASSWORD_MAX)]],
  });
  protected readonly enviando = signal(false);
  protected readonly error = signal('');

  protected enviar(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.enviando()) return;
    this.enviando.set(true);
    this.error.set('');
    this.auth.login(this.form.getRawValue()).subscribe({
      next: () => void this.router.navigateByUrl(destinoSeguro(this.volver())),
      error: (e: unknown) => {
        this.error.set(this.errores.mapear(e, 'login').mensaje);
        this.enviando.set(false);
      },
    });
  }
}
