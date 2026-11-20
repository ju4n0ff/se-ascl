# -*- coding: utf-8 -*-
"""
test_local.py — Prueba en vivo (webcam) del modelo LSCh v3.

Ubicación esperada:  C:\\SenaCL\\conversor\\test_local.py
Requiere en la misma carpeta:
    features_lsch.py                      (v3: preparar_entrada_modelo, verificar_config)
    modelos/mejor_modelo_lsch.keras       (entrada (None, 30, 576), salida (None, 89))
    modelos/etiquetas_lsch.json           (lista o mapa de 89 clases)
    modelos/config_features.json

Paridad con el entrenamiento v3:
    * El frame que entra a holistic.process() NUNCA se espeja.
    * 1629 floats/frame: Pose(33) + Rostro(468) + Mano Izq(21) + Mano Der(21),
      cada punto = [x, y * (h / w), z]; bloque ausente = 0.0 exacto.
    * N frames -> (30, 1629) -> features_lsch.preparar_entrada_modelo -> (30, 576).

Controles:
    ESPACIO  iniciar / detener grabación manual (cambia a modo MANUAL)
    A        modo automático (por defecto)
    M        alternar vista espejo (solo visual)
    C        limpiar frase acumulada
    Q / ESC  salir
"""

import os
import sys
import json
import time
import unicodedata
from collections import deque

import numpy as np
import cv2

# --------------------------------------------------------------------------
# Rutas: todo relativo a la carpeta del script (C:\SenaCL\conversor\)
# --------------------------------------------------------------------------
DIR_BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(DIR_BASE)
if DIR_BASE not in sys.path:
    sys.path.insert(0, DIR_BASE)

RUTA_CONFIG = "modelos/config_features.json"
RUTA_MODELO = "modelos/mejor_modelo_lsch.keras"
RUTA_ETIQUETAS = "modelos/etiquetas_lsch.json"

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
CAMARA_INDICE = 0
ANCHO_CAM, ALTO_CAM = 640, 480       # resolución solicitada a la webcam

N_FRAMES_MODELO = 30
N_FEATURES_RAW = 1629                # (33 + 468 + 21 + 21) * 3
N_FEATURES_MODELO = 576

UMBRAL_CONFIANZA = 0.55
EVITAR_DUPLICADOS = True             # no repetir la misma palabra consecutiva

# Segmentación automática
FRAMES_INICIO = 3                    # frames consecutivos con mano para empezar
FRAMES_FIN = 10                      # frames consecutivos sin manos para terminar
MAX_FRAMES_AUTO = 90                 # tope de seguridad
MIN_FRAMES_SENA = 12                 # menos que esto = ruido, se descarta

# Grabación manual
MAX_FRAMES_MANUAL = 600              # tope de memoria (~20 s a 30 FPS)

# Secuencias con N < 30 frames:
#   "ceros"    -> zero-padding al final
#   "linspace" -> muestreo uniforme con repetición de frames
# Debe coincidir con lo que hace preprocesar_lsch_v2.py.
RELLENO_CORTO = "ceros"

ESPEJO_INICIAL = True

# Layout de la ventana
ANCHO_PANEL_LATERAL = 330
ALTO_PANEL_INFERIOR = 110
NOMBRE_VENTANA = "LSCh - Prueba en vivo (v3)"

# Colores BGR
C_VERDE = (80, 200, 60)
C_ROJO = (60, 60, 230)
C_AMBAR = (40, 170, 240)
C_BLANCO = (245, 245, 245)
C_GRIS = (150, 150, 150)
C_GRIS_OSC = (70, 70, 70)
C_FONDO = (32, 28, 26)
C_CIAN = (220, 200, 60)
C_MAGENTA = (200, 80, 220)

# Bloques del vector de features (orden del dataset)
N_POSE, N_ROSTRO, N_MANO = 33, 468, 21


# ==========================================================================
# Extracción de landmarks (paridad exacta con el dataset)
# ==========================================================================
def _bloque_a_array(bloque, n_puntos, aspecto):
    """[x, y*aspecto, z] por punto; 0.0 exacto si el bloque es None."""
    if bloque is None:
        return np.zeros(n_puntos * 3, dtype=np.float32)
    pts = np.array(
        [[lm.x, lm.y * aspecto, lm.z] for lm in bloque.landmark],
        dtype=np.float32,
    )
    if pts.shape[0] != n_puntos:  # salvaguarda (p.ej. 478 pts si refine=True)
        fijo = np.zeros((n_puntos, 3), dtype=np.float32)
        k = min(n_puntos, pts.shape[0])
        fijo[:k] = pts[:k]
        pts = fijo
    return pts.reshape(-1)


def extraer_vector(results, h, w):
    """Devuelve (vector (1629,) float32, hay_mano_izq, hay_mano_der)."""
    aspecto = h / w
    vec = np.concatenate([
        _bloque_a_array(results.pose_landmarks, N_POSE, aspecto),
        _bloque_a_array(results.face_landmarks, N_ROSTRO, aspecto),
        _bloque_a_array(results.left_hand_landmarks, N_MANO, aspecto),
        _bloque_a_array(results.right_hand_landmarks, N_MANO, aspecto),
    ]).astype(np.float32, copy=False)
    assert vec.shape == (N_FEATURES_RAW,), vec.shape
    return (vec,
            results.left_hand_landmarks is not None,
            results.right_hand_landmarks is not None)


# ==========================================================================
# Remuestreo a 30 frames
# ==========================================================================
def remuestrear(frames):
    """Lista de N vectores (1629,) -> np.ndarray (30, 1629) float32.

    Idéntico a preprocesar_lsch_v2.indices_uniformes + estandarizar_secuencia:
    N > 30 -> linspace(0, N-1, 30).round().astype(int);  N <= 30 -> padding final.
    (.round() y no solo .astype(int), para coincidir con el dataset.)
    """
    arr = np.stack(frames).astype(np.float32, copy=False)
    n = arr.shape[0]
    if n > N_FRAMES_MODELO or (n < N_FRAMES_MODELO and RELLENO_CORTO == "linspace"):
        idx = np.linspace(0, n - 1, N_FRAMES_MODELO).round().astype(int)
        return arr[idx]
    if n == N_FRAMES_MODELO:
        return arr
    out = np.zeros((N_FRAMES_MODELO, N_FEATURES_RAW), dtype=np.float32)
    out[:n] = arr
    return out


# ==========================================================================
# Segmentador automático: ESPERANDO -> GRABANDO
# ==========================================================================
class SegmentadorAuto:
    ESPERANDO, GRABANDO = "ESPERANDO", "GRABANDO"

    def __init__(self):
        self.reset()

    def reset(self):
        self.estado = self.ESPERANDO
        self.buffer = []
        self.racha_manos = 0
        self.racha_sin_manos = 0
        # Guarda los frames de la racha inicial para no perder el comienzo
        self.previos = deque(maxlen=FRAMES_INICIO)

    @property
    def n_frames(self):
        return len(self.buffer)

    def actualizar(self, vec, hay_manos):
        """
        Devuelve (evento, dato):
            (None, None)        nada que reportar
            ("inicio", None)    empezó una grabación
            ("fin", frames)     seña completa (lista de vectores, ya recortada)
            ("ruido", n)        segmento descartado por corto
        """
        if self.estado == self.ESPERANDO:
            if hay_manos:
                self.racha_manos += 1
                self.previos.append(vec)
            else:
                self.racha_manos = 0
                self.previos.clear()
            if self.racha_manos >= FRAMES_INICIO:
                self.estado = self.GRABANDO
                self.buffer = list(self.previos)
                self.previos.clear()
                self.racha_sin_manos = 0
                return "inicio", None
            return None, None

        # GRABANDO
        self.buffer.append(vec)
        self.racha_sin_manos = 0 if hay_manos else self.racha_sin_manos + 1

        if self.racha_sin_manos >= FRAMES_FIN or len(self.buffer) >= MAX_FRAMES_AUTO:
            # Recorta la cola sin manos (tiempo muerto final)
            if self.racha_sin_manos > 0:
                frames = self.buffer[:-self.racha_sin_manos]
            else:
                frames = self.buffer
            self.reset()
            if len(frames) < MIN_FRAMES_SENA:
                return "ruido", len(frames)
            return "fin", frames
        return None, None


# ==========================================================================
# Etiquetas
# ==========================================================================
def cargar_etiquetas(ruta, n_clases):
    with open(ruta, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Contenedor tipo {"etiquetas": [...]} / {"clases": {...}}
    if isinstance(data, dict):
        for k in ("etiquetas", "clases", "labels", "classes", "idx_to_label",
                  "id2label", "index_to_label"):
            if k in data and isinstance(data[k], (list, dict)):
                data = data[k]
                break

    etiquetas = [None] * n_clases
    if isinstance(data, list):
        for i, v in enumerate(data[:n_clases]):
            if isinstance(v, dict):
                v = next((v[k] for k in ("nombre", "etiqueta", "label", "clase")
                          if k in v), str(v))
            etiquetas[i] = str(v)
    elif isinstance(data, dict):
        claves_int = all(str(k).lstrip("-").isdigit() for k in data.keys())
        valores_int = all(isinstance(v, int) for v in data.values())
        if claves_int:                      # {"0": "hola", ...}
            for k, v in data.items():
                if 0 <= int(k) < n_clases:
                    etiquetas[int(k)] = str(v)
        elif valores_int:                   # {"hola": 0, ...}
            for k, v in data.items():
                if 0 <= v < n_clases:
                    etiquetas[v] = str(k)
        else:
            raise ValueError(f"Formato de {ruta} no reconocido.")
    else:
        raise ValueError(f"Formato de {ruta} no reconocido.")

    faltan = [i for i, e in enumerate(etiquetas) if e is None]
    if faltan:
        print(f"[AVISO] {len(faltan)} índices sin etiqueta en {ruta}; "
              f"se usarán nombres genéricos (clase_i).")
        for i in faltan:
            etiquetas[i] = f"clase_{i}"
    return etiquetas


# ==========================================================================
# Predictor (modelo + features v3)
# ==========================================================================
class PredictorLSCh:
    def __init__(self):
        import features_lsch
        self.fl = features_lsch

        # 1) Verificar config de features
        print(f"[INFO] Verificando {RUTA_CONFIG} ...")
        try:
            features_lsch.verificar_config(RUTA_CONFIG)   # lanza ValueError si no coincide
        except ValueError as e:
            raise SystemExit(f"[ERROR] {e}")

        # 2) Cargar modelo
        print(f"[INFO] Cargando modelo {RUTA_MODELO} ...")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
        import tensorflow as tf
        self.tf = tf
        self.model = tf.keras.models.load_model(RUTA_MODELO, compile=False)

        in_shape = tuple(self.model.input_shape)
        out_shape = tuple(self.model.output_shape)
        print(f"[INFO] Modelo: entrada {in_shape} -> salida {out_shape}")
        if in_shape[1:] != (N_FRAMES_MODELO, N_FEATURES_MODELO):
            raise SystemExit(f"[ERROR] Se esperaba entrada (None, 30, 576), "
                             f"el modelo tiene {in_shape}")
        self.n_clases = int(out_shape[-1])

        # 3) Etiquetas
        self.etiquetas = cargar_etiquetas(RUTA_ETIQUETAS, self.n_clases)
        print(f"[INFO] {len(self.etiquetas)} clases cargadas.")

        # 4) Warm-up (antes de abrir la webcam)
        print("[INFO] Warm-up del modelo ...")
        t0 = time.perf_counter()
        self.model(np.zeros((1, N_FRAMES_MODELO, N_FEATURES_MODELO),
                            dtype=np.float32), training=False)
        t1 = time.perf_counter()
        self.model(np.zeros((1, N_FRAMES_MODELO, N_FEATURES_MODELO),
                            dtype=np.float32), training=False)
        t2 = time.perf_counter()
        # Warm-up también del pipeline de features (no crítico)
        try:
            self._preparar(np.zeros((N_FRAMES_MODELO, N_FEATURES_RAW), np.float32))
        except Exception as e:  # noqa: BLE001
            print(f"[AVISO] Warm-up de preparar_entrada_modelo falló con ceros: {e}")
        print(f"[INFO] Warm-up listo: 1ª llamada {(t1 - t0) * 1e3:.0f} ms, "
              f"2ª llamada {(t2 - t1) * 1e3:.1f} ms")

        self._salida_es_softmax = None

    def _preparar(self, secuencia):
        """(30, 1629) -> (1, 30, 576) float32 vía features_lsch v3."""
        x = np.asarray(self.fl.preparar_entrada_modelo(secuencia), dtype=np.float32)
        if x.ndim == 2:
            x = x[np.newaxis]
        if x.shape != (1, N_FRAMES_MODELO, N_FEATURES_MODELO):
            raise ValueError(f"preparar_entrada_modelo devolvió {x.shape}, "
                             f"se esperaba (30, 576)")
        return x

    def predecir(self, frames):
        n = len(frames)
        t0 = time.perf_counter()
        secuencia = remuestrear(frames)                 # (30, 1629)
        x = self._preparar(secuencia)                    # (1, 30, 576)
        t1 = time.perf_counter()
        probs = self.model(x, training=False).numpy()[0]
        t2 = time.perf_counter()

        # Si la última capa no es softmax (logits), normalizar
        if self._salida_es_softmax is None:
            self._salida_es_softmax = bool(
                np.all(probs >= 0) and abs(float(probs.sum()) - 1.0) < 1e-3)
            if not self._salida_es_softmax:
                print("[INFO] La salida no parece softmax; se aplicará softmax.")
        if not self._salida_es_softmax:
            e = np.exp(probs - probs.max())
            probs = e / e.sum()

        top = np.argsort(probs)[::-1][:3]
        return {
            "top3": [(self.etiquetas[i], float(probs[i])) for i in top],
            "n_frames": n,
            "prep_ms": (t1 - t0) * 1e3,
            "lat_ms": (t2 - t1) * 1e3,
        }


# ==========================================================================
# Texto (Unicode con PIL si está disponible; si no, ASCII con OpenCV)
# ==========================================================================
class CapaTexto:
    FUENTES = {
        False: ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        True: ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    }

    def __init__(self):
        self.items = []
        self._cache = {}
        self.pil = None
        try:
            from PIL import Image, ImageDraw, ImageFont
            self.pil = (Image, ImageDraw, ImageFont)
            self._fuente(16, False)  # prueba
        except Exception:  # noqa: BLE001
            self.pil = None
            print("[INFO] PIL no disponible: el texto se mostrará sin tildes/ñ.")

    def _fuente(self, size, negrita):
        key = (size, negrita)
        if key not in self._cache:
            _, _, ImageFont = self.pil
            fuente = None
            for ruta in self.FUENTES[negrita] + self.FUENTES[False]:
                if os.path.exists(ruta):
                    fuente = ImageFont.truetype(ruta, size)
                    break
            if fuente is None:
                fuente = ImageFont.load_default()
            self._cache[key] = fuente
        return self._cache[key]

    @staticmethod
    def _ascii(texto):
        return (unicodedata.normalize("NFKD", texto)
                .encode("ascii", "ignore").decode("ascii"))

    def ancho(self, texto, size, negrita=False):
        if self.pil:
            return int(self._fuente(size, negrita).getlength(texto))
        (tw, _), _ = cv2.getTextSize(self._ascii(texto), cv2.FONT_HERSHEY_SIMPLEX,
                                     size / 30.0, 2 if negrita else 1)
        return tw

    def poner(self, texto, x, y, size=16, color=C_BLANCO, negrita=False):
        """(x, y) = esquina superior izquierda del texto."""
        self.items.append((texto, int(x), int(y), size, color, negrita))

    def renderizar(self, img):
        if not self.items:
            return img
        if self.pil:
            Image, ImageDraw, _ = self.pil
            pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            d = ImageDraw.Draw(pil_img)
            for texto, x, y, size, color, negrita in self.items:
                d.text((x, y), texto, font=self._fuente(size, negrita),
                       fill=(color[2], color[1], color[0]))
            img = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)
        else:
            for texto, x, y, size, color, negrita in self.items:
                cv2.putText(img, self._ascii(texto), (x, y + int(size * 0.8)),
                            cv2.FONT_HERSHEY_SIMPLEX, size / 30.0, color,
                            2 if negrita else 1, cv2.LINE_AA)
        self.items.clear()
        return img


# ==========================================================================
# Dibujo de landmarks (solo manos + brazos)
# ==========================================================================
CONEX_MANO = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]
CONEX_BRAZOS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (15, 17), (15, 19), (15, 21), (17, 19),
    (16, 18), (16, 20), (16, 22), (18, 20),
]
PUNTOS_BRAZOS = sorted({i for c in CONEX_BRAZOS for i in c})


def dibujar_landmarks(img, results):
    h, w = img.shape[:2]

    if results.pose_landmarks is not None:
        lms = results.pose_landmarks.landmark
        px = {i: (int(lms[i].x * w), int(lms[i].y * h)) for i in PUNTOS_BRAZOS
              if getattr(lms[i], "visibility", 1.0) > 0.5}
        for a, b in CONEX_BRAZOS:
            if a in px and b in px:
                cv2.line(img, px[a], px[b], (200, 200, 200), 2, cv2.LINE_AA)
        for p in px.values():
            cv2.circle(img, p, 4, (255, 255, 255), -1, cv2.LINE_AA)

    for mano, color in ((results.left_hand_landmarks, C_CIAN),
                        (results.right_hand_landmarks, C_MAGENTA)):
        if mano is None:
            continue
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in mano.landmark]
        for a, b in CONEX_MANO:
            cv2.line(img, pts[a], pts[b], color, 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, p, 3, (255, 255, 255), -1, cv2.LINE_AA)


# ==========================================================================
# HUD
# ==========================================================================
def legible(etiqueta):
    """'a_que_hora_abren.I' -> 'a que hora abren.I' (solo para mostrar)."""
    return etiqueta.replace("_", " ")


def rect_translucido(img, p1, p2, color=(0, 0, 0), alpha=0.55):
    x1, y1 = p1
    x2, y2 = p2
    roi = img[y1:y2, x1:x2]
    capa = np.full_like(roi, color)
    cv2.addWeighted(capa, alpha, roi, 1 - alpha, 0, roi)


def dibujar_hud(canvas, txt, est):
    """est: dict con todo el estado a mostrar."""
    vw, vh = est["vw"], est["vh"]
    W = canvas.shape[1]
    grabando = est["grabando"]

    # ---------------- Panel superior (sobre el video) ----------------
    rect_translucido(canvas, (0, 0), (vw, 66))
    if grabando:
        if int(time.time() * 2) % 2 == 0:
            cv2.circle(canvas, (18, 20), 8, C_ROJO, -1, cv2.LINE_AA)
        txt.poner(f"GRABANDO [{est['n_frames']} frames]", 34, 8, 20, C_ROJO, True)
    else:
        sub = " (ESPACIO para grabar)" if est["modo"] == "MANUAL" else ""
        txt.poner("ESPERANDO" + sub, 12, 8, 20, C_BLANCO, True)

    linea2 = (f"Modo: {est['modo']}   Espejo: {'ON' if est['espejo'] else 'OFF'}   "
              f"FPS: {est['fps']:.1f}   Lat: "
              + (f"{est['lat_ms']:.1f} ms" if est['lat_ms'] is not None else "--"))
    txt.poner(linea2, 12, 38, 15, C_GRIS)

    # Indicadores de manos (perspectiva del señante: Izq/Der del dataset)
    x0 = vw - 190
    for etiqueta, presente, color in (("Izq", est["mano_izq"], C_CIAN),
                                      ("Der", est["mano_der"], C_MAGENTA)):
        cv2.circle(canvas, (x0, 20), 7, color if presente else C_GRIS_OSC, -1,
                   cv2.LINE_AA)
        txt.poner(f"Mano {etiqueta}", x0 + 12, 10, 14,
                  C_BLANCO if presente else C_GRIS)
        x0 += 95

    # Barra de progreso de grabación
    if grabando:
        tope = MAX_FRAMES_AUTO if est["modo"] == "AUTO" else MAX_FRAMES_MANUAL
        frac = min(est["n_frames"] / tope, 1.0)
        cv2.rectangle(canvas, (0, 62), (int(vw * frac), 66), C_ROJO, -1)
        cv2.rectangle(canvas, (1, 1), (vw - 2, vh - 2), C_ROJO, 3)

    # ---------------- Panel lateral: Top-3 ----------------
    px = vw + 18
    pw = W - vw - 36
    txt.poner("Predicción", px, 14, 20, C_BLANCO, True)
    pred = est["pred"]
    if pred is None:
        txt.poner("Haz una seña frente a la cámara…", px, 56, 15, C_GRIS)
    else:
        palabra, conf = pred["top3"][0]
        palabra = legible(palabra)
        aceptada = conf >= UMBRAL_CONFIANZA
        color = C_VERDE if aceptada else C_AMBAR
        tam = 34
        while tam > 18 and txt.ancho(palabra, tam, True) > pw:
            tam -= 2
        txt.poner(palabra, px, 48, tam, color, True)
        txt.poner(f"{conf * 100:.1f}%  " +
                  ("✔ aceptada" if aceptada and txt.pil else
                   "aceptada" if aceptada else "bajo el umbral"),
                  px, 48 + tam + 10, 15, color)

        y = 150
        txt.poner("Top-3", px, y, 16, C_GRIS, True)
        y += 28
        for i, (lab, p) in enumerate(pred["top3"]):
            col = (C_VERDE if p >= UMBRAL_CONFIANZA else C_AMBAR) if i == 0 else C_GRIS
            txt.poner(f"{i + 1}. {legible(lab)}", px, y, 16, C_BLANCO)
            txt.poner(f"{p * 100:5.1f}%", px + pw - txt.ancho("100.0%", 16), y,
                      16, C_BLANCO)
            by = y + 24
            cv2.rectangle(canvas, (px, by), (px + pw, by + 10), C_GRIS_OSC, -1)
            cv2.rectangle(canvas, (px, by), (px + int(pw * p), by + 10), col, -1)
            ux = px + int(pw * UMBRAL_CONFIANZA)
            cv2.line(canvas, (ux, by - 3), (ux, by + 13), C_BLANCO, 1)
            y += 52

        txt.poner(f"Frames: {pred['n_frames']} → {N_FRAMES_MODELO}", px, y + 4, 14, C_GRIS)
        txt.poner(f"Inferencia: {pred['lat_ms']:.1f} ms  (prep {pred['prep_ms']:.1f} ms)",
                  px, y + 24, 14, C_GRIS)

    txt.poner(f"Umbral: {UMBRAL_CONFIANZA * 100:.0f}%", px, vh - 54, 14, C_GRIS)
    if est["mensaje"]:
        txt.poner(est["mensaje"], px, vh - 30, 14, C_AMBAR)

    # ---------------- Panel inferior: frase + controles ----------------
    y0 = vh
    cv2.line(canvas, (0, y0), (W, y0), C_GRIS_OSC, 1)
    txt.poner("Frase:", 14, y0 + 14, 18, C_GRIS, True)
    frase_completa = "  ".join(legible(p) for p in est["frase"])
    frase = frase_completa
    max_w = W - 100
    while frase and txt.ancho(frase, 24, True) > max_w:   # mostrar el final
        frase = frase.split(" ", 1)[1] if " " in frase else frase[1:]
    if frase != frase_completa:
        frase = "… " + frase
    txt.poner(frase if frase else "—", 80, y0 + 10, 24, C_VERDE, True)

    controles = ("[ESPACIO] grabar/parar manual    [A] modo auto    "
                 "[M] espejo    [C] limpiar frase    [Q] salir")
    txt.poner(controles, 14, y0 + ALTO_PANEL_INFERIOR - 32, 14, C_GRIS)


# ==========================================================================
# Cámara
# ==========================================================================
def abrir_camara():
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if os.name == "nt" \
        else [cv2.CAP_ANY]
    for be in backends:
        cap = cv2.VideoCapture(CAMARA_INDICE, be)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO_CAM)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO_CAM)
            ok, _ = cap.read()
            if ok:
                return cap
        cap.release()
    raise SystemExit(f"[ERROR] No se pudo abrir la cámara {CAMARA_INDICE}.")


# ==========================================================================
# Main
# ==========================================================================
def main():
    try:
        import mediapipe as mp
        mp_holistic = mp.solutions.holistic
    except AttributeError:
        raise SystemExit(
            "[ERROR] Tu versión de mediapipe no incluye mp.solutions (API legacy).\n"
            "        Instala la misma versión con la que generaste el dataset, p. ej.:\n"
            "        pip install \"mediapipe==0.10.14\"")

    predictor = PredictorLSCh()          # config + modelo + warm-up ANTES de la webcam
    cap = abrir_camara()
    txt = CapaTexto()
    seg = SegmentadorAuto()

    modo = "AUTO"
    espejo = ESPEJO_INICIAL
    grabando_manual = False
    buffer_manual = []
    frase = []
    pred = None
    ultima_lat = None
    mensaje, mensaje_hasta = "", 0.0
    fps, t_prev = 0.0, time.perf_counter()

    def avisar(msg, seg_dur=2.0):
        nonlocal mensaje, mensaje_hasta
        mensaje, mensaje_hasta = msg, time.time() + seg_dur
        print(f"[INFO] {msg}")

    def ejecutar_prediccion(frames, origen):
        nonlocal pred, ultima_lat
        pred = predictor.predecir(frames)
        ultima_lat = pred["lat_ms"]
        palabra, conf = pred["top3"][0]
        top_str = " | ".join(f"{l} {p * 100:.1f}%" for l, p in pred["top3"])
        print(f"[{origen}] {pred['n_frames']:3d} frames -> {top_str}   "
              f"({pred['lat_ms']:.1f} ms + prep {pred['prep_ms']:.1f} ms)")
        if conf >= UMBRAL_CONFIANZA:
            if not (EVITAR_DUPLICADOS and frase and frase[-1] == palabra):
                frase.append(palabra)

    cv2.namedWindow(NOMBRE_VENTANA, cv2.WINDOW_AUTOSIZE)
    print("[INFO] Cámara abierta. Controles: ESPACIO, A, M, C, Q")

    with mp_holistic.Holistic(min_detection_confidence=0.5,
                              min_tracking_confidence=0.5,
                              model_complexity=1,
                              refine_face_landmarks=False) as holistic:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[AVISO] Frame no leído; reintentando…")
                if cv2.waitKey(10) & 0xFF in (ord("q"), ord("Q"), 27):
                    break
                continue

            h, w = frame.shape[:2]

            # ---- MediaPipe sobre el frame ORIGINAL (sin espejo) ----
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = holistic.process(rgb)

            vec, izq, der = extraer_vector(results, h, w)
            hay_manos = izq or der

            # ---- Segmentación ----
            if modo == "AUTO":
                evento, dato = seg.actualizar(vec, hay_manos)
                if evento == "fin":
                    ejecutar_prediccion(dato, "AUTO")
                elif evento == "ruido":
                    avisar(f"Ruido descartado ({dato} frames < {MIN_FRAMES_SENA})")
                grabando = seg.estado == SegmentadorAuto.GRABANDO
                n_frames = seg.n_frames
            else:
                if grabando_manual:
                    buffer_manual.append(vec)
                    if len(buffer_manual) >= MAX_FRAMES_MANUAL:
                        avisar(f"Tope manual alcanzado ({MAX_FRAMES_MANUAL} frames)")
                        ejecutar_prediccion(buffer_manual, "MANUAL")
                        buffer_manual, grabando_manual = [], False
                grabando = grabando_manual
                n_frames = len(buffer_manual)

            # ---- Visualización (copia; espejo solo aquí) ----
            vis = frame.copy()
            dibujar_landmarks(vis, results)
            if espejo:
                vis = cv2.flip(vis, 1)

            canvas = np.empty((h + ALTO_PANEL_INFERIOR, w + ANCHO_PANEL_LATERAL, 3),
                              dtype=np.uint8)
            canvas[:] = C_FONDO
            canvas[:h, :w] = vis

            ahora = time.perf_counter()
            dt = ahora - t_prev
            t_prev = ahora
            if dt > 0:
                fps = 1.0 / dt if fps == 0 else 0.9 * fps + 0.1 / dt

            if mensaje and time.time() > mensaje_hasta:
                mensaje = ""

            dibujar_hud(canvas, txt, {
                "vw": w, "vh": h, "modo": modo, "espejo": espejo,
                "grabando": grabando, "n_frames": n_frames,
                "fps": fps, "lat_ms": ultima_lat, "pred": pred,
                "frase": frase, "mensaje": mensaje,
                "mano_izq": izq, "mano_der": der,
            })
            canvas = txt.renderizar(canvas)       # HUD después del flip
            cv2.imshow(NOMBRE_VENTANA, canvas)

            # ---- Teclado ----
            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), ord("Q"), 27):
                break
            elif k == 32:  # ESPACIO
                if modo != "MANUAL":
                    modo = "MANUAL"
                    seg.reset()
                if not grabando_manual:
                    grabando_manual, buffer_manual = True, []
                    avisar("Grabación manual iniciada", 1.2)
                else:
                    grabando_manual = False
                    if buffer_manual:
                        if len(buffer_manual) < MIN_FRAMES_SENA:
                            avisar(f"Secuencia corta ({len(buffer_manual)} frames)")
                        ejecutar_prediccion(buffer_manual, "MANUAL")
                    buffer_manual = []
            elif k in (ord("a"), ord("A")):
                if modo != "AUTO":
                    modo = "AUTO"
                    grabando_manual, buffer_manual = False, []
                    seg.reset()
                    avisar("Modo AUTO", 1.2)
            elif k in (ord("m"), ord("M")):
                espejo = not espejo
            elif k in (ord("c"), ord("C")):
                frase.clear()
                avisar("Frase limpiada", 1.2)

            if cv2.getWindowProperty(NOMBRE_VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break

    cap.release()
    cv2.destroyAllWindows()
    if frase:
        print("Frase final:", " ".join(frase))


if __name__ == "__main__":
    main()
