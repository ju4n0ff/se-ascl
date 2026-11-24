---
name: angular-mediapipe-frontend
description: Frontend Angular de SeñaCL (frontend/) con MediaPipe Holistic en el navegador, WebSocket binario, voz y despliegue en Vercel. Usar al crear o modificar vistas, servicios, landmarks, sesión, estilos, pruebas o configuración del frontend.
---

# Skill: Frontend Angular + MediaPipe + Vercel

Angular 22 (standalone, signals, sin Zone), TypeScript `strict`, CSS propio, Vitest. Contrato de API: `backend/README.md` y `backend/app/schemas/schemas.py`.

## 1. Arquitectura por capas (Criterio A2 del Hito 3)
| Carpeta de `src/app/` | Responsabilidad |
|---|---|
| `core/` | `config/` (`API_CONFIG`), `auth/` (`SessionService`, `AuthService`, interceptor, guards), `errors/` (`ErrorMapperService`), `validation/`, `ui/` (avisos) |
| `models/` | Interfaces que espejan `schemas.py`. Si cambia el backend, cambian aquí primero |
| `services/` | HTTP tipado (`*ApiService` sobre `ApiService`), `WsRecognitionService`, `MediaPipeService`, `landmarks.ts`, `CameraService`, `SpeechService` y los casos de uso (`TraductorService`, `HistorialService`, `GlosarioService`) |
| `shared/`, `layout/` | Piezas visuales sin lógica de negocio |
| `features/` | Vistas: coordinan estado `loading / empty / error / ready` y delegan |

- **Prohibido** en `features/`, `layout/` y `shared/`: `HttpClient`, `ApiService`, `*ApiService`, `fetch`, `WebSocket`, `getUserMedia`, MediaPipe y lógica de negocio. Lo exige `scripts/verificar-capas.mjs`, que corre con `npm test`.
- Solo `ApiService` usa `HttpClient`; solo `SessionService` usa almacenamiento del navegador.
- `TraductorService` y `WsRecognitionService` se proveen en la vista: al salir se apaga la cámara y se cierra el socket.
- `(ngSubmit)` exige `[formGroup]` en el `<form>`; sin él el navegador recarga la página.

## 2. Geometría (PROHIBIDO ROMPER)
- Todo el vector se arma en `services/landmarks.ts`: 1629 floats = Pose 0–98, Rostro 99–1502, Mano izq 1503–1565, Mano der 1566–1628. Punto = `[x, y * (alto / ancho), z]`; bloque ausente = `0.0` exacto; NaN/Inf descarta el frame completo.
- Paquete: **`@mediapipe/holistic` 0.5.1675471629** (versión exacta). Es el mismo grafo y los mismos modelos del entrenamiento (`mp.solutions.holistic` 0.10.14). **No** migrar a `@mediapipe/tasks-vision`: usa otros modelos y 478 puntos de rostro. Cualquier cambio de motor exige repetir la medición de paridad de `frontend/README.md`.
- `OPCIONES_HOLISTIC` es fija: `modelComplexity: 1`, `refineFaceLandmarks: false`, `selfieMode: false`, confianzas 0.5.
- El `<video>` entra a MediaPipe **sin espejar**. El espejo es solo `transform: scaleX(-1)` en `.espejo`, que contiene video y canvas. El texto superpuesto va fuera de `.espejo`.
- MediaPipe se carga de forma perezosa al encender la cámara, desde `/mediapipe/holistic-<versión>/` (copiado de `node_modules` por `angular.json`; sin CDN). Al cambiar de versión, actualizar `package.json`, `angular.json` y `RUTA_MEDIAPIPE`.

## 3. Tiempo real
- WebSocket: primer mensaje `{"type":"auth","token"}` si hay sesión, luego `config`; el JWT **nunca** en la URL. `save_history: true` solo tras `{"type":"auth","ok":true}`.
- Frames en binario: `ArrayBuffer` de 6516 bytes little-endian. 24 FPS objetivo, tope duro de 28/s (el backend corta sobre 35). Si `bufferedAmount` crece, se descartan frames.
- En manual solo se transmite mientras se graba; `config` vacío cada 25 s mantiene viva la conexión.
- Cierres `1001`, `1008`, `1009` y `1011`: mensaje y botón Reconectar, nunca automático. Cortes de red (`1006`): 3 reintentos (1, 2, 4 s) y se detiene; solo una conexión estable de 10 s recupera los reintentos. Un `Origin` rechazado o el tope por IP se ven como `1006`.
- Rutas REST **sin barra final** (404 con `DEBUG=false`).

## 4. Sesión, errores y privacidad
- JWT en `sessionStorage` (decisión en `frontend/README.md`). El interceptor adjunta `Authorization` solo a `apiUrl` (comparación con `/` final) y da por vencida la sesión con `401`, salvo contraseña actual incorrecta (`REAUTENTICACION`).
- Todo error pasa por `ErrorMapperService`: español claro, nunca JSON, trazas ni textos del servidor.
- Validadores idénticos a `schemas.py`. `?volver=` solo admite rutas internas (`destinoSeguro`).
- Cero persistencia biométrica: prohibido grabar, serializar o almacenar video, frames o landmarks. Sin fuentes, scripts ni analítica de terceros.

## 5. Identidad y accesibilidad
- Verde SeñaCL `#1E4438`, acento menta `#C2ECDA`, rojo `#C8413A`, fondos crema `#FAF8F5`/`#F6F3EE` y verde oscuro `#123027` en franjas/pie. El rojo de marca no alcanza AA en texto normal: usarlo en rellenos, bordes y texto grande en negrita (≥ 19 px); para texto normal, `--coral-oscuro`.
- Foco visible, `aria-live` en resultados, `role="alert"` en errores, `prefers-reduced-motion`, sin desborde horizontal a 375 px. Espacio graba solo si el foco no está en un control.

## 6. Vercel
- `vercel.json`: `npm ci`, salida `dist/senacl-frontend/browser`, rewrite SPA, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy: camera=(self), microphone=(), geolocation=()` y caché inmutable en `/mediapipe/`.
- `environment.prod.ts` con `https://` y `wss://` del mismo host y sin barra final. El dominio de Vercel debe estar en `ALLOWED_ORIGINS` de Render.

## Checklist
1. `npm test` (arquitectura + unitarias), `npm run typecheck` y `npm run build` en verde.
2. Prueba manual: levantar solo la mano derecha enciende «Mano der.»; recargar `/historial` conserva la sesión.
3. `git status` sin `node_modules/`, `dist/` ni `.angular/`.
