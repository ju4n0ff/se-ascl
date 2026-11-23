import { HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { TimeoutError } from 'rxjs';

import { ContextoError, ErrorMapperService } from './error-mapper.service';

const http = (status: number, detail?: unknown, headers: Record<string, string> = {}) =>
  new HttpErrorResponse({
    status,
    error: detail === undefined ? null : { detail, request_id: 'abc123' },
    headers: new HttpHeaders(headers),
  });

describe('ErrorMapperService', () => {
  const mapper = new ErrorMapperService();
  const mensaje = (e: unknown, c?: ContextoError) => mapper.mapear(e, c).mensaje;

  it.each<[number, ContextoError, string]>([
    [0, 'general', 'No pudimos conectar'],
    [400, 'general', 'no es válida'],
    [401, 'login', 'Credenciales inválidas'],
    [401, 'perfil', 'contraseña actual no es correcta'],
    [401, 'general', 'iniciar sesión'],
    [403, 'general', 'No tienes permiso'],
    [404, 'historial', 'ya no existe'],
    [404, 'general', 'No encontramos'],
    [409, 'registro', 'El usuario o correo ya está registrado'],
    [409, 'perfil', 'correo ya está en uso'],
    [413, 'general', 'demasiado larga'],
    [429, 'login', 'Demasiados intentos'],
    [500, 'general', 'problema inesperado'],
    [502, 'general', 'iniciando'],
    [503, 'general', 'no está disponible'],
    [504, 'general', 'iniciando'],
    [418, 'general', 'problema inesperado'],
  ])('%d en %s', (status, contexto, esperado) => {
    expect(mensaje(http(status, 'detalle técnico'), contexto)).toContain(esperado);
  });

  it('usa Retry-After en 429', () => {
    expect(mensaje(http(429, 'x', { 'Retry-After': '37' }))).toContain('37 segundos');
    expect(mensaje(http(429, 'x', { 'Retry-After': 'abc' }))).toContain('unos segundos');
  });

  it('traduce los campos del 422 sin mostrar el texto técnico', () => {
    const e = mapper.mapear(
      http(422, [
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'new_password'], msg: 'String should have at least 8', type: 'too_short' },
        { loc: ['body', 'email'], msg: 'otra vez', type: 'x' },
      ]),
    );
    expect(e.campos).toEqual(['email', 'new_password']);
    expect(e.mensaje).toBe('Revisa el correo y la contraseña nueva: el formato no es válido.');
  });

  it.each([
    ['Secuencia inválida'],
    [null],
    [[]],
    [[null, 7, { loc: 'x' }, { loc: [1, 'constructor'] }]],
    [{ raro: true }],
  ])('tolera detalles 422 inesperados: %j', (detalle) => {
    const e = mapper.mapear(http(422, detalle));
    expect(e.campos).toEqual([]);
    expect(e.mensaje).toContain('formato no válido');
  });

  it('nunca filtra el cuerpo crudo de la respuesta', () => {
    const secreto = 'Traceback SELECT password_hash {"json":1}';
    for (const status of [0, 400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503]) {
      const texto = mensaje(
        new HttpErrorResponse({ status, error: secreto, url: 'http://interno/api' }),
      );
      expect(texto).not.toMatch(/Traceback|SELECT|[{}]|http/);
    }
  });

  it('distingue lo reintentable', () => {
    expect([0, 429, 500, 503].every((s) => mapper.mapear(http(s)).reintentable)).toBe(true);
    expect([401, 403, 404, 409, 422].some((s) => mapper.mapear(http(s)).reintentable)).toBe(false);
  });

  it.each([new Error('boom'), 'texto', null, undefined])('error no HTTP: %s', (e) => {
    expect(mensaje(e)).toContain('problema inesperado');
  });

  it('timeout', () => {
    expect(mensaje(new TimeoutError())).toContain('tardando');
  });
});
