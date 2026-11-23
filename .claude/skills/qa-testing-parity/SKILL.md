---
name: qa-testing-parity
description: Pruebas automatizadas con pytest, validación de paridad numérica del modelo LSCh v3, tests de abuso/seguridad, tests de despliegue cloud (Supabase/Render/Vercel) y análisis estático (ruff, bandit). Usar después de implementar o endurecer el backend.
---

# Skill: QA, Testing Automatizado y Paridad ML

## 1. Suite de Pruebas Requerida (`backend/tests/`)
Configurar `pytest` + `pytest-asyncio` + `httpx` (`ASGITransport`) usando exclusivamente PostgreSQL local `signia_test`, sin ensuciar los datos de `signia`.

**Aislamiento total (no negociable):** la suite trunca tablas, así que `conftest.py` aborta si la base no termina en `_test` o si el servidor no es local (host remoto, puerto `6543` o `?host=`). Prohibido relajar esa guarda o apuntar `TEST_DATABASE_URL` a Supabase. `ENV_TESTS` fija toda variable de `Settings` que pueda venir de `backend/.env`. Los tests cloud solo **analizan** URLs remotas ficticias; si ejecutan DDL (RLS), lo hacen en una transacción que siempre se revierte.

### A. Tests de Paridad ML (`tests/test_ml_parity.py`)
- Cargar `LSChPredictor` y probar con un tensor determinista `(30, 1629)` (y secuencias de longitud `15` y `45` para validar padding y remuestreo).
- Verificar que la probabilidad Top-1 devuelta por `POST /api/recognize` coincide con la inferencia directa local hasta el **4.º decimal** (`abs(a - b) < 1e-4`).
- Verificar el formateo de preguntas con sufijo `.I` (ej. `donde_salida.I` -> `¿donde salida?`, `es_pregunta=True`).

### B. Tests de Seguridad y Abuso (`tests/test_security.py`)
- **Auth:** contraseña débil (`"1234"`) rechazada con `422`; contraseña fuerte aceptada con `201`; login inválido devuelve `401` genérico; acceso a rutas protegidas sin token devuelve `401`.
- **Anti-BOLA / IDOR:** Usuario A intenta `GET /api/history/{user_B_id}` → `403`. Usuario A intenta `DELETE /api/history/{entry_de_B}` → `404` (y el registro sigue existiendo).
- **Validación numérica:** enviar `NaN`, `Infinity`, vector de `1628` floats, `5` frames (`< 12`) y `601` frames (`> 600`) → `422`.
- **Anti-DoS:** enviar cuerpo HTTP > 5 MB → `413`; superar el límite de login → `429`.
- **Headers de seguridad:** comprobar presencia de `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` y `Permissions-Policy`.
- **WebSocket:** conexión con `Origin` no autorizado → rechazada; envío de mensaje gigante o vector inválido → error controlado sin tumbar el servidor.

### C. Tests Funcionales de WebSocket (`tests/test_websocket.py`)
- Simular el flujo completo de la máquina de estados: 3 frames con manos → 15 frames de seña → 10 frames sin manos → verificar respuesta `prediccion` con `top_k` de longitud 3 y latencia registrada.
- Probar `manual_start`, `manual_stop` y `reset`.

### D. Tests de Despliegue Cloud (`tests/test_cloud.py`)
Obligatorios al tocar configuración, sesión, red, orígenes o despliegue:
- **`DATABASE_URL`:** `postgres://`/`postgresql://` → `postgresql+asyncpg://`, limpieza de `sslmode`/`pgbouncer`, contraseña codificada intacta, local sin cambios y errores que no filtran la clave.
- **`connect_args`:** SSL (`require`, CA propia, `verify-*` sin degradar), PgBouncer (los dos cachés en 0 y nombres únicos, comprobados contra asyncpg real en local), autodetección y precedencia de las variables explícitas.
- **IP:** `TRUST_PROXY_HOPS=0` ignora XFF; con N saltos se cuenta desde la derecha; spoofing, cabeceras repetidas, entradas malformadas o insuficientes; `429` y tope WS no evadibles; uvicorn con los flags reales de `render.yaml`.
- **CORS/WS:** varios orígenes `https://`, política `http://` solo loopback, `ALLOWED_ORIGIN_REGEX` abierto rechazado y **misma decisión** en CORS y en el handshake.
- **RLS:** contenido e idempotencia de `supabase_rls.sql` sin alterar `signia_test`.
- **Render:** `render.yaml` sin secretos, con flags obligatorios y que produce `Settings` válidos; pool de hashes acotado y Argon2id sin rebajar.

## 2. Compuertas de Calidad (Quality Gates)
Antes de dar por cerrada cualquier tarea, ejecutar y reportar la salida exacta de:
1. `ruff check backend/app backend/tests`
2. `bandit -r backend/app -ll`
3. `pytest backend/tests -v`

No marcar una tarea como completada si falla cualquiera de los 3 comandos.