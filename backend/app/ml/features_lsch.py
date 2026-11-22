"""
features_lsch.py (v3) — Selección de landmarks y normalización espacial para LSCh.

Módulo compartido entre el entrenamiento, la inferencia local y la API (FastAPI).
Importar SIEMPRE estas funciones (en lugar de reimplementarlas) garantiza que el
modelo reciba exactamente la misma representación en todos los contextos.
Solo depende de NumPy: no importa TensorFlow.

Entrada: tensor (30, 1629) float32 de MediaPipe Holistic con y ISOTRÓPICA
(y * alto/ancho, misma unidad que x), en este orden:
    Pose              0:99     (33 landmarks x 3: x, y, z)
    Rostro           99:1503   (468 landmarks x 3)
    Mano izquierda 1503:1566   (21 landmarks x 3)
    Mano derecha   1566:1629   (21 landmarks x 3)

Pipeline por secuencia:
    1. seleccionar_landmarks    (30, 1629)  -> (30, 76, 3)   543 -> 76 landmarks
    2. normalizar_por_hombros   (30, 76, 3) -> (30, 76, 3)   centro/escala de hombros (z centrada
                                                             solo en pose), clip, máscara
       --- en entrenamiento, el aumento de datos se aplica aquí ---
    3. construir_features       (30, 76, 3) -> (30, 576)
         [coords_global (228) | velocidad_global (228) | forma_local_manos (120)]

Uso en inferencia (local o FastAPI):
    import features_lsch as fx
    fx.verificar_config("modelos/config_features.json")   # una vez, al arrancar
    x = fx.preparar_entrada_modelo(tensor)                 # (30, 576) float32
    probabilidades = modelo.predict(x[np.newaxis], verbose=0)[0]
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np

VERSION_CONFIG = 3  # v2: z de rostro/manos sin centrar | v3: + forma local de manos, y isotrópica

# =============================================================================
# FORMATO DE ENTRADA (MediaPipe Holistic aplanado)
# =============================================================================
N_FRAMES = 30
N_LANDMARKS_POSE = 33
N_LANDMARKS_ROSTRO = 468
N_LANDMARKS_MANO = 21
N_LANDMARKS_ORIGINAL = N_LANDMARKS_POSE + N_LANDMARKS_ROSTRO + 2 * N_LANDMARKS_MANO  # 543
N_FEATURES_ORIGINAL = N_LANDMARKS_ORIGINAL * 3                                        # 1629
SHAPE_ENTRADA = (N_FRAMES, N_FEATURES_ORIGINAL)

# Primer landmark de cada bloque dentro de los 543
INICIO_POSE = 0
INICIO_ROSTRO = INICIO_POSE + N_LANDMARKS_POSE            # 33  -> features 99
INICIO_MANO_IZQ = INICIO_ROSTRO + N_LANDMARKS_ROSTRO      # 501 -> features 1503
INICIO_MANO_DER = INICIO_MANO_IZQ + N_LANDMARKS_MANO      # 522 -> features 1566

# =============================================================================
# SELECCIÓN DE LANDMARKS (543 -> 76)
# =============================================================================
POSE_SELECCION = [0, 11, 12, 13, 14, 15, 16]  # nariz, hombros, codos, muñecas
_NOMBRES_POSE = {
    0: "nariz", 11: "hombro_izq", 12: "hombro_der", 13: "codo_izq",
    14: "codo_der", 15: "muneca_izq", 16: "muneca_der",
}

# Rostro: 27 puntos expresivos de FaceMesh (componentes no manuales de la seña).
ROSTRO_SELECCION = {
    "nariz": [1],
    "ojos": [33, 133, 159, 145, 362, 263, 386, 374],
    "cejas": [70, 63, 105, 66, 107, 336, 296, 334, 293, 300],
    "boca": [61, 291, 13, 14, 78, 308, 0, 17],
}
_ROSTRO_PLANO = [indice for grupo in ROSTRO_SELECCION.values() for indice in grupo]

MANO_SELECCION = list(range(N_LANDMARKS_MANO))  # las 21 de cada mano

INDICES_LANDMARKS = np.array(
    [INICIO_POSE + i for i in POSE_SELECCION]
    + [INICIO_ROSTRO + i for i in _ROSTRO_PLANO]
    + [INICIO_MANO_IZQ + i for i in MANO_SELECCION]
    + [INICIO_MANO_DER + i for i in MANO_SELECCION],
    dtype=np.intp,
)
NOMBRES_LANDMARKS = (
    [f"pose_{_NOMBRES_POSE[i]}" for i in POSE_SELECCION]
    + [f"rostro_{grupo}_{i}" for grupo, indices in ROSTRO_SELECCION.items() for i in indices]
    + [f"mano_izq_{i}" for i in MANO_SELECCION]
    + [f"mano_der_{i}" for i in MANO_SELECCION]
)

N_LANDMARKS = len(INDICES_LANDMARKS)   # 76
N_COORDS = N_LANDMARKS * 3             # 228

# Rango [inicio, fin) de cada bloque dentro de los 76 landmarks seleccionados
_FIN_POSE = len(POSE_SELECCION)
_FIN_ROSTRO = _FIN_POSE + len(_ROSTRO_PLANO)
_FIN_MANO_IZQ = _FIN_ROSTRO + N_LANDMARKS_MANO
BLOQUES = {
    "pose": (0, _FIN_POSE),
    "rostro": (_FIN_POSE, _FIN_ROSTRO),
    "mano_izquierda": (_FIN_ROSTRO, _FIN_MANO_IZQ),
    "mano_derecha": (_FIN_MANO_IZQ, N_LANDMARKS),
}
BLOQUES_MANOS = ("mano_izquierda", "mano_derecha")

# Posición de los hombros (Pose 11 y 12) dentro de los 76 landmarks
IDX_HOMBRO_IZQ = POSE_SELECCION.index(11)
IDX_HOMBRO_DER = POSE_SELECCION.index(12)

# Forma local de la mano: landmarks relativos a la muñeca, escalados por la palma
IDX_MUNECA = 0          # dentro de cada mano
IDX_NUDILLO_MEDIO = 9   # base del dedo medio
N_LANDMARKS_FORMA_MANO = N_LANDMARKS_MANO - 1  # 20: la muñeca se omite (siempre sería 0)

# Tamaño de cada bloque de features por frame
N_FEATURES_COORDS = N_COORDS                                          # 228
N_FEATURES_VELOCIDAD = N_COORDS                                       # 228
N_FEATURES_FORMA = len(BLOQUES_MANOS) * N_LANDMARKS_FORMA_MANO * 3    # 120
N_FEATURES_MODELO = N_FEATURES_COORDS + N_FEATURES_VELOCIDAD + N_FEATURES_FORMA  # 576
SHAPE_MODELO = (N_FRAMES, N_FEATURES_MODELO)

assert N_LANDMARKS == 76 and len(set(INDICES_LANDMARKS.tolist())) == N_LANDMARKS
assert N_FEATURES_MODELO == 576

# Qué coordenadas se centran en el punto medio de los hombros (1.0) y cuáles solo
# se dividen por la escala (0.0): x, y en todos los bloques; z solo en pose.
# MediaPipe mide la z de cada bloque desde un origen propio: la pose desde el
# punto medio de las caderas, el rostro desde el centro de la cabeza y cada mano
# desde su muñeca. Restarle a una mano la z de los hombros mezclaría sistemas de
# referencia y añadiría un desplazamiento sin significado.
BLOQUES_Z_CENTRADA = ("pose",)


def _mascara_centrado() -> np.ndarray:
    mascara = np.ones((N_LANDMARKS, 3), dtype=np.float32)
    for bloque, (inicio, fin) in BLOQUES.items():
        if bloque not in BLOQUES_Z_CENTRADA:
            mascara[inicio:fin, 2] = 0.0
    mascara.setflags(write=False)
    return mascara


CENTRAR_COORDENADA = _mascara_centrado()  # (76, 3)

# =============================================================================
# PARÁMETROS DE NORMALIZACIÓN
# =============================================================================
UMBRAL_DETECCION = 1e-6   # norma (x, y, z) por debajo de esto = landmark no detectado
ESCALA_MINIMA = 1e-4      # distancia entre hombros (o tamaño de palma) por debajo = inválida
LIMITE_CLIP = 5.0         # features recortadas a [-5, 5]


# =============================================================================
# 1. SELECCIÓN
# =============================================================================
def seleccionar_landmarks(tensor: np.ndarray) -> np.ndarray:
    """(..., 1629) -> (..., 76, 3) float32.

    NaN e infinitos se convierten en 0.0, es decir, se tratan como no detectados.
    """
    datos = np.asarray(tensor, dtype=np.float32)
    if datos.shape[-1] != N_FEATURES_ORIGINAL:
        raise ValueError(f"Se esperaban {N_FEATURES_ORIGINAL} features por frame; llegó {datos.shape}")
    datos = np.nan_to_num(datos, nan=0.0, posinf=0.0, neginf=0.0)
    landmarks = datos.reshape(*datos.shape[:-1], N_LANDMARKS_ORIGINAL, 3)
    return landmarks[..., INDICES_LANDMARKS, :]


# =============================================================================
# 2. MÁSCARAS
# =============================================================================
def mascara_deteccion(landmarks: np.ndarray) -> np.ndarray:
    """(..., 3) -> (...) bool: True si norma(x, y, z) >= UMBRAL_DETECCION.

    MediaPipe escribe (0, 0, 0) cuando no detecta un landmark (p. ej. una mano
    fuera de cuadro). Ese cero significa "ausente", no "posición 0".
    """
    return np.linalg.norm(landmarks, axis=-1) >= UMBRAL_DETECCION


def mascara_no_nulos(coords: np.ndarray) -> np.ndarray:
    """(..., 3) -> (...) bool. Para coordenadas YA NORMALIZADAS: True si no es exactamente (0, 0, 0).

    normalizar_por_hombros deja los landmarks no detectados en 0.0 exacto, así
    que tras normalizar "ausente" equivale a "las tres coordenadas son cero".
    """
    return np.any(coords != 0.0, axis=-1)


# =============================================================================
# 3. NORMALIZACIÓN CENTRADA EN HOMBROS
# =============================================================================
def _validar_secuencia(landmarks: np.ndarray) -> np.ndarray:
    lm = np.asarray(landmarks, dtype=np.float32)
    if lm.ndim != 3 or lm.shape[1:] != (N_LANDMARKS, 3):
        raise ValueError(f"Se esperaba una secuencia (T, {N_LANDMARKS}, 3); llegó {lm.shape}")
    return lm


def _hombros(lm: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centro (T, 3), escala (T,) y frames válidos (T,) a partir de los hombros crudos."""
    hombro_izq = lm[:, IDX_HOMBRO_IZQ, :].astype(np.float64)
    hombro_der = lm[:, IDX_HOMBRO_DER, :].astype(np.float64)
    centro = (hombro_izq + hombro_der) / 2.0
    escala = np.linalg.norm(hombro_izq[:, :2] - hombro_der[:, :2], axis=-1)  # distancia 2D (x, y)
    detectado = mascara_deteccion(lm)
    validos = detectado[:, IDX_HOMBRO_IZQ] & detectado[:, IDX_HOMBRO_DER] & (escala >= ESCALA_MINIMA)
    return centro, escala, validos


def frames_con_hombros_validos(landmarks: np.ndarray) -> np.ndarray:
    """(T, 76, 3) crudos -> (T,) bool: ambos hombros detectados y separados al menos ESCALA_MINIMA."""
    return _hombros(_validar_secuencia(landmarks))[2]


def referencia_hombros(landmarks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centro (T, 3) y escala (T,) por frame, con el respaldo ya aplicado.

    Frames sin hombros válidos usan la mediana del centro y de la escala de los
    frames válidos de la MISMA secuencia. Si ningún frame es válido: centro = 0,
    escala = 1 (las coordenadas quedan sin normalizar, solo recortadas).
    """
    centro, escala, validos = _hombros(_validar_secuencia(landmarks))
    if validos.any():
        centro_ref = np.median(centro[validos], axis=0)
        escala_ref = float(np.median(escala[validos]))
    else:
        centro_ref, escala_ref = np.zeros(3), 1.0
    centro[~validos] = centro_ref
    escala[~validos] = escala_ref
    return centro, escala


def normalizar_por_hombros(landmarks: np.ndarray) -> np.ndarray:
    """(T, 76, 3) crudos -> (T, 76, 3) normalizados, invariantes a posición, estatura y distancia.

    Por frame, con centro = punto medio de los hombros y escala = distancia 2D
    (x, y) entre hombros:
        x, y  (todos los bloques)          ->  (coord - centro) / escala
        z     de pose                      ->  (z - centro_z) / escala
        z     de rostro, mano izq y der    ->  z / escala   (conserva su origen
                                               local de cabeza/muñeca; ver
                                               CENTRAR_COORDENADA)
    Dividir todo por la misma escala iguala las proporciones entre sujetos.
    Luego se recorta a [-LIMITE_CLIP, LIMITE_CLIP] para frenar anomalías puntuales.

    La máscara de detección se calcula ANTES de normalizar y se re-aplica al
    final: un landmark no detectado vale exactamente 0.0 a la salida. Sin esto,
    (0 - centro) / escala convertiría la mano ausente en una "mano fantasma".
    """
    lm = _validar_secuencia(landmarks)
    detectado = mascara_deteccion(lm)                       # (T, 76), antes de normalizar
    centro, escala = referencia_hombros(lm)                 # (T, 3), (T,)
    origen = centro[:, np.newaxis, :] * CENTRAR_COORDENADA  # (T, 76, 3): z = 0 fuera de pose
    normalizado = (lm - origen) / escala[:, np.newaxis, np.newaxis]
    normalizado = np.clip(normalizado, -LIMITE_CLIP, LIMITE_CLIP)
    normalizado[~detectado] = 0.0
    return normalizado.astype(np.float32)


# =============================================================================
# 4. FEATURES DEL MODELO (se calculan DESPUÉS del aumento de datos)
# =============================================================================
def _validar_coords(coords_norm: np.ndarray) -> np.ndarray:
    coords = np.asarray(coords_norm, dtype=np.float32)
    if coords.ndim < 3 or coords.shape[-2:] != (N_LANDMARKS, 3):
        raise ValueError(f"Se esperaba (..., T, {N_LANDMARKS}, 3); llegó {coords.shape}")
    return coords


def agregar_velocidad(coords_norm: np.ndarray) -> np.ndarray:
    """(..., T, 76, 3) normalizado -> (..., T, 456) float32 = [coords_global | velocidad_global].

    vel[t] = coords[t] - coords[t-1], con vel[0] = 0.
    Si el landmark falta en t o en t-1, su velocidad es 0.0: así una mano que
    entra o sale de cuadro no produce un salto artificial desde/hacia el origen.
    Acepta una secuencia (T, 76, 3) o un lote (N, T, 76, 3).
    """
    coords = _validar_coords(coords_norm)
    presentes = mascara_no_nulos(coords)                                     # (..., T, 76)
    velocidad = np.zeros_like(coords)
    velocidad[..., 1:, :, :] = coords[..., 1:, :, :] - coords[..., :-1, :, :]
    continuo = np.zeros_like(presentes)
    continuo[..., 1:, :] = presentes[..., 1:, :] & presentes[..., :-1, :]
    velocidad *= continuo[..., np.newaxis]

    forma_plana = coords.shape[:-2] + (N_COORDS,)
    salida = np.concatenate([coords.reshape(forma_plana), velocidad.reshape(forma_plana)], axis=-1)
    return salida.astype(np.float32, copy=False)


def forma_local_manos(coords_norm: np.ndarray) -> np.ndarray:
    """(..., T, 76, 3) normalizado -> (..., T, 120) float32: forma de cada mano en su propio marco.

    Para cada mano (izquierda y luego derecha) y cada frame donde esté detectada:
        forma[k] = (landmark_k - muñeca) / escala_palma,   k = 1..20   (x, y, z)
        escala_palma = norma 3D(landmark_9 - muñeca)  (muñeca a nudillo del dedo medio)
    Si escala_palma < ESCALA_MINIMA se usa la mediana de los frames válidos de
    esa mano en la secuencia (respaldo 1.0). Luego se recorta a [-5, 5].
    Si la mano no está detectada en el frame, sus 60 valores quedan en 0.0.

    Al restar la muñeca y dividir por la palma, esta forma no depende de dónde
    está la mano ni de la distancia a la cámara: describe solo la configuración
    de los dedos, que es justo lo que la normalización por hombros diluye.
    """
    coords = _validar_coords(coords_norm)
    partes = []
    for bloque in BLOQUES_MANOS:
        inicio, fin = BLOQUES[bloque]
        mano = coords[..., inicio:fin, :].astype(np.float64)                  # (..., T, 21, 3)
        presentes = mascara_deteccion(mano)                                    # (..., T, 21)
        detectada = presentes.any(axis=-1)                                     # (..., T)
        muneca = mano[..., IDX_MUNECA, :]
        relativa = mano[..., 1:, :] - muneca[..., np.newaxis, :]               # (..., T, 20, 3)

        palma = np.linalg.norm(mano[..., IDX_NUDILLO_MEDIO, :] - muneca, axis=-1)  # (..., T)
        valida = detectada & (palma >= ESCALA_MINIMA)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # secuencias sin ninguna palma válida
            referencia = np.nanmedian(np.where(valida, palma, np.nan), axis=-1, keepdims=True)
        referencia = np.where(np.isnan(referencia), 1.0, referencia)
        palma = np.where(valida, palma, referencia)

        forma = np.clip(relativa / palma[..., np.newaxis, np.newaxis], -LIMITE_CLIP, LIMITE_CLIP)
        visible = detectada[..., np.newaxis] & presentes[..., 1:]               # (..., T, 20)
        forma = np.where(visible[..., np.newaxis], forma, 0.0)
        partes.append(forma.reshape(*forma.shape[:-2], N_LANDMARKS_FORMA_MANO * 3))
    return np.concatenate(partes, axis=-1).astype(np.float32)


def construir_features(coords_norm: np.ndarray) -> np.ndarray:
    """(..., T, 76, 3) normalizado -> (..., T, 576) float32: exactamente lo que recibe el modelo.

    [coords_global (228) | velocidad_global (228) | forma_local_manos (120)].
    Es la misma función para el aumento al vuelo, la validación, el test y la inferencia.
    """
    return np.concatenate([agregar_velocidad(coords_norm), forma_local_manos(coords_norm)], axis=-1)


# =============================================================================
# PIPELINE COMPLETO
# =============================================================================
def extraer_coordenadas(tensor: np.ndarray) -> np.ndarray:
    """(30, 1629) crudo -> (30, 76, 3) normalizado (entrada del aumento de datos)."""
    datos = np.asarray(tensor)
    if datos.shape != SHAPE_ENTRADA:
        raise ValueError(f"Se esperaba un tensor {SHAPE_ENTRADA}; llegó {datos.shape}")
    return normalizar_por_hombros(seleccionar_landmarks(datos))


def preparar_entrada_modelo(tensor: np.ndarray) -> np.ndarray:
    """(30, 1629) crudo -> (30, 576) float32: exactamente lo que recibe el modelo."""
    return construir_features(extraer_coordenadas(tensor))


# =============================================================================
# CONFIGURACIÓN (modelos/config_features.json)
# =============================================================================
def configuracion() -> dict:
    """Descripción completa de la transformación, para guardarla junto al modelo."""
    return {
        "version": VERSION_CONFIG,
        "features_por_frame": N_FEATURES_MODELO,
        "requiere_y_isotropica": True,
        "entrada": {
            "shape": list(SHAPE_ENTRADA),
            "y_isotropica": "y multiplicada por alto/ancho del video (misma unidad que x)",
            "bloques_features": {
                "pose": [INICIO_POSE * 3, INICIO_ROSTRO * 3],
                "rostro": [INICIO_ROSTRO * 3, INICIO_MANO_IZQ * 3],
                "mano_izquierda": [INICIO_MANO_IZQ * 3, INICIO_MANO_DER * 3],
                "mano_derecha": [INICIO_MANO_DER * 3, N_FEATURES_ORIGINAL],
            },
        },
        "seleccion": {
            "pose": POSE_SELECCION,
            "rostro": ROSTRO_SELECCION,
            "mano_izquierda": MANO_SELECCION,
            "mano_derecha": MANO_SELECCION,
        },
        "n_landmarks": N_LANDMARKS,
        "indices_landmarks_543": INDICES_LANDMARKS.tolist(),
        "nombres_landmarks": NOMBRES_LANDMARKS,
        "bloques_seleccion": {nombre: list(rango) for nombre, rango in BLOQUES.items()},
        "normalizacion": {
            "metodo": "centro y escala de hombros, por frame",
            "hombros_pose": [11, 12],
            "centro": "(hombro_izq + hombro_der) / 2",
            "escala": "distancia euclidiana 2D (x, y) entre hombros",
            "x_y": "(coord - centro) / escala en todos los bloques",
            "z_centrada_y_escalada": list(BLOQUES_Z_CENTRADA),
            "z_solo_escalada": [b for b in BLOQUES if b not in BLOQUES_Z_CENTRADA],
            "umbral_deteccion": UMBRAL_DETECCION,
            "escala_minima": ESCALA_MINIMA,
            "respaldo": "mediana de los frames válidos de la secuencia; sin frames válidos: centro=0, escala=1",
            "clip": [-LIMITE_CLIP, LIMITE_CLIP],
            "no_detectados": "permanecen en 0.0",
        },
        "velocidad": "vel[t] = x[t] - x[t-1]; vel[0] = 0; 0 si el landmark falta en t o en t-1",
        "forma_local_manos": {
            "manos": list(BLOQUES_MANOS),
            "landmarks": "1..20 de cada mano, (x, y, z) relativos a la muñeca (landmark 0)",
            "escala": f"norma 3D(landmark_{IDX_NUDILLO_MEDIO} - landmark_{IDX_MUNECA})",
            "respaldo": "mediana de los frames válidos de esa mano; sin frames válidos: 1.0",
            "clip": [-LIMITE_CLIP, LIMITE_CLIP],
            "no_detectada": "60 valores en 0.0",
        },
        "salida": {
            "shape": list(SHAPE_MODELO),
            "orden": [
                f"coords_global ({N_FEATURES_COORDS}: lm0_x, lm0_y, lm0_z, lm1_x, ...)",
                f"velocidad_global ({N_FEATURES_VELOCIDAD}, mismo orden)",
                f"forma_local_manos ({N_FEATURES_FORMA}: mano izq lm1..20 x,y,z | mano der lm1..20 x,y,z)",
            ],
        },
    }


def guardar_config(ruta: str | Path) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(configuracion(), ensure_ascii=False, indent=2), encoding="utf-8")


def verificar_config(ruta: str | Path) -> None:
    """Falla si la configuración guardada con el modelo no coincide con este módulo.

    Evita que la inferencia use, sin aviso, una selección o normalización
    distinta a la del entrenamiento (p. ej. un modelo v2 con features v3).
    """
    guardada = json.loads(Path(ruta).read_text(encoding="utf-8"))
    actual = json.loads(json.dumps(configuracion(), ensure_ascii=False))
    if guardada.get("version") != actual["version"]:
        raise ValueError(
            f"{ruta} es versión {guardada.get('version')} y features_lsch.py es versión "
            f"{actual['version']} ({actual['features_por_frame']} features por frame). "
            "El modelo se entrenó con otra transformación: reentrénalo o usa la versión correspondiente."
        )
    if guardada != actual:
        distintas = sorted(k for k in set(guardada) | set(actual) if guardada.get(k) != actual.get(k))
        raise ValueError(
            f"{ruta} no coincide con features_lsch.py (claves distintas: {distintas}). "
            "El modelo se entrenó con otra transformación de features."
        )
