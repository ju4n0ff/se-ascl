"""
Entrenamiento BiLSTM para Lengua de Señas Chilena (LSCh) con K-Fold
Cross-Validation y evaluación final Cross-Subject.

Estructura (la etiqueta es el nombre de la carpeta que contiene cada .npy):
    dataset/tensores/train/<clase>/<archivo>.npy               persona base
    dataset/tensores/test/<clase>/<archivo>.npy                personas nuevas
    dataset/tensores/test/<persona>/<clase>/<archivo>.npy      (también válido)

Representación (features_lsch.py, el mismo módulo que usará la inferencia):
    (30, 1629) -> 76 landmarks normalizados por hombros (30, 76, 3)
               -> [coordenadas | velocidad] (30, 456) al construir cada batch.

Tubería:
    1. Carga de train y test con recorte + normalización. LabelEncoder SOLO con
       train. Se guardan modelos/etiquetas_lsch.json y modelos/config_features.json.
    2. StratifiedKFold (K=5) SOLO sobre train. Aumento al vuelo solo en la parte
       de entrenamiento de cada fold; la validación usa videos originales intactos.
    3. Modelo definitivo: split 90/10 sobre videos originales, aumento solo al
       90 %, EarlyStopping contra el 10 % intacto, guardado en
       modelos/mejor_modelo_lsch.keras.
    4. Evaluación Cross-Subject: se carga el modelo guardado y se evalúa en test.

AISLAMIENTO CONTRA FUGA DE DATOS
    * Los sujetos de test no intervienen en ninguna decisión previa a la etapa 4:
      el LabelEncoder se ajusta con train, ejecutar_kfold y entrenar_modelo_final
      no reciben X_test, y el EarlyStopping solo mira videos de la persona base.
    * Dentro de train, toda división (folds y 90/10) se hace sobre videos
      ORIGINALES y el aumento se aplica después, solo del lado de entrenamiento:
      ninguna variante de un video de validación aparece en entrenamiento.
    * La normalización es por secuencia (no usa estadísticas del dataset), así
      que aplicarla antes de dividir no traspasa información entre conjuntos.

GESTIÓN DE VRAM
    * memory growth se activa al importar el script, antes de crear tensores.
    * Los datos viven en RAM: los tf.data.Dataset se crean bajo /CPU:0 y a la
      GPU solo viaja un batch de 32 muestras por paso. El set aumentado nunca se
      materializa: cada época genera variantes nuevas al vuelo.
    * clear_session() + gc.collect() al terminar cada fold, antes del modelo
      definitivo y antes de cargar el modelo para la evaluación final.

Uso:
    python entrenar_lstm_lsch_kfold.py      (features_lsch.py en la misma carpeta)
"""

from __future__ import annotations

import gc
import json
from collections import Counter
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder

import features_lsch as fx


# =============================================================================
# 0. GPU (debe ejecutarse antes de crear cualquier tensor o modelo)
# =============================================================================
def configurar_gpu() -> None:
    """Activa memory growth en todas las GPUs físicas.

    Sin esto TensorFlow reserva casi toda la VRAM al arrancar, y con 5 GB la
    fragmentación entre folds termina en CUDA_ERROR_OUT_OF_MEMORY.
    """
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
RUTA_TRAIN = Path("dataset/tensores/train")
RUTA_TEST = Path("dataset/tensores/test")
RUTA_MODELOS = Path("modelos")
RUTA_MODELO_FINAL = RUTA_MODELOS / "mejor_modelo_lsch.keras"
RUTA_ETIQUETAS = RUTA_MODELOS / "etiquetas_lsch.json"
RUTA_CONFIG_FEATURES = RUTA_MODELOS / "config_features.json"

NUM_CLASES_ESPERADAS = 89
N_SPLITS = 5
VAL_INTERNA_FINAL = 0.10          # fracción de videos ORIGINALES de train para EarlyStopping
SEMILLA = 42

# Aumento al vuelo. Unidades normalizadas: 1.0 = ancho de hombros.
REPETICIONES_POR_EPOCA = 4        # cada video aparece 4 veces por época, con variantes distintas
AUM_ESCALA = (0.90, 1.10)         # escala alrededor del centro de los hombros
AUM_DESPLAZAMIENTO_XY = 0.05      # traslación máxima en x e y
AUM_SIGMA_RUIDO = 0.015           # desviación del ruido gaussiano por coordenada
AUM_VELOCIDAD_TEMPORAL = (0.90, 1.10)  # >1 seña más rápida, <1 más lenta
AUM_CURVATURA_TEMPORAL = 0.05     # amplitud de la curva suave de tempo (fracción de la secuencia)
AUM_DESPLAZAMIENTO_FRAMES = 2     # desplazamiento temporal máximo (+-frames)

# Entrenamiento
BATCH_SIZE = 32
EPOCHS = 200
LR_INICIAL = 1e-3
CLIPNORM = 1.0
LABEL_SMOOTHING = 0.1
PACIENCIA_EARLY_STOPPING = 25
PACIENCIA_REDUCE_LR = 8
FACTOR_REDUCE_LR = 0.5
LR_MINIMO = 1e-5
TOP_K = 5
TOP_CONFUSIONES = 10
VERBOSE_FOLDS = 0                 # 0 = silencioso, 2 = una línea por época
VERBOSE_FINAL = 2


# =============================================================================
# 1. CARGA, NORMALIZACIÓN Y ETIQUETAS
# =============================================================================
def cargar_datos(ruta: Path, nombre: str) -> tuple[np.ndarray, np.ndarray]:
    """Lee todos los .npy bajo `ruta` (recursivo) y devuelve (X, y).

    X: (N, 30, 76, 3) float32, recortado y normalizado por hombros (sin velocidad).
    y: etiquetas de texto = nombre de la carpeta padre de cada archivo.
    Los archivos ilegibles o con shape distinto de (30, 1629) se omiten con aviso.
    """
    if not ruta.is_dir():
        raise FileNotFoundError(f"[{nombre}] No existe la carpeta: {ruta.resolve()}")

    secuencias, etiquetas = [], []
    omitidos = sin_hombros = frames_sustituidos = 0
    for archivo in sorted(ruta.rglob("*.npy")):
        try:
            tensor = np.load(archivo)
        except (OSError, ValueError) as error:
            print(f"[AVISO] No se pudo leer {archivo}: {error}")
            omitidos += 1
            continue
        if tensor.shape != fx.SHAPE_ENTRADA:
            print(f"[AVISO] Shape {tensor.shape} != {fx.SHAPE_ENTRADA}, se omite: {archivo}")
            omitidos += 1
            continue

        validos = fx.frames_con_hombros_validos(fx.seleccionar_landmarks(tensor))
        sin_hombros += int(not validos.any())
        frames_sustituidos += int((~validos).sum())
        secuencias.append(fx.extraer_coordenadas(tensor))  # misma función que la inferencia
        etiquetas.append(archivo.parent.name)

    if not secuencias:
        raise ValueError(f"[{nombre}] No hay tensores válidos en {ruta.resolve()}")

    X = np.stack(secuencias)
    y = np.array(etiquetas)

    presentes = fx.mascara_no_nulos(X)  # (N, 30, 76)
    deteccion = "  |  ".join(
        f"{bloque} {presentes[..., inicio:fin].any(axis=-1).mean() * 100:.1f}%"
        for bloque, (inicio, fin) in fx.BLOQUES.items()
    )
    total_frames = X.shape[0] * X.shape[1]
    print(f"[{nombre}] {len(X)} tensores, {len(set(etiquetas))} clases, {omitidos} omitidos. "
          f"Rango normalizado: [{X.min():.2f}, {X.max():.2f}]")
    print(f"[{nombre}] Frames con el bloque detectado: {deteccion}")
    print(f"[{nombre}] Hombros: {frames_sustituidos} frames ({frames_sustituidos / total_frames:.2%}) "
          f"usaron la mediana de su secuencia; {sin_hombros} secuencias sin ningún frame válido "
          "(centro=0, escala=1).")
    return X, y


def ajustar_codificador(y_train_texto: np.ndarray, ruta_json: Path) -> LabelEncoder:
    """Ajusta el LabelEncoder SOLO con train y guarda el orden de las clases.

    El índice i de la salida softmax corresponde a clases[i] del JSON.
    """
    codificador = LabelEncoder().fit(y_train_texto)
    ruta_json.parent.mkdir(parents=True, exist_ok=True)
    ruta_json.write_text(
        json.dumps(codificador.classes_.tolist(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_clases = len(codificador.classes_)
    if n_clases != NUM_CLASES_ESPERADAS:
        print(f"[AVISO] Train tiene {n_clases} clases; se esperaban {NUM_CLASES_ESPERADAS}.")
    print(f"Etiquetas guardadas en {ruta_json} ({n_clases} clases).")
    return codificador


def codificar_test(
    X_test: np.ndarray, y_test_texto: np.ndarray, codificador: LabelEncoder
) -> tuple[np.ndarray, np.ndarray]:
    """Transforma las etiquetas de test con el encoder de train (sin re-ajustarlo).

    Los videos de test cuya clase no existe en train se descartan con aviso: el
    modelo no tiene neurona de salida para ellos.
    """
    conocidas = np.isin(y_test_texto, codificador.classes_)
    if not conocidas.all():
        desconocidas = sorted(set(y_test_texto[~conocidas].tolist()))
        print(f"[AVISO] {(~conocidas).sum()} videos de test con clases ausentes en train "
              f"se descartan: {desconocidas}")
    if not conocidas.any():
        raise ValueError("Ninguna clase de test coincide con las clases de train.")

    sin_test = sorted(set(codificador.classes_.tolist()) - set(y_test_texto.tolist()))
    if sin_test:
        print(f"[AVISO] {len(sin_test)} clases de train no tienen videos en test: {sin_test}")

    return X_test[conocidas], codificador.transform(y_test_texto[conocidas])


# =============================================================================
# 2. AUMENTO AL VUELO (solo entrenamiento)
# =============================================================================
def indices_distorsion_temporal(n_frames: int, rng: np.random.Generator) -> np.ndarray:
    """Índices de frame para re-muestrear la secuencia con un tempo levemente distinto.

    origen(t) = 0.5 + (t - 0.5)·v + a·sin(π·t)     (t normalizado en [0, 1])
    y luego se suma un desplazamiento entero d (en frames).
        v en AUM_VELOCIDAD_TEMPORAL       -> ejecución más rápida (v > 1) o más lenta (v < 1)
        a en ±AUM_CURVATURA_TEMPORAL      -> curva suave: acelera una mitad y frena la otra
        d en ±AUM_DESPLAZAMIENTO_FRAMES   -> la seña empieza un poco antes o después
    La curva es monótona (v - π·|a| > 0): el orden temporal nunca se invierte.
    Los índices fuera de rango repiten el primer/último frame (pose de reposo).

    Se toma el frame MÁS CERCANO, sin interpolar: interpolar entre un frame con
    la mano detectada y otro sin ella crearía una mano a medio camino del origen.
    """
    t = np.linspace(0.0, 1.0, n_frames)
    velocidad = rng.uniform(*AUM_VELOCIDAD_TEMPORAL)
    curvatura = rng.uniform(-AUM_CURVATURA_TEMPORAL, AUM_CURVATURA_TEMPORAL)
    desplazamiento = rng.integers(-AUM_DESPLAZAMIENTO_FRAMES, AUM_DESPLAZAMIENTO_FRAMES + 1)
    origen = (0.5 + (t - 0.5) * velocidad + curvatura * np.sin(np.pi * t)) * (n_frames - 1)
    return np.clip(np.rint(origen + desplazamiento), 0, n_frames - 1).astype(np.intp)


def aumentar_secuencia(coords: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Aumento de UNA secuencia normalizada: (30, 76, 3) -> (30, 456) float32.

    Orden: distorsión temporal -> escala -> desplazamiento (x, y) -> ruido
    gaussiano -> clip -> máscara -> velocidad.

    * La escala se aplica alrededor del origen, que tras normalizar es el centro
      de los hombros: simula brazos más largos o cortos respecto del torso.
    * Los landmarks ausentes (exactamente 0.0) siguen en 0.0: la distorsión
      temporal copia frames completos y la máscara se re-aplica al final.
    * La velocidad se calcula DESPUÉS, sobre las posiciones ya aumentadas, para
      que posición y velocidad sean coherentes entre sí.
    """
    coords = np.asarray(coords, dtype=np.float32)
    coords = coords[indices_distorsion_temporal(coords.shape[0], rng)]  # copia
    presentes = fx.mascara_no_nulos(coords)[..., np.newaxis]            # (30, 76, 1)

    escala = np.float32(rng.uniform(*AUM_ESCALA))
    desplazamiento = np.zeros(3, dtype=np.float32)
    desplazamiento[:2] = rng.uniform(-AUM_DESPLAZAMIENTO_XY, AUM_DESPLAZAMIENTO_XY, size=2)
    ruido = rng.standard_normal(coords.shape, dtype=np.float32) * np.float32(AUM_SIGMA_RUIDO)

    coords = coords * escala + desplazamiento + ruido
    coords = np.clip(coords, -fx.LIMITE_CLIP, fx.LIMITE_CLIP)
    coords = np.where(presentes, coords, np.float32(0.0)).astype(np.float32, copy=False)
    return fx.agregar_velocidad(coords)


# =============================================================================
# 3. PIPELINES tf.data (datos en RAM, un batch por paso a la GPU)
# =============================================================================
def crear_dataset_entrenamiento(
    X_coords: np.ndarray, y: np.ndarray, n_clases: int, semilla: int
) -> tf.data.Dataset:
    """Pipeline de ENTRENAMIENTO con aumento al vuelo.

    from_tensor_slices (/CPU:0) -> shuffle -> repeat(4) -> map(aumento) -> batch(32) -> prefetch

    El aumento está en NumPy y se envuelve con tf.numpy_function + set_shape
    explícito. Así reutiliza exactamente fx.agregar_velocidad, la misma función
    que verán la validación, el test y la inferencia.
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
        # drop_remainder evita un último batch diminuto que desestabiliza BatchNormalization.
        ds = ds.batch(BATCH_SIZE, drop_remainder=True)
        ds = ds.prefetch(tf.data.AUTOTUNE)
    return ds


def crear_dataset_evaluacion(X_modelo: np.ndarray, y: np.ndarray, n_clases: int) -> tf.data.Dataset:
    """Pipeline DETERMINISTA para validación y test: sin aumento y sin shuffle.

    Recibe X ya en formato de modelo (N, 30, 456), con la velocidad calculada.
    """
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
    """Libera el grafo de Keras y la memoria de Python entre entrenamientos."""
    tf.keras.backend.clear_session()
    gc.collect()


# =============================================================================
# 4. ARQUITECTURA, CALLBACKS Y MÉTRICAS
# =============================================================================
def construir_modelo(n_clases: int) -> tf.keras.Model:
    capas = tf.keras.layers
    modelo = tf.keras.Sequential(
        [
            capas.Input(shape=fx.SHAPE_MODELO),
            capas.LayerNormalization(),
            capas.Conv1D(128, kernel_size=3, padding="same", activation="relu"),
            capas.BatchNormalization(),
            capas.SpatialDropout1D(0.25),
            capas.Bidirectional(capas.LSTM(128, return_sequences=True)),
            capas.Dropout(0.3),
            capas.Bidirectional(capas.LSTM(64, return_sequences=False)),
            capas.Dropout(0.3),
            capas.Dense(256, activation="relu"),
            capas.BatchNormalization(),
            capas.Dropout(0.4),
            capas.Dense(n_clases, activation="softmax"),
        ],
        name="bilstm_lsch",
    )
    modelo.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LR_INICIAL, clipnorm=CLIPNORM),
        loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=LABEL_SMOOTHING),
        metrics=["accuracy", tf.keras.metrics.TopKCategoricalAccuracy(k=TOP_K, name="top5_acc")],
    )
    return modelo


def crear_callbacks(ruta_checkpoint: Path | None = None) -> list:
    """Callbacks nuevos en cada entrenamiento (guardan estado interno)."""
    callbacks = [
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=FACTOR_REDUCE_LR, patience=PACIENCIA_REDUCE_LR,
            min_lr=LR_MINIMO, verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=PACIENCIA_EARLY_STOPPING, restore_best_weights=True, verbose=1
        ),
    ]
    if ruta_checkpoint is not None:
        ruta_checkpoint.parent.mkdir(parents=True, exist_ok=True)
        callbacks.append(
            tf.keras.callbacks.ModelCheckpoint(
                filepath=str(ruta_checkpoint), monitor="val_loss", save_best_only=True, verbose=1
            )
        )
    return callbacks


def predecir(modelo: tf.keras.Model, ds: tf.data.Dataset) -> np.ndarray:
    """Probabilidades (N, n_clases) en el orden del dataset (que no se baraja)."""
    return modelo.predict(ds.map(lambda x, etiqueta: x), verbose=0)


def accuracy_top_k(probabilidades: np.ndarray, y: np.ndarray, k: int = TOP_K) -> tuple[float, float]:
    """(accuracy top-1, accuracy top-k) calculados a partir de las predicciones."""
    probabilidades, y = np.asarray(probabilidades), np.asarray(y)
    top1 = float(np.mean(np.argmax(probabilidades, axis=1) == y))
    k = min(k, probabilidades.shape[1])
    mejores_k = np.argpartition(-probabilidades, k - 1, axis=1)[:, :k]
    topk = float(np.mean(np.any(mejores_k == y[:, np.newaxis], axis=1)))
    return top1, topk


def top_confusiones(
    y_real: np.ndarray, y_pred: np.ndarray, clases: np.ndarray, n: int = TOP_CONFUSIONES
) -> list[tuple[str, str, int]]:
    """Los n pares (real, predicha) más frecuentes entre los errores."""
    pares = Counter((int(r), int(p)) for r, p in zip(y_real, y_pred) if r != p)
    return [(str(clases[r]), str(clases[p]), c) for (r, p), c in pares.most_common(n)]


def _imprimir_destacado(lineas: list[str]) -> None:
    ancho = max(len(linea) for linea in lineas) + 8
    borde = "#" * ancho
    vacia = "##" + " " * (ancho - 4) + "##"
    print(f"\n\n{borde}\n{borde}\n{vacia}")
    for linea in lineas:
        print(f"##  {linea.ljust(ancho - 8)}  ##")
    print(f"{vacia}\n{borde}\n{borde}\n")


# =============================================================================
# 5. K-FOLD CROSS-VALIDATION (SOLO TRAIN)
# =============================================================================
def entrenar_y_evaluar_fold(
    fold: int,
    X_fold_train: np.ndarray,
    y_fold_train: np.ndarray,
    X_fold_val: np.ndarray,
    y_fold_val: np.ndarray,
    n_clases: int,
) -> dict:
    """Entrena un modelo desde cero en un fold y lo evalúa en su validación intacta."""
    tf.keras.utils.set_random_seed(SEMILLA + fold)

    # Validación: videos originales, solo se agrega la velocidad (determinista).
    X_val_modelo = fx.agregar_velocidad(X_fold_val)
    ds_train = crear_dataset_entrenamiento(X_fold_train, y_fold_train, n_clases, SEMILLA + fold)
    ds_val = crear_dataset_evaluacion(X_val_modelo, y_fold_val, n_clases)

    modelo = construir_modelo(n_clases)
    historial = modelo.fit(
        ds_train,
        validation_data=ds_val,
        epochs=EPOCHS,
        callbacks=crear_callbacks(),
        verbose=VERBOSE_FOLDS,
    )
    top1, top5 = accuracy_top_k(predecir(modelo, ds_val), y_fold_val)
    perdidas = historial.history["val_loss"]
    resultado = {
        "top1": top1,
        "top5": top5,
        "mejor_epoca": int(np.argmin(perdidas)) + 1,
        "epocas": len(perdidas),
    }
    del modelo, historial, ds_train, ds_val  # el History y los callbacks también apuntan al modelo
    return resultado


def ejecutar_kfold(X_train_base: np.ndarray, y_train_base: np.ndarray, n_clases: int) -> list[dict]:
    """StratifiedKFold sobre la persona base. Esta función no recibe datos de test."""
    conteos = np.bincount(y_train_base, minlength=n_clases)
    if conteos.min() < N_SPLITS:
        escasas = np.flatnonzero(conteos < N_SPLITS).tolist()
        raise ValueError(
            f"StratifiedKFold(n_splits={N_SPLITS}) necesita al menos {N_SPLITS} videos por clase. "
            f"Clases (ids) con menos: {escasas}"
        )

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEMILLA)
    resultados: list[dict] = []
    for fold, (idx_train, idx_val) in enumerate(skf.split(np.zeros(len(y_train_base)), y_train_base), 1):
        print(f"\n--- Fold {fold}/{N_SPLITS}: train={len(idx_train)} videos x "
              f"{REPETICIONES_POR_EPOCA} variantes/época | val={len(idx_val)} videos intactos ---")
        resultado = entrenar_y_evaluar_fold(
            fold,
            X_train_base[idx_train], y_train_base[idx_train],
            X_train_base[idx_val], y_train_base[idx_val],
            n_clases,
        )
        resultados.append(resultado)
        print(f"Fold {fold}: top-1={resultado['top1']:.2%}  top-5={resultado['top5']:.2%}  "
              f"(mejor época {resultado['mejor_epoca']} de {resultado['epocas']})")
        liberar_memoria()

    top1 = np.array([r["top1"] for r in resultados])
    top5 = np.array([r["top5"] for r in resultados])
    epocas = [r["mejor_epoca"] for r in resultados]
    print("\n" + "=" * 66)
    print(f"K-FOLD (K={N_SPLITS}) - validación con videos originales de la persona base")
    print(f"Accuracy Top-1 promedio: {top1.mean():.2%} (+/- {top1.std():.2%})")
    print(f"Accuracy Top-5 promedio: {top5.mean():.2%} (+/- {top5.std():.2%})")
    print("Top-1 por fold: " + "  ".join(f"{a:.2%}" for a in top1))
    print(f"Mejor época por fold: {epocas} (mediana: {int(np.median(epocas))})")
    print("=" * 66)
    return resultados


# =============================================================================
# 6. MODELO DEFINITIVO
# =============================================================================
def entrenar_modelo_final(
    X_train_base: np.ndarray, y_train_base: np.ndarray, n_clases: int, ruta_modelo: Path
) -> None:
    """Split 90/10 sobre videos ORIGINALES, aumento al vuelo solo en el 90 %.

    El 10 % de validación queda intacto (sin ninguna variante en entrenamiento),
    así que el val_loss que vigilan EarlyStopping, ReduceLROnPlateau y
    ModelCheckpoint mide videos nunca vistos de la persona base.
    """
    liberar_memoria()
    tf.keras.utils.set_random_seed(SEMILLA)

    # Un split estratificado necesita al menos 1 video por clase en validación.
    # Si el 10 % no alcanza (p. ej. 89 clases x 8 videos = 712 -> 72 < 89), se
    # amplía la validación al mínimo posible: 1 video por clase.
    n_val = int(np.ceil(len(X_train_base) * VAL_INTERNA_FINAL))
    test_size: float | int = VAL_INTERNA_FINAL
    if n_val < n_clases:
        print(f"[AVISO] El {VAL_INTERNA_FINAL:.0%} de train son {n_val} videos, menos que las "
              f"{n_clases} clases. La validación se amplía a {n_clases} videos (1 por clase).")
        test_size = n_clases

    X_final_train, X_final_val, y_final_train, y_final_val = train_test_split(
        X_train_base, y_train_base, test_size=test_size, stratify=y_train_base, random_state=SEMILLA
    )
    ds_train = crear_dataset_entrenamiento(X_final_train, y_final_train, n_clases, SEMILLA)
    ds_val = crear_dataset_evaluacion(fx.agregar_velocidad(X_final_val), y_final_val, n_clases)
    print(f"\nModelo definitivo: train={len(X_final_train)} videos x {REPETICIONES_POR_EPOCA} "
          f"variantes/época | validación={len(X_final_val)} videos originales intactos")

    modelo = construir_modelo(n_clases)
    modelo.summary()
    historial = modelo.fit(
        ds_train,
        validation_data=ds_val,
        epochs=EPOCHS,
        callbacks=crear_callbacks(ruta_modelo),
        verbose=VERBOSE_FINAL,
    )
    perdidas = historial.history["val_loss"]
    print(f"Mejor época: {int(np.argmin(perdidas)) + 1} de {len(perdidas)} "
          f"(val_loss={min(perdidas):.4f}). Modelo guardado en {ruta_modelo}")
    del modelo, historial, ds_train, ds_val


# =============================================================================
# 7. EVALUACIÓN CROSS-SUBJECT
# =============================================================================
def evaluar_cross_subject(
    ruta_modelo: Path, X_test: np.ndarray, y_test: np.ndarray, clases: np.ndarray
) -> tuple[float, float]:
    """Carga el modelo guardado y lo evalúa en los sujetos nuevos (único uso de test)."""
    liberar_memoria()
    fx.verificar_config(RUTA_CONFIG_FEATURES)  # misma transformación que en entrenamiento
    modelo = tf.keras.models.load_model(ruta_modelo)

    ds_test = crear_dataset_evaluacion(fx.agregar_velocidad(X_test), y_test, len(clases))
    probabilidades = predecir(modelo, ds_test)
    if probabilidades.shape[1] != len(clases):
        raise ValueError(f"El modelo tiene {probabilidades.shape[1]} salidas y hay {len(clases)} clases.")

    top1, top5 = accuracy_top_k(probabilidades, y_test)
    _imprimir_destacado([
        f"ACCURACY EN SUJETOS NUEVOS (TEST CROSS-SUBJECT): {top1 * 100:.2f}%",
        f"TOP-{TOP_K} EN SUJETOS NUEVOS (TEST CROSS-SUBJECT):    {top5 * 100:.2f}%",
        f"Videos de test evaluados: {len(y_test)}",
    ])

    confusiones = top_confusiones(y_test, np.argmax(probabilidades, axis=1), clases)
    print(f"Top {TOP_CONFUSIONES} pares más confundidos (Real -> Predicha (conteo)):")
    if not confusiones:
        print("  (sin errores)")
    for posicion, (real, predicha, conteo) in enumerate(confusiones, 1):
        print(f"  {posicion:>2}. {real} -> {predicha} ({conteo})")

    del modelo
    return top1, top5


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    tf.keras.utils.set_random_seed(SEMILLA)  # semillas de Python, NumPy y TensorFlow

    print("\n========== ETAPA 1: carga, normalización y etiquetas ==========")
    X_train_base, y_train_texto = cargar_datos(RUTA_TRAIN, "TRAIN")
    X_test, y_test_texto = cargar_datos(RUTA_TEST, "TEST")

    codificador = ajustar_codificador(y_train_texto, RUTA_ETIQUETAS)
    fx.guardar_config(RUTA_CONFIG_FEATURES)
    print(f"Configuración de features guardada en {RUTA_CONFIG_FEATURES}")
    clases = codificador.classes_
    n_clases = len(clases)
    y_train_base = codificador.transform(y_train_texto)
    X_test, y_test = codificar_test(X_test, y_test_texto, codificador)

    print("\n========== ETAPA 2: K-Fold sobre train ==========")
    resultados_kfold = ejecutar_kfold(X_train_base, y_train_base, n_clases)

    print("\n========== ETAPA 3: modelo definitivo ==========")
    entrenar_modelo_final(X_train_base, y_train_base, n_clases, RUTA_MODELO_FINAL)

    print("\n========== ETAPA 4: evaluación cross-subject ==========")
    top1_test, top5_test = evaluar_cross_subject(RUTA_MODELO_FINAL, X_test, y_test, clases)

    top1_kfold = np.mean([r["top1"] for r in resultados_kfold])
    top5_kfold = np.mean([r["top5"] for r in resultados_kfold])
    print(f"\nResumen -> K-Fold (misma persona): top-1 {top1_kfold:.2%}, top-5 {top5_kfold:.2%}   |   "
          f"Cross-Subject (personas nuevas): top-1 {top1_test:.2%}, top-5 {top5_test:.2%}")


if __name__ == "__main__":
    main()
