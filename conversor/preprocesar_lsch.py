#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preprocesar_lsch.py
===================
Preprocesamiento de un dataset de videos de Lengua de Señas Chilena (LSCh)
para entrenar una red LSTM.

Pipeline por video:
    video .mp4 -> frames BGR -> RGB -> MediaPipe Holistic -> landmarks (x, y, z)
    -> vector 1D de 1629 features por frame -> secuencia (30, 1629) -> .npy

Estructura de directorios esperada:
    dataset/videos/<nombre_seña>/<video>.mp4      (entrada)
    dataset/tensores/<nombre_seña>/<video>.npy    (salida, se crea automáticamente)

Dimensionalidad por frame (solo coordenadas x, y, z):
    Pose        : 33 landmarks  * 3 =   99
    Rostro      : 468 landmarks * 3 = 1404   (refine_face_landmarks=False)
    Mano izq.   : 21 landmarks  * 3 =   63
    Mano der.   : 21 landmarks  * 3 =   63
    ---------------------------------------
    Total                           = 1629

Dependencias:
    pip install opencv-python mediapipe numpy
"""

import os
import sys
import time

import cv2
import numpy as np
import mediapipe as mp

# =============================================================================
# CONFIGURACIÓN GLOBAL
# =============================================================================
SEQUENCE_LENGTH = 30  # Nº de frames por secuencia (pasos temporales de la LSTM)

VIDEOS_DIR = os.path.join("dataset", "videos")
TENSORES_DIR = os.path.join("dataset", "tensores")
VIDEO_EXTENSIONS = (".mp4",)

# Número de landmarks por componente de MediaPipe Holistic
N_POSE = 33
N_FACE = 468  # 478 si se activa refine_face_landmarks=True (iris); aquí se mantiene en 468
N_HAND = 21
N_COORDS = 3  # x, y, z

POSE_SIZE = N_POSE * N_COORDS   # 99
FACE_SIZE = N_FACE * N_COORDS   # 1404
HAND_SIZE = N_HAND * N_COORDS   # 63
FEATURES_PER_FRAME = POSE_SIZE + FACE_SIZE + 2 * HAND_SIZE  # 1629

# Parámetros del modelo Holistic
MIN_DETECTION_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5
MODEL_COMPLEXITY = 1  # 0 = rápido, 1 = balanceado, 2 = más preciso

# Las versiones recientes de MediaPipe (p. ej. 0.10.32) eliminaron la API
# heredada 'mp.solutions' (incluido Holistic). Se valida explícitamente.
if not hasattr(mp, "solutions"):
    sys.exit(
        f"[ERROR] mediapipe {getattr(mp, '__version__', '?')} no incluye "
        "'mp.solutions.holistic'.\n"
        "Instala una versión que la incluya, por ejemplo:\n"
        "    pip install \"mediapipe==0.10.14\"   (requiere Python 3.8–3.12)"
    )
mp_holistic = mp.solutions.holistic


# =============================================================================
# EXTRACCIÓN DE LANDMARKS
# =============================================================================
def landmarks_a_array(landmark_list, n_landmarks):
    """
    Convierte un NormalizedLandmarkList de MediaPipe en un array 1D (x, y, z).

    Si el componente no fue detectado (landmark_list es None), devuelve un
    vector de ceros del tamaño exacto (n_landmarks * 3) para preservar la
    dimensionalidad fija del frame.

    Nota: se descarta 'visibility' (presente en Pose) a propósito, para que
    todos los componentes compartan el mismo formato de 3 coordenadas.
    """
    if landmark_list is None:
        return np.zeros(n_landmarks * N_COORDS, dtype=np.float32)

    coords = np.array(
        [[lm.x, lm.y, lm.z] for lm in landmark_list.landmark],
        dtype=np.float32,
    )
    # Salvaguarda: si por versión/configuración llegara un número distinto de
    # landmarks (p. ej. 478 en rostro con refine), se recorta/rellena al tamaño esperado.
    if coords.shape[0] != n_landmarks:
        fixed = np.zeros((n_landmarks, N_COORDS), dtype=np.float32)
        n = min(n_landmarks, coords.shape[0])
        fixed[:n] = coords[:n]
        coords = fixed

    return coords.flatten()  # shape: (n_landmarks * 3,)


def extraer_keypoints(results):
    """
    Construye el vector de features de un frame a partir del resultado de Holistic.

    Orden de concatenación: pose + cara + mano_izq + mano_der  -> shape (1629,)

    Nota: en MediaPipe Holistic, 'left_hand_landmarks' corresponde a la mano
    izquierda de la PERSONA (no del lado izquierdo de la imagen).
    """
    pose = landmarks_a_array(results.pose_landmarks, N_POSE)
    cara = landmarks_a_array(results.face_landmarks, N_FACE)
    mano_izq = landmarks_a_array(results.left_hand_landmarks, N_HAND)
    mano_der = landmarks_a_array(results.right_hand_landmarks, N_HAND)

    keypoints = np.concatenate([pose, cara, mano_izq, mano_der])
    assert keypoints.shape == (FEATURES_PER_FRAME,), (
        f"Dimensión inesperada por frame: {keypoints.shape}"
    )
    return keypoints


def procesar_video(ruta_video):
    """
    Lee un video COMPLETO frame a frame y devuelve la lista de vectores de keypoints.
    Ya no se detiene en el frame 30, captura toda la duración de la seña.
    """
    cap = cv2.VideoCapture(ruta_video)
    if not cap.isOpened():
        return None

    secuencia = []
    with mp_holistic.Holistic(
        static_image_mode=False,
        model_complexity=MODEL_COMPLEXITY,
        refine_face_landmarks=False,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    ) as holistic:
        while cap.isOpened():
            ok, frame_bgr = cap.read()
            if not ok:
                break  # Fin del video

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = holistic.process(frame_rgb)

            secuencia.append(extraer_keypoints(results))

    cap.release()
    return secuencia


# =============================================================================
# ESTANDARIZACIÓN TEMPORAL (NUEVA LÓGICA DE MUESTREO UNIFORME)
# =============================================================================
def estandarizar_secuencia(secuencia, longitud=SEQUENCE_LENGTH):
    """
    Lleva una lista de frames a un tensor de shape exacta (30, 1629).
    - Si tiene más de 30 frames (ej. 6 segundos = 180 frames): Hace un muestreo 
      uniforme, seleccionando frames equitativamente distanciados.
    - Si tiene menos de 30 frames: Aplica zero-padding al final.
    """
    total_frames = len(secuencia)
    tensor = np.zeros((longitud, FEATURES_PER_FRAME), dtype=np.float32)
    
    if total_frames == 0:
        return tensor

    if total_frames <= longitud:
        # Zero-padding normal si el video duró menos de 1 segundo
        tensor[:total_frames] = np.stack(secuencia, axis=0)
    else:
        # Muestreo uniforme: Calcula 30 índices equidistantes entre 0 y el total de frames
        indices = np.linspace(0, total_frames - 1, longitud, dtype=int)
        frames_seleccionados = [secuencia[i] for i in indices]
        tensor[:] = np.stack(frames_seleccionados, axis=0)
        
    return tensor

# =============================================================================
# E/S: DESCUBRIMIENTO DE VIDEOS Y GUARDADO
# =============================================================================
def listar_videos(videos_dir=VIDEOS_DIR):
    """
    Recorre dataset/videos/<nombre_seña>/ y devuelve una lista ordenada de
    tuplas (nombre_seña, ruta_video).
    """
    if not os.path.isdir(videos_dir):
        raise FileNotFoundError(f"No existe el directorio de entrada: {videos_dir}")

    videos = []
    for nombre_sena in sorted(os.listdir(videos_dir)):
        dir_sena = os.path.join(videos_dir, nombre_sena)
        if not os.path.isdir(dir_sena):
            continue
        for archivo in sorted(os.listdir(dir_sena)):
            if archivo.lower().endswith(VIDEO_EXTENSIONS):
                videos.append((nombre_sena, os.path.join(dir_sena, archivo)))
    return videos


def guardar_tensor(tensor, nombre_sena, nombre_video, tensores_dir=TENSORES_DIR):
    """
    Guarda el tensor en dataset/tensores/<nombre_seña>/<nombre_video>.npy,
    creando la carpeta de destino si no existe.
    """
    dir_destino = os.path.join(tensores_dir, nombre_sena)
    os.makedirs(dir_destino, exist_ok=True)

    nombre_base = os.path.splitext(nombre_video)[0]
    ruta_salida = os.path.join(dir_destino, f"{nombre_base}.npy")
    np.save(ruta_salida, tensor)
    return ruta_salida


# =============================================================================
# BARRA DE PROGRESO (sin dependencias externas)
# =============================================================================
def barra_progreso(actual, total, inicio, prefijo="", ancho=40):
    """Imprime una barra de progreso en una sola línea de consola."""
    fraccion = actual / total if total else 1.0
    llenos = int(ancho * fraccion)
    barra = "█" * llenos + "-" * (ancho - llenos)
    transcurrido = time.time() - inicio
    eta = (transcurrido / actual) * (total - actual) if actual else 0.0
    sys.stdout.write(
        f"\r{prefijo} |{barra}| {actual}/{total} "
        f"({fraccion * 100:5.1f}%) ETA: {eta:5.1f}s"
    )
    sys.stdout.flush()
    if actual == total:
        sys.stdout.write("\n")


# =============================================================================
# MAIN
# =============================================================================
def main():
    videos = listar_videos()
    total = len(videos)
    if total == 0:
        print(f"No se encontraron videos en '{VIDEOS_DIR}'.")
        return

    print(f"Videos encontrados: {total}")
    print(f"Shape de salida por video: ({SEQUENCE_LENGTH}, {FEATURES_PER_FRAME})\n")
    os.makedirs(TENSORES_DIR, exist_ok=True)

    errores = []
    con_padding = 0
    inicio = time.time()

    for i, (nombre_sena, ruta_video) in enumerate(videos, start=1):
        secuencia = procesar_video(ruta_video)

        if secuencia is None or len(secuencia) == 0:
            errores.append(ruta_video)
        else:
            if len(secuencia) < SEQUENCE_LENGTH:
                con_padding += 1
            tensor = estandarizar_secuencia(secuencia)
            assert tensor.shape == (SEQUENCE_LENGTH, FEATURES_PER_FRAME)
            guardar_tensor(tensor, nombre_sena, os.path.basename(ruta_video))

        barra_progreso(i, total, inicio, prefijo="Procesando")

    # Resumen final
    print(f"\nTiempo total: {time.time() - inicio:.1f}s")
    print(f"Tensores generados: {total - len(errores)}/{total}")
    print(f"Videos con zero-padding (< {SEQUENCE_LENGTH} frames): {con_padding}")
    if errores:
        print("Videos que no se pudieron leer:")
        for ruta in errores:
            print(f"  - {ruta}")


if __name__ == "__main__":
    main()
