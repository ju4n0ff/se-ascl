import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { API_CONFIG, crearApiConfig } from '../core/config/api.config';
import { environment as prod } from '../../environments/environment.prod';
import { HistoryEntry } from '../models/history.model';
import { AuthApiService } from './auth-api.service';
import { BackendStatusService } from './backend-status.service';
import { GlosarioService, normalizarBusqueda } from './glosario.service';
import { HistorialService } from './historial.service';
import { HistoryApiService } from './history-api.service';
import { N_FLOATS } from './landmarks';
import { MetaApiService } from './meta-api.service';
import { RecognitionApiService } from './recognition-api.service';
import { UsersApiService } from './users-api.service';

const API = 'https://api.test';
const entrada = (id: number, spanish_text = 'hola'): HistoryEntry => ({
  id,
  spanish_text,
  user_id: 1,
  predicted_label: 'hola',
  confidence: 0.9,
  mode: 'dynamic',
  created_at: '2026-11-23T12:00:00Z',
});

describe('servicios HTTP', () => {
  let control: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        HistorialService,
        GlosarioService,
        // Con barra final a propósito: no debe llegar a la URL.
        { provide: API_CONFIG, useValue: crearApiConfig({ apiUrl: `${API}/`, wsUrl: 'wss://x/' }) },
      ],
    });
    control = TestBed.inject(HttpTestingController);
  });
  afterEach(() => control.verify());

  it('ninguna ruta lleva barra final ni doble barra', () => {
    const auth = TestBed.inject(AuthApiService);
    const users = TestBed.inject(UsersApiService);
    const history = TestBed.inject(HistoryApiService);
    const meta = TestBed.inject(MetaApiService);
    auth.login({ username: 'a', password: 'b' }).subscribe();
    auth.registrar({ username: 'a', email: 'b', password: 'c' }).subscribe();
    users.yo().subscribe();
    users.actualizar({ current_password: 'x' }).subscribe();
    users.eliminar().subscribe();
    history.listar().subscribe();
    history.actualizar(7, { spanish_text: 'x' }).subscribe();
    history.eliminar(7).subscribe();
    meta.salud().subscribe();
    meta.clases().subscribe();
    const vistas = control
      .match(() => true)
      .map((r) => `${r.request.method} ${r.request.urlWithParams}`);
    expect(vistas).toEqual([
      `POST ${API}/api/auth/login`,
      `POST ${API}/api/auth/register`,
      `GET ${API}/api/users/me`,
      `PATCH ${API}/api/users/me`,
      `DELETE ${API}/api/users/me`,
      `GET ${API}/api/history/me?limit=50`,
      `PATCH ${API}/api/history/7`,
      `DELETE ${API}/api/history/7`,
      `GET ${API}/api/health`,
      `GET ${API}/api/clases`,
    ]);
  });

  it('reconocer envía N*6516 bytes como octet-stream', () => {
    const frames = [1, 2].map((v) => new Float32Array(N_FLOATS).fill(v));
    TestBed.inject(RecognitionApiService).reconocer(frames, { guardar: true }).subscribe();
    const r = control.expectOne(`${API}/api/recognize?top_k=3&save_history=true`);
    expect(r.request.headers.get('Content-Type')).toBe('application/octet-stream');
    const cuerpo = r.request.body as ArrayBuffer;
    expect(cuerpo.byteLength).toBe(2 * 6516);
    expect(new Float32Array(cuerpo)[N_FLOATS]).toBe(2);
    r.flush({});
  });

  it('historial: cargando, vacío, listo, editar y eliminar', () => {
    const h = TestBed.inject(HistorialService);
    h.cargar();
    expect(h.estado()).toBe('loading');
    control.expectOne(`${API}/api/history/me?limit=50`).flush([]);
    expect(h.estado()).toBe('empty');
    h.cargar();
    control.expectOne(`${API}/api/history/me?limit=50`).flush([entrada(1), entrada(2)]);
    expect(h.estado()).toBe('ready');

    h.actualizarTexto(2, '  ¿dónde?  ').subscribe();
    expect(h.ocupada()).toBe(2);
    const r = control.expectOne(`${API}/api/history/2`);
    expect(r.request.body).toEqual({ spanish_text: '¿dónde?' });
    r.flush(entrada(2, '¿dónde?'));
    expect(h.entradas().map((e) => e.spanish_text)).toEqual(['hola', '¿dónde?']);
    expect(h.ocupada()).toBeNull();

    h.eliminar(1).subscribe();
    control.expectOne(`${API}/api/history/1`).flush(null, { status: 204, statusText: 'x' });
    h.quitar(2);
    expect(h.estado()).toBe('empty');
  });

  it('historial: un fallo al editar no altera la lista', () => {
    const h = TestBed.inject(HistorialService);
    h.cargar();
    control.expectOne(() => true).flush([entrada(1)]);
    h.actualizarTexto(1, 'otro').subscribe({ error: () => undefined });
    control.expectOne(`${API}/api/history/1`).flush({}, { status: 422, statusText: 'x' });
    expect(h.entradas()[0].spanish_text).toBe('hola');
    expect(h.ocupada()).toBeNull();
  });

  it('historial: error con mensaje legible', () => {
    const h = TestBed.inject(HistorialService);
    h.cargar();
    control.expectOne(() => true).error(new ProgressEvent('error'));
    expect(h.estado()).toBe('error');
    expect(h.mensajeError()).toContain('No pudimos conectar');
  });

  it('glosario: busca sin tildes ni signos y filtra preguntas', () => {
    const g = TestBed.inject(GlosarioService);
    g.cargar();
    expect(g.estado()).toBe('loading');
    control.expectOne(`${API}/api/clases`).flush({
      total: 3,
      clases: [
        { indice: 0, clase_raw: 'hola', texto: 'hola', es_pregunta: false },
        { indice: 1, clase_raw: 'donde_salida.I', texto: '¿donde salida?', es_pregunta: true },
        { indice: 2, clase_raw: 'manana', texto: 'mañana', es_pregunta: false },
      ],
    });
    const textos = () => g.visibles().map((c) => c.texto);
    expect(g.total()).toBe(3);
    g.busqueda.set('¿DÓNDE  salida');
    expect(textos()).toEqual(['¿donde salida?']);
    g.filtro.set('afirmaciones');
    expect(g.estado()).toBe('empty');
    g.busqueda.set('');
    expect(textos()).toEqual(['hola', 'mañana']);
    g.filtro.set('preguntas');
    expect(textos()).toEqual(['¿donde salida?']);
  });

  it('la búsqueda conserva la ñ', () => {
    expect(normalizarBusqueda('Mañana')).toBe('mañana');
    expect(normalizarBusqueda('¿Cómo estás?')).toBe('como estas');
  });

  it('estado del backend: disponible, degradado y sin conexión con reintentos acotados', () => {
    vi.useFakeTimers();
    const b = TestBed.inject(BackendStatusService);
    b.comprobar();
    expect(b.estado()).toBe('comprobando');
    control
      .expectOne(`${API}/api/health`)
      .flush({ status: 'degraded' }, { status: 503, statusText: 'x' });
    expect(b.estado()).toBe('degradado');
    for (let i = 0; i < 4; i++) {
      vi.advanceTimersByTime(20_000);
      control.expectOne(`${API}/api/health`).error(new ProgressEvent('error'));
      expect(b.estado()).toBe('sin-conexion');
    }
    vi.advanceTimersByTime(200_000);
    control.expectNone(`${API}/api/health`);
    b.comprobar();
    control.expectOne(`${API}/api/health`).flush({ status: 'ok' });
    expect(b.estado()).toBe('disponible');
    vi.useRealTimers();
  });
});

describe('configuración', () => {
  it('detecta la URL de Render sin reemplazar', () => {
    const marcador = 'https://REPLACE_WITH_RENDER_SERVICE.onrender.com';
    expect(crearApiConfig({ apiUrl: marcador, wsUrl: '' }).configurado).toBe(false);
    expect(
      crearApiConfig({ apiUrl: 'https://senacl-api.onrender.com', wsUrl: '' }).configurado,
    ).toBe(true);
  });

  it('producción usa https y wss, sin barra final y el mismo host', () => {
    expect(prod.production).toBe(true);
    expect(prod.apiUrl).toMatch(/^https:\/\/[^/]+$/);
    expect(prod.wsUrl).toMatch(/^wss:\/\/[^/]+\/ws\/recognize$/);
    expect(new URL(prod.wsUrl).host).toBe(new URL(prod.apiUrl).host);
  });
});
