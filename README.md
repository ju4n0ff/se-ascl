# SeñaCL - Traductor de Lengua de Señas Chilena

**Promesa del producto:** Entregar una traducción automática, unidireccional y en tiempo real de la Lengua de Señas Chilena (LSCh) a texto y audio mediante una aplicación web de fácil acceso.

## Equipo de Desarrollo
*   **Javier Ignacio Concha** - [@UsuarioJavier](https://github.com/a3rshH)
*   **Luis Jesús Urbina Garcidueñas** - [@UsuarioLuis](https://github.com/LuisU1138)
*   **Juan Carlos Vega Graterol** - [@UsuarioJuan](https://github.com/ju4n0ff)

## Instalación rápida (back-end, Hito 2)

Requisitos: Python 3.11 y PostgreSQL 14+ (bases `signia` y, para los tests, `signia_test`).

```powershell
git clone https://github.com/ju4n0ff/se-ascl.git
cd se-ascl
copy .env.example backend\.env
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

1. Editar `backend/.env`: `DATABASE_URL`, `DATABASE_URL_SYNC` y `SECRET_KEY` (para la demo local, `DEBUG=true` habilita `/docs`).
2. Crear la base: `createdb signia` y `psql -d signia -f db/schema.sql` (datos de prueba opcionales: `db/seed.sql`).
3. Levantar el servidor: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --ws-max-size 49152`.
4. Verificar: `GET http://127.0.0.1:8000/api/health` responde `200` con `"status": "ok"`.

El detalle (PostgreSQL en WSL, variables, endpoints y tests) está en [backend/README.md](./backend/README.md).

## Arranque del frontend (Angular)

Requiere Node.js 24 o superior y el back-end corriendo en `http://127.0.0.1:8000` con
`ALLOWED_ORIGINS=http://localhost:4200` (valor por defecto). En otra terminal:

```powershell
cd frontend
npm install
npm start
```

Abrir `http://localhost:4200` (con `localhost`, no `127.0.0.1`: es el origen permitido). El video se
procesa en el navegador y nunca se envía. Pruebas, decisiones y despliegue en Vercel:
[frontend/README.md](./frontend/README.md).

## Documentación del Hito 2

*   [Guía del back-end: instalación, endpoints y tests](./backend/README.md)
*   [Seguridad: controles OWASP y limitaciones](./backend/SECURITY.md)
*   [Despliegue en Supabase + Render](./backend/README.md#despliegue-en-supabase--render) e [integración con Angular en Vercel](./backend/README.md#integración-con-frontend-angular-en-vercel)
*   [Colección Postman](./backend/postman_collection.json)
*   [Esquema](./backend/db/schema.sql), [datos de prueba](./backend/db/seed.sql) y [modelo de datos (Mermaid)](./backend/db/modelo_datos.mmd)
*   [Especificación del modelo ML v3](./README_ML.md)
*   [Carpeta `docs/`](./docs/) ([documentos reemplazados](./docs/archivo/README.md))

## Entregables del Hito 1

### Prototipo Navegable
*   [Abrir Prototipo Interactivo (Clic aquí)](https://claude.ai/artifact/2hsuz35qUDKM3iUSKMk3dU)
### Documentación Técnica
Los siguientes documentos se encuentran alojados en la carpeta `docs/` de este repositorio:

*   [Documento de Propuesta (PDF)](./docs/Documento_Propuesta.pdf)
*   [Láminas de Presentación (PDF)](./docs/PptSeñaCL.pdf)
*   [Mapa del Producto (PNG)](./docs/Mapa_Producto.png)
*   [Diagrama de Arquitectura (PNG)](./docs/Diagrama_Arquitectura.png)
