import {
  BYTES_FRAME,
  INICIO_MANO_DER,
  INICIO_MANO_IZQ,
  INICIO_ROSTRO,
  N_FLOATS,
  N_MANO,
  N_POSE,
  N_ROSTRO,
  Punto,
  ResultadosHolistic,
  construirVector,
} from './landmarks';

/** Puntos distinguibles por bloque e índice. */
const puntos = (n: number, base: number): Punto[] =>
  Array.from({ length: n }, (_, i) => ({ x: base + i, y: base + i + 0.5, z: -(base + i) }));

const COMPLETO: ResultadosHolistic = {
  poseLandmarks: puntos(N_POSE, 1000),
  faceLandmarks: puntos(N_ROSTRO, 2000),
  leftHandLandmarks: puntos(N_MANO, 3000),
  rightHandLandmarks: puntos(N_MANO, 4000),
};

describe('construirVector', () => {
  it('mantiene las dimensiones del contrato v3', () => {
    expect([INICIO_ROSTRO, INICIO_MANO_IZQ, INICIO_MANO_DER, N_FLOATS, BYTES_FRAME]).toEqual([
      99, 1503, 1566, 1629, 6516,
    ]);
    const v = construirVector(COMPLETO, 640, 480)!;
    expect(v).toBeInstanceOf(Float32Array);
    expect(v.length).toBe(1629);
    expect(v.byteLength).toBe(6516);
    expect(v.buffer.byteLength).toBe(6516); // se envía el buffer completo
  });

  it('ordena Pose, Rostro, Mano izquierda y Mano derecha', () => {
    const v = construirVector(COMPLETO, 100, 100)!;
    expect(v[0]).toBe(1000);
    expect(v[98]).toBe(-1032); // z del punto 32 de la pose
    expect(v[99]).toBe(2000);
    expect(v[1502]).toBe(-2467);
    expect(v[1503]).toBe(3000);
    expect(v[1565]).toBe(-3020);
    expect(v[1566]).toBe(4000);
    expect(v[1628]).toBe(-4020);
  });

  it.each([
    [640, 480, 0.75],
    [1280, 720, 0.5625],
    [720, 1280, 1280 / 720],
  ])('escala solo y por alto/ancho (%dx%d)', (ancho, alto, aspecto) => {
    const v = construirVector(
      { poseLandmarks: Array.from({ length: N_POSE }, () => ({ x: 0.3, y: 0.5, z: -0.2 })) },
      ancho,
      alto,
    )!;
    for (let p = 0; p < N_POSE; p++) {
      expect(v[p * 3]).toBeCloseTo(0.3, 6);
      expect(v[p * 3 + 1]).toBeCloseTo(0.5 * aspecto, 6);
      expect(v[p * 3 + 2]).toBeCloseTo(-0.2, 6);
    }
  });

  it('no espeja: x llega sin invertir', () => {
    const mano = Array.from({ length: N_MANO }, (_, i) => ({ x: 0.1 + i * 0.01, y: 0, z: 0 }));
    const v = construirVector({ rightHandLandmarks: mano }, 640, 480)!;
    expect(v[INICIO_MANO_DER]).toBeCloseTo(0.1, 6);
    expect(v[INICIO_MANO_DER + 60]).toBeCloseTo(0.3, 6);
  });

  it.each([
    ['poseLandmarks', 0, 99],
    ['faceLandmarks', 99, 1503],
    ['leftHandLandmarks', 1503, 1566],
    ['rightHandLandmarks', 1566, 1629],
  ] as const)('deja en 0.0 exacto el bloque ausente %s', (bloque, inicio, fin) => {
    for (const ausente of [undefined, null, []]) {
      const v = construirVector({ ...COMPLETO, [bloque]: ausente }, 640, 480)!;
      expect(v.subarray(inicio, fin).every((x) => Object.is(x, 0))).toBe(true);
      expect(v.subarray(0, inicio).some((x) => x === 0)).toBe(false);
      expect(v.subarray(fin).some((x) => x === 0)).toBe(false);
    }
  });

  it('sin detecciones produce 1629 ceros', () => {
    expect(construirVector({}, 640, 480)!.every((x) => Object.is(x, 0))).toBe(true);
  });

  it('descarta los puntos de iris si llegaran 478 de rostro', () => {
    const v = construirVector({ ...COMPLETO, faceLandmarks: puntos(478, 2000) }, 100, 100)!;
    expect(v[1500]).toBe(2467);
    expect(v[1503]).toBe(3000);
  });

  it.each([NaN, Infinity, -Infinity, 1e300])('rechaza el frame con %s', (malo) => {
    for (const eje of ['x', 'y', 'z'] as const) {
      const mano = puntos(N_MANO, 1);
      mano[7] = { ...mano[7], [eje]: malo };
      expect(construirVector({ ...COMPLETO, leftHandLandmarks: mano }, 640, 480)).toBeNull();
    }
  });

  it.each([
    [0, 480],
    [640, 0],
    [NaN, 480],
  ])('rechaza dimensiones inválidas (%s x %s)', (ancho, alto) => {
    expect(construirVector(COMPLETO, ancho, alto)).toBeNull();
  });

  it('no reutiliza memoria entre frames', () => {
    const a = construirVector(COMPLETO, 640, 480)!;
    const b = construirVector({}, 640, 480)!;
    expect(a.buffer).not.toBe(b.buffer);
    expect(a[0]).toBe(1000);
  });
});
