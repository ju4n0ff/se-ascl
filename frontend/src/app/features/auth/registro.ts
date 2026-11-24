import { Component, inject, input, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { destinoSeguro } from '../../core/auth/auth.guard';
import { AuthService } from '../../core/auth/auth.service';
import { ErrorMapperService } from '../../core/errors/error-mapper.service';
import { NotificationService } from '../../core/ui/notification.service';
import {
  PATRON_USERNAME,
  VALIDADORES_EMAIL,
  passwordFuerte,
} from '../../core/validation/validators';
import { RequisitosPassword } from '../../shared/requisitos-password';

@Component({
  selector: 'app-registro',
  imports: [ReactiveFormsModule, RouterLink, RequisitosPassword],
  template: `
    <section class="tarjeta angosta tarjeta-auth">
      <div class="cabecera">
        <span class="sello" aria-hidden="true">Aa</span>
        <h1>Crear cuenta</h1>
        <p class="suave">
          Guardamos tu usuario, correo y traducciones. Nunca tu video ni los puntos de tu cuerpo.
        </p>
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
            aria-describedby="ayuda-username"
          />
          <p
            id="ayuda-username"
            [class]="
              form.controls.username.touched && form.controls.username.invalid
                ? 'error-campo'
                : 'ayuda'
            "
          >
            De 3 a 50 caracteres: letras sin tilde, números, punto, guion o guion bajo.
          </p>
        </div>
        <div class="campo">
          <label for="email">Correo</label>
          <input id="email" type="email" formControlName="email" autocomplete="email" />
          @if (form.controls.email.touched && form.controls.email.invalid) {
            <p class="error-campo">Escribe un correo válido, por ejemplo nombre&#64;correo.cl.</p>
          }
        </div>
        <div class="campo">
          <label for="password">Contraseña</label>
          <div class="campo-clave">
            <input
              id="password"
              [type]="verPassword() ? 'text' : 'password'"
              formControlName="password"
              autocomplete="new-password"
              [attr.aria-invalid]="form.controls.password.touched && form.controls.password.invalid"
              aria-describedby="requisitos-password"
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
          <div id="requisitos-password">
            <app-requisitos-password [valor]="password()" />
          </div>
          @if (form.controls.password.touched && form.controls.password.invalid) {
            <p class="error-campo">La contraseña aún no cumple los requisitos.</p>
          }
        </div>
        @if (error()) {
          <p class="alerta" role="alert">{{ error() }}</p>
        }
        <button class="boton ancho" type="submit" [disabled]="enviando()">
          {{ enviando() ? 'Creando cuenta…' : 'Crear cuenta' }}
        </button>
      </form>
      <p class="centro">
        ¿Ya tienes cuenta?
        <a routerLink="/login" queryParamsHandling="preserve">Iniciar sesión</a>
      </p>
    </section>
  `,
  styleUrl: './auth.css',
})
export class Registro {
  readonly volver = input<string>();

  private readonly auth = inject(AuthService);
  private readonly errores = inject(ErrorMapperService);
  private readonly avisos = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly fb = inject(NonNullableFormBuilder);

  protected readonly form = this.fb.group({
    username: ['', [Validators.required, Validators.pattern(PATRON_USERNAME)]],
    email: ['', [Validators.required, ...VALIDADORES_EMAIL]],
    password: ['', [Validators.required, passwordFuerte]],
  });
  protected readonly password = toSignal(this.form.controls.password.valueChanges, {
    initialValue: '',
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
    const datos = this.form.getRawValue();
    this.auth.registrar(datos).subscribe({
      next: () => this.ingresar(datos.username, datos.password),
      error: (e: unknown) => {
        this.error.set(this.errores.mapear(e, 'registro').mensaje);
        this.enviando.set(false);
      },
    });
  }

  /** La cuenta ya existe: si el ingreso automático falla, se pide ingresar a mano. */
  private ingresar(username: string, password: string): void {
    this.auth.login({ username, password }).subscribe({
      next: () => {
        this.avisos.exito('Tu cuenta está lista.');
        void this.router.navigateByUrl(destinoSeguro(this.volver()));
      },
      error: () => {
        this.avisos.info('Tu cuenta está lista. Ahora inicia sesión.');
        void this.router.navigate(['/login'], { queryParamsHandling: 'preserve' });
      },
    });
  }
}
