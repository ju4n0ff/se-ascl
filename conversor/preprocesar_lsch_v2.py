#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preprocesar_lsch_v2.py
======================
Preprocesamiento v2 del dataset de Lengua de Señas Chilena (LSCh) para LSTM.

Corrige dos problemas detectados en la v1:
  1. Rotación: ~77% de los videos verticales de celular se leían acostados 90°
     (metadato de rotación del contenedor ignorado/mal aplicado). Ahora la
     orientación se determina EMPÍRICAMENTE con MediaPipe Pose sobre frames de
     muestra y se corrige ANTES de pasar los frames a Holistic.
  2. Relación de aspecto: MediaPipe normaliza x por el ancho e y por el alto,
     así que 9:16, 16:9 y 4:3 producían escalas incompatibles. Ahora se guarda
     [x, y * (h/w), z]: las tres coordenadas quedan en "unidades de ancho del
     frame" (isotrópicas).

Pipeline por video:
    abrir (autorrotación OFF) -> muestreo uniforme de 30 frames -> BGR→RGB
    -> detectar rotación (Pose estático, nariz vs. hombros, en píxeles)
    -> rotar todos los frames -> Holistic (instancia nueva por video)
    -> [x, y*aspect, z] por landmark -> (30, 1629) float32 -> .npy

Entrada : dataset/videos/<split>/<clase>/<video>.{mp4,mov,avi}
Salida  : dataset/tensores_v2/<split>/<clase>/<video>.npy   (no toca la v1)

Formato por frame (1629 = 99 + 1404 + 63 + 63):
    Pose 33×3 | Rostro 468×3 (sin refine) | Mano izq 21×3 | Mano der 21×3

Dependencias:
    pip install opencv-python numpy "mediapipe==0.10.14"
    (las versiones nuevas de mediapipe, p. ej. 0.10.32, ya no traen
     mp.solutions.holistic / mp.solutions.pose; requiere Python 3.8–3.12)
"""

import multiprocessing
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

# =============================================================================
# CONFIGURACIÓN (editable)
# =============================================================================
DATASET_DIR = "dataset"
VIDEOS_DIR = os.path.join(DATASET_DIR, "videos")
TENSORES_DIR = os.path.join(DATASET_DIR, "tensores_v2")  # carpeta NUEVA (v1 intacta)
SPLITS = ("train", "test")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi")

SEQUENCE_LENGTH = 30
MAX_WORKERS = min(6, os.cpu_count() or 1)

# Holistic (extracción principal)
HOLISTIC_MODEL_COMPLEXITY = 1
MIN_DETECTION_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# Detección de rotación (Pose estático, rápido)
ROT_MODEL_COMPLEXITY = 0
ROT_SAMPLE_POSITIONS = (0.30, 0.40, 0.50, 0.60, 0.70)  # posiciones relativas en el video
ROT_MIN_VISIBILITY = 0.5  # visibilidad mínima de nariz y hombros para usar el frame

# =============================================================================
# CONSTANTES DE DIMENSIONALIDAD
# =============================================================================
N_POSE, N_FACE, N_HAND, N_COORDS = 33, 468, 21, 3
POSE_SIZE = N_POSE * N_COORDS   # 99
FACE_SIZE = N_FACE * N_COORDS   # 1404
HAND_SIZE = N_HAND * N_COORDS   # 63
FEATURES_PER_FRAME = POSE_SIZE + FACE_SIZE + 2 * HAND_SIZE  # 1629

# Índices de Pose usados para la orientación
NOSE, L_SHOULDER, R_SHOULDER = 0, 11, 12

# OJO: cv2.ROTATE_90_CLOCKWISE == 0 (falsy). "Sin rotación" se representa con
# None y siempre se compara con 'is None', nunca con 'if rot:'.
ROT_LABELS = {
    None: "0°",
    cv2.ROTATE_90_CLOCKWISE: "90° CW",
    cv2.ROTATE_90_COUNTERCLOCKWISE: "90° CCW",
    cv2.ROTATE_180: "180°",
}
ROT_ORDER = ["0°", "90° CW", "90° CCW", "180°"]
COMPONENTES = ("pose", "rostro", "mano_izquierda", "mano_derecha")


# =============================================================================
# MEDIAPIPE (import validado)
# =============================================================================
def importar_mediapipe():
    """Importa mediapipe y verifica que exista la API heredada 'solutions'."""
    import mediapipe as mp

    if not (hasattr(mp, "solutions") and hasattr(mp.solutions, "holistic")):
        raise RuntimeError(
            f"mediapipe {getattr(mp, '__version__', '?')} no incluye "
            "'mp.solutions.holistic' / 'mp.solutions.pose'.\n"
            "Instala una versión que la incluya, por ejemplo:\n"
            '    pip install "mediapipe==0.10.14"   (Python 3.8–3.12)'
        )
    return mp


# Estado por proceso worker (se inicializa en _init_worker)
_mp = None
_POSE_ROT = None


def _init_worker():
    """
    Inicializador de cada proceso del pool.
    - cv2.setNumThreads(1): evita sobresuscripción de hilos (N procesos × N hilos).
    - Pose en static_image_mode=True NO tiene estado de tracking, por lo que se
      puede reutilizar entre videos del mismo proceso sin fuga de estado.
      (Holistic, que sí hace tracking, se crea nuevo para cada video.)
    """
    global _mp, _POSE_ROT
    cv2.setNumThreads(1)
    _mp = importar_mediapipe()
    _POSE_ROT = _mp.solutions.pose.Pose(
        static_image_mode=True,
        model_complexity=ROT_MODEL_COMPLEXITY,
        min_detection_confidence=0.5,
    )


# =============================================================================
# LECTURA DE VIDEO Y MUESTREO UNIFORME
# =============================================================================
def abrir_video(ruta):
    """
    Abre el video con la autorrotación de OpenCV DESACTIVADA. Así el resultado
    no depende del backend ni del metadato de rotación del contenedor, y toda la
    corrección queda a cargo de la detección empírica (determinista).
    """
    cap = cv2.VideoCapture(ruta)
    if hasattr(cv2, "CAP_PROP_ORIENTATION_AUTO"):
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    return cap


def contar_frames(ruta):
    """
    Cuenta frames reales con grab() (sin convertir ni copiar). Más fiable que
    CAP_PROP_FRAME_COUNT, que en .mov/.avi de celular suele venir mal.
    """
    cap = abrir_video(ruta)
    if not cap.isOpened():
        return 0
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    return n


def indices_uniformes(n_frames, longitud=SEQUENCE_LENGTH):
    """
    Índices de muestreo uniforme sobre todo el video.
    - n >= longitud: 'longitud' índices equiespaciados (estrictamente crecientes,
      ya que el paso (n-1)/(longitud-1) >= 1).
    - n <  longitud: todos los frames (luego se hace zero-padding).
    """
    if n_frames <= longitud:
        return np.arange(n_frames)
    return np.linspace(0, n_frames - 1, longitud).round().astype(int)


def leer_frames_muestreados(ruta, longitud=SEQUENCE_LENGTH):
    """
    Lee SOLO los frames muestreados (máx. 30 en memoria por video, en vez de
    todo el video), usando dos pasadas: conteo con grab() + retrieve() selectivo.
    Retorna (lista de frames BGR, nº total de frames del video).
    """
    n_total = contar_frames(ruta)
    if n_total == 0:
        return [], 0

    objetivo = set(indices_uniformes(n_total, longitud).tolist())
    cap = abrir_video(ruta)
    frames, i = [], 0
    while len(frames) < len(objetivo):
        if not cap.grab():
            break
        if i in objetivo:
            ok, frame = cap.retrieve()
            if ok:
                frames.append(frame)
        i += 1
    cap.release()
    return frames, n_total


def rotar(frame, rot):
    """Aplica una rotación cv2.ROTATE_* (o ninguna si rot is None)."""
    return frame if rot is None else cv2.rotate(frame, rot)


# =============================================================================
# DETECCIÓN DE ORIENTACIÓN (Pose estático, en PÍXELES)
# =============================================================================
def vector_nariz_hombros(frame_rgb):
    """
    Corre Pose estático y devuelve (dx, dy) en PÍXELES desde el centro de los
    hombros hasta la nariz, o None si no hay detección fiable.
    Se multiplica por (w, h) porque x e y normalizados no comparten escala.
    """
    h, w = frame_rgb.shape[:2]
    res = _POSE_ROT.process(frame_rgb)
    if res.pose_landmarks is None:
        return None
    lm = res.pose_landmarks.landmark
    nariz, h_izq, h_der = lm[NOSE], lm[L_SHOULDER], lm[R_SHOULDER]
    if min(nariz.visibility, h_izq.visibility, h_der.visibility) < ROT_MIN_VISIBILITY:
        return None
    cx = (h_izq.x + h_der.x) / 2.0
    cy = (h_izq.y + h_der.y) / 2.0
    return ((nariz.x - cx) * w, (nariz.y - cy) * h)


def vectores_validos(frames_rgb):
    """Lista de (dx, dy) de los frames con detección válida."""
    return [v for v in (vector_nariz_hombros(f) for f in frames_rgb) if v is not None]


def mediana_vector(frames_rgb):
    """Mediana de (dx, dy) sobre frames válidos (robusta a detecciones erráticas)."""
    vecs = vectores_validos(frames_rgb)
    if not vecs:
        return None
    dx, dy = np.median(np.asarray(vecs, dtype=np.float64), axis=0)
    return float(dx), float(dy)


def es_derecho(dx, dy):
    """Persona derecha: nariz ARRIBA de los hombros y eje dominante vertical."""
    return dy < 0 and abs(dy) > abs(dx)


def clasificar_rotacion(dx, dy):
    """
    Regla de decisión (ejes de imagen: x → derecha, y → abajo):
      dy < 0, |dy| >= |dx| -> derecho              -> None
      dx > 0, |dx| >  |dy| -> cabeza a la derecha  -> ROTATE_90_COUNTERCLOCKWISE
      dx < 0, |dx| >  |dy| -> cabeza a la izquierda-> ROTATE_90_CLOCKWISE
      dy > 0, |dy| >= |dx| -> cabeza abajo         -> ROTATE_180
    """
    if dx == 0 and dy == 0:
        return None
    if dy < 0 and abs(dy) >= abs(dx):
        return None
    if dx > 0 and abs(dx) > abs(dy):
        return cv2.ROTATE_90_COUNTERCLOCKWISE
    if dx < 0 and abs(dx) > abs(dy):
        return cv2.ROTATE_90_CLOCKWISE
    return cv2.ROTATE_180


def detectar_rotacion(frames_rgb):
    """
    Determina la rotación que deja a la persona derecha.

    1. Muestrea frames al 30/40/50/60/70% de la secuencia y calcula la mediana
       de (dx, dy) nariz–hombros en píxeles -> rotación candidata.
    2. Verificación de seguridad: rota el frame central con la candidata y
       confirma dy < 0 y |dy| > |dx| (si el central no tiene detección, usa las
       muestras rotadas).
    3. Respaldo: si no hubo detección o la verificación falla (p. ej. Pose no
       detecta bien a una persona acostada), prueba las 4 rotaciones y elige la
       que deja más frames de muestra derechos.

    Retorna (rotación, método) con método ∈ {"directa", "verificada",
    "busqueda", "sin_deteccion"}.
    """
    n = len(frames_rgb)
    idx = sorted({min(n - 1, int(round(p * (n - 1)))) for p in ROT_SAMPLE_POSITIONS})
    muestras = [frames_rgb[i] for i in idx]

    med = mediana_vector(muestras)
    if med is not None:
        rot = clasificar_rotacion(*med)
        if rot is None:
            return None, "directa"

        v = mediana_vector([rotar(frames_rgb[n // 2], rot)])
        if v is None:
            v = mediana_vector([rotar(m, rot) for m in muestras])
        if v is not None and es_derecho(*v):
            return rot, "verificada"

    # Respaldo: búsqueda exhaustiva sobre las 4 orientaciones
    mejor_rot, mejor_score = None, 0
    for rot in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE, cv2.ROTATE_180):
        score = sum(es_derecho(*v) for v in vectores_validos([rotar(m, rot) for m in muestras]))
        if score > mejor_score:
            mejor_rot, mejor_score = rot, score
    if mejor_score > 0:
        return mejor_rot, "busqueda"
    return None, "sin_deteccion"


# =============================================================================
# EXTRACCIÓN DE LANDMARKS ISOTRÓPICOS
# =============================================================================
def landmarks_a_array(landmark_list, n_landmarks, aspect):
    """
    Convierte un NormalizedLandmarkList en un vector 1D [x, y*aspect, z].

    MediaPipe entrega x/ancho e y/alto. Multiplicando y por aspect = h/w,
    y pasa a estar también en unidades del ANCHO, igual que x (y que z, que
    MediaPipe escala aproximadamente como x). Resultado: un círculo sigue
    siendo un círculo en 9:16, 16:9 o 4:3.

    Componente no detectado -> ceros exactos (0.0) del tamaño correcto.
    """
    if landmark_list is None:
        return np.zeros(n_landmarks * N_COORDS, dtype=np.float32)

    coords = np.array(
        [[lm.x, lm.y * aspect, lm.z] for lm in landmark_list.landmark],
        dtype=np.float32,
    )
    if coords.shape[0] != n_landmarks:  # salvaguarda (p. ej. 478 si refine=True)
        fijo = np.zeros((n_landmarks, N_COORDS), dtype=np.float32)
        k = min(n_landmarks, coords.shape[0])
        fijo[:k] = coords[:k]
        coords = fijo
    return coords.ravel()


def extraer_keypoints(results, aspect):
    """
    Vector del frame en orden pose + cara + mano_izq + mano_der -> (1629,),
    más un vector booleano de detección por componente (para estadísticas).
    'left_hand_landmarks' = mano izquierda de la PERSONA.
    """
    bloques = (
        (results.pose_landmarks, N_POSE),
        (results.face_landmarks, N_FACE),
        (results.left_hand_landmarks, N_HAND),
        (results.right_hand_landmarks, N_HAND),
    )
    kp = np.concatenate([landmarks_a_array(lm, n, aspect) for lm, n in bloques])
    detectado = np.array([lm is not None for lm, _ in bloques], dtype=np.int64)
    assert kp.shape == (FEATURES_PER_FRAME,), kp.shape
    return kp, detectado


def estandarizar_secuencia(secuencia, longitud=SEQUENCE_LENGTH):
    """(n, 1629) -> (longitud, 1629) float32 con zero-padding al final si n < longitud."""
    tensor = np.zeros((longitud, FEATURES_PER_FRAME), dtype=np.float32)
    secuencia = secuencia[:longitud]
    if secuencia:
        tensor[: len(secuencia)] = np.stack(secuencia)
    return tensor


# =============================================================================
# WORKER: PROCESAMIENTO DE UN VIDEO
# =============================================================================
def procesar_video(tarea):
    """
    Procesa un video completo en un proceso worker. Nunca lanza excepciones
    hacia el pool: los errores se devuelven en el dict de resultado.
    """
    split, clase, ruta, ruta_salida = tarea
    res = {"split": split, "clase": clase, "ruta": ruta, "salida": ruta_salida, "ok": False}
    try:
        frames_bgr, n_total = leer_frames_muestreados(ruta)
        if not frames_bgr:
            res["error"] = "no se pudieron leer frames"
            return res

        frames = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames_bgr]
        del frames_bgr

        # 1) Orientación empírica ANTES de Holistic, aplicada a TODOS los frames
        rot, metodo = detectar_rotacion(frames)
        frames = [rotar(f, rot) for f in frames]

        # 2) Holistic NUEVO por video (evita fuga de tracking entre videos)
        secuencia = []
        detecciones = np.zeros(len(COMPONENTES), dtype=np.int64)
        with _mp.solutions.holistic.Holistic(
            static_image_mode=False,
            model_complexity=HOLISTIC_MODEL_COMPLEXITY,
            refine_face_landmarks=False,  # 468 puntos de rostro
            min_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        ) as holistic:
            for frame_rgb in frames:
                h, w = frame_rgb.shape[:2]  # dimensiones YA rotadas
                aspect = h / float(w)
                frame_rgb.flags.writeable = False
                kp, det = extraer_keypoints(holistic.process(frame_rgb), aspect)
                secuencia.append(kp)
                detecciones += det

        # 3) Estandarizar y guardar
        tensor = estandarizar_secuencia(secuencia)
        assert tensor.shape == (SEQUENCE_LENGTH, FEATURES_PER_FRAME) and tensor.dtype == np.float32
        os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
        np.save(ruta_salida, tensor)

        res.update(
            ok=True,
            rotacion=ROT_LABELS[rot],
            metodo=metodo,
            frames_video=n_total,
            frames_usados=len(secuencia),
            detecciones=detecciones.tolist(),
            resolucion=f"{w}x{h}",
        )
    except Exception as e:  # noqa: BLE001 - se reporta en el resumen
        res["error"] = f"{type(e).__name__}: {e}"
    return res


# =============================================================================
# DESCUBRIMIENTO DE VIDEOS
# =============================================================================
def listar_tareas():
    """
    Devuelve [(split, clase, ruta_video, ruta_salida), ...].
    Si en una misma clase coinciden nombres base (p. ej. a.mp4 y a.mov), se
    añade la extensión al nombre de salida para no sobrescribir.
    """
    tareas = []
    for split in SPLITS:
        dir_split = os.path.join(VIDEOS_DIR, split)
        if not os.path.isdir(dir_split):
            print(f"[AVISO] No existe '{dir_split}', se omite el split '{split}'.")
            continue
        for clase in sorted(os.listdir(dir_split)):
            dir_clase = os.path.join(dir_split, clase)
            if not os.path.isdir(dir_clase):
                continue
            archivos = sorted(
                f for f in os.listdir(dir_clase) if f.lower().endswith(VIDEO_EXTENSIONS)
            )
            bases = Counter(os.path.splitext(f)[0] for f in archivos)
            for archivo in archivos:
                base, ext = os.path.splitext(archivo)
                nombre = base if bases[base] == 1 else f"{base}_{ext[1:].lower()}"
                ruta_salida = os.path.join(TENSORES_DIR, split, clase, nombre + ".npy")
                tareas.append((split, clase, os.path.join(dir_clase, archivo), ruta_salida))
    return tareas


# =============================================================================
# VERIFICACIÓN GEOMÉTRICA SOBRE LOS TENSORES GUARDADOS
# =============================================================================
def metricas_geometricas(ruta_npy):
    """
    Carga un tensor generado y calcula, sobre los frames con pose detectada,
    el promedio de:
      dx_homb, dy_homb   = hombro izq (11) − hombro der (12)
      dx_nariz, dy_nariz = nariz (0) − centro de hombros
    Como x e y ya son isotrópicas, comparar |dy| con |dx| es geométricamente
    válido. Persona derecha => dy_nariz < 0 y |dy_nariz| > |dx_nariz|;
    hombros ~horizontales => |dy_homb| << |dx_homb|.
    (El signo de dx_homb depende de si el video está espejado, p. ej. selfie.)
    """
    t = np.load(ruta_npy)
    pose = t[:, :POSE_SIZE].reshape(-1, N_POSE, N_COORDS)
    validos = np.any(pose != 0.0, axis=(1, 2))
    if not validos.any():
        return None
    p = pose[validos][:, :, :2].astype(np.float64)
    hi, hd, nariz = p[:, L_SHOULDER], p[:, R_SHOULDER], p[:, NOSE]
    homb = (hi - hd).mean(axis=0)
    nar = (nariz - (hi + hd) / 2.0).mean(axis=0)
    return {"dx_homb": homb[0], "dy_homb": homb[1], "dx_nariz": nar[0], "dy_nariz": nar[1]}


# =============================================================================
# PROGRESO Y RESUMEN
# =============================================================================
def barra_progreso(actual, total, inicio, ancho=40):
    frac = actual / total if total else 1.0
    llenos = int(ancho * frac)
    transcurrido = time.time() - inicio
    eta = transcurrido / actual * (total - actual) if actual else 0.0
    sys.stdout.write(
        f"\rProcesando |{'█' * llenos}{'-' * (ancho - llenos)}| {actual}/{total} "
        f"({frac * 100:5.1f}%) {transcurrido:6.1f}s ETA {eta:6.1f}s"
    )
    sys.stdout.flush()
    if actual == total:
        sys.stdout.write("\n")


def imprimir_resumen(resultados):
    por_split = defaultdict(list)
    for r in resultados:
        por_split[r["split"]].append(r)

    for split in [s for s in SPLITS if s in por_split]:
        rs = por_split[split]
        ok = [r for r in rs if r["ok"]]
        err = [r for r in rs if not r["ok"]]

        print("\n" + "=" * 64)
        print(f" SPLIT: {split}")
        print("=" * 64)
        print(f" Procesados OK: {len(ok)}/{len(rs)}   Errores: {len(err)}")

        # --- Rotaciones aplicadas ---
        rot = Counter(r["rotacion"] for r in ok)
        print(" Rotación aplicada:")
        for etiqueta in ROT_ORDER:
            print(f"   {etiqueta:>8}: {rot.get(etiqueta, 0)}")
        met = Counter(r["metodo"] for r in ok)
        print(" Método de decisión: " + ", ".join(f"{k}={v}" for k, v in sorted(met.items())))
        con_padding = sum(r["frames_usados"] < SEQUENCE_LENGTH for r in ok)
        print(f" Videos con zero-padding (< {SEQUENCE_LENGTH} frames): {con_padding}")

        # --- Verificación geométrica sobre los .npy generados ---
        metricas = [m for m in (metricas_geometricas(r["salida"]) for r in ok) if m is not None]
        print(f" Verificación geométrica ({len(metricas)} tensores con pose):")
        if metricas:
            prom = {k: float(np.mean([m[k] for m in metricas])) for k in metricas[0]}
            print("   " + "  ".join(f"{k}={v:+.4f}" for k, v in prom.items()))
            acostados = sum(abs(m["dy_nariz"]) < abs(m["dx_nariz"]) for m in metricas)
            invertidos = sum(m["dy_nariz"] > 0 for m in metricas)
            print(f"   Videos con |dy_nariz| < |dx_nariz| (debería ser ~0): {acostados}")
            print(f"   Videos con dy_nariz > 0 (cabeza bajo hombros):    {invertidos}")

        # --- Tasa de detección por componente (sobre frames reales) ---
        frames_tot = sum(r["frames_usados"] for r in ok)
        if frames_tot:
            det = np.sum([r["detecciones"] for r in ok], axis=0)
            print(f" Tasa de detección ({frames_tot} frames reales):")
            for nombre, d in zip(COMPONENTES, det):
                print(f"   {nombre:<15}: {d / frames_tot * 100:6.2f}%")

        # --- Casos a revisar ---
        dudosos = [r for r in ok if r["metodo"] == "sin_deteccion"]
        if dudosos:
            print(" Sin detección de orientación (se dejaron sin rotar, revisar):")
            for r in dudosos:
                print(f"   - {r['ruta']}")
        if err:
            print(" Errores:")
            for r in err:
                print(f"   - {r['ruta']}: {r['error']}")


# =============================================================================
# MAIN
# =============================================================================
def main():
    try:
        importar_mediapipe()  # falla rápido, antes de lanzar el pool
    except RuntimeError as e:
        sys.exit(f"[ERROR] {e}")

    tareas = listar_tareas()
    total = len(tareas)
    if total == 0:
        print(f"No se encontraron videos {VIDEO_EXTENSIONS} en '{VIDEOS_DIR}/<split>/<clase>/'.")
        return

    conteo = Counter(t[0] for t in tareas)
    print(f"Videos encontrados: {total} ({', '.join(f'{s}={n}' for s, n in conteo.items())})")
    print(f"Salida: {TENSORES_DIR}/<split>/<clase>/*.npy  shape=({SEQUENCE_LENGTH}, {FEATURES_PER_FRAME}) float32")
    print(f"Workers: {MAX_WORKERS}\n")

    resultados = []
    inicio = time.time()
    # 'spawn': procesos limpios (MediaPipe/TFLite no es fork-safe) y mismo
    # comportamiento en Linux, macOS y Windows.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=MAX_WORKERS, mp_context=ctx, initializer=_init_worker) as pool:
        futuros = [pool.submit(procesar_video, t) for t in tareas]
        for i, fut in enumerate(as_completed(futuros), start=1):
            resultados.append(fut.result())
            barra_progreso(i, total, inicio)

    print(f"\nTiempo total: {time.time() - inicio:.1f}s")
    imprimir_resumen(resultados)


if __name__ == "__main__":
    main()
