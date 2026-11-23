# SeñaCL Frontend

SPA en Angular que traduce Lengua de Señas Chilena a texto y voz. Extrae 1629 landmarks por cuadro con
MediaPipe Holistic **dentro del navegador** y los envía al back-end por WebSocket. El video nunca sale
del equipo.

## Requisitos

- Node.js 24 o superior (probado con 26.13) y npm 11.
- Back-end de SeñaCL corriendo (ver [`backend/README.md`](../backend/README.md)).
- Navegador moderno con WebGL 2. Chrome y Edge recomendados.

## Desarrollo local

```powershell
npm install
npm start
```

Abrir **http://localhost:4200** (no `127.0.0.1:4200`: el back-end permite el origen `localhost`). El
entorno local apunta a `http://127.0.0.1:8000`; se cambia en `src/environments/environment.ts`. Del lado
del back-end, `ALLOWED_ORIGINS` debe incluir `http://localhost:4200` (es el valor por defecto).

| Comando | Qué hace |
|---|---|
| `npm start` | Servidor de desarrollo |
| `npm test` | Reglas de arquitectura (`scripts/verificar-capas.mjs`) y pruebas unitarias, una pasada |
| `npm run test:watch` | Pruebas en modo observador |
| `npm run typecheck` | TypeScript y plantillas en modo estricto, sin emitir |
| `npm run build` | Build de producción en `dist/senacl-frontend/browser` |

## Rutas

| Ruta | Acceso | Contenido |
|---|---|---|
| `/` | Pública | Traductor en vivo |
| `/glosario` | Pública | Las 89 señas, con buscador y filtros |
| `/login`, `/registro` | Solo sin sesión | Cuenta |
| `/historial` | 🔒 | Traducciones guardadas: corregir, escuchar, eliminar |
| `/perfil` | 🔒 | Datos, privacidad (Ley 21.719) y eliminación de la cuenta |

## Despliegue en Vercel

1. **Poner la URL de Render.** En `src/environments/environment.prod.ts` reemplazar
   `REPLACE_WITH_RENDER_SERVICE` en `apiUrl` **y** en `wsUrl` (aparece dos veces), por ejemplo:

   ```ts
   apiUrl: 'https://senacl-api.onrender.com',
   wsUrl: 'wss://senacl-api.onrender.com/ws/recognize',
   ```

   `https://` y `wss://`, mismo host y sin barra final. Mientras quede el marcador, la barra muestra
   «Servidor sin configurar» y la app no intenta conectarse.
2. **Vercel → Add New → Project**, importar el repositorio y definir **Root Directory: `frontend`**. El
   preset Angular, los comandos y la carpeta de salida ya están en `vercel.json`. No hay variables de
   entorno ni secretos.
3. **Render → Environment → `ALLOWED_ORIGINS`**: agregar el dominio exacto de Vercel, sin barra final
   (`https://senacl.vercel.app,https://www.senacl.cl`), y redesplegar. Vale para CORS y para el WebSocket.
4. Comprobar: indicador «Servidor disponible», iniciar la cámara y recargar `/historial` sin `404`.

Los previews de Vercel usan otro dominio: no funcionarán contra el back-end salvo que se configure
`ALLOWED_ORIGIN_REGEX` (ver riesgos en `backend/README.md`).

| Síntoma | Causa probable |
|---|---|
| «Servidor sin conexión» y error CORS en la consola | El dominio no está en `ALLOWED_ORIGINS`, o un `500` del back-end (sale sin cabeceras CORS) |
| REST funciona pero el traductor no conecta | `Origin` rechazado, más de 5 conexiones por IP, o `wsUrl` mal escrita |
| El primer acceso tarda cerca de un minuto | Render (plan gratuito) está despertando; la app espera hasta 75 s |
| «Credenciales inválidas» pasa a «Demasiados intentos» para todos | `TRUST_PROXY_HOPS` por confirmar en Render |

## Decisiones

### MediaPipe: por qué `@mediapipe/holistic`

El modelo se entrenó con `mp.solutions.holistic` (0.10.14, `model_complexity=1`,
`refine_face_landmarks=False`). `@mediapipe/holistic` 0.5.1675471629 empaqueta ese grafo y esos modelos, y
es lo que exige `README_ML.md`. `HolisticLandmarker` (`@mediapipe/tasks-vision`) usa modelos distintos y
478 puntos de rostro: no reproduce los 1629 floats. Es un paquete sin desarrollo activo, por eso va con
versión exacta y autoalojado (`angular.json` copia 30 MB a `/mediapipe/`, en caché tras la primera vez;
sin CDN de terceros).

Paridad medida el 23-11-2026 con 14 videos de prueba (826 cuadros), mismos cuadros en Python y en el
navegador, en unidades de ancho de hombros:

| Bloque | Error xy mediano | Percentil 95 |
|---|---|---|
| Mano izquierda | 0,008 | 0,088 |
| Mano derecha | 0,005 | 0,038 |
| Rostro | 0,005 | 0,007 |
| Pose (33 puntos, incluye piernas fuera de cuadro) | 0,026 | 0,147 |

Sin inversión de manos (511 de 515 cuadros coinciden). La seña top-1 coincide en 11 de 14 videos,
incluidos **todos** los que superan el umbral 0,55; las 3 diferencias tienen confianza menor a 0,16. En
9 de los 14 videos la predicción de **ambos** extractores no supera el umbral: se usaron solo los primeros
60 cuadros y sin la corrección de orientación de `preprocesar_lsch_v2.py`. Mide paridad, no precisión.

### Dónde vive el JWT

En **`sessionStorage`**. Sobrevive a recargar la página y se borra al cerrar la pestaña.

| Opción | A favor | En contra |
|---|---|---|
| `sessionStorage` (elegida) | Sobrevive a F5; no queda en equipos compartidos; no se comparte entre pestañas | Cada pestaña nueva pide iniciar sesión; legible por un XSS |
| `localStorage` | Persiste entre pestañas y reinicios | Queda en disco en equipos compartidos; misma exposición a XSS |
| Cookie `HttpOnly` | No legible por JavaScript | El back-end usa CORS sin credenciales; exigiría CSRF y cookies entre dominios |

El riesgo residual (XSS) se acota con el saneamiento de Angular, la prohibición de `innerHTML`, cero
scripts de terceros y un token de 60 minutos. La sesión se cierra sola al vencer o ante un `401`.

### Privacidad

- El único almacenamiento es el JWT. Ni video, ni cuadros, ni landmarks se guardan o registran.
- En modo manual solo se transmite mientras se graba. Al salir del traductor se apaga la cámara.
- «Guardar en mi historial» parte apagado y exige sesión confirmada por el servidor.
- `scripts/verificar-capas.mjs` falla si aparece grabación de video, almacenamiento nuevo, HTML sin sanear o
  un token en una URL.

### Tiempo real

24 FPS objetivo (tope duro de 28 mensajes/s; el back-end admite 35). MediaPipe tarda unos 50 ms por cuadro
en un equipo de escritorio, así que lo habitual son 15–20 FPS. En una pestaña en segundo plano el navegador
frena la captura y el servidor cierra a los 60 s (`1001`): aparece el botón Reconectar.

## Estructura

```
src/app/
  core/       config, auth (sesión, interceptor, guards), errores, validación, avisos
  models/     interfaces que espejan backend/app/schemas/schemas.py
  services/   HTTP tipado, WebSocket, MediaPipe, cámara, voz y casos de uso
  shared/     piezas visuales reutilizables
  layout/     barra superior
  features/   vistas (sin HttpClient ni lógica de negocio)
  testing/    utilidades de prueba
```

## Prueba manual recomendada (con cámara real)

1. Levantar **solo la mano derecha**: debe encenderse «Mano der.» y no «Mano izq.». Si sale al revés, la
   cámara espeja por hardware o por su software.
2. Traducir una seña del glosario en modo Automático y otra en Manual (botón y tecla Espacio).
3. Con sesión y «Guardar en mi historial», recargar `/historial` y comprobar que la entrada sigue ahí.
