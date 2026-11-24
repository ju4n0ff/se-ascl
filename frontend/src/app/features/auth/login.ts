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
    <section class="tarjeta angosta tarjeta-auth">
      <div class="cabecera">
        <span class="sello" aria-hidden="true">Aa</span>
        <h1>Iniciar sesión</h1>
        <p class="suave">Con una cuenta puedes guardar y corregir tus traducciones.</p>
      </div>
      <form [formGroup]="form" (ngSubmit)="enviar()" novalidate>
        <div class="campo">
          <label for="username">Usuario</label>
          <input
            id="username"
            formControlName="username"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            [attr.aria-invalid]="form.controls.username.touched && form.controls.username.invalid"
            aria-describedby="error-username"
          />
          @if (form.controls.username.touched && form.controls.username.invalid) {
            <p class="error-campo" id="error-username">Escribe tu usuario (hasta 50 caracteres).</p>
          }
        </div>
        <div class="campo">
          <label for="password">Contraseña</label>
          <div class="campo-clave">
            <input
              id="password"
              [type]="verPassword() ? 'text' : 'password'"
              formControlName="password"
              autocomplete="current-password"
              [attr.aria-invalid]="form.controls.password.touched && form.controls.password.invalid"
              aria-describedby="error-password"
            />
            <button
              type="button"
              class="ver-clave"
              [attr.aria-label]="verPassword() ? 'Ocultar contraseña' : 'Mostrar contraseña'"
              [attr.aria-pressed]="verPassword()"
              (click)="alternarPassword()"
            >
              {{ verPassword() ? 'Ocultar' : 'Mostrar' }}
            </button>
          </div>
          @if (form.controls.password.touched && form.controls.password.invalid) {
            <p class="error-campo" id="error-password">Escribe tu contraseña.</p>
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
      <p class="centro suave pequeno">Traducir sin cuenta también es posible.</p>
    </section>
  `,
  styleUrl: './auth.css',
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
  protected readonly verPassword = signal(false);

  protected alternarPassword(): void {
    this.verPassword.update((visible) => !visible);
  }

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
