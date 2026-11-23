import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';

import { UsersApiService } from '../../services/users-api.service';
import { jwtDePrueba } from '../../testing/jwt';
import { API_CONFIG, crearApiConfig } from '../config/api.config';
import { authGuard, destinoSeguro, invitadoGuard } from './auth.guard';
import { authInterceptor, esUrlDeApi } from './auth.interceptor';
import { AuthService } from './auth.service';
import { SessionService, expiracionMs } from './session.service';

const API = 'https://api.test';
const PERFIL = { id: 1, username: 'ana', email: 'ana@example.com' };

function preparar(): void {
  sessionStorage.clear();
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([authInterceptor])),
      provideHttpClientTesting(),
      {
        provide: API_CONFIG,
        useValue: crearApiConfig({ apiUrl: API, wsUrl: 'wss://api.test/ws' }),
      },
    ],
  });
}

describe('authInterceptor', () => {
  let http: HttpClient;
  let control: HttpTestingController;
  let sesion: SessionService;

  beforeEach(() => {
    preparar();
    http = TestBed.inject(HttpClient);
    control = TestBed.inject(HttpTestingController);
    sesion = TestBed.inject(SessionService);
  });
  afterEach(() => control.verify());

  it('adjunta Bearer a las rutas del backend', () => {
    const token = jwtDePrueba();
    sesion.iniciar(token);
    http.get(`${API}/api/users/me`).subscribe();
    const r = control.expectOne(`${API}/api/users/me`);
    expect(r.request.headers.get('Authorization')).toBe(`Bearer ${token}`);
    expect(r.request.urlWithParams).not.toContain(token);
    r.flush(PERFIL);
  });

  it.each([
    'https://otro.test/api/users/me',
    'https://api.test.evil.example/api/users/me',
    'https://api.test@evil.example/api',
    'http://api.test/api/users/me',
    '/assets/algo.json',
  ])('no filtra el token a %s', (url) => {
    sesion.iniciar(jwtDePrueba());
    http.get(url).subscribe();
    const r = control.expectOne(url);
    expect(r.request.headers.has('Authorization')).toBe(false);
    r.flush({});
  });

  it('sin sesión no agrega cabecera', () => {
    http.get(`${API}/api/clases`).subscribe();
    const r = control.expectOne(`${API}/api/clases`);
    expect(r.request.headers.has('Authorization')).toBe(false);
    r.flush({});
  });

  it('401 limpia la sesión y avisa una vez', () => {
    sesion.iniciar(jwtDePrueba());
    let avisos = 0;
    sesion.expirada$.subscribe(() => avisos++);
    for (const ruta of ['a', 'b'])
      http.get(`${API}/api/${ruta}`).subscribe({ error: () => undefined });
    for (const ruta of ['a', 'b']) {
      control
        .expectOne(`${API}/api/${ruta}`)
        .flush({ detail: 'No autenticado' }, { status: 401, statusText: 'x' });
    }
    expect(sesion.autenticado()).toBe(false);
    expect(sessionStorage.length).toBe(0);
    expect(avisos).toBe(1);
  });

  it.each([403, 404, 409, 422, 429, 500])('%d no cierra la sesión', (status) => {
    sesion.iniciar(jwtDePrueba());
    http.get(`${API}/api/x`).subscribe({ error: () => undefined });
    control.expectOne(`${API}/api/x`).flush({}, { status, statusText: 'x' });
    expect(sesion.autenticado()).toBe(true);
  });

  it('un 401 tardío del token anterior no cierra la sesión nueva', () => {
    sesion.iniciar(jwtDePrueba(3600, '1'));
    http.get(`${API}/api/x`).subscribe({ error: () => undefined });
    sesion.iniciar(jwtDePrueba(3600, '2'));
    control.expectOne(`${API}/api/x`).flush({}, { status: 401, statusText: 'x' });
    expect(sesion.autenticado()).toBe(true);
  });

  it('contraseña actual incorrecta no cierra la sesión; token vencido sí', () => {
    const users = TestBed.inject(UsersApiService);
    const intentar = (detail: string) => {
      users
        .actualizar({ current_password: 'x', email: 'a@b.cl' })
        .subscribe({ error: () => undefined });
      control.expectOne(`${API}/api/users/me`).flush({ detail }, { status: 401, statusText: 'x' });
    };
    sesion.iniciar(jwtDePrueba());
    intentar('Credenciales inválidas');
    expect(sesion.autenticado()).toBe(true);
    intentar('No autenticado');
    expect(sesion.autenticado()).toBe(false);
  });

  it('esUrlDeApi exige el límite de ruta', () => {
    expect(esUrlDeApi(`${API}/api/x`, API)).toBe(true);
    expect(esUrlDeApi(`${API}x/api`, API)).toBe(false);
  });
});

describe('SessionService', () => {
  beforeEach(() => sessionStorage.clear());

  it('sobrevive a recargar la página', () => {
    const token = jwtDePrueba();
    new SessionService().iniciar(token);
    const tras = new SessionService();
    expect(tras.token()).toBe(token);
    tras.cerrar();
    expect(new SessionService().autenticado()).toBe(false);
  });

  it.each(['', 'basura', 'a.b.c', jwtDePrueba(-10)])('descarta el token guardado %j', (token) => {
    sessionStorage.setItem('senacl.token', token);
    expect(new SessionService().autenticado()).toBe(false);
  });

  it('no usa localStorage', () => {
    localStorage.clear();
    new SessionService().iniciar(jwtDePrueba());
    expect(localStorage.length).toBe(0);
  });

  it('expira sola cuando vence el JWT', () => {
    vi.useFakeTimers();
    const s = new SessionService();
    const expirada = vi.fn();
    s.expirada$.subscribe(expirada);
    s.iniciar(jwtDePrueba(60));
    vi.advanceTimersByTime(61_000);
    expect(s.autenticado()).toBe(false);
    expect(expirada).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it('cerrar a pedido no se informa como expiración', () => {
    const s = new SessionService();
    const expirada = vi.fn();
    s.expirada$.subscribe(expirada);
    s.iniciar(jwtDePrueba());
    s.cerrar();
    expect(expirada).not.toHaveBeenCalled();
  });

  it('funciona en memoria si el almacenamiento está bloqueado', () => {
    const espia = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('bloqueado');
    });
    const s = new SessionService();
    s.iniciar(jwtDePrueba());
    expect(s.autenticado()).toBe(true);
    espia.mockRestore();
  });

  it('lee exp en base64url', () => {
    expect(expiracionMs(jwtDePrueba(100))).toBeGreaterThan(Date.now());
    expect(expiracionMs('x.eyJzdWIiOiIxIn0.y')).toBeNull();
  });
});

describe('AuthService', () => {
  let auth: AuthService;
  let control: HttpTestingController;

  beforeEach(() => {
    preparar();
    auth = TestBed.inject(AuthService);
    control = TestBed.inject(HttpTestingController);
  });
  afterEach(() => control.verify());

  it('login guarda el token y permite cargar el perfil', () => {
    auth.login({ username: 'ana', password: 'Clave1234' }).subscribe();
    const r = control.expectOne(`${API}/api/auth/login`);
    expect(r.request.body).toEqual({ username: 'ana', password: 'Clave1234' });
    r.flush({ access_token: jwtDePrueba(), token_type: 'bearer' });
    expect(auth.autenticado()).toBe(true);
    auth.cargarPerfil().subscribe();
    control.expectOne(`${API}/api/users/me`).flush(PERFIL);
    expect(auth.usuario()).toEqual(PERFIL);
  });

  it('login fallido no crea sesión', () => {
    auth.login({ username: 'ana', password: 'mala' }).subscribe({ error: () => undefined });
    control
      .expectOne(`${API}/api/auth/login`)
      .flush({ detail: 'Credenciales inválidas' }, { status: 401, statusText: 'x' });
    expect(auth.autenticado()).toBe(false);
  });

  it('eliminar la cuenta limpia la sesión solo si el servidor confirma', () => {
    const sesion = TestBed.inject(SessionService);
    sesion.iniciar(jwtDePrueba());
    auth.eliminarCuenta().subscribe({ error: () => undefined });
    control.expectOne(`${API}/api/users/me`).flush({}, { status: 503, statusText: 'x' });
    expect(auth.autenticado()).toBe(true);
    auth.eliminarCuenta().subscribe();
    const r = control.expectOne(`${API}/api/users/me`);
    expect(r.request.method).toBe('DELETE');
    r.flush(null, { status: 204, statusText: 'No Content' });
    expect(auth.autenticado()).toBe(false);
    expect(auth.usuario()).toBeNull();
  });
});

describe('guards', () => {
  beforeEach(preparar);
  const ejecutar = (guard: typeof authGuard, url: string) =>
    TestBed.runInInjectionContext(() =>
      guard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot),
    );

  it('sin sesión lleva a /login recordando el destino', () => {
    const r = ejecutar(authGuard, '/historial') as UrlTree;
    expect(TestBed.inject(Router).serializeUrl(r)).toBe('/login?volver=%2Fhistorial');
    expect(ejecutar(invitadoGuard, '/login')).toBe(true);
  });

  it('con sesión deja pasar y saca de /login', () => {
    TestBed.inject(SessionService).iniciar(jwtDePrueba());
    expect(ejecutar(authGuard, '/perfil')).toBe(true);
    expect(ejecutar(invitadoGuard, '/login')).toBeInstanceOf(UrlTree);
  });

  it.each([
    ['/historial', '/historial'],
    [undefined, '/'],
    ['', '/'],
    ['//evil.example', '/'],
    ['/\\evil.example', '/'],
    ['https://evil.example', '/'],
    ['javascript:alert(1)', '/'],
  ])('destinoSeguro(%j) = %s', (entrada, esperado) => {
    expect(destinoSeguro(entrada)).toBe(esperado);
  });
});
