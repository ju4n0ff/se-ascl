// Reglas de arquitectura y privacidad que ningún test de componente puede garantizar.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const APP = join(import.meta.dirname, '..', 'src', 'app');

function* archivos(dir) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const ruta = join(dir, e.name);
    if (e.isDirectory()) yield* archivos(ruta);
    else if (/\.(ts|html)$/.test(e.name) && !e.name.endsWith('.spec.ts')) yield ruta;
  }
}

const VISTAS = /^(features|layout|shared)\//;
const REGLAS = [
  {
    nombre: 'Las vistas no importan HttpClient ni ApiService ni los *ApiService',
    aplica: (r) => VISTAS.test(r),
    prohibido: /\bHttpClient\b|\bApiService\b|\b\w+ApiService\b|\bfetch\s*\(|XMLHttpRequest/,
  },
  {
    nombre: 'Las vistas no abren WebSocket ni usan MediaPipe directamente',
    aplica: (r) => VISTAS.test(r),
    prohibido: /new WebSocket|@mediapipe\/|getUserMedia/,
  },
  {
    nombre: 'Solo ApiService usa HttpClient',
    aplica: (r) => r !== 'services/api.service.ts' && r !== 'app.config.ts',
    prohibido: /\bHttpClient\b/,
  },
  {
    nombre: 'Solo SessionService usa almacenamiento del navegador (cero biometría persistida)',
    aplica: (r) => r !== 'core/auth/session.service.ts',
    prohibido: /\b(local|session)Storage\s*[.[]|indexedDB|document\.cookie|caches\.open/,
  },
  {
    nombre: 'El video no se graba ni se serializa',
    aplica: () => true,
    prohibido: /MediaRecorder|RTCPeerConnection|toDataURL|toBlob|captureStream|getImageData/,
  },
  {
    nombre: 'El JWT no va en ninguna URL',
    aplica: () => true,
    prohibido: /[?&](token|access_token|jwt)=/i,
  },
  {
    nombre: 'Rutas REST sin barra final',
    aplica: (r) => r.startsWith('services/'),
    prohibido: /['"`]api\/[^'"`]*\/['"`]/,
  },
  {
    nombre: 'Sin HTML sin sanear',
    aplica: () => true,
    prohibido: /\[innerHTML\]|bypassSecurityTrust|\.innerHTML\s*=/,
  },
];

let revisados = 0;
let vistas = 0;
const fallas = [];
for (const ruta of archivos(APP)) {
  const r = relative(APP, ruta).split(sep).join('/');
  revisados++;
  if (r.startsWith('features/')) vistas++;
  const lineas = readFileSync(ruta, 'utf8').split('\n');
  for (const regla of REGLAS.filter((x) => x.aplica(r))) {
    lineas.forEach((linea, i) => {
      if (regla.prohibido.test(linea))
        fallas.push(`${r}:${i + 1}  ${regla.nombre}\n    ${linea.trim()}`);
    });
  }
}

if (!existsSync(join(APP, 'features')) || vistas === 0) fallas.push('No hay vistas que revisar');
if (fallas.length) {
  console.error(`Arquitectura: ${fallas.length} falla(s)\n\n${fallas.join('\n')}`);
  process.exit(1);
}
console.log(
  `Arquitectura: ${REGLAS.length} reglas, ${revisados} archivos (${vistas} en features/): OK`,
);
