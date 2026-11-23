import { Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { ErrorMapperService } from '../../core/errors/error-mapper.service';
import { NotificationService } from '../../core/ui/notification.service';
import { PASSWORD_MAX, VALIDADORES_EMAIL, passwordFuerte } from '../../core/validation/validators';
import { UserUpdate } from '../../models/user.model';
import { EstadoVista } from '../../models/vista.model';
import { DialogoConfirmar } from '../../shared/dialogo-confirmar';
import { EstadoVistaPanel } from '../../shared/estado-vista';
import { RequisitosPassword } from '../../shared/requisitos-password';

@Component({
  selector: 'app-perfil',
  imports: [ReactiveFormsModule, DialogoConfirmar, EstadoVistaPanel, RequisitosPassword],
  templateUrl: './perfil.html',
  styleUrl: './perfil.css',
})
export class Perfil {
  protected readonly auth = inject(AuthService);
  private readonly errores = inject(ErrorMapperService);
  private readonly avisos = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly fb = inject(NonNullableFormBuilder);

  protected readonly estado = signal<EstadoVista>('loading');
  protected readonly mensajeCarga = signal('');
  protected readonly guardando = signal(false);
  protected readonly errorForm = signal('');

  protected readonly dialogoAbierto = signal(false);
  protected readonly entiende = signal(false);
  protected readonly eliminando = signal(false);
  protected readonly errorEliminar = signal('');

  protected readonly form = this.fb.group({
    email: ['', [Validators.required, ...VALIDADORES_EMAIL]],
    new_password: ['', [passwordFuerte]],
    current_password: ['', [Validators.required, Validators.maxLength(PASSWORD_MAX)]],
  });
  protected readonly nueva = toSignal(this.form.controls.new_password.valueChanges, {
    initialValue: '',
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.estado.set('loading');
    this.auth.cargarPerfil().subscribe({
      next: (u) => {
        this.form.reset({ email: u.email });
        this.estado.set('ready');
      },
      error: (e: unknown) => {
        this.mensajeCarga.set(this.errores.mapear(e).mensaje);
        this.estado.set('error');
      },
    });
  }

  protected guardar(): void {
    this.form.markAllAsTouched();
    this.errorForm.set('');
    if (this.form.invalid || this.guardando()) return;

    const { email, new_password, current_password } = this.form.getRawValue();
    const cambios: UserUpdate = { current_password };
    if (email.trim().toLowerCase() !== this.auth.usuario()?.email) cambios.email = email.trim();
    if (new_password) cambios.new_password = new_password;
    if (cambios.email === undefined && cambios.new_password === undefined) {
      this.errorForm.set(
        'No hay cambios que guardar: modifica el correo o escribe una contraseña nueva.',
      );
      return;
    }
    this.guardando.set(true);
    this.auth.actualizarPerfil(cambios).subscribe({
      next: (u) => {
        this.form.reset({ email: u.email });
        this.guardando.set(false);
        this.avisos.exito('Tus datos se actualizaron.');
      },
      error: (e: unknown) => {
        this.errorForm.set(this.errores.mapear(e, 'perfil').mensaje);
        this.guardando.set(false);
      },
    });
  }

  protected abrirDialogo(): void {
    this.entiende.set(false);
    this.errorEliminar.set('');
    this.dialogoAbierto.set(true);
  }

  protected cerrarDialogo(): void {
    if (!this.eliminando()) this.dialogoAbierto.set(false);
  }

  protected eliminarCuenta(): void {
    if (!this.entiende() || this.eliminando()) return;
    this.eliminando.set(true);
    this.errorEliminar.set('');
    this.auth.eliminarCuenta().subscribe({
      next: () => {
        this.eliminando.set(false);
        this.dialogoAbierto.set(false);
        this.avisos.exito('Tu cuenta y tu historial fueron eliminados.');
        void this.router.navigateByUrl('/');
      },
      error: (e: unknown) => {
        this.eliminando.set(false);
        this.errorEliminar.set(this.errores.mapear(e).mensaje);
      },
    });
  }
}
