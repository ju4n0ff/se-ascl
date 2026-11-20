"""
diagnosticar_test.py — Diagnóstico del modelo LSCh sobre test (NO reentrena nada).

Carga modelos/mejor_modelo_lsch.keras, modelos/etiquetas_lsch.json y
modelos/config_features.json, prepara las entradas con features_lsch.py y
genera un reporte en consola:
    1. Balance de clases en train y clases dominantes en las predicciones de test.
    2. Relación de aspecto (ratio_vh) en train vs test, y accuracy según ese rango.
    3. Frames muertos: ambas manos sin detectar al inicio y al final.
    4. Prueba de espejo horizontal (flip) a nivel de video.
    5. Patrones en nombres de archivo de test (posibles grupos por persona).

Estructura esperada: dataset/tensores/{train,test}/<categoria>/<archivo>.npy

Uso (en la carpeta que contiene features_lsch.py):
    python diagnosticar_test.py

Los mensajes de arranque de TensorFlow/CUDA se silencian para dejar solo el
reporte; si algo falla, la excepción de Python se muestra igual.
"""

from __future__ import annotations

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # antes de importar TensorFlow

import contextlib
import json
import re
import sys
import time
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import features_lsch as fx

warnings.filterwarnings("ignore")


@contextlib.contextmanager
def _sin_mensajes_de_tensorflow():
    """Redirige el stderr del proceso (fd 2), donde TensorFlow/CUDA escriben sus avisos."""
    try:
        sys.stderr.flush()
        copia, nulo = os.dup(2), os.open(os.devnull, os.O_WRONLY)
        os.dup2(nulo, 2)
    except (OSError, ValueError, AttributeError):  # stderr no redirigible: seguir sin silenciar
        yield
        return
    try:
        yield
    finally:
        sys.stderr.flush()
        os.dup2(copia, 2)
        os.close(nulo)
        os.close(copia)


with _sin_mensajes_de_tensorflow():
    import tensorflow as tf

    tf.get_logger().setLevel("ERROR")
    try:
        import absl.logging

        absl.logging.set_verbosity(absl.logging.ERROR)
    except ImportError:
        pass


# =============================================================================
# CONFIGURACIÓN
# =============================================================================
RUTA_TRAIN = Path("dataset/tensores/train")
RUTA_TEST = Path("dataset/tensores/test")
RUTA_MODELO = Path("modelos/mejor_modelo_lsch.keras")
RUTA_ETIQUETAS = Path("modelos/etiquetas_lsch.json")
RUTA_CONFIG = Path("modelos/config_features.json")

CLASES_DESTACADAS = ("perdon", "gracias2")
TOP_PREDICHAS = 10
TOP_K = 5
ANCHO_BIN_RATIO = 0.2
RATIO_MAXIMO_HISTOGRAMA = 3.0       # el último bin agrupa todo lo que esté por encima
EJEMPLOS_SOLO_ESPEJO = 10
EJEMPLOS_AL_AZAR = 15
MIN_VIDEOS_POR_GRUPO = 20
GRUPOS_MIN, GRUPOS_MAX = 2, 10
COBERTURA_MIN_GRUPOS = 0.90         # los grupos de >=20 videos deben cubrir el 90 % de test
MAX_AGRUPACIONES = 3
BATCH_PREDICCION = 256
SEMILLA = 42
ANCHO = 78

# Espejo: pares izquierda/derecha (índices dentro de cada bloque de MediaPipe).
# De Pose bastan los que usa el modelo; el resto se descarta en features_lsch.
PARES_POSE = [(11, 12), (13, 14), (15, 16)]
# Pares de los 27 puntos de rostro que usa el modelo (FaceMesh). En un video
# espejado de verdad, MediaPipe etiquetaría como "ojo derecho" al que antes era
# el izquierdo; sin este intercambio el rostro espejado tendría los ojos, cejas y
# comisuras con la etiqueta cambiada. Ponlo en False para invertir solo x.
PARES_ROSTRO = [
    (33, 263), (133, 362), (159, 386), (145, 374),           # ojos
    (70, 300), (63, 293), (105, 334), (66, 296), (107, 336),  # cejas
    (61, 291), (78, 308),                                     # comisuras de la boca
]
ESPEJAR_PARES_ROSTRO = True

NARIZ, HOMBRO_IZQ, HOMBRO_DER = 0, 11, 12  # índices de Pose


# =============================================================================
# CARGA
# =============================================================================
@dataclass
class Conjunto:
    rutas: np.ndarray   # rutas relativas a la carpeta del conjunto ("clase/archivo.npy")
    clases: np.ndarray  # nombre de la carpeta de cada archivo
    X: np.ndarray       # (N, 30, 1629) float32 crudo
    omitidos: list

    def __len__(self) -> int:
        return len(self.rutas)

    def filtrar(self, mascara: np.ndarray) -> "Conjunto":
        return Conjunto(self.rutas[mascara], self.clases[mascara], self.X[mascara], self.omitidos)


def cargar(ruta: Path) -> Conjunto:
    if not ruta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta: {ruta.resolve()}")
    rutas, clases, tensores, omitidos = [], [], [], []
    for archivo in sorted(ruta.rglob("*.npy")):
        relativa = archivo.relative_to(ruta).as_posix()
        try:
            tensor = np.load(archivo)
        except (OSError, ValueError):
            omitidos.append(relativa)
            continue
        if tensor.shape != fx.SHAPE_ENTRADA:
            omitidos.append(relativa)
            continue
        tensores.append(np.nan_to_num(tensor.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0))
        rutas.append(relativa)
        clases.append(archivo.parent.name)
    if not tensores:
        raise ValueError(f"No hay tensores {fx.SHAPE_ENTRADA} válidos en {ruta.resolve()}")
    return Conjunto(np.array(rutas), np.array(clases), np.stack(tensores), omitidos)


# =============================================================================
# MÉTRICAS SOBRE TENSORES CRUDOS
# =============================================================================
def _landmarks(X: np.ndarray) -> np.ndarray:
    return X.reshape(len(X), fx.N_FRAMES, fx.N_LANDMARKS_ORIGINAL, 3)


def _detectado(puntos: np.ndarray) -> np.ndarray:
    return np.linalg.norm(puntos, axis=-1) >= fx.UMBRAL_DETECCION


def ratio_vh(X: np.ndarray) -> np.ndarray:
    """(N,) = mediana por video de |y_nariz - y_centro_hombros| / distancia 2D entre hombros.

    Solo frames con nariz y ambos hombros detectados (y hombros separados). NaN
    si el video no tiene ningún frame válido.
    """
    lm = _landmarks(X)
    nariz = lm[:, :, fx.INICIO_POSE + NARIZ]
    hombro_izq = lm[:, :, fx.INICIO_POSE + HOMBRO_IZQ]
    hombro_der = lm[:, :, fx.INICIO_POSE + HOMBRO_DER]
    ancho = np.linalg.norm(hombro_izq[..., :2] - hombro_der[..., :2], axis=-1)
    valido = (_detectado(nariz) & _detectado(hombro_izq) & _detectado(hombro_der)
              & (ancho >= fx.ESCALA_MINIMA))
    alto = np.abs(nariz[..., 1] - (hombro_izq[..., 1] + hombro_der[..., 1]) / 2)
    ratio = np.divide(alto, ancho, out=np.full_like(alto, np.nan), where=valido)
    return np.array([np.median(r[v]) if v.any() else np.nan for r, v in zip(ratio, valido)])


def presencia_manos(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(N, 30) bool por mano: True si algún landmark de esa mano fue detectado en el frame."""
    lm = _landmarks(X)

    def mano(inicio: int) -> np.ndarray:
        return _detectado(lm[:, :, inicio : inicio + fx.N_LANDMARKS_MANO]).any(axis=-1)

    return mano(fx.INICIO_MANO_IZQ), mano(fx.INICIO_MANO_DER)


def resumen_frames(mano_izq: np.ndarray, mano_der: np.ndarray) -> dict:
    """Frames muertos (ninguna mano) al inicio/fin y % de frames activos."""
    activo = mano_izq | mano_der
    sin_manos = ~activo.any(axis=1)
    con_manos = ~sin_manos
    inicio = np.argmax(activo, axis=1)          # primer frame activo = frames muertos al inicio
    fin = np.argmax(activo[:, ::-1], axis=1)    # idem desde el final
    return {
        "inicio": inicio[con_manos].mean() if con_manos.any() else np.nan,
        "fin": fin[con_manos].mean() if con_manos.any() else np.nan,
        "activos": activo.mean(),
        "izq": mano_izq.mean(),
        "der": mano_der.mean(),
        "sin_manos": int(sin_manos.sum()),
    }


# =============================================================================
# ESPEJO HORIZONTAL
# =============================================================================
def _permutacion_espejo() -> np.ndarray:
    perm = np.arange(fx.N_LANDMARKS_ORIGINAL)
    pares = [(fx.INICIO_MANO_IZQ + i, fx.INICIO_MANO_DER + i) for i in range(fx.N_LANDMARKS_MANO)]
    pares += [(fx.INICIO_POSE + a, fx.INICIO_POSE + b) for a, b in PARES_POSE]
    if ESPEJAR_PARES_ROSTRO:
        pares += [(fx.INICIO_ROSTRO + a, fx.INICIO_ROSTRO + b) for a, b in PARES_ROSTRO]
    for a, b in pares:
        perm[a], perm[b] = b, a
    return perm


PERMUTACION_ESPEJO = _permutacion_espejo()


def espejar(X: np.ndarray) -> np.ndarray:
    """Copia espejada de tensores crudos (N, 30, 1629).

    x -> 1 - x en los landmarks detectados (los no detectados siguen en 0) e
    intercambio izquierda <-> derecha: manos completas, hombros, codos,
    muñecas y, si ESPEJAR_PARES_ROSTRO, los pares de rostro.
    """
    lm = _landmarks(X).copy()
    detectado = _detectado(lm)
    lm[..., 0] = np.where(detectado, 1.0 - lm[..., 0], lm[..., 0])
    return lm[:, :, PERMUTACION_ESPEJO].reshape(X.shape)


# =============================================================================
# MODELO
# =============================================================================
def configurar_dispositivo() -> str:
    gpus = tf.config.list_physical_devices("GPU")
    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError:
            pass
    return f"GPU x{len(gpus)}" if gpus else "CPU"


def entradas_modelo(X: np.ndarray) -> np.ndarray:
    """(N, 30, 1629) crudo -> (N, 30, 456) con la misma función que la inferencia."""
    return np.stack([fx.preparar_entrada_modelo(tensor) for tensor in X])


def predecir(modelo, X_modelo: np.ndarray) -> np.ndarray:
    with tf.device("/CPU:0"):  # los datos quedan en RAM; a la GPU va un batch a la vez
        ds = tf.data.Dataset.from_tensor_slices(X_modelo.astype(np.float32)).batch(BATCH_PREDICCION)
    return np.asarray(modelo.predict(ds, verbose=0))


def accuracy_top_k(probabilidades: np.ndarray, y: np.ndarray, k: int = TOP_K) -> float:
    k = min(k, probabilidades.shape[1])
    mejores = np.argpartition(-probabilidades, k - 1, axis=1)[:, :k]
    return float(np.mean(np.any(mejores == y[:, np.newaxis], axis=1)))


# =============================================================================
# AGRUPACIÓN POR NOMBRE DE ARCHIVO
# =============================================================================
_SEPARADORES = r"[_\-\s.]+"


def _bloque(texto: str, posicion: int) -> str:
    partes = [p for p in re.split(_SEPARADORES, texto) if p]
    return partes[posicion] if len(partes) > posicion else ""


def _primer_numero(texto: str) -> str:
    encontrado = re.search(r"\d+", texto)
    return encontrado.group() if encontrado else ""


ESTRATEGIAS = [
    ("texto antes del primer separador (_ - . espacio)", lambda s: _bloque(s, 0)),
    ("2.º bloque entre separadores", lambda s: _bloque(s, 1)),
    ("3.º bloque entre separadores", lambda s: _bloque(s, 2)),
    ("texto antes del primer bloque numérico", lambda s: re.match(r"\D*", s).group().strip("_-. ")),
    ("primer bloque numérico", _primer_numero),
    ("texto sin números ni separadores", lambda s: re.sub(r"[\d_\-\s.]+", "", s)),
    ("primeros 4 caracteres", lambda s: s[:4]),
]


def nombre_sin_categoria(ruta: str, categoria: str) -> str:
    """'gracias2/gracias2_ana_03.npy' -> 'ana_03'. Si no empieza por la categoría, queda igual."""
    stem = Path(ruta).stem
    patron = re.compile(rf"^{re.escape(categoria)}(?=[_\-\s.\d]|$)", re.IGNORECASE)
    return patron.sub("", stem).strip("_-. ") or stem


def buscar_agrupaciones(nombres: list[str]) -> list[tuple[str, np.ndarray]]:
    """Estrategias que dan entre 2 y 10 grupos de >=20 videos cubriendo >=90 % de test."""
    encontradas, vistas = [], set()
    total = len(nombres)
    for descripcion, clave in ESTRATEGIAS:
        claves = [clave(nombre) or "(vacío)" for nombre in nombres]
        conteo = Counter(claves)
        grandes = {k for k, n in conteo.items() if n >= MIN_VIDEOS_POR_GRUPO}
        cubiertos = sum(conteo[k] for k in grandes)
        if not (GRUPOS_MIN <= len(grandes) <= GRUPOS_MAX and cubiertos >= COBERTURA_MIN_GRUPOS * total):
            continue
        grupos = [k if k in grandes else "(otros)" for k in claves]
        orden: dict[str, int] = {}
        firma = tuple(orden.setdefault(g, len(orden)) for g in grupos)  # misma partición = misma firma
        if firma in vistas:
            continue
        vistas.add(firma)
        encontradas.append((descripcion, np.array(grupos)))
        if len(encontradas) == MAX_AGRUPACIONES:
            break
    return encontradas


# =============================================================================
# REPORTE
# =============================================================================
def _titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * ANCHO}")


def _lista(nombres: list[str], maximo: int = 5) -> str:
    return ", ".join(nombres[:maximo]) + (f" y {len(nombres) - maximo} más" if len(nombres) > maximo else "")


def _pct(mascara: np.ndarray, valores: np.ndarray) -> str:
    return f"{valores[mascara].mean():.1%}" if mascara.any() else "-"


def reporte_balance(train: Conjunto, clases: np.ndarray, y: np.ndarray, pred: np.ndarray) -> None:
    _titulo("1. BALANCE EN TRAIN Y DOMINANCIA DE PREDICCIONES EN TEST")
    conteo = Counter(train.clases.tolist())
    valores = np.array(list(conteo.values()))
    minimo, maximo = int(valores.min()), int(valores.max())
    con_minimo = sum(1 for n in valores if n == minimo)
    con_maximo = sorted(c for c, n in conteo.items() if n == maximo)
    print(f"Videos por clase en train: mínimo {minimo} ({con_minimo} clases) | "
          f"mediana {np.median(valores):g} | máximo {maximo} ({_lista(con_maximo)})")
    print("  " + "  |  ".join(
        f"{c}: {conteo[c]} videos" if c in conteo else f"{c}: no existe en train" for c in CLASES_DESTACADAS
    ))

    n = len(pred)
    print(f"\nTop {TOP_PREDICHAS} clases más predichas en test ({n} videos; con reparto uniforme "
          f"serían ~{n / len(clases):.1f} por clase = {1 / len(clases):.1%}):")
    print(f"  {'#':>2}  {'clase':<22}{'predichas':>10}{'% test':>9}{'reales':>9}{'aciertos':>10}{'en train':>10}")
    reales = Counter(y.tolist())
    for posicion, (k, cuenta) in enumerate(Counter(pred.tolist()).most_common(TOP_PREDICHAS), 1):
        aciertos = int(np.sum((pred == k) & (y == k)))
        print(f"  {posicion:>2}  {clases[k]:<22}{cuenta:>10}{cuenta / n:>9.1%}{reales.get(k, 0):>9}"
              f"{aciertos:>10}{conteo.get(str(clases[k]), 0):>10}")
    print("  (reales = videos de test de esa clase; aciertos = predicciones correctas de esa clase)")


def _fila_estadisticas(nombre: str, ratios: np.ndarray) -> str:
    validos = ratios[np.isfinite(ratios)]
    if not len(validos):
        return f"  {nombre:<7}{0:>6}   sin frames válidos"
    percentiles = np.percentile(validos, [5, 25, 50, 75, 95])
    return (f"  {nombre:<7}{len(validos):>6}{validos.mean():>8.2f}{np.median(validos):>9.2f}"
            + "".join(f"{v:>7.2f}" for v in percentiles) + f"{int(np.isnan(ratios).sum()):>14}")


def _histograma(ratio_train: np.ndarray, ratio_test: np.ndarray) -> None:
    n_bins = int(round(RATIO_MAXIMO_HISTOGRAMA / ANCHO_BIN_RATIO))  # + 1 bin de desborde

    def contar(r: np.ndarray) -> np.ndarray:
        r = r[np.isfinite(r)]
        return np.bincount(np.minimum((r / ANCHO_BIN_RATIO).astype(int), n_bins), minlength=n_bins + 1)

    def celda(n: int, total: int) -> str:
        p = n / total if total else 0.0
        return f"{n:>5} {p:>6.1%} {'#' * int(round(p * 25)):<25}"

    c_train, c_test = contar(ratio_train), contar(ratio_test)
    t_train, t_test = int(c_train.sum()), int(c_test.sum())
    usados = np.flatnonzero(c_train + c_test)
    if not len(usados):
        return
    print(f"Histograma (bins de {ANCHO_BIN_RATIO}; cada # = 4 % de los videos del conjunto):")
    print(f"  {'rango':<10}{'train':<40}{'test'}")
    for b in range(usados.min(), usados.max() + 1):
        if b == n_bins:
            rango = f">={RATIO_MAXIMO_HISTOGRAMA:.1f}"
        else:
            rango = f"{b * ANCHO_BIN_RATIO:.1f}-{(b + 1) * ANCHO_BIN_RATIO:.1f}"
        print(f"  {rango:<10}{celda(c_train[b], t_train)}  {celda(c_test[b], t_test)}".rstrip())


def reporte_ratio(ratio_train: np.ndarray, ratio_test: np.ndarray, acierto: np.ndarray) -> None:
    _titulo("2. RELACIÓN DE ASPECTO: ratio_vh = |y_nariz - y_centro_hombros| / ancho_hombros_2d")
    print("Por video: mediana de los frames con nariz y ambos hombros detectados. Como x se")
    print("normaliza por el ancho e y por el alto, la misma persona da un ratio ~3.2x mayor")
    print("en 16:9 que en 9:16: dos montañas separadas en el histograma indican mezcla.")
    print(f"\n  {'':<7}{'n':>6}{'media':>8}{'mediana':>9}{'p5':>7}{'p25':>7}{'p50':>7}{'p75':>7}"
          f"{'p95':>7}{'sin válidos':>14}")
    print(_fila_estadisticas("train", ratio_train))
    print(_fila_estadisticas("test", ratio_test))
    print()
    _histograma(ratio_train, ratio_test)

    validos_train = ratio_train[np.isfinite(ratio_train)]
    if not len(validos_train):
        return
    p10, p90 = np.percentile(validos_train, [10, 90])
    sin_validos = np.isnan(ratio_test)
    dentro = ~sin_validos & (ratio_test >= p10) & (ratio_test <= p90)
    fuera = ~sin_validos & ~dentro
    print(f"\nAccuracy top-1 en test según ratio_vh (rango [p10, p90] de train = [{p10:.2f}, {p90:.2f}];")
    print("por definición, ~20 % de los videos de train también quedan fuera de ese rango):")
    for etiqueta, mascara in (("dentro del rango", dentro), ("fuera del rango", fuera),
                              ("sin frames válidos", sin_validos)):
        print(f"  {etiqueta:<20}{int(mascara.sum()):>6} videos   top-1 {_pct(mascara, acierto):>6}")


def reporte_frames(resumen_train: dict, resumen_test: dict) -> None:
    _titulo("3. FRAMES MUERTOS (ambas manos sin detectar) EN SECUENCIAS DE 30 FRAMES")
    print(f"  {'':<7}{'muertos inicio':>15}{'muertos final':>15}{'% activos':>11}"
          f"{'% mano izq':>12}{'% mano der':>12}{'videos sin manos':>18}")
    for nombre, r in (("train", resumen_train), ("test", resumen_test)):
        print(f"  {nombre:<7}{r['inicio']:>15.2f}{r['fin']:>15.2f}{r['activos']:>11.1%}"
              f"{r['izq']:>12.1%}{r['der']:>12.1%}{r['sin_manos']:>18}")
    print("  (muertos inicio/final: promedio por video, sin contar los videos sin ninguna mano;")
    print("   % activos: frames con al menos una mano detectada)")


def reporte_espejo(test: Conjunto, clases: np.ndarray, pred_normal: np.ndarray,
                   acierto_normal: np.ndarray, acierto_espejo: np.ndarray) -> None:
    _titulo("4. PRUEBA DE ESPEJO HORIZONTAL EN TEST")
    alcance = "manos, hombros, codos, muñecas" + (" y pares de rostro" if ESPEJAR_PARES_ROSTRO else "")
    print(f"Espejo: x -> 1 - x en landmarks detectados; intercambio izq <-> der de {alcance}.")
    print(f"Top-1 normal: {acierto_normal.mean():.1%}   |   Top-1 espejado: {acierto_espejo.mean():.1%}\n")
    solo_espejo = ~acierto_normal & acierto_espejo
    filas = (
        ("Acertados solo normal", acierto_normal & ~acierto_espejo),
        ("Acertados solo espejado", solo_espejo),
        ("Acertados en ambos", acierto_normal & acierto_espejo),
        ("Fallados en ambos", ~acierto_normal & ~acierto_espejo),
    )
    for etiqueta, mascara in filas:
        print(f"  {etiqueta:<28}{int(mascara.sum()):>6}  ({mascara.mean():.1%})")

    indices = np.flatnonzero(solo_espejo)
    if len(indices):
        rng = np.random.default_rng(SEMILLA)
        muestra = np.sort(rng.choice(indices, size=min(EJEMPLOS_SOLO_ESPEJO, len(indices)), replace=False))
        print(f"\nEjemplos de 'acertados solo espejado' ({len(muestra)} de {len(indices)}):")
        for i in muestra:
            print(f"  {test.rutas[i]:<50} (sin espejo predijo: {clases[pred_normal[i]]})")


def reporte_nombres(test: Conjunto, acierto_normal: np.ndarray, acierto_espejo: np.ndarray,
                    activo: np.ndarray, ratio_test: np.ndarray) -> None:
    _titulo("5. PATRONES EN NOMBRES DE ARCHIVO (test)")
    nombres = [nombre_sin_categoria(r, c) for r, c in zip(test.rutas, test.clases)]
    agrupaciones = buscar_agrupaciones(nombres)
    if not agrupaciones:
        print(f"No se encontró ninguna agrupación con {GRUPOS_MIN}-{GRUPOS_MAX} grupos de "
              f">={MIN_VIDEOS_POR_GRUPO} videos (se probó: {', '.join(d for d, _ in ESTRATEGIAS)}).")
    for descripcion, grupos in agrupaciones:
        conteo = Counter(grupos.tolist())
        orden = sorted(conteo, key=lambda g: (g == "(otros)", -conteo[g], g))
        print(f"Agrupación por {descripcion} (nombre sin la categoría al inicio): {len(conteo)} grupos")
        print(f"  {'grupo':<16}{'videos':>7}{'top-1 normal':>14}{'top-1 espejo':>14}"
              f"{'% frames con mano':>19}{'ratio_vh medio':>16}")
        for grupo in orden:
            m = grupos == grupo
            ratios = ratio_test[m][np.isfinite(ratio_test[m])]
            ratio = f"{ratios.mean():.2f}" if len(ratios) else "-"
            print(f"  {grupo[:15]:<16}{int(m.sum()):>7}{_pct(m, acierto_normal):>14}"
                  f"{_pct(m, acierto_espejo):>14}{activo[m].mean():>19.1%}{ratio:>16}")
        print()

    rng = np.random.default_rng(SEMILLA)
    muestra = np.sort(rng.choice(len(test), size=min(EJEMPLOS_AL_AZAR, len(test)), replace=False))
    print(f"{len(muestra)} nombres de archivo de test al azar:")
    for i in muestra:
        print(f"  {test.rutas[i]}")


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    inicio = time.perf_counter()
    for ruta in (RUTA_MODELO, RUTA_ETIQUETAS, RUTA_CONFIG):
        if not ruta.is_file():
            raise FileNotFoundError(f"No existe {ruta.resolve()}")
    fx.verificar_config(RUTA_CONFIG)  # misma transformación de features que en el entrenamiento
    clases = np.array(json.loads(RUTA_ETIQUETAS.read_text(encoding="utf-8")))
    dispositivo = configurar_dispositivo()

    train = cargar(RUTA_TRAIN)
    test = cargar(RUTA_TEST)
    indice = {str(c): i for i, c in enumerate(clases)}
    conocidas = np.array([c in indice for c in test.clases])
    desconocidas = sorted(set(test.clases[~conocidas].tolist()))
    test = test.filtrar(conocidas)
    if not len(test):
        raise ValueError("Ningún video de test pertenece a una clase del modelo.")
    y = np.array([indice[c] for c in test.clases])

    # Métricas sobre los tensores crudos
    ratio_train, ratio_test = ratio_vh(train.X), ratio_vh(test.X)
    resumen_train = resumen_frames(*presencia_manos(train.X))
    izq_test, der_test = presencia_manos(test.X)
    resumen_test = resumen_frames(izq_test, der_test)
    activo_test = (izq_test | der_test).mean(axis=1)  # fracción de frames con mano, por video

    # Predicciones: normal y espejado en una sola pasada
    n = len(test)
    entradas = np.concatenate([entradas_modelo(test.X), entradas_modelo(espejar(test.X))])
    with _sin_mensajes_de_tensorflow():
        modelo = tf.keras.models.load_model(RUTA_MODELO, compile=False)
        probabilidades = predecir(modelo, entradas)
    if probabilidades.shape[1] != len(clases):
        raise ValueError(f"El modelo tiene {probabilidades.shape[1]} salidas y etiquetas_lsch.json "
                         f"{len(clases)} clases.")
    prob_normal, prob_espejo = probabilidades[:n], probabilidades[n:]
    pred_normal, pred_espejo = prob_normal.argmax(axis=1), prob_espejo.argmax(axis=1)
    acierto_normal, acierto_espejo = pred_normal == y, pred_espejo == y

    # ------------------------------------------------------------------ reporte
    print("=" * ANCHO)
    print("DIAGNÓSTICO DEL MODELO LSCh EN TEST (sin reentrenar)")
    print("=" * ANCHO)
    print(f"Modelo: {RUTA_MODELO} | {len(clases)} clases | dispositivo: {dispositivo}")
    print(f"Train: {len(train)} videos en {len(set(train.clases.tolist()))} clases | Test: {n} videos")
    for nombre, conjunto in (("train", train), ("test", test)):
        if conjunto.omitidos:
            print(f"[AVISO] {len(conjunto.omitidos)} archivos de {nombre} omitidos (ilegibles o con "
                  f"shape distinto de {fx.SHAPE_ENTRADA}): {_lista(conjunto.omitidos, 3)}")
    if desconocidas:
        print(f"[AVISO] {int((~conocidas).sum())} videos de test con clases que el modelo no conoce "
              f"quedan fuera: {_lista(desconocidas)}")
    print(f"Accuracy en test: top-1 {acierto_normal.mean():.1%} | top-{TOP_K} "
          f"{accuracy_top_k(prob_normal, y):.1%}")

    reporte_balance(train, clases, y, pred_normal)
    reporte_ratio(ratio_train, ratio_test, acierto_normal)
    reporte_frames(resumen_train, resumen_test)
    reporte_espejo(test, clases, pred_normal, acierto_normal, acierto_espejo)
    reporte_nombres(test, acierto_normal, acierto_espejo, activo_test, ratio_test)

    print(f"\n{'=' * ANCHO}\nTiempo total: {time.perf_counter() - inicio:.1f} s")


if __name__ == "__main__":
    main()
