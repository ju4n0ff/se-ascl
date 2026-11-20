# Guía de Integración — Traductor de Lengua de Señas Chilena (LSCh) v3

Documentación técnica para el desarrollo del **Backend (FastAPI)** y el **Frontend (Web/Angular)** conectados al modelo de reconocimiento de señas LSCh (`Conv1D + BiLSTM v3`).

---

## 1. Artefactos de Producción y Especificaciones del Modelo

Todos los archivos necesarios para inferencia viven en `conversor/`:

| Archivo | Propósito | Notas |
| :--- | :--- | :--- |
| `conversor/modelos/mejor_modelo_lsch.keras` | Modelo definitivo v3 (`Conv1D + BiLSTM`) | < 3 MB. Solo capas estándar de Keras 3. Corre en **CPU** (~20–40 ms por inferencia). |
| `conversor/modelos/etiquetas_lsch.json` | Mapeo de las 89 clases de salida | Índice `0..88` correspondiente al vector `softmax`. |
| `conversor/modelos/config_features.json` | Contrato de extracción de características | Validado al arranque con `features_lsch.verificar_config()`. |
| `conversor/features_lsch.py` | Preprocesador v3 (`(30, 1629)` → `(30, 576)`) | **Dependencia única: NumPy.** Reutilizar directamente en FastAPI sin reescribir la lógica. |
| `conversor/test_local.py` | Referencia funcional en vivo con webcam | Usar como "fuente de verdad" para validar paridad del backend/frontend. |

### Métricas y dimensiones
* **Entrada cruda esperada por `features_lsch.py`:** `(30, 1629)` en `float32`.
* **Entrada del modelo `.keras`:** `(None, 30, 576)` en `float32` (228 coords globales normalizadas + 228 velocidades + 120 forma local de manos relativa a la muñeca).
* **Salida del modelo `.keras`:** `(None, 89)` en `float32` (probabilidades `softmax`).
* **Rendimiento de referencia:** 92.50% Top-1 / 98.00% Top-5 en validación intacta (200 videos); 63.33% Top-1 / 82.22% Top-5 en prueba *cross-subject* sobre webcam no vista.

---

## 2. Reglas Críticas de Geometría (NO ROMPER)

El modelo se entrenó bajo restricciones estrictas de orientación y aspecto. Romper cualquiera de estas 5 reglas desploma la precisión en vivo:

1. **NUNCA espejar la imagen antes de MediaPipe:**
   * Voltear horizontalmente el frame antes de extraer landmarks intercambia mano izquierda y derecha (en pruebas reales esto redujo la precisión en más de un 75%).
   * Si se quiere efecto espejo para comodidad del usuario, aplicarlo **únicamente de forma visual** en el frontend (ej. CSS `transform: scaleX(-1)` sobre el `<video>` o `<canvas>`), nunca sobre el frame o los datos que entran a MediaPipe.
2. **Coordenada `y` isotrópica (`y * alto / ancho`):**
   * MediaPipe entrega `x` normalizado al ancho e `y` normalizado al alto. Para que webcams 16:9, 4:3 y celulares 9:16 produzcan exactamente la misma geometría, cada punto detectado **debe** guardarse como:
     ```text
     [lm.x, lm.y * (alto_frame / ancho_frame), lm.z]
     ```
   * **No multiplicar `x` ni `z`**, solo `y`.
3. **Orden exacto del vector de 1629 floats por frame:**
   Debe respetarse este orden exacto (con `refine_face_landmarks = False`):
   * `0 .. 98` → **Pose:** 33 landmarks × 3 (`x, y*aspect, z`) = `99`
   * `99 .. 1502` → **Rostro:** 468 landmarks × 3 (`x, y*aspect, z`) = `1404`
   * `1503 .. 1565` → **Mano Izquierda:** 21 landmarks × 3 (`x, y*aspect, z`) = `63`
   * `1566 .. 1628` → **Mano Derecha:** 21 landmarks × 3 (`x, y*aspect, z`) = `63`
   * **Total:** `1629` valores `float32`.
   * Si un bloque no fue detectado en ese frame (`null` / `None`), **rellenar con `0.0` exacto** (el módulo `features_lsch.py` usa máscaras de ceros para ignorar bloques ausentes y evitar falsas velocidades).
4. **Remuestreo temporal exacto a 30 frames:**
   * Si se capturan `N >= 30` frames: muestreo uniforme con redondeo (`np.linspace(0, N - 1, 30).round().astype(int)`).
   * Si se capturan `N < 30` frames: rellenar con frames de ceros (`0.0`) al final hasta completar 30.
5. **Encuadre del usuario:**
   * La normalización centra y escala el cuerpo usando la distancia entre ambos hombros. La interfaz debe indicar al usuario que mantenga **cabeza y ambos hombros visibles** dentro de la cámara.

---

## 3. Guía para el Desarrollador Backend (FastAPI)

### Arquitectura recomendada: MediaPipe en Cliente vs. Servidor

| Opción | Qué recibe FastAPI | Pros / Contras |
| :--- | :--- | :--- |
| **A. MediaPipe en Frontend (Recomendada)** | Secuencia de landmarks `(N, 1629)` en JSON o binario (`Float32Array`) | Mínima carga en servidor, escala a múltiples usuarios simultáneos en CPU y ahorra ancho de banda. |
| **B. MediaPipe en Backend** | Frames JPEG o video corto por WebSocket/HTTP | Garantiza 100% paridad con `mediapipe==0.10.14` en Python, pero consume alta CPU por cliente conectado. |

> **Advertencia de versiones si se elige Opción B:** el pipeline usa `mp.solutions.holistic`, que fue eliminado en versiones recientes de MediaPipe (ej. `0.10.32+`). El entorno de servidor debe fijar **`mediapipe==0.10.14`**.

### Requisitos de implementación en FastAPI

1. **Carga única en `lifespan` + Warm-up:**
   * Cargar el modelo una sola vez al iniciar la app usando `compile=False`.
   * Validar `config_features.json` al inicio para evitar desajustes de versión.
   * Ejecutar una inferencia de calentamiento con ceros para eliminar la latencia del primer request.
2. **Usar `model(x, training=False)` en lugar de `model.predict()`:**
   * `model.predict()` está pensado para lotes grandes y genera sobrecarga/fugas de memoria al llamarse repetidamente en un servidor.
3. **No bloquear el Event Loop:**
   * La inferencia de TensorFlow y el cálculo de NumPy son síncronos (CPU-bound). Ejecutarlos dentro de `await asyncio.to_thread(...)` o `run_in_threadpool(...)` para no congelar otras conexiones WebSocket/HTTP.

### Código base de servicio de inferencia (`predictor.py`)

```python
import json
import time
import numpy as np
import tensorflow as tf
import features_lsch


class LSChPredictor:
    def __init__(
        self,
        modelo_path: str = "modelos/mejor_modelo_lsch.keras",
        etiquetas_path: str = "modelos/etiquetas_lsch.json",
        config_path: str = "modelos/config_features.json",
        umbral_confianza: float = 0.55,
    ):
        features_lsch.verificar_config(config_path)
        self.umbral = umbral_confianza

        with open(etiquetas_path, "r", encoding="utf-8") as f:
            raw_labels = json.load(f)
        # Soporta tanto lista ["hola", ...] como dict {"0": "hola", ...}
        if isinstance(raw_labels, list):
            self.etiquetas = raw_labels
        else:
            self.etiquetas = [raw_labels[str(i)] for i in range(len(raw_labels))]

        self.model = tf.keras.models.load_model(modelo_path, compile=False)

        # Warm-up obligatorio para evitar lag en la primera predicción
        dummy = np.zeros((1, 30, 576), dtype=np.float32)
        _ = self.model(dummy, training=False)

    @staticmethod
    def remuestrear_a_30(frames: np.ndarray) -> np.ndarray:
        """Recibe (N, 1629) float32 y devuelve (30, 1629) float32."""
        n = frames.shape[0]
        if n == 30:
            return frames.astype(np.float32, copy=False)
        if n > 30:
            idx = np.linspace(0, n - 1, 30).round().astype(int)
            return frames[idx].astype(np.float32, copy=False)
        salida = np.zeros((30, 1629), dtype=np.float32)
        salida[:n] = frames
        return salida

    @staticmethod
    def formatear_etiqueta(etiqueta_raw: str) -> tuple[str, bool]:
        """Convierte 'a_que_hora_abren.I' -> ('¿a que hora abren?', True)."""
        es_pregunta = etiqueta_raw.endswith(".I")
        limpia = etiqueta_raw[:-2] if es_pregunta else etiqueta_raw
        limpia = limpia.replace("_", " ").strip()
        if es_pregunta:
            limpia = f"¿{limpia}?"
        return limpia, es_pregunta

    def predecir_secuencia(self, secuencia_cruda: np.ndarray, top_k: int = 3) -> dict:
        """
        secuencia_cruda: np.ndarray de shape (N, 1629) con y ya isotrópica (y * h / w).
        """
        t0 = time.perf_counter()
        seq_30 = self.remuestrear_a_30(secuencia_cruda)
        entrada = features_lsch.preparar_entrada_modelo(seq_30)  # (30, 576)
        entrada = np.expand_dims(entrada, axis=0)                # (1, 30, 576)

        probs = self.model(entrada, training=False).numpy()[0]
        # Normalización defensiva si el modelo devolviera logits
        if not np.isclose(np.sum(probs), 1.0, atol=1e-2):
            probs = tf.nn.softmax(probs).numpy()

        top_idx = np.argsort(probs)[::-1][:top_k]
        candidatos = []
        for idx in top_idx:
            raw = self.etiquetas[int(idx)]
            texto, es_pregunta = self.formatear_etiqueta(raw)
            candidatos.append({
                "clase_raw": raw,
                "texto": texto,
                "es_pregunta": es_pregunta,
                "confianza": round(float(probs[idx]), 4),
            })

        mejor = candidatos[0]
        latencia_ms = round((time.perf_counter() - t0) * 1000, 2)

        return {
            "aceptada": mejor["confianza"] >= self.umbral,
            "prediccion": mejor,
            "top_k": candidatos,
            "frames_recibidos": int(secuencia_cruda.shape[0]),
            "latencia_ms": latencia_ms,
        }
```

### Contrato de API sugerido

#### 1. Endpoint REST (ideal si el frontend segmenta la seña completa)
* `POST /api/v1/predecir`
* **Request JSON** (o binario `application/octet-stream` con `Float32Array` de longitud `N * 1629` para menor peso en red):
  ```json
  {
    "frames": [
      [0.512, 0.241, -0.32, "... (1629 floats)"],
      ["..."]
    ],
    "top_k": 3
  }
  ```
* **Validaciones:** `12 <= len(frames) <= 600` y cada frame debe tener exactamente `1629` números finitos (`!NaN`, `!Inf`).

#### 2. Endpoint WebSocket (si se hace streaming continuo frame a frame)
* `WS /ws/v1/traducir`
* **Mensajes Cliente → Servidor:**
  * `{"type": "frame", "data": [ ...1629 floats... ]}` (o mensaje binario de `1629 * 4 = 6516` bytes por frame).
  * `{"type": "config", "modo": "auto" | "manual", "umbral": 0.55}`
  * `{"type": "manual_start"}` / `{"type": "manual_stop"}` (en modo manual).
  * `{"type": "reset"}` (limpia el buffer de la sesión actual).
* **Mensajes Servidor → Cliente:**
  * Estado de grabación: `{"type": "estado", "estado": "ESPERANDO" | "GRABANDO", "frames_acumulados": 18}`
  * Resultado de seña:
    ```json
    {
      "type": "prediccion",
      "aceptada": true,
      "prediccion": {
        "clase_raw": "donde_salida.I",
        "texto": "¿donde salida?",
        "es_pregunta": true,
        "confianza": 0.8742
      },
      "top_k": [
        { "clase_raw": "donde_salida.I", "texto": "¿donde salida?", "es_pregunta": true, "confianza": 0.8742 },
        { "clase_raw": "donde.I", "texto": "¿donde?", "es_pregunta": true, "confianza": 0.0615 },
        { "clase_raw": "salida", "texto": "salida", "es_pregunta": false, "confianza": 0.0210 }
      ],
      "frames_recibidos": 38,
      "latencia_ms": 26.4
    }
    ```

#### 3. Healthcheck y metadatos
* `GET /api/v1/health` → retorna estado del modelo, número de clases (`89`) y versión de features (`3`).
* `GET /api/v1/clases` → retorna la lista de las 89 señas soportadas (útil para mostrar un glosario/ayuda en el frontend).

---

## 4. Guía para el Desarrollador Frontend (Angular / Web)

### 1. Configuración exacta de MediaPipe Holistic en el navegador
Si se ejecuta `@mediapipe/holistic` en el cliente, configurar obligatoriamente:

```typescript
holistic.setOptions({
  modelComplexity: 1,
  smoothLandmarks: true,
  enableSegmentation: false,
  refineFaceLandmarks: false, // CRÍTICO: debe ser false para mantener exactamente 468 puntos faciales
  minDetectionConfidence: 0.5,
  minTrackingConfidence: 0.5,
  selfieMode: false,          // CRÍTICO: NUNCA activar true (espejaría los landmarks y rompería el modelo)
});
```

* Para que el usuario se vea como en un espejo, aplicar únicamente CSS sobre el contenedor de video/canvas:
  ```css
  .camera-preview {
    transform: scaleX(-1);
  }
  ```

### 2. Extracción del vector de 1629 floats con `y` isotrópica

```typescript
interface Landmark { x: number; y: number; z: number; }

function extraerVector1629(
  results: {
    poseLandmarks?: Landmark[];
    faceLandmarks?: Landmark[];
    leftHandLandmarks?: Landmark[];
    rightHandLandmarks?: Landmark[];
  },
  videoWidth: number,
  videoHeight: number
): Float32Array {
  const vector = new Float32Array(1629); // Inicializado en 0.0 exacto
  const aspect = videoHeight / videoWidth;
  let offset = 0;

  const escribirBloque = (landmarks: Landmark[] | undefined, expectedLen: number) => {
    if (landmarks && landmarks.length >= expectedLen) {
      for (let i = 0; i < expectedLen; i++) {
        vector[offset++] = landmarks[i].x;
        vector[offset++] = landmarks[i].y * aspect; // Escala isotrópica obligatoria
        vector[offset++] = landmarks[i].z;
      }
    } else {
      offset += expectedLen * 3; // Deja los ceros intactos
    }
  };

  escribirBloque(results.poseLandmarks, 33);       // 99
  escribirBloque(results.faceLandmarks, 468);      // 1404
  escribirBloque(results.leftHandLandmarks, 21);   // 63
  escribirBloque(results.rightHandLandmarks, 21);  // 63

  return vector;
}
```

### 3. Máquina de estados para detectar inicio y fin de seña (Modo Automático)
Esta lógica ya fue probada y calibrada en `conversor/test_local.py`:

* **Condición de mano activa:** `Boolean(results.leftHandLandmarks || results.rightHandLandmarks)`.
* **`ESPERANDO` → `GRABANDO`:** cuando hay mano activa durante **3 frames consecutivos**. Conservar esos 3 frames iniciales dentro del buffer para no recortar el arranque de la seña.
* **Durante `GRABANDO`:** acumular vectores `(1629,)` hasta un límite máximo de seguridad de **90 frames**.
* **`GRABANDO` → `PREDECIR`:** cuando pasan **10 frames consecutivos sin ninguna mano detectada** (o al alcanzar 90 frames).
  * Recortar los últimos 10 frames sin manos antes de enviar.
  * Si quedan menos de **12 frames** útiles, descartar como ruido y volver a `ESPERANDO`.
  * Si quedan `>= 12` frames, enviar la secuencia completa al backend y volver a `ESPERANDO`.
* **Modo Manual (recomendado como botón/atajo `ESPACIO`):** permite al usuario iniciar y detener la grabación explícitamente (límite de seguridad: 600 frames), muy útil para señas compuestas o pruebas en entornos con poca luz.

### 4. Recomendaciones de UX para maximizar la precisión percibida
* **Guía visual de encuadre:** mostrar una silueta suave indicando que la cabeza y ambos hombros deben quedar visibles.
* **Indicadores en vivo:** mostrar estado (`Esperando` / `Grabando`), detección de `Mano Izq` / `Mano Der` y FPS actuales (ideal `>= 15 FPS`).
* **Aprovechar el Top-3 (el modelo tiene ~82%–98% en Top-5):**
  * Si `aceptada === true` (`confianza >= 0.55`), agregar `prediccion.texto` a la frase traducida automáticamente.
  * Mostrar debajo los 2 candidatos alternativos como chips clickeables para permitir corregir la última palabra con un toque si el usuario lo desea.
* **Salida de audio (TTS):** usar la Web Speech API (`window.speechSynthesis`) con voz `es-CL` (fallback `es-ES` / `es-MX`) para leer la palabra o la frase acumulada; el campo `es_pregunta` y los signos `¿...?` ya permiten entonación interrogativa natural.
* **Etiquetas con sufijo `.I` y variantes:** existen algunas clases terminadas en `.I` (preguntas, ej. `que.I`, `donde_salida.I`) y variantes como `gracias2`; conviene mantener un diccionario opcional de presentación en el frontend (ej. `gracias2` → `"gracias"`).

---

## 5. Checklist de Verificación antes de Producción

1. **Paridad local:** ejecutar `python conversor/test_local.py` y confirmar que el modelo predice correctamente en la misma máquina.
2. **Test de mano izquierda vs. derecha:** levantar solo la mano derecha frente a la cámara web del navegador y confirmar que se llena el bloque `1566..1628` (`rightHandLandmarks`) y **no** el izquierdo. Si salen invertidos, revisar `selfieMode: false` o si la cámara aplica espejo por hardware.
3. **Test de isotropía:** comprobar que `videoHeight / videoWidth` es `~0.5625` en cámara 16:9 (`1280x720`) o `0.75` en 4:3 (`640x480`), y que el valor de `y` enviado en el vector refleja esa multiplicación.
4. **Test de extremo a extremo:** guardar un `.npy` crudo `(30, 1629)` capturado por `test_local.py`, enviarlo al endpoint de FastAPI y verificar que la probabilidad Top-1 devuelta por la API coincida hasta el 4.º decimal con la inferencia local.