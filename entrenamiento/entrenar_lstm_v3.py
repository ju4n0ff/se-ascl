"""
entrenar_lstm_v3.py — Entrenamiento LSCh v3 (features de 576 por frame) con tres modos.

Modos (--modo):
    eval_webcam (por defecto)
        train_base = train/ + videos de test grabados en vertical (~1.819).
        test_webcam = videos de test grabados en horizontal (webcam, ~180).
        Etapas: 1) carga y diagnóstico, 2) K-Fold (K=5) sobre train_base,
        3) modelo definitivo -> modelos/mejor_modelo_eval_webcam.keras,
        4) evaluación en test_webcam.
    comparar_original
        Split original train/ (1.087) vs test/ (912) sobre tensores_v2, para medir
        cuánto mejoró el Cross-Subject solo por corregir rotación y aspecto.
        Mismas 4 etapas -> modelos/mejor_modelo_comparacion.keras.
    produccion
        100 % de los videos (train/ + test/, ~1.999). Split estratificado 90/10
        (al menos 1 video por clase en validación) -> modelos/mejor_modelo_lsch.keras
        + etiquetas_lsch.json + config_features.json. Imprime top-1/top-5 de esa
        validación intacta.

Identificación de los videos de webcam (modo eval_webcam), por prioridad:
    1. --webcam-dir <carpeta>/<clase>/<archivo>.npy, si se pasa (decisión explícita).
    2. <tensores-dir>/metadata_v2.json: split == "test" y orientacion_orig ==
       "horizontal" -> webcam; "vertical" -> train_base.
    3. Respaldo v1: el mismo archivo en <tensores-v1-dir>/test/ (sin rotar) con
       ratio_vh >= 0.5 -> webcam; < 0.5 -> train_base.
Los videos de test que no se puedan clasificar quedan fuera de ambos conjuntos.

AISLAMIENTO CONTRA FUGA DE DATOS
    * Los videos de evaluación no intervienen antes de la etapa 4: el
      LabelEncoder se ajusta con train_base, el K-Fold y el modelo definitivo
      solo reciben train_base, y el EarlyStopping solo mira train_base.
    * Toda división (folds y 90/10) se hace sobre videos ORIGINALES; el aumento
      se aplica después y solo del lado de entrenamiento.
    * La normalización es por secuencia (sin estadísticas del dataset), así que
      aplicarla antes de dividir no traspasa información entre conjuntos.

GESTIÓN DE VRAM
    * memory growth al importar, antes de crear tensores.
    * Datasets creados bajo /CPU:0: a la GPU viaja un batch por paso.
    * clear_session() + gc.collect() entre folds y etapas.

Uso (en la carpeta de features_lsch.py):
    python entrenar_lstm_v3.py                                  # eval_webcam
    python entrenar_lstm_v3.py --modo comparar_original
    python entrenar_lstm_v3.py --modo produccion
    python entrenar_lstm_v3.py --modo eval_webcam --webcam-dir dataset/webcam --sin-kfold
"""

from __future__ import annotations

import argparse
import gc
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import tensorflow as tf
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder

import features_lsch as fx


# =============================================================================
# 0. GPU (antes de crear cualquier tensor o modelo)
# =============================================================================
def configurar_gpu() -> None:
    """Activa memory growth en todas las GPUs físicas."""
    gpus = tf.config.list_physical_devices("GPU")
    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError as error:  # la GPU ya estaba inicializada
            print(f"[AVISO] No se pudo activar memory growth en {gpu.name}: {error}")
    print(f"GPUs detectadas: {[gpu.name for gpu in gpus] or 'ninguna (se usará CPU)'}")


configurar_gpu()


# =============================================================================
# CONFIGURACIÓN
# =============================================================================
RUTA_MODELOS = Path("modelos")
RUTA_ETIQUETAS = RUTA_MODELOS / "etiquetas_lsch.json"
RUTA_CONFIG_FEATURES = RUTA_MODELOS / "config_features.json"
MODELO_POR_MODO = {
    "eval_webcam": RUTA_MODELOS / "mejor_modelo_eval_webcam.keras",
    "comparar_original": RUTA_MODELOS / "mejor_modelo_comparacion.keras",
    "produccion": RUTA_MODELOS / "mejor_modelo_lsch.keras",
}
NOMBRE_METADATA = "metadata_v2.json"
UMBRAL_RATIO_WEBCAM_V1 = 0.5      # ratio_vh en v1 (sin rotar) >= 0.5 -> grabado en horizontal

NUM_CLASES_ESPERADAS = 89
N_SPLITS = 5
VAL_INTERNA_FINAL = 0.10          # fracción de videos ORIGINALES para EarlyStopping
SEMILLA = 42

# Aumento al vuelo. Unidades normalizadas: 1.0 = ancho de hombros.
REPETICIONES_POR_EPOCA = 4
AUM_ESCALA = (0.85, 1.15)
AUM_ROTACION_GRADOS = 10.0        # rotación en el plano (x, y) alrededor del centro de hombros
AUM_DESPLAZAMIENTO_XY = 0.06
AUM_SIGMA_RUIDO = 0.015
AUM_VELOCIDAD_TEMPORAL = (0.90, 1.10)
AUM_CURVATURA_TEMPORAL = 0.05
AUM_DESPLAZAMIENTO_FRAMES = 2
AUM_PROB_DROPOUT_MANO = 0.20      # prob. de borrar una mano en 1-2 frames (microcortes de MediaPipe)
AUM_MAX_FRAMES_DROPOUT = 2

# Entrenamiento
BATCH_SIZE = 32
EPOCHS = 200                      # se puede cambiar con --epochs
LR_INICIAL = 1e-3
WEIGHT_DECAY = 1e-4
CLIPNORM = 1.0
LABEL_SMOOTHING = 0.1
PACIENCIA_EARLY_STOPPING = 25
PACIENCIA_REDUCE_LR = 8
FACTOR_REDUCE_LR = 0.5
LR_MINIMO = 1e-5
TOP_K = 5
TOP_N_REPORTE = 10
VERBOSE_FOLDS = 0
VERBOSE_FINAL = 2


# =============================================================================
# 1. CARGA
# =============================================================================
@dataclass
class Videos:
    rutas: np.ndarray          # p. ej. "test/hola/abc.npy" (relativa a la carpeta de tensores)
    clases: np.ndarray         # nombre de la carpeta de cada archivo
    coords: np.ndarray         # (N, 30, 76, 3) normalizado por hombros (sin features derivadas)
    ratio_vh: np.ndarray       # (N,) sanidad de la y isotrópica
    frames_respaldo: np.ndarray  # (N,) frames sin hombros válidos (usaron la mediana)

    def __len__(self) -> int:
        return len(self.rutas)

    def subconjunto(self, mascara: np.ndarray) -> "Videos":
        return Videos(self.rutas[mascara], self.clases[mascara], self.coords[mascara],
                      self.ratio_vh[mascara], self.frames_respaldo[mascara])

    def unir(self, otro: "Videos") -> "Videos":
        return Videos(*(np.concatenate([a, b]) for a, b in zip(
            (self.rutas, self.clases, self.coords, self.ratio_vh, self.frames_respaldo),
            (otro.rutas, otro.clases, otro.coords, otro.ratio_vh, otro.frames_respaldo))))


def ratio_vh_crudo(tensor: np.ndarray) -> float:
    """Mediana por frame de |y_nariz - y_centro_hombros| / distancia 2D entre hombros (NaN si no hay)."""
    lm = np.nan_to_num(np.asarray(tensor, dtype=np.float32)).reshape(fx.N_FRAMES, fx.N_LANDMARKS_ORIGINAL, 3)
    nariz, h_izq, h_der = lm[:, fx.INICIO_POSE + 0], lm[:, fx.INICIO_POSE + 11], lm[:, fx.INICIO_POSE + 12]
    ancho = np.linalg.norm(h_izq[:, :2] - h_der[:, :2], axis=-1)
    valido = (fx.mascara_deteccion(nariz) & fx.mascara_deteccion(h_izq) & fx.mascara_deteccion(h_der)
              & (ancho >= fx.ESCALA_MINIMA))
    if not valido.any():
        return float("nan")
    alto = np.abs(nariz[:, 1] - (h_izq[:, 1] + h_der[:, 1]) / 2)
    return float(np.median(alto[valido] / ancho[valido]))


def cargar_videos(carpeta: Path, prefijo: str) -> Videos:
    """Lee <carpeta>/<clase>/<archivo>.npy (recursivo). Omite con aviso los ilegibles o mal formados."""
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {carpeta.resolve()}")
    rutas, clases, coords, ratios, respaldos, omitidos = [], [], [], [], [], []
    for archivo in sorted(carpeta.rglob("*.npy")):
        relativa = f"{prefijo}/{archivo.relative_to(carpeta).as_posix()}"
        try:
            tensor = np.load(archivo)
        except (OSError, ValueError):
            omitidos.append(relativa)
            continue
        if tensor.shape != fx.SHAPE_ENTRADA:
            omitidos.append(relativa)
            continue
        validos = fx.frames_con_hombros_validos(fx.seleccionar_landmarks(tensor))
        rutas.append(relativa)
        clases.append(archivo.parent.name)
        coords.append(fx.extraer_coordenadas(tensor))  # misma función que la inferencia
        ratios.append(ratio_vh_crudo(tensor))
        respaldos.append(int((~validos).sum()))
    if omitidos:
        print(f"[AVISO] {len(omitidos)} archivos omitidos en {carpeta} (ilegibles o shape distinto de "
              f"{fx.SHAPE_ENTRADA}): {', '.join(omitidos[:3])}{' ...' if len(omitidos) > 3 else ''}")
    if not rutas:
        raise ValueError(f"No hay tensores válidos en {carpeta.resolve()}")
    return Videos(np.array(rutas), np.array(clases), np.stack(coords), np.array(ratios), np.array(respaldos))


def imprimir_diagnostico(nombre: str, videos: Videos) -> None:
    """Detección por bloque, respaldo de hombros y ratio_vh (sanidad de la y isotrópica)."""
    presentes = fx.mascara_no_nulos(videos.coords)  # (N, 30, 76)
    deteccion = "  |  ".join(
        f"{bloque} {presentes[..., ini:fin].any(axis=-1).mean():.1%}" for bloque, (ini, fin) in fx.BLOQUES.items()
    )
    ratios = videos.ratio_vh[np.isfinite(videos.ratio_vh)]
    ratio = (f"mediana {np.median(ratios):.2f} (p5 {np.percentile(ratios, 5):.2f} - p95 "
             f"{np.percentile(ratios, 95):.2f})" if len(ratios) else "sin frames válidos")
    total_frames = videos.coords.shape[0] * videos.coords.shape[1]
    print(f"[{nombre}] {len(videos)} videos, {len(set(videos.clases.tolist()))} clases")
    print(f"[{nombre}] Frames con el bloque detectado: {deteccion}")
    print(f"[{nombre}] Hombros: {videos.frames_respaldo.sum()} frames ({videos.frames_respaldo.sum() / total_frames:.2%}) "
          f"usaron la mediana de su secuencia | ratio_vh {ratio}")


# =============================================================================
# 2. SEPARACIÓN SEGÚN EL MODO
# =============================================================================
CLAVES_RUTA_METADATA = ("ruta_npy", "npy", "ruta_tensor", "tensor", "archivo_npy", "ruta", "path",
                        "archivo", "file", "nombre", "video", "ruta_video", "_clave")
CLAVES_CLASE_METADATA = ("clase", "categoria", "etiqueta", "label", "sena", "seña")


def _registros_metadata(metadata) -> list[dict]:
    if isinstance(metadata, list):
        return [r for r in metadata if isinstance(r, dict)]
    if isinstance(metadata, dict):
        for clave in ("videos", "registros", "items", "data", "archivos"):
            if isinstance(metadata.get(clave), list):
                return [r for r in metadata[clave] if isinstance(r, dict)]
        if metadata and all(isinstance(v, dict) for v in metadata.values()):
            return [{"_clave": k, **v} for k, v in metadata.items()]
    raise ValueError("Formato de metadata_v2.json no reconocido (se esperaba una lista de registros).")


def webcam_desde_metadata(ruta_metadata: Path, test: Videos) -> tuple[np.ndarray, np.ndarray, str]:
    """Máscaras (webcam, vertical) sobre `test` según orientacion_orig de los registros de test."""
    registros = _registros_metadata(json.loads(ruta_metadata.read_text(encoding="utf-8")))
    por_clase_y_nombre = {(c, PurePosixPath(r).stem): i for i, (r, c) in enumerate(zip(test.rutas, test.clases))}
    por_nombre = defaultdict(list)
    for i, r in enumerate(test.rutas):
        por_nombre[PurePosixPath(r).stem].append(i)

    def emparejar(registro: dict) -> int | None:
        clase = next((str(registro[k]) for k in CLAVES_CLASE_METADATA if registro.get(k)), None)
        for clave in CLAVES_RUTA_METADATA:
            valor = registro.get(clave)
            if not isinstance(valor, str) or not valor:
                continue
            ruta = PurePosixPath(valor.replace("\\", "/"))
            indice = por_clase_y_nombre.get((clase or ruta.parent.name, ruta.stem))
            if indice is None and len(por_nombre.get(ruta.stem, [])) == 1:
                indice = por_nombre[ruta.stem][0]
            if indice is not None:
                return indice
        return None

    webcam = np.zeros(len(test), bool)
    vertical = np.zeros(len(test), bool)
    sin_pareja = otra_orientacion = 0
    for registro in registros:
        if str(registro.get("split", "")).strip().lower() != "test":
            continue
        orientacion = str(registro.get("orientacion_orig", "")).strip().lower()
        indice = emparejar(registro)
        if indice is None:
            sin_pareja += 1
        elif orientacion == "horizontal":
            webcam[indice] = True
        elif orientacion == "vertical":
            vertical[indice] = True
        else:
            otra_orientacion += 1
    conflicto = webcam & vertical
    webcam &= ~conflicto
    vertical &= ~conflicto
    detalle = (f"{NOMBRE_METADATA}: {webcam.sum()} horizontales, {vertical.sum()} verticales"
               + (f", {sin_pareja} registros de test sin archivo" if sin_pareja else "")
               + (f", {otra_orientacion} con orientación desconocida" if otra_orientacion else "")
               + (f", {conflicto.sum()} con orientación contradictoria" if conflicto.any() else ""))
    return webcam, vertical, detalle


def webcam_desde_v1(carpeta_v1_test: Path, test: Videos) -> tuple[np.ndarray, np.ndarray, str]:
    """Máscaras (webcam, vertical) según ratio_vh del mismo archivo en v1 (sin rotar)."""
    webcam = np.zeros(len(test), bool)
    vertical = np.zeros(len(test), bool)
    for i, ruta in enumerate(test.rutas):
        equivalente = carpeta_v1_test / PurePosixPath(ruta).relative_to("test")
        try:
            tensor = np.load(equivalente)
        except (OSError, ValueError):
            continue
        if tensor.shape != fx.SHAPE_ENTRADA:
            continue
        ratio = ratio_vh_crudo(tensor)
        if np.isfinite(ratio):
            webcam[i] = ratio >= UMBRAL_RATIO_WEBCAM_V1
            vertical[i] = ratio < UMBRAL_RATIO_WEBCAM_V1
    detalle = (f"respaldo v1 ({carpeta_v1_test}, ratio_vh >= {UMBRAL_RATIO_WEBCAM_V1}): "
               f"{webcam.sum()} horizontales, {vertical.sum()} verticales")
    return webcam, vertical, detalle


def separar_eval_webcam(train: Videos, test: Videos, args: argparse.Namespace) -> tuple[Videos, Videos, str]:
    """train_base = train + test vertical; test_webcam = test horizontal (o --webcam-dir)."""
    if args.webcam_dir is not None:
        webcam = cargar_videos(args.webcam_dir, "webcam")
        claves_webcam = {(c, PurePosixPath(r).name) for r, c in zip(webcam.rutas, webcam.clases)}
        en_webcam = np.array([(c, PurePosixPath(r).name) in claves_webcam for r, c in zip(test.rutas, test.clases)])
        detalle = (f"--webcam-dir {args.webcam_dir}: {len(webcam)} videos de webcam; {en_webcam.sum()} "
                   f"archivos de test con el mismo nombre se excluyen de train_base")
        return train.unir(test.subconjunto(~en_webcam)), webcam, detalle

    ruta_metadata = args.tensores_dir / NOMBRE_METADATA
    carpeta_v1_test = args.tensores_v1_dir / "test"
    if ruta_metadata.is_file():
        es_webcam, es_vertical, detalle = webcam_desde_metadata(ruta_metadata, test)
    elif carpeta_v1_test.is_dir():
        es_webcam, es_vertical, detalle = webcam_desde_v1(carpeta_v1_test, test)
    else:
        raise FileNotFoundError(
            f"No se pueden identificar los videos de webcam: no existe {ruta_metadata} ni "
            f"{carpeta_v1_test}. Usa --webcam-dir."
        )
    sin_clasificar = ~es_webcam & ~es_vertical
    if sin_clasificar.any():
        detalle += (f" | [AVISO] {sin_clasificar.sum()} videos de test sin orientación quedan fuera "
                    f"de ambos conjuntos: {', '.join(test.rutas[sin_clasificar][:3])}")
    if not es_webcam.any():
        raise ValueError(f"No se identificó ningún video de webcam ({detalle}).")
    return train.unir(test.subconjunto(es_vertical)), test.subconjunto(es_webcam), detalle


# =============================================================================
# 3. ETIQUETAS
# =============================================================================
def guardar_etiquetas(clases: list[str], modo: str) -> Path:
    """Guarda modelos/etiquetas_lsch.json (índice i de la salida softmax = clases[i]).

    En los modos de evaluación no se pisa un etiquetas_lsch.json existente con
    otras clases (protege al modelo de producción): se guarda etiquetas_<modo>.json.
    """
    ruta = RUTA_ETIQUETAS
    if modo != "produccion" and ruta.is_file():
        try:
            previas = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previas = None
        if previas is not None and previas != clases:
            ruta = RUTA_MODELOS / f"etiquetas_{modo}.json"
            print(f"[AVISO] {RUTA_ETIQUETAS} ya existe con otras clases; las de este modo se guardan en {ruta}.")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(clases, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def codificar_evaluacion(videos: Videos, codificador: LabelEncoder) -> tuple[Videos, np.ndarray]:
    """Etiquetas de evaluación con el encoder de train_base; descarta clases desconocidas."""
    conocidas = np.isin(videos.clases, codificador.classes_)
    if not conocidas.all():
        print(f"[AVISO] {(~conocidas).sum()} videos de evaluación con clases ausentes en train_base se "
              f"descartan: {sorted(set(videos.clases[~conocidas].tolist()))}")
    if not conocidas.any():
        raise ValueError("Ninguna clase de evaluación coincide con las de train_base.")
    videos = videos.subconjunto(conocidas)
    return videos, codificador.transform(videos.clases)


# =============================================================================
# 4. AUMENTO AL VUELO (solo entrenamiento)
# =============================================================================
def indices_distorsion_temporal(n_frames: int, rng: np.random.Generator) -> np.ndarray:
    """Índices de frame con un tempo levemente distinto (frame más cercano, sin interpolar).

    origen(t) = 0.5 + (t - 0.5)·v + a·sin(π·t)  (t en [0, 1]) + desplazamiento entero d.
    Monótona (v - π·|a| > 0). Interpolar entre un frame con mano y otro sin ella
    crearía una mano a medio camino del origen; por eso se toma el más cercano.
    """
    t = np.linspace(0.0, 1.0, n_frames)
    velocidad = rng.uniform(*AUM_VELOCIDAD_TEMPORAL)
    curvatura = rng.uniform(-AUM_CURVATURA_TEMPORAL, AUM_CURVATURA_TEMPORAL)
    desplazamiento = rng.integers(-AUM_DESPLAZAMIENTO_FRAMES, AUM_DESPLAZAMIENTO_FRAMES + 1)
    origen = (0.5 + (t - 0.5) * velocidad + curvatura * np.sin(np.pi * t)) * (n_frames - 1)
    return np.clip(np.rint(origen + desplazamiento), 0, n_frames - 1).astype(np.intp)


def aumentar_secuencia(coords: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Aumento de UNA secuencia normalizada: (30, 76, 3) -> (30, 576) float32.

    1. escala uniforme [0.85, 1.15]          (alrededor del centro de hombros)
    2. rotación 2D en (x, y) de ±10°         (alrededor del centro de hombros)
    3. desplazamiento (x, y) en ±0.06
    4. ruido gaussiano sigma = 0.015, clip y máscara (ausentes siguen en 0.0)
    5. distorsión temporal (frame más cercano)
    6. hand dropout: con prob. 0.2 se borra una mano al azar en 1-2 frames
    7. velocidad_global y forma_local_manos se calculan AL FINAL (construir_features),
       coherentes con las posiciones aumentadas.
    """
    coords = np.asarray(coords, dtype=np.float32)
    n_frames = coords.shape[0]
    presentes = fx.mascara_no_nulos(coords)[..., np.newaxis]

    escala = np.float32(rng.uniform(*AUM_ESCALA))
    angulo = np.deg2rad(rng.uniform(-AUM_ROTACION_GRADOS, AUM_ROTACION_GRADOS))
    coseno, seno = np.float32(np.cos(angulo)), np.float32(np.sin(angulo))
    desplazamiento = rng.uniform(-AUM_DESPLAZAMIENTO_XY, AUM_DESPLAZAMIENTO_XY, size=2).astype(np.float32)
    ruido = rng.standard_normal(coords.shape, dtype=np.float32) * np.float32(AUM_SIGMA_RUIDO)

    x, y = coords[..., 0] * escala, coords[..., 1] * escala
    aumentado = np.empty_like(coords)
    aumentado[..., 0] = coseno * x - seno * y + desplazamiento[0]
    aumentado[..., 1] = seno * x + coseno * y + desplazamiento[1]
    aumentado[..., 2] = coords[..., 2] * escala
    aumentado += ruido
    aumentado = np.clip(aumentado, -fx.LIMITE_CLIP, fx.LIMITE_CLIP)
    aumentado = np.where(presentes, aumentado, np.float32(0.0)).astype(np.float32, copy=False)

    aumentado = aumentado[indices_distorsion_temporal(n_frames, rng)]  # copia; la máscara viaja con el frame

    if rng.random() < AUM_PROB_DROPOUT_MANO:
        inicio, fin = fx.BLOQUES[fx.BLOQUES_MANOS[rng.integers(len(fx.BLOQUES_MANOS))]]
        n_cortes = rng.integers(1, AUM_MAX_FRAMES_DROPOUT + 1)
        aumentado[rng.choice(n_frames, size=n_cortes, replace=False), inicio:fin] = 0.0

    return fx.construir_features(aumentado)


# =============================================================================
# 5. PIPELINES tf.data
# =============================================================================
def crear_dataset_entrenamiento(X_coords: np.ndarray, y: np.ndarray, n_clases: int, semilla: int):
    """from_tensor_slices (/CPU:0) -> shuffle -> repeat(4) -> map(aumento, AUTOTUNE) -> batch -> prefetch.

    El aumento es NumPy dentro de tf.numpy_function con set_shape explícito, y
    termina en fx.construir_features: la misma función que la inferencia.
    """
    rng = np.random.default_rng(semilla)  # Generator es thread-safe (lock interno)

    def _aumentar_np(x: np.ndarray) -> np.ndarray:
        return aumentar_secuencia(x, rng)

    def _mapear(x, etiqueta):
        x_aumentado = tf.numpy_function(_aumentar_np, [x], Tout=tf.float32, name="aumento_lsch")
        x_aumentado.set_shape(fx.SHAPE_MODELO)
        return x_aumentado, tf.one_hot(etiqueta, depth=n_clases, dtype=tf.float32)

    with tf.device("/CPU:0"):
        ds = tf.data.Dataset.from_tensor_slices(
            (np.asarray(X_coords, dtype=np.float32), np.asarray(y, dtype=np.int32))
        )
        ds = ds.shuffle(len(X_coords), seed=semilla, reshuffle_each_iteration=True)
        ds = ds.repeat(REPETICIONES_POR_EPOCA)
        ds = ds.map(_mapear, num_parallel_calls=tf.data.AUTOTUNE)
        ds = ds.batch(BATCH_SIZE, drop_remainder=True)  # sin batch final diminuto (BatchNormalization)
        ds = ds.prefetch(tf.data.AUTOTUNE)
    return ds


def crear_dataset_evaluacion(X_modelo: np.ndarray, y: np.ndarray, n_clases: int):
    """Pipeline determinista (validación y test): sin aumento ni shuffle. X ya en (N, 30, 576)."""
    if X_modelo.shape[1:] != fx.SHAPE_MODELO:
        raise ValueError(f"Se esperaba (N, {fx.SHAPE_MODELO}); llegó {X_modelo.shape}")
    with tf.device("/CPU:0"):
        ds = tf.data.Dataset.from_tensor_slices(
            (np.asarray(X_modelo, dtype=np.float32), np.asarray(y, dtype=np.int32))
        )
        ds = ds.map(
            lambda x, etiqueta: (x, tf.one_hot(etiqueta, depth=n_clases, dtype=tf.float32)),
            num_parallel_calls=tf.data.AUTOTUNE,
        )
        ds = ds.batch(BATCH_SIZE).prefetch(tf.data.AUTOTUNE)
    return ds


def liberar_memoria() -> None:
    tf.keras.backend.clear_session()
    gc.collect()


# =============================================================================
# 6. ARQUITECTURA v3
# =============================================================================
def construir_modelo(n_clases: int):
    """Conv1D x2 -> BiLSTM x2 -> pooling medio + máximo -> Dense. Solo capas estándar de Keras."""
    capas = tf.keras.layers
    entrada = capas.Input(shape=fx.SHAPE_MODELO, name="features")
    x = capas.LayerNormalization()(entrada)
    for _ in range(2):
        x = capas.Conv1D(128, kernel_size=3, padding="same", activation="gelu")(x)
        x = capas.BatchNormalization()(x)
        x = capas.SpatialDropout1D(0.25)(x)
    x = capas.Bidirectional(capas.LSTM(128, return_sequences=True))(x)
    x = capas.Dropout(0.3)(x)
    x = capas.Bidirectional(capas.LSTM(96, return_sequences=True))(x)
    x = capas.Dropout(0.3)(x)
    # Promedio = postura sostenida; máximo = pico dinámico. No depende solo del último frame.
    x = capas.Concatenate()([capas.GlobalAveragePooling1D()(x), capas.GlobalMaxPooling1D()(x)])
    x = capas.Dense(256, activation="gelu")(x)
    x = capas.BatchNormalization()(x)
    x = capas.Dropout(0.45)(x)
    salida = capas.Dense(n_clases, activation="softmax", name="clase")(x)

    modelo = tf.keras.Model(entrada, salida, name="lsch_v3")
    modelo.compile(
        optimizer=tf.keras.optimizers.AdamW(learning_rate=LR_INICIAL, weight_decay=WEIGHT_DECAY, clipnorm=CLIPNORM),
        loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=LABEL_SMOOTHING),
        metrics=["accuracy", tf.keras.metrics.TopKCategoricalAccuracy(k=TOP_K, name="top5_acc")],
    )
    return modelo


def crear_callbacks(ruta_checkpoint: Path | None = None) -> list:
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=FACTOR_REDUCE_LR, patience=PACIENCIA_REDUCE_LR, min_lr=LR_MINIMO, verbose=1
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=PACIENCIA_EARLY_STOPPING, restore_best_weights=True, verbose=1
        ),
    ]
    if ruta_checkpoint is not None:
        ruta_checkpoint.parent.mkdir(parents=True, exist_ok=True)
        callbacks.append(tf.keras.callbacks.ModelCheckpoint(
            filepath=str(ruta_checkpoint), monitor="val_loss", save_best_only=True, verbose=1
        ))
    return callbacks


def entrenar(modelo, ds_train, ds_val, callbacks: list, verbose: int):
    """model.fit con tf.data (sin shuffle=: el Dataset ya baraja)."""
    return modelo.fit(ds_train, validation_data=ds_val, epochs=EPOCHS, callbacks=callbacks, verbose=verbose)


def predecir(modelo, ds) -> np.ndarray:
    solo_x = ds.map(lambda x, etiqueta: x, num_parallel_calls=tf.data.AUTOTUNE)
    return np.asarray(modelo.predict(solo_x, verbose=0))


def accuracy_top_k(probabilidades: np.ndarray, y: np.ndarray, k: int = TOP_K) -> tuple[float, float]:
    probabilidades, y = np.asarray(probabilidades), np.asarray(y)
    top1 = float(np.mean(np.argmax(probabilidades, axis=1) == y))
    k = min(k, probabilidades.shape[1])
    mejores_k = np.argpartition(-probabilidades, k - 1, axis=1)[:, :k]
    return top1, float(np.mean(np.any(mejores_k == y[:, np.newaxis], axis=1)))


def _imprimir_destacado(lineas: list[str]) -> None:
    ancho = max(len(linea) for linea in lineas) + 8
    borde = "#" * ancho
    vacia = "##" + " " * (ancho - 4) + "##"
    print(f"\n{borde}\n{borde}\n{vacia}")
    for linea in lineas:
        print(f"##  {linea.ljust(ancho - 8)}  ##")
    print(f"{vacia}\n{borde}\n{borde}\n")


# =============================================================================
# 7. K-FOLD (solo train_base)
# =============================================================================
def entrenar_y_evaluar_fold(fold: int, X_tr: np.ndarray, y_tr: np.ndarray,
                            X_val: np.ndarray, y_val: np.ndarray, n_clases: int) -> dict:
    tf.keras.utils.set_random_seed(SEMILLA + fold)
    ds_train = crear_dataset_entrenamiento(X_tr, y_tr, n_clases, SEMILLA + fold)
    ds_val = crear_dataset_evaluacion(fx.construir_features(X_val), y_val, n_clases)  # intacta
    modelo = construir_modelo(n_clases)
    historial = entrenar(modelo, ds_train, ds_val, crear_callbacks(), VERBOSE_FOLDS)
    top1, top5 = accuracy_top_k(predecir(modelo, ds_val), y_val)
    perdidas = historial.history["val_loss"]
    resultado = {"top1": top1, "top5": top5, "mejor_epoca": int(np.argmin(perdidas)) + 1, "epocas": len(perdidas)}
    del modelo, historial, ds_train, ds_val  # el History y los callbacks también apuntan al modelo
    return resultado


def ejecutar_kfold(X: np.ndarray, y: np.ndarray, n_clases: int) -> list[dict]:
    """StratifiedKFold sobre train_base. No recibe datos de evaluación."""
    conteos = np.bincount(y, minlength=n_clases)
    if conteos.min() < N_SPLITS:
        raise ValueError(f"StratifiedKFold(n_splits={N_SPLITS}) necesita >= {N_SPLITS} videos por clase; "
                         f"clases (ids) con menos: {np.flatnonzero(conteos < N_SPLITS).tolist()}")
    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEMILLA)
    resultados = []
    for fold, (idx_tr, idx_val) in enumerate(skf.split(np.zeros(len(y)), y), 1):
        print(f"\n--- Fold {fold}/{N_SPLITS}: train={len(idx_tr)} videos x {REPETICIONES_POR_EPOCA} "
              f"variantes/época | val={len(idx_val)} videos intactos ---")
        liberar_memoria()
        r = entrenar_y_evaluar_fold(fold, X[idx_tr], y[idx_tr], X[idx_val], y[idx_val], n_clases)
        resultados.append(r)
        print(f"Fold {fold}: top-1={r['top1']:.2%}  top-5={r['top5']:.2%}  "
              f"(mejor época {r['mejor_epoca']} de {r['epocas']})")
        liberar_memoria()

    top1 = np.array([r["top1"] for r in resultados])
    top5 = np.array([r["top5"] for r in resultados])
    epocas = [r["mejor_epoca"] for r in resultados]
    print("\n" + "=" * 66)
    print(f"K-FOLD (K={N_SPLITS}) sobre train_base - validación con videos originales intactos")
    print(f"Accuracy Top-1 promedio: {top1.mean():.2%} (+/- {top1.std():.2%})")
    print(f"Accuracy Top-5 promedio: {top5.mean():.2%} (+/- {top5.std():.2%})")
    print("Top-1 por fold: " + "  ".join(f"{a:.2%}" for a in top1))
    print(f"Mejor época por fold: {epocas} (mediana: {int(np.median(epocas))})")
    print("=" * 66)
    return resultados


# =============================================================================
# 8. MODELO DEFINITIVO
# =============================================================================
def entrenar_modelo_final(X: np.ndarray, y: np.ndarray, n_clases: int,
                          ruta_modelo: Path) -> tuple[np.ndarray, np.ndarray]:
    """Split 90/10 sobre videos ORIGINALES (>= 1 por clase en val), aumento solo en el 90 %.

    Devuelve (X_val, y_val) intactos para reportar la validación de cierre.
    """
    liberar_memoria()
    tf.keras.utils.set_random_seed(SEMILLA)
    n_val = int(np.ceil(len(X) * VAL_INTERNA_FINAL))
    test_size: float | int = VAL_INTERNA_FINAL
    if n_val < n_clases:
        print(f"[AVISO] El {VAL_INTERNA_FINAL:.0%} son {n_val} videos, menos que las {n_clases} clases: "
              f"la validación se amplía a {n_clases} videos (1 por clase).")
        test_size = n_clases
    X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=test_size, stratify=y, random_state=SEMILLA)

    ds_train = crear_dataset_entrenamiento(X_tr, y_tr, n_clases, SEMILLA)
    ds_val = crear_dataset_evaluacion(fx.construir_features(X_val), y_val, n_clases)
    print(f"\nModelo definitivo: train={len(X_tr)} videos x {REPETICIONES_POR_EPOCA} variantes/época | "
          f"validación={len(X_val)} videos originales intactos ({len(set(y_val.tolist()))} clases)")
    modelo = construir_modelo(n_clases)
    modelo.summary()
    historial = entrenar(modelo, ds_train, ds_val, crear_callbacks(ruta_modelo), VERBOSE_FINAL)
    perdidas = historial.history["val_loss"]
    print(f"Mejor época: {int(np.argmin(perdidas)) + 1} de {len(perdidas)} (val_loss={min(perdidas):.4f}). "
          f"Modelo guardado en {ruta_modelo}")
    del modelo, historial, ds_train, ds_val
    return X_val, y_val


# =============================================================================
# 9. EVALUACIÓN
# =============================================================================
def evaluar_modelo(ruta_modelo: Path, X_coords: np.ndarray, y: np.ndarray, clases: np.ndarray,
                   titulo: str, detalle: bool = True) -> tuple[float, float]:
    """Carga el modelo guardado y lo evalúa en videos intactos."""
    liberar_memoria()
    fx.verificar_config(RUTA_CONFIG_FEATURES)
    modelo = tf.keras.models.load_model(ruta_modelo)
    probabilidades = predecir(modelo, crear_dataset_evaluacion(fx.construir_features(X_coords), y, len(clases)))
    if probabilidades.shape[1] != len(clases):
        raise ValueError(f"El modelo tiene {probabilidades.shape[1]} salidas y hay {len(clases)} clases.")
    top1, top5 = accuracy_top_k(probabilidades, y)
    _imprimir_destacado([
        f"ACCURACY {titulo}: {top1 * 100:.2f}%",
        f"TOP-{TOP_K} {titulo}: {top5 * 100:.2f}%",
        f"Videos evaluados: {len(y)}",
    ])
    if detalle:
        pred = np.argmax(probabilidades, axis=1)
        pares = Counter((int(r), int(p)) for r, p in zip(y, pred) if r != p).most_common(TOP_N_REPORTE)
        print(f"Top {TOP_N_REPORTE} pares más confundidos (Real -> Predicha (conteo)):")
        for posicion, ((r, p), conteo) in enumerate(pares, 1):
            print(f"  {posicion:>2}. {clases[r]} -> {clases[p]} ({conteo})")
        if not pares:
            print("  (sin errores)")
        reales = Counter(y.tolist())
        print(f"\nTop {TOP_N_REPORTE} clases más predichas ({len(y)} videos; uniforme = {1 / len(clases):.1%}):")
        print(f"  {'#':>2}  {'clase':<22}{'predichas':>10}{'%':>8}{'reales':>8}{'aciertos':>10}")
        for posicion, (k, cuenta) in enumerate(Counter(pred.tolist()).most_common(TOP_N_REPORTE), 1):
            aciertos = int(np.sum((pred == k) & (y == k)))
            print(f"  {posicion:>2}  {clases[k]:<22}{cuenta:>10}{cuenta / len(y):>8.1%}"
                  f"{reales.get(k, 0):>8}{aciertos:>10}")
    del modelo
    return top1, top5


# =============================================================================
# MAIN
# =============================================================================
def parsear_argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrenamiento LSCh v3 (features de 576 por frame).")
    parser.add_argument("--modo", choices=list(MODELO_POR_MODO), default="eval_webcam")
    parser.add_argument("--tensores-dir", type=Path, default=Path("dataset/tensores_v2"),
                        help="carpeta con train/ y test/ (y opcionalmente metadata_v2.json)")
    parser.add_argument("--webcam-dir", type=Path, default=None,
                        help="carpeta <clase>/<archivo>.npy con los videos de webcam (eval_webcam)")
    parser.add_argument("--tensores-v1-dir", type=Path, default=Path("dataset/tensores"),
                        help="tensores v1 sin rotar, para el respaldo por ratio_vh (eval_webcam)")
    parser.add_argument("--sin-kfold", action="store_true", help="omite la etapa 2 en los modos de evaluación")
    parser.add_argument("--epochs", type=int, default=EPOCHS, help=f"máximo de épocas (por defecto {EPOCHS})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    global EPOCHS
    args = parsear_argumentos(argv)
    EPOCHS = args.epochs
    tf.keras.utils.set_random_seed(SEMILLA)
    ruta_modelo = MODELO_POR_MODO[args.modo]
    print(f"\n========== MODO: {args.modo} | tensores: {args.tensores_dir} | modelo: {ruta_modelo} ==========")

    print("\n========== ETAPA 1: carga, diagnóstico y etiquetas ==========")
    train = cargar_videos(args.tensores_dir / "train", "train")
    test = cargar_videos(args.tensores_dir / "test", "test")
    if args.modo == "eval_webcam":
        train_base, evaluacion, detalle = separar_eval_webcam(train, test, args)
        print(f"Separación webcam: {detalle}")
        titulo = "EN WEBCAM (TEST CROSS-SUBJECT)"
    elif args.modo == "comparar_original":
        train_base, evaluacion = train, test
        titulo = "EN SUJETOS NUEVOS (SPLIT ORIGINAL, TENSORES V2)"
    else:
        train_base, evaluacion = train.unir(test), None
        titulo = ""
    del train, test

    imprimir_diagnostico("TRAIN_BASE", train_base)
    codificador = LabelEncoder().fit(train_base.clases)
    clases = codificador.classes_
    n_clases = len(clases)
    if n_clases != NUM_CLASES_ESPERADAS:
        print(f"[AVISO] train_base tiene {n_clases} clases; se esperaban {NUM_CLASES_ESPERADAS}.")
    ruta_etiquetas = guardar_etiquetas(clases.tolist(), args.modo)
    fx.guardar_config(RUTA_CONFIG_FEATURES)
    print(f"Etiquetas en {ruta_etiquetas} ({n_clases} clases) | configuración de features v{fx.VERSION_CONFIG} "
          f"({fx.N_FEATURES_MODELO} por frame) en {RUTA_CONFIG_FEATURES}")
    y_base = codificador.transform(train_base.clases)
    if evaluacion is not None:
        evaluacion, y_eval = codificar_evaluacion(evaluacion, codificador)
        imprimir_diagnostico("EVALUACIÓN", evaluacion)

    if args.modo != "produccion":
        if args.sin_kfold:
            print("\n========== ETAPA 2: K-Fold omitido (--sin-kfold) ==========")
        else:
            print("\n========== ETAPA 2: K-Fold sobre train_base ==========")
            ejecutar_kfold(train_base.coords, y_base, n_clases)

    print("\n========== ETAPA 3: modelo definitivo ==========")
    X_val, y_val = entrenar_modelo_final(train_base.coords, y_base, n_clases, ruta_modelo)
    top1_val, top5_val = evaluar_modelo(ruta_modelo, X_val, y_val, clases,
                                        "EN VALIDACIÓN DE CIERRE (10 % INTACTO)", detalle=False)

    if evaluacion is not None:
        print("\n========== ETAPA 4: evaluación final ==========")
        top1, top5 = evaluar_modelo(ruta_modelo, evaluacion.coords, y_eval, clases, titulo)
        print(f"\nResumen [{args.modo}] -> validación de cierre: top-1 {top1_val:.2%}, top-5 {top5_val:.2%} | "
              f"evaluación ({len(y_eval)} videos): top-1 {top1:.2%}, top-5 {top5:.2%}")
    else:
        print(f"\nResumen [produccion] -> {len(y_base)} videos | validación de cierre ({len(y_val)} videos): "
              f"top-1 {top1_val:.2%}, top-5 {top5_val:.2%} | artefactos: {ruta_modelo}, {ruta_etiquetas}, "
              f"{RUTA_CONFIG_FEATURES}")


if __name__ == "__main__":
    main()
