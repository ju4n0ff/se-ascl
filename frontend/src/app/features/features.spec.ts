import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { registerLocaleData } from '@angular/common';
import localeEsCl from '@angular/common/locales/es-CL';
import { LOCALE_ID, Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { authInterceptor } from '../core/auth/auth.interceptor';
import { SessionService } from '../core/auth/session.service';
import { API_CONFIG, crearApiConfig } from '../core/config/api.config';
import { jwtDePrueba } from '../testing/jwt';
import { Login } from './auth/login';
import { Registro } from './auth/registro';
import { Historial } from './historial/historial';
import { Perfil } from './perfil/perfil';
import { Traductor } from './traductor/traductor';

const API = 'https://api.test';
registerLocaleData(localeEsCl);

describe('vistas', () => {
  let control: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: LOCALE_ID, useValue: 'es-CL' },
        {
          provide: API_CONFIG,
          useValue: crearApiConfig({ apiUrl: API, wsUrl: 'wss://api.test/ws' }),
        },
      ],
    });
    control = TestBed.inject(HttpTestingController);
    // jsdom no implementa <dialog>.
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
      this.open = true;
    };
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
      this.open = false;
    };
  });

  async function crear<T>(tipo: Type<T>) {
    const f: ComponentFixture<T> = TestBed.createComponent(tipo);
    await f.whenStable();
    const el = f.nativeElement as HTMLElement;
    return {
      el,
      texto: () => el.textContent ?? '',
      boton: (t: string) =>
        [...el.querySelectorAll('button')].find((b) => b.textContent?.includes(t))!,
      escribir: async (sel: string, valor: string) => {
        const i = el.querySelector<HTMLInputElement>(sel)!;
        i.value = valor;
        i.dispatchEvent(new Event('input'));
        i.dispatchEvent(new Event('blur'));
        await f.whenStable();
      },
      clic: async (b: HTMLElement) => {
        b.click();
        await f.whenStable();
      },
      estable: () => f.whenStable(),
    };
  }

  it('login: valida en cliente y muestra 401 y 429 legibles', async () => {
    const v = await crear(Login);
    await v.clic(v.boton('Ingresar'));
    expect(v.texto()).toContain('Escribe tu usuario');
    control.expectNone(`${API}/api/auth/login`);
    await v.escribir('#username', 'ana');
    await v.escribir('#password', 'x');
    await v.clic(v.boton('Ingresar'));
    control
      .expectOne(`${API}/api/auth/login`)
      .flush({ detail: 'Credenciales inválidas' }, { status: 401, statusText: 'x' });
    await v.estable();
    expect(v.texto()).toContain('Credenciales inválidas');
    await v.clic(v.boton('Ingresar'));
    control
      .expectOne(`${API}/api/auth/login`)
      .flush({}, { status: 429, statusText: 'x', headers: { 'Retry-After': '30' } });
    await v.estable();
    expect(v.texto()).toContain('espera 30 segundos');
  });

  it('registro: checklist en vivo y 409 genérico', async () => {
    const v = await crear(Registro);
    await v.escribir('#username', 'ana');
    await v.escribir('#email', 'ana@example.com');
    await v.escribir('#password', 'abc');
    expect(v.el.querySelectorAll('li.ok').length).toBe(1);
    await v.clic(v.boton('Crear cuenta'));
    control.expectNone(`${API}/api/auth/register`);
    await v.escribir('#password', 'Clave1234');
    expect(v.el.querySelectorAll('li.ok').length).toBe(4);
    await v.clic(v.boton('Crear cuenta'));
    control.expectOne(`${API}/api/auth/register`).flush({}, { status: 409, statusText: 'x' });
    await v.estable();
    expect(v.texto()).toContain('El usuario o correo ya está registrado');
  });

  it('historial: error con reintento, edición y borrado con confirmación', async () => {
    TestBed.inject(SessionService).iniciar(jwtDePrueba());
    const url = `${API}/api/history/me?limit=50`;
    const v = await crear(Historial);
    expect(v.texto()).toContain('Cargando');
    control.expectOne(url).flush({}, { status: 503, statusText: 'x' });
    await v.estable();
    await v.clic(v.boton('Reintentar'));
    control.expectOne(url).flush([
      {
        id: 9,
        user_id: 1,
        predicted_label: 'hola',
        spanish_text: 'hola',
        confidence: 0.91,
        mode: 'dynamic',
        created_at: '2026-11-23T12:00:00Z',
      },
    ]);
    await v.estable();
    expect(v.texto()).toContain('91%');
    expect(v.texto()).toContain('2026');

    await v.clic(v.boton('Corregir'));
    await v.escribir('textarea', '   ');
    expect(v.boton('Guardar').disabled).toBe(true);
    await v.escribir('textarea', 'hola a todos');
    await v.clic(v.boton('Guardar'));
    const r = control.expectOne(`${API}/api/history/9`);
    expect(r.request.method).toBe('PATCH');
    r.flush({
      id: 9,
      user_id: 1,
      predicted_label: 'hola',
      spanish_text: 'hola a todos',
      confidence: 0.91,
      mode: 'dynamic',
      created_at: '2026-11-23T12:00:00Z',
    });
    await v.estable();
    expect(v.texto()).toContain('hola a todos');

    await v.clic(v.boton('Eliminar'));
    control.expectNone(`${API}/api/history/9`);
    await v.clic(v.boton('Sí, eliminar'));
    control.expectOne(`${API}/api/history/9`).flush(null, { status: 204, statusText: 'x' });
    await v.estable();
    expect(v.texto()).toContain('Aún no tienes traducciones');
  });

  it('perfil: exige contraseña actual y confirma antes de borrar la cuenta', async () => {
    const sesion = TestBed.inject(SessionService);
    sesion.iniciar(jwtDePrueba());
    const v = await crear(Perfil);
    const url = `${API}/api/users/me`;
    control.expectOne(url).flush({ id: 1, username: 'ana', email: 'ana@example.com' });
    await v.estable();

    await v.clic(v.boton('Guardar cambios'));
    control.expectNone(url);
    await v.escribir('#current_password', 'Clave1234');
    await v.clic(v.boton('Guardar cambios'));
    expect(v.texto()).toContain('No hay cambios');
    await v.escribir('#email', 'nuevo@example.com');
    await v.clic(v.boton('Guardar cambios'));
    const r = control.expectOne(url);
    expect(r.request.body).toEqual({ current_password: 'Clave1234', email: 'nuevo@example.com' });
    r.flush({ detail: 'Credenciales inválidas' }, { status: 401, statusText: 'x' });
    await v.estable();
    expect(v.texto()).toContain('contraseña actual no es correcta');
    expect(sesion.autenticado()).toBe(true);

    await v.clic(v.boton('Eliminar mi cuenta'));
    const definitivo = v.boton('Eliminar definitivamente');
    expect(definitivo.disabled).toBe(true);
    const casilla = v.el.querySelector<HTMLInputElement>('dialog input')!;
    casilla.checked = true;
    casilla.dispatchEvent(new Event('change'));
    await v.estable();
    await v.clic(definitivo);
    const borrado = control.expectOne(url);
    expect(borrado.request.method).toBe('DELETE');
    borrado.flush(null, { status: 204, statusText: 'x' });
    await v.estable();
    expect(sesion.autenticado()).toBe(false);
  });

  it('traductor: accesible sin cuenta, con espejo solo CSS y guardar deshabilitado', async () => {
    const v = await crear(Traductor);
    expect(v.texto()).toContain('Solo se envían landmarks — nunca video');
    expect(v.el.querySelector('.espejo video')).not.toBeNull();
    const guardar = [...v.el.querySelectorAll('label')].find((l) =>
      l.textContent?.includes('Guardar en mi historial'),
    )!;
    expect(guardar.querySelector('input')!.disabled).toBe(true);
    expect(v.texto()).toContain('inicia sesión');
    // Sin getUserMedia (jsdom) el error es legible.
    await v.clic(v.boton('Iniciar cámara'));
    await v.estable();
    expect(v.texto()).toContain('bloqueó la cámara por seguridad');
    expect(v.boton('Probar conexión')).toBeTruthy();
  });

  it('traductor: el botón Grabar solo aparece en modo manual', async () => {
    const v = await crear(Traductor);
    expect(v.boton('Grabar seña')).toBeUndefined();
    await v.clic(v.boton('Manual'));
    expect(v.boton('Grabar seña').disabled).toBe(true);
  });
});
