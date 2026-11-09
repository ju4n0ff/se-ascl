"""
Entrenamiento de una red LSTM para clasificar Lengua de Señas Chilena (LSCh).

Estructura esperada del dataset:
    dataset/tensores/<clase>/<archivo>.npy     -> cada tensor con shape (30, 1629)

Pipeline:
    1. Carga de tensores y etiquetas (nombre de la carpeta padre).
    2. LabelEncoder (strings -> enteros).
    3. Duplicado de clases con un solo video (para que ninguna clase quede con 1 muestra).
    4. Data augmentation en memoria con ruido gaussiano (15 variaciones por video).
    5. Validaciones previas + train_test_split estratificado (test_size=0.15).
    6. One-hot encoding (to_categorical).
    7. Modelo Sequential: LSTM -> Dropout -> Dense(relu) -> Dropout -> Dense(softmax).
    8. Entrenamiento con EarlyStopping + ModelCheckpoint; mejor modelo en modelos/*.keras.

Uso:
    python entrenar_lstm_lsch.py
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input
from tensorflow.keras.models import Sequential
from tensorflow.keras.utils import set_random_seed, to_categorical

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
RUTA_DATASET = Path("dataset/tensores")
RUTA_MODELOS = Path("modelos")
NOMBRE_MODELO = "mejor_modelo_lsch.keras"
NOMBRE_ETIQUETAS = "etiquetas_lsch.json"

SHAPE_ESPERADO = (30, 1629)      # (frames, features) -> 543 landmarks x 3 coordenadas
NUM_CLASES_ESPERADAS = 91

MIN_VIDEOS_POR_CLASE = 2         # clases con menos videos se duplican hasta este mínimo
VARIACIONES_POR_VIDEO = 15       # copias con ruido por cada video original
SIGMA_RUIDO = 0.01               # desviación estándar del ruido (ver aumentar_con_ruido)
PRESERVAR_CEROS = True           # no meter ruido donde el landmark no fue detectado (0.0)

TEST_SIZE = 0.15
UNIDADES_LSTM = 128
UNIDADES_DENSE = 64
DROPOUT_LSTM = 0.5
DROPOUT_DENSE = 0.4

EPOCHS = 200
BATCH_SIZE = 32
PACIENCIA = 15
SEMILLA = 42


# =============================================================================
# 1. CARGA DE DATOS
# =============================================================================
def cargar_datos(ruta_dataset: Path, shape_esperado: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Lee todos los .npy de `ruta_dataset/<clase>/` y devuelve (X, y).

    - X: float32 con shape (n_videos, 30, 1629).
    - y: array de strings; la etiqueta es el nombre de la carpeta padre del archivo.

    Los archivos corruptos o con un shape distinto al esperado se omiten con un
    aviso, en lugar de abortar toda la carga.
    """
    if not ruta_dataset.is_dir():
        raise FileNotFoundError(f"No existe la carpeta del dataset: {ruta_dataset.resolve()}")

    tensores: list[np.ndarray] = []
    etiquetas: list[str] = []
    omitidos = 0

    carpetas = sorted(p for p in ruta_dataset.iterdir() if p.is_dir())
    for carpeta in carpetas:
        cargados_en_clase = 0
        for archivo in sorted(carpeta.glob("*.npy")):
            try:
                tensor = np.load(archivo)
            except (OSError, ValueError) as error:
                print(f"[AVISO] No se pudo leer {archivo}: {error}")
                omitidos += 1
                continue

            if tensor.shape != shape_esperado:
                print(f"[AVISO] Shape {tensor.shape} != {shape_esperado}, se omite: {archivo}")
                omitidos += 1
                continue

            # NaN/inf romperían el entrenamiento (loss = nan); se reemplazan por 0.
            tensor = np.nan_to_num(tensor.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
            tensores.append(tensor)
            etiquetas.append(archivo.parent.name)
            cargados_en_clase += 1

        if cargados_en_clase == 0:
            print(f"[AVISO] La clase '{carpeta.name}' no tiene tensores válidos y queda fuera.")

    if not tensores:
        raise ValueError(f"No se encontró ningún tensor válido en {ruta_dataset.resolve()}")

    X = np.stack(tensores)
    y = np.array(etiquetas)
    print(f"Cargados {len(X)} tensores de {len(set(etiquetas))} clases ({omitidos} archivos omitidos).")
    print(f"Rango de valores: min={X.min():.4f}  max={X.max():.4f}  std={X.std():.4f}")
    return X, y


# =============================================================================
# 2. PREPROCESAMIENTO DE ETIQUETAS
# =============================================================================
def codificar_etiquetas(y_texto: np.ndarray) -> tuple[np.ndarray, LabelEncoder]:
    """Convierte las etiquetas de texto a enteros 0..n_clases-1 con LabelEncoder."""
    codificador = LabelEncoder()
    y_entero = codificador.fit_transform(y_texto)
    return y_entero, codificador


# =============================================================================
# 3. MANEJO DE CLASES MINORITARIAS
# =============================================================================
def duplicar_clases_minoritarias(
    X: np.ndarray, y: np.ndarray, min_videos: int = 2
) -> tuple[np.ndarray, np.ndarray]:
    """Duplica, sin modificar, los videos de las clases con menos de `min_videos`.

    Una clase con un único video tendría un solo "origen" para todas sus muestras
    aumentadas. Duplicarlo intacto antes del aumento garantiza que cada clase
    entre a la etapa de augmentation con al menos 2 videos base, igual que el
    resto del dataset, y que ninguna quede sub-representada tras multiplicar.
    """
    conteo = Counter(y.tolist())
    extra_X, extra_y = [], []

    for clase, cantidad in conteo.items():
        faltan = min_videos - cantidad
        if faltan <= 0:
            continue
        indices = np.flatnonzero(y == clase)
        # np.resize repite los índices cíclicamente hasta completar los que faltan.
        for indice in np.resize(indices, faltan):
            extra_X.append(X[indice].copy())
            extra_y.append(clase)
        print(f"[MINORITARIA] Clase {clase}: {cantidad} video(s) -> se duplica {faltan} vez/veces.")

    if not extra_X:
        return X, y
    return np.concatenate([X, np.stack(extra_X)]), np.concatenate([y, np.array(extra_y, dtype=y.dtype)])


# =============================================================================
# 4. DATA AUGMENTATION CON RUIDO GAUSSIANO
# =============================================================================
def aumentar_con_ruido(
    X: np.ndarray,
    y: np.ndarray,
    n_variaciones: int = 15,
    sigma: float = 0.01,
    preservar_ceros: bool = True,
    semilla: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Multiplica el dataset creando `n_variaciones` copias con ruido por cada video.

    Lógica del ruido gaussiano
    --------------------------
    Para cada video original x (30 frames x 1629 coordenadas) se genera

        x_sintetico = x + ruido,    ruido ~ N(media=0, desviación=sigma)

    con un valor de ruido independiente para cada coordenada de cada frame.

    * Media 0: el ruido no desplaza la seña en ninguna dirección; cada punto
      "tiembla" alrededor de su posición real. Esto imita la imprecisión natural
      del detector de landmarks entre una grabación y otra.

    * sigma controla cuánto tiembla. 1629 = 543 landmarks x 3 (x, y, z), el
      formato de MediaPipe Holistic, cuyas coordenadas están normalizadas en
      [0, 1]. Con sigma=0.01 el desplazamiento típico es ~1 % del ancho de la
      imagen y el 99.7 % de los valores cae dentro de +-3 %. Es suficiente para
      que la red no memorice coordenadas exactas, pero no deforma la mano: la
      distancia entre dedos es del orden de 0.02-0.05, así que un sigma mayor
      (>0.03) empieza a volver indistinguibles las configuraciones manuales.
      Si tus datos NO están en [0, 1], ajusta SIGMA_RUIDO a ~1-2 % del rango
      real (el rango se imprime al cargar los datos).

    * preservar_ceros: cuando el detector no encuentra una mano, sus coordenadas
      quedan en 0.0 exacto. Ese cero significa "ausente", no "posición 0". Si se
      le suma ruido aparece una mano fantasma cerca de la esquina de la imagen y
      se destruye la señal de ausencia, por eso el ruido se anula en esos puntos.

    El resultado conserva los videos originales al inicio y agrega las copias:
    total = n_videos * (1 + n_variaciones).
    """
    if n_variaciones < 1:
        raise ValueError("n_variaciones debe ser >= 1")
    if sigma <= 0:
        raise ValueError("sigma debe ser > 0")

    rng = np.random.default_rng(semilla)
    n_videos = len(X)
    total = n_videos * (1 + n_variaciones)

    # Se reserva el array final una sola vez (float32) para no duplicar memoria.
    X_aug = np.empty((total, *X.shape[1:]), dtype=np.float32)
    X_aug[:n_videos] = X
    y_aug = np.tile(y, 1 + n_variaciones)

    mascara = (X != 0) if preservar_ceros else None

    for variacion in range(n_variaciones):
        ruido = rng.normal(loc=0.0, scale=sigma, size=X.shape).astype(np.float32)
        if mascara is not None:
            ruido *= mascara
        inicio = n_videos * (variacion + 1)
        X_aug[inicio : inicio + n_videos] = X + ruido

    print(f"Augmentation: {n_videos} videos -> {total} muestras "
          f"({n_variaciones} variaciones con sigma={sigma}).")
    return X_aug, y_aug


# =============================================================================
# 5. VALIDACIÓN Y DIVISIÓN
# =============================================================================
def validar_antes_del_split(y_aug: np.ndarray, test_size: float) -> None:
    """Comprueba las condiciones que harían fallar al split estratificado.

    train_test_split con stratify lanza errores poco claros cuando:
      a) alguna clase tiene menos de 2 muestras, o
      b) el conjunto de test (o el de train) tiene menos muestras que clases.
    Aquí se detectan antes, con un mensaje que indica qué clase corregir.
    """
    clases, conteos = np.unique(y_aug, return_counts=True)
    n_clases = len(clases)

    escasas = clases[conteos < 2]
    if len(escasas) > 0:
        raise ValueError(
            f"Clases con menos de 2 muestras tras el aumento (ids {escasas.tolist()}). "
            "Revisa duplicar_clases_minoritarias / VARIACIONES_POR_VIDEO."
        )

    n_test = math.ceil(len(y_aug) * test_size)
    n_train = len(y_aug) - n_test
    if n_test < n_clases or n_train < n_clases:
        raise ValueError(
            f"Split imposible: train={n_train}, test={n_test}, clases={n_clases}. "
            "Cada conjunto necesita al menos una muestra por clase; aumenta VARIACIONES_POR_VIDEO."
        )

    print(f"Muestras por clase tras el aumento: min={conteos.min()}  max={conteos.max()}  "
          f"total={len(y_aug)}")


def dividir_datos(
    X_aug: np.ndarray, y_aug: np.ndarray, n_clases: int, test_size: float, semilla: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split estratificado sobre el dataset aumentado y one-hot de las etiquetas.

    Se estratifica con las etiquetas enteras (y_aug) y el one-hot se aplica
    después: el resultado es el mismo y evita que sklearn tenga que comparar
    filas de 91 columnas para identificar cada clase.
    """
    validar_antes_del_split(y_aug, test_size)

    X_train, X_test, y_train, y_test = train_test_split(
        X_aug, y_aug, test_size=test_size, stratify=y_aug, random_state=semilla
    )
    y_train = to_categorical(y_train, num_classes=n_clases)
    y_test = to_categorical(y_test, num_classes=n_clases)

    print(f"Train: {X_train.shape}  |  Test: {X_test.shape}")
    return X_train, X_test, y_train, y_test


# =============================================================================
# 6. ARQUITECTURA
# =============================================================================
def construir_modelo(input_shape: tuple[int, int], n_clases: int) -> Sequential:
    """LSTM -> Dropout -> Dense(relu) -> Dropout -> Dense(softmax).

    Una sola capa LSTM es deliberado: con ~200 videos reales, apilar más capas
    recurrentes solo añade capacidad para memorizar. El Dropout alto (0.5 y 0.4)
    obliga a la red a no depender de unidades concretas.
    """
    modelo = Sequential(
        [
            Input(shape=input_shape),
            LSTM(UNIDADES_LSTM),
            Dropout(DROPOUT_LSTM),
            Dense(UNIDADES_DENSE, activation="relu"),
            Dropout(DROPOUT_DENSE),
            Dense(n_clases, activation="softmax"),
        ],
        name="lstm_lsch",
    )
    modelo.compile(optimizer="adam", loss="categorical_crossentropy", metrics=["accuracy"])
    return modelo


# =============================================================================
# 7. ENTRENAMIENTO Y EXPORTACIÓN
# =============================================================================
def entrenar(
    modelo: Sequential,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    ruta_modelo: Path,
):
    """Entrena con EarlyStopping (patience=15) y guarda el mejor modelo en .keras."""
    ruta_modelo.parent.mkdir(parents=True, exist_ok=True)

    callbacks = [
        EarlyStopping(
            monitor="val_loss", patience=PACIENCIA, restore_best_weights=True, verbose=1
        ),
        ModelCheckpoint(
            filepath=str(ruta_modelo), monitor="val_loss", save_best_only=True, verbose=1
        ),
    ]
    return modelo.fit(
        X_train,
        y_train,
        validation_data=(X_test, y_test),
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        callbacks=callbacks,
        verbose=2,
    )


def guardar_etiquetas(codificador: LabelEncoder, ruta: Path) -> None:
    """Guarda el orden de las clases: el índice i de la salida softmax es clases[i]."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(codificador.classes_.tolist(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    set_random_seed(SEMILLA)  # fija semillas de Python, NumPy y TensorFlow

    # 1. Carga
    X, y_texto = cargar_datos(RUTA_DATASET, SHAPE_ESPERADO)

    # 2. Etiquetas -> enteros
    y, codificador = codificar_etiquetas(y_texto)
    n_clases = len(codificador.classes_)
    if n_clases != NUM_CLASES_ESPERADAS:
        print(f"[AVISO] Se encontraron {n_clases} clases; se esperaban {NUM_CLASES_ESPERADAS}. "
              "La capa de salida usará las clases encontradas.")

    # 3. Clases minoritarias (antes del aumento y del split)
    X, y = duplicar_clases_minoritarias(X, y, MIN_VIDEOS_POR_CLASE)

    # 4. Augmentation
    X_aug, y_aug = aumentar_con_ruido(
        X, y, VARIACIONES_POR_VIDEO, SIGMA_RUIDO, PRESERVAR_CEROS, SEMILLA
    )
    del X  # ya está contenido en X_aug

    # 5. Split estratificado + one-hot
    X_train, X_test, y_train, y_test = dividir_datos(X_aug, y_aug, n_clases, TEST_SIZE, SEMILLA)
    del X_aug

    # 6. Modelo
    modelo = construir_modelo(SHAPE_ESPERADO, n_clases)
    modelo.summary()

    # 7. Entrenamiento y exportación
    ruta_modelo = RUTA_MODELOS / NOMBRE_MODELO
    guardar_etiquetas(codificador, RUTA_MODELOS / NOMBRE_ETIQUETAS)
    entrenar(modelo, X_train, y_train, X_test, y_test, ruta_modelo)

    # EarlyStopping restauró los mejores pesos, así que esto evalúa el mejor modelo.
    perdida, exactitud = modelo.evaluate(X_test, y_test, verbose=0)
    print(f"\nMejor modelo -> val_loss={perdida:.4f}  val_accuracy={exactitud:.4f}")
    print(f"Modelo guardado en:    {ruta_modelo}")
    print(f"Etiquetas guardadas en: {RUTA_MODELOS / NOMBRE_ETIQUETAS}")


if __name__ == "__main__":
    main()
