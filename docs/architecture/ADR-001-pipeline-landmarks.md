# ADR-001: Pipeline de 3 etapas con landmarks

## Estado: Aceptado

## Contexto
Se necesita una arquitectura para reconocimiento de señas en tiempo real que funcione en dispositivos móviles de gama media, proteja la privacidad del usuario y permita un modelo de tamaño razonable.

## Decisión
Adoptar pipeline de 3 etapas:
1. **Extracción de landmarks** (MediaPipe Hand/Face Landmarker) — 21 puntos × mano, coordenadas 3D
2. **Modelo de clasificación** (TFLite) — opera sobre landmarks, no imágenes
3. **Post-procesamiento lingüístico** — reconstrucción de palabras, gramática LSCh→español

## Consecuencias
- Modelo de ~10 MB (vs cientos de MB con CNN sobre imágenes)
- Privacidad: el video nunca sale del dispositivo
- Latencia < 200 ms en hardware medio
- Requiere captura de dataset de landmarks (no solo imágenes)
