/**
 * Geometría exacta de un frame LSCh v3 (README_ML.md §2 y conversor/features_lsch.py).
 *
 *   Pose        0..98      33 puntos
 *   Rostro     99..1502   468 puntos (refineFaceLandmarks = false)
 *   Mano izq 1503..1565    21 puntos (mano izquierda de la PERSONA)
 *   Mano der 1566..1628    21 puntos
 *
 * Cada punto es [x, y * (alto / ancho), z]. Un bloque ausente queda en 0.0 exacto. Los
 * datos nunca se espejan: el espejo es solo CSS.
 */
export const N_POSE = 33;
export const N_ROSTRO = 468;
export const N_MANO = 21;

export const INICIO_POSE = 0;
export const INICIO_ROSTRO = INICIO_POSE + N_POSE * 3; // 99
export const INICIO_MANO_IZQ = INICIO_ROSTRO + N_ROSTRO * 3; // 1503
export const INICIO_MANO_DER = INICIO_MANO_IZQ + N_MANO * 3; // 1566
export const N_FLOATS = INICIO_MANO_DER + N_MANO * 3; // 1629
export const BYTES_FRAME = N_FLOATS * 4; // 6516

/** Float32Array respaldado por un ArrayBuffer propio (lo que acepta WebSocket.send). */
export type VectorFrame = Float32Array<ArrayBuffer>;

export interface Punto {
  x: number;
  y: number;
  z: number;
}

/** Subconjunto de los resultados de MediaPipe Holistic que usa el modelo. */
export interface ResultadosHolistic {
  poseLandmarks?: readonly Punto[] | null;
  faceLandmarks?: readonly Punto[] | null;
  leftHandLandmarks?: readonly Punto[] | null;
  rightHandLandmarks?: readonly Punto[] | null;
}

function escribirBloque(
  vector: VectorFrame,
  inicio: number,
  puntos: readonly Punto[] | null | undefined,
  cantidad: number,
  aspecto: number,
): void {
  if (!puntos || puntos.length < cantidad) return; // ausente: quedan los ceros
  let i = inicio;
  for (let p = 0; p < cantidad; p++) {
    const { x, y, z } = puntos[p];
    vector[i++] = x;
    vector[i++] = y * aspecto;
    vector[i++] = z;
  }
}

/** Devuelve el frame de 1629 floats, o `null` si trae valores no finitos o no hay imagen. */
export function construirVector(
  resultados: ResultadosHolistic,
  ancho: number,
  alto: number,
): VectorFrame | null {
  if (!(ancho > 0) || !(alto > 0)) return null;
  const aspecto = alto / ancho;
  const vector = new Float32Array(N_FLOATS);
  escribirBloque(vector, INICIO_POSE, resultados.poseLandmarks, N_POSE, aspecto);
  escribirBloque(vector, INICIO_ROSTRO, resultados.faceLandmarks, N_ROSTRO, aspecto);
  escribirBloque(vector, INICIO_MANO_IZQ, resultados.leftHandLandmarks, N_MANO, aspecto);
  escribirBloque(vector, INICIO_MANO_DER, resultados.rightHandLandmarks, N_MANO, aspecto);
  // Se revisa después del cast a float32: 1e300 es finito en JS y aquí pasa a Infinity.
  return vector.every(Number.isFinite) ? vector : null;
}
