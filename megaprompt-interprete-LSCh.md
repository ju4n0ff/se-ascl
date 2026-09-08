# MEGA-PROMPT MAESTRO
## Desarrollo de "SeñasCL" — Intérprete de Lengua de Señas Chilena (LSCh) → Texto y Voz

> **Cómo usar este documento:** Es un prompt maestro pensado para pegarlo (completo o por secciones) en un asistente de desarrollo con IA (Claude Code, Cursor, etc.) o para usarlo como brief de producto con un equipo humano. Está escrito en modo imperativo, dirigido a "ti" (la IA/equipo que va a construir el producto). Contiene contexto real de investigación (septiembre 2026), arquitectura, roles, buenas prácticas de UX/accesibilidad y un roadmap por fases.

---

## 1. ROL Y MISIÓN

Actúa como un **equipo de ingeniería de producto senior full-stack especializado en accesibilidad, visión por computador y aplicaciones multiplataforma**. Tu misión es diseñar y comenzar a construir **SeñasCL**, una aplicación que:

1. Usa la cámara del dispositivo (PC/notebook, Android, iOS) para capturar en tiempo real a una persona haciendo señas en **Lengua de Señas Chilena (LSCh)**.
2. Reconoce las señas (deletreo dactilológico + palabras/frases básicas) y las traduce a **texto en español escrito**.
3. Opcionalmente convierte ese texto a **voz hablada** (texto-a-voz) reproducida por el parlante/altavoz del dispositivo.
4. Funciona con una **base de código compartida en la mayor proporción posible** entre PC (Windows/macOS/Linux), Android e iOS.
5. Está diseñada **con y para la comunidad sorda chilena**, no solo "sobre" ella.

No es un traductor de texto a señas (avatar firmante) en su versión inicial — eso queda como fase futura opcional (ver §9). El foco es **seña → texto/voz**, que es el sentido de traducción con mayor demanda real y el que valida antes el modelo de reconocimiento.

---

## 2. CONTEXTO REAL Y ESTADO DEL ARTE (a considerar, no ignorar)

Antes de proponer arquitectura, ten en cuenta este contexto verificado:

- **Marco legal chileno**: la Ley 20.422 (2010) reconoce derechos de personas con discapacidad, y la **Ley 21.303 (2021)** reconoce oficialmente la LSCh como lengua de la comunidad sorda de Chile. Esto es relevante para justificar el producto y para lineamientos de accesibilidad/e-inclusión al presentarlo ante instituciones públicas.
- **La LSCh es una lengua con gramática propia**, distinta del español (orden de palabras, uso de espacio y referencia, expresiones faciales gramaticales, no es "español firmado"). Traducir seña→texto no es un mapeo símbolo-por-palabra: es traducción entre dos lenguas con estructuras distintas. Este matiz debe reflejarse en el diseño del pipeline de NLP (no solo clasificación de gestos).
- **Ya existen esfuerzos académicos chilenos activos** que puedes usar como referencia técnica y como potenciales aliados/fuentes de datos (contáctalos o cita su enfoque, no copies datasets sin permiso):
  - Un dataset de **Reconocimiento Aislado de LSCh** construido a partir de videos segmentados de estudiantes sordos, usando estimación de postura + modelos Transformer, publicado en SciELO Chile (Ingeniare), con métricas de referencia (~0.75 de exactitud en LSCh vs ~0.94 en el corpus argentino LSA64, lo que indica que LSCh todavía tiene pocos datos comparado a otras lenguas de señas de la región — oportunidad y advertencia).
  - Proyectos estudiantiles (USM y UdeC) que usan **visión por computador + detección de landmarks de la mano y rostro**, en dos etapas: (1) extracción de puntos clave, (2) clasificación con un segundo modelo liviano. Un dato de arquitectura valioso: uno de estos proyectos logra que **toda la base de reconocimiento pese ~10 MB**, porque en vez de procesar imágenes pesadas, trabaja con **coordenadas (landmarks) como texto/vectores** — mismo principio que debes adoptar tú (ver §5).
  - Existe un **dataset abierto en Roboflow** ("Lengua de señas chilena desde cero") con imágenes del alfabeto dactilológico, útil como punto de partida para el MVP de letras, aunque debe ampliarse y validarse con hablantes nativos sordos antes de producción.
  - La **Fundación Lengua de Señas Chilena** dicta cursos certificados y trabaja en inclusión: es un actor clave a considerar para validación lingüística, banco de señas y pruebas de usabilidad con usuarios reales.
- **Tecnología de tracking de manos madura y gratuita**: MediaPipe (ahora "Google AI Edge", con la API "Hand Landmarker" y "Gesture Recognizer") detecta 21 puntos clave 3D por mano en tiempo real, corre en celulares de gama media, y tiene guías oficiales para Android, iOS, Python y Web. Es el enfoque más probado en la literatura de reconocimiento de lengua de señas por landmarks (incluyendo el paper chileno citado arriba).
- **Frameworks multiplataforma con soporte real de cámara + ML on-device en 2026**:
  - **React Native** con `react-native-vision-camera` (v5, sobre Nitro Modules) + `react-native-fast-tflite` permite Frame Processors en tiempo real que corren modelos TFLite directamente sobre los frames de cámara, con aceleración GPU/CoreML/NNAPI, sin escribir código nativo extenso.
  - **Flutter** es la otra opción validada (existen apps de referencia tipo "ISLE" — reconocimiento de señas con MediaPipe/ML Kit + TensorFlow Lite en Flutter, aunque limitadas a Android en sus versiones demo).
  - Para escritorio, la vía más pragmática **no es reinventar una app nativa distinta**, sino reusar la mayor parte de la lógica: Electron/Tauri (si vas con stack web) o Kotlin Multiplatform/.NET MAUI si prefieres nativo compartido. La recomendación de este prompt es **React Native + React Native for Windows/macOS o un shell Tauri para desktop**, manteniendo el modelo de IA (TFLite) y la lógica de negocio en un paquete compartido.
  - Alternativa on-device más nueva a evaluar (no obligatoria): motores híbridos tipo "Cactus" que ofrecen SDKs unificados para Swift/Kotlin/Flutter/React Native con fallback a nube, útiles si más adelante se agregan modelos de lenguaje más grandes (p. ej. para mejorar gramática LSCh→español).

**Conclusión de este análisis**: la arquitectura ganadora, validada tanto por la literatura académica chilena como por el ecosistema de frameworks 2026, es **landmarks primero, imagen nunca cruda al modelo final** (privacidad + tamaño + rendimiento), con **React Native + Vision Camera + MediaPipe/TFLite** como stack multiplataforma principal.

---

## 3. PRINCIPIO NO NEGOCIABLE: DISEÑO CON LA COMUNIDAD SORDA

Aplica en cada fase el principio *"nada sobre nosotros sin nosotros"*:

- Todo banco de señas y todo dataset de entrenamiento debe ser validado por **personas sordas nativas de LSCh e intérpretes certificados** (idealmente vía la Fundación LSCh u otras organizaciones de la comunidad sorda chilena), no solo por estudiantes de ingeniería reproduciendo señas de memoria.
- Las pruebas de usabilidad (UX testing) deben incluir usuarios sordos reales en cada fase, no solo al final.
- El equipo debe incluir o consultar a un **lingüista de LSCh / intérprete certificado** como rol permanente, no como consultoría puntual (ver §7, roles).
- Evita go **"español señado"** o glosas artificiales impuestas por conveniencia técnica; el objetivo final es respetar la gramática real de la LSCh.

---

## 4. ALCANCE FUNCIONAL DEL MVP Y VERSIONES SIGUIENTES

### MVP (Fase 1 — validar el reconocimiento básico)
- Reconocimiento del **alfabeto dactilológico completo de LSCh** (deletreo letra por letra) en tiempo real vía cámara.
- Reconocimiento de un **set inicial de 20–50 señas/palabras de uso frecuente** (saludos, agradecimientos, números, palabras de necesidad básica: "ayuda", "baño", "gracias", "por favor", "sí", "no", etc.), elegidas junto a la comunidad sorda, no arbitrariamente.
- Salida como **texto en pantalla, en tiempo real**, con reconstrucción de palabras a partir de letras deletreadas (autocompletado opcional).
- Botón/gesto para **reproducir el texto acumulado como voz** (texto-a-voz nativo del dispositivo).
- Funciona **100% offline** para el reconocimiento (modelo on-device), para no depender de conectividad ni exponer video del usuario a servidores por defecto.
- Disponible como app **Android e iOS** primero (mayor impacto y facilidad de despliegue); versión de **escritorio (Windows/macOS/Linux)** en paralelo o inmediatamente después, reutilizando el mismo modelo y la mayor parte de la UI.

### Fase 2 — palabras y frases cortas continuas
- Reconocimiento de **secuencias de señas continuas** (no solo signos aislados), usando modelos temporales (Transformer/LSTM sobre secuencias de landmarks), como en el enfoque del paper LSCh citado en §2.
- Incorporar **expresiones faciales** (Face Landmarker/Face Mesh) como parte de la gramática (la LSCh, como otras lenguas de señas, usa cejas, mirada y boca con función gramatical, no solo emocional).
- Mejorar la reconstrucción sintáctica LSCh→español con un módulo de **post-procesamiento de lenguaje** (no un traductor palabra-por-palabra).

### Fase 3 — features de calidad de vida
- Historial de conversación, modo "conversación" con dos paneles (persona sorda firma → texto/voz; persona oyente habla → texto en pantalla, usando reconocimiento de voz nativo del dispositivo, para hacerlo bidireccional aunque sin avatar de señas).
- Modo de baja luz / ajuste de encuadre asistido ("acerca tus manos", "hay poca luz").
- Perfiles de usuario y ajuste de sensibilidad/velocidad de firma.
- Exportar conversación como texto o audio.

### Fase futura (opcional, mucho más compleja — no comprometerse en el pitch inicial)
- Texto/voz → **avatar 3D que interpreta en LSCh** (traducción inversa). Es un problema de investigación mucho mayor (generación de movimiento, no clasificación) y no debe prometerse como parte del alcance inicial.

---

## 5. ARQUITECTURA TÉCNICA

### 5.1 Principio de diseño: pipeline de 3 etapas, todo on-device

```
Cámara (frame RGB)
   │
   ▼
[1] EXTRACCIÓN DE LANDMARKS
    MediaPipe Hand Landmarker (21 puntos x mano, hasta 2 manos)
    + MediaPipe Face Landmarker (rasgos faciales gramaticales)
    + (opcional) Pose Landmarker (posición de hombros/torso, relevante en LSCh)
   │  → vector numérico ligero (x,y,z por punto), NO se envía la imagen a ningún servidor
   ▼
[2] MODELO DE RECONOCIMIENTO DE SEÑAS
    - Señas estáticas (letras): clasificador liviano (MLP/SVM) sobre landmarks de un frame.
    - Señas dinámicas/palabras: modelo temporal (Transformer ligero o LSTM/GRU) sobre
      una ventana deslizante de N frames de landmarks.
    - Exportado a TensorFlow Lite (.tflite) para correr con react-native-fast-tflite /
      TFLite nativo en Android/iOS, y con TFLite/ONNX Runtime en desktop.
   │  → gloss/etiqueta (ej. "A", "GRACIAS", "AYUDA")
   ▼
[3] POST-PROCESAMIENTO LINGÜÍSTICO
    - Reconstrucción de palabras desde deletreo (letra→palabra con diccionario/autocompletado).
    - Reordenamiento gramatical LSCh→español para secuencias (fase 2+), no concatenación literal.
    - Salida final: texto en español natural.
   │
   ▼
[4] SALIDA
    - Texto en pantalla (siempre).
    - Texto-a-voz vía motor nativo del dispositivo (Android TextToSpeech / iOS AVSpeechSynthesizer /
      Web Speech API o librería equivalente en desktop) — no dependas de una nube de voz por defecto,
      para que funcione offline; deja un motor de voz más natural (nube) como opción configurable.
```

**Por qué landmarks y no imágenes crudas al clasificador final:** reduce drásticamente el tamaño del modelo (referencia real: proyectos chilenos similares logran bases de reconocimiento de ~10 MB), permite correr en tiempo real en celulares de gama media, y **protege la privacidad** porque el video de la cámara no necesita salir del dispositivo ni almacenarse — solo se procesan coordenadas numéricas efímeras.

### 5.2 Stack multiplataforma recomendado

| Capa | Elección recomendada | Alternativa | Justificación |
|---|---|---|---|
| Apps Android/iOS | **React Native** + `react-native-vision-camera` (v5) para captura y frame processors en tiempo real | Flutter + camera plugin + MediaPipe/ML Kit | RN tiene el pipeline de cámara→ML en tiempo real más maduro documentado hoy (Vision Camera + `react-native-fast-tflite`), con un solo código base para ambos móviles |
| Extracción de landmarks | MediaPipe Tasks (Hand Landmarker / Face Landmarker), vía binding nativo expuesto como Frame Processor plugin | Google ML Kit (solo si se prioriza integración Android nativa) | Es multiplataforma oficial (Android, iOS, Web, Python), con modelo entrenado en ~30K imágenes reales + sintéticas, y es el estándar usado en la literatura de reconocimiento de señas |
| Modelo de clasificación de señas | TensorFlow Lite (.tflite), cargado con `react-native-fast-tflite` (GPU delegate en Android, CoreML delegate en iOS) | ONNX Runtime Mobile | Integración directa y ya probada con Vision Camera; ecosistema y tooling de conversión más grande |
| App de escritorio | React Native for Windows/macOS, o shell Tauri/Electron reutilizando la lógica de negocio en TypeScript compartido, con la cámara vía `getUserMedia` (web) o binding nativo, y el modelo vía TFLite/ONNX Runtime en Node/Rust | App nativa separada en Python (prototipo rápido con OpenCV + MediaPipe Python, útil para investigación/dataset, no como producto final) | Minimiza duplicar UI y lógica de dominio; deja el pipeline de IA como paquete compartido |
| Texto-a-voz | APIs nativas del SO (Android `TextToSpeech`, iOS `AVSpeechSynthesizer`, Web Speech API / librería TTS de escritorio) | Motor de voz en la nube (ej. servicios de síntesis neuronal) como mejora opcional configurable | Evita costos/latencia/dependencia de red por defecto; deja la opción de voz más natural como upgrade |
| Backend (opcional, no crítico para MVP) | Servicio mínimo para: cuentas de usuario, sincronización de historial, telemetría de mejora del modelo (con consentimiento explícito), distribución de actualizaciones del modelo | — | El reconocimiento en sí NO debe requerir backend; el backend es para features de valor agregado, nunca un bloqueante de la función principal |

### 5.3 Organización del repositorio (monorepo)

```
señascl/
├── apps/
│   ├── mobile/            # React Native (Android + iOS)
│   ├── desktop/           # Shell RN-Windows/macOS o Tauri
│   └── web-demo/          # Demo liviana en navegador (opcional, útil para pruebas rápidas)
├── packages/
│   ├── core-ml/           # Wrapper unificado: carga de modelo TFLite, pre/post-procesamiento
│   ├── landmarks/          # Integración MediaPipe (hand/face/pose) como frame processors
│   ├── nlp-lsch/           # Reconstrucción léxica/gramatical LSCh→español, diccionario
│   ├── tts/                # Abstracción de texto-a-voz multiplataforma
│   ├── ui-kit/             # Componentes de diseño compartidos (ver §6 UX)
│   └── shared-types/       # Tipos TypeScript compartidos
├── ml/
│   ├── datasets/           # Scripts de captura/etiquetado de dataset (NO subir videos de personas sin consentimiento)
│   ├── training/           # Notebooks/scripts de entrenamiento (Python, TensorFlow/PyTorch)
│   ├── export/             # Conversión a TFLite/ONNX + cuantización
│   └── eval/               # Métricas, matrices de confusión, pruebas con hablantes nativos
├── docs/
│   ├── product/            # Brief, personas, historias de usuario
│   ├── architecture/        # ADRs (decisiones de arquitectura)
│   ├── accessibility/       # Checklist WCAG + pautas específicas de LSCh
│   └── ethics-data/         # Consentimiento informado, política de datos biométricos
└── .github/workflows/       # CI: lint, tests, build por plataforma
```

---

## 6. UX, USABILIDAD Y ACCESIBILIDAD (obligatorio, no "nice to have")

Diseña siguiendo estos criterios concretos:

1. **Feedback en tiempo real y honesto**: muestra un indicador de confianza/calidad del reconocimiento (ej. "no se detectan manos claramente", "acércate más a la cámara", "hay poca luz"). Nunca muestres una traducción sin indicar cuándo el sistema tiene baja certeza.
2. **Accesibilidad visual primero, pero no exclusiva**: el usuario principal (persona sorda) depende 100% de la interfaz visual — usa alto contraste, texto grande configurable, iconografía clara, evita depender de sonidos como única señal de estado (usa también vibración y cambios visuales).
3. **Diseño para uso con las manos ocupadas firmando**: minimiza la necesidad de tocar la pantalla mientras se está haciendo una seña. Usa temporizadores automáticos, gestos simples (ej. mantener la mano en reposo) o un botón grande de una sola pulsación para iniciar/pausar, alcanzable con el pulgar en sostenido de una mano.
4. **Encuadre asistido**: guía visual (silueta/rectángulo) que indique dónde debe ubicarse el usuario respecto a la cámara, con corrección si está muy cerca/lejos/mal iluminado — esto es UX crítica en reconocimiento de gestos, no un detalle estético.
5. **Progresividad y aprendizaje**: en el onboarding, enseña con ejemplos en video reales (grabados con hablantes nativos sordos) qué señas reconoce el sistema hoy, y sé transparente sobre sus límites ("por ahora reconoce el alfabeto y 40 palabras").
6. **Modo bidireccional simple sin sobreprometer**: para la conversación con oyentes, usa reconocimiento de voz nativo del dispositivo mostrado como texto grande, dejando claro que esto es distinto (y más simple) que un traductor de texto a señas.
7. **Privacidad visible**: indica explícitamente en la UI cuándo la cámara está activa, cuándo el procesamiento es local (por defecto) y pide consentimiento explícito y revocable si alguna vez se ofrece enviar datos a un servidor (p. ej. para mejorar el modelo).
8. **Cumple lineamientos WCAG 2.2 AA como piso mínimo** en las apps (contraste, tamaños de toque ≥44px, navegación por lector de pantalla para las partes de la UI que no dependen de la cámara, soporte de "reduce motion").
9. **Pruebas de usabilidad con usuarios sordos reales** en cada iteración (no asumir que un equipo oyente puede validar por sí solo si la interfaz es clara o si el reconocimiento es útil en la práctica).
10. **Rendimiento percibido**: apunta a latencia de reconocimiento por debajo de ~200 ms para que se sienta "en tiempo real"; si el hardware no lo permite, comunica claramente el estado de procesamiento (no dejar la UI "congelada").

---

## 7. ROLES DEL EQUIPO

| Rol | Responsabilidad clave |
|---|---|
| **Product Manager / Owner** | Define alcance por fases, prioriza con base en impacto real para la comunidad sorda, gestiona relación con Fundación LSCh u organizaciones aliadas |
| **Lingüista LSCh / Intérprete certificado** (rol permanente, no consultoría puntual) | Valida corpus de señas, gramática, evita "español señado", revisa cada set de datos y cada traducción de UI |
| **Consultores/testers sordos** (community advisory) | Prueban cada iteración, dan feedback de usabilidad real y de fidelidad lingüística |
| **ML Engineer / Computer Vision** | Diseña y entrena el pipeline de landmarks + clasificación temporal, cuantiza y exporta modelos a TFLite/ONNX |
| **Mobile Engineer (React Native)** | Implementa apps Android/iOS, integra Vision Camera + frame processors + TFLite |
| **Desktop Engineer** | Adapta el shell de escritorio reutilizando la lógica compartida |
| **Backend Engineer** (part-time/fase 2+) | Servicios opcionales: cuentas, sync, distribución de modelos, telemetría con consentimiento |
| **UX/UI Designer especializado en accesibilidad** | Diseña interacción cámara-en-vivo, feedback de confianza, sistema de diseño de alto contraste |
| **QA / Accessibility tester** | Verifica WCAG, prueba en dispositivos de gama baja/media, prueba con distintas condiciones de luz/piel/mano |
| **Data/Ethics lead** | Redacta consentimiento informado, política de datos biométricos, cumplimiento de la Ley 19.628 y Ley 21.719 de protección de datos personales en Chile |

---

## 8. DATOS, ÉTICA Y PRIVACIDAD

- Los **landmarks de manos/rostro son datos biométricos**: trátalos con el mismo cuidado que datos sensibles de salud, aunque el procesamiento sea local. Documenta política de datos clara y visible.
- Si se recolectan videos para entrenar/mejorar el modelo, **consentimiento informado explícito, específico y revocable** de cada persona grabada (y de sus representantes si son menores de edad), indicando uso, tiempo de retención y si se compartirán con terceros (universidades, papers, etc.).
- Prioriza que el reconocimiento en producción **no necesite subir video a un servidor**; si en el futuro se ofrece un modo "mejorar el modelo con mis datos", debe ser **opt-in**, nunca por defecto.
- Cita y da crédito a los datasets/investigación académica chilena existente (SciELO/Ingeniare, proyectos USM/UdeC, dataset Roboflow) en vez de tratarlos como si no existieran; evalúa colaborar en vez de duplicar esfuerzo desde cero.

---

## 9. MÉTRICAS DE ÉXITO

- **Exactitud de reconocimiento** por seña/letra (matriz de confusión), reportada por separado para alfabeto vs. palabras, y por condiciones (buena/mala luz, manos de distinto tono de piel, zurdos vs diestros — el paper LSCh de referencia mostró que un solo modelo puede aprender de señantes zurdos y diestros si el dataset lo contempla).
- **Latencia end-to-end** (frame capturado → texto mostrado).
- **Tamaño del modelo/app** (referencia de la industria local: ~10 MB solo para el paquete de reconocimiento es alcanzable con el enfoque de landmarks).
- **Usabilidad real medida con usuarios sordos** (tasa de tareas completadas, SUS score o equivalente), no solo métricas técnicas del modelo.
- **Tasa de uso del modo voz** y de la app en general en el tiempo (retención), como proxy de utilidad percibida.

---

## 10. ROADMAP SUGERIDO (alto nivel)

1. **Descubrimiento (2–4 semanas)**: alianza con Fundación LSCh u otra organización de la comunidad sorda; validar alcance del alfabeto + primeras 20–50 palabras; ADRs de arquitectura.
2. **Dataset y modelo v0 (4–8 semanas)**: capturar/curar landmarks para alfabeto + palabras iniciales con hablantes nativos; entrenar clasificador estático; exportar a TFLite.
3. **MVP móvil (6–10 semanas)**: app React Native con Vision Camera + modelo v0, salida texto + TTS, UX de encuadre y confianza.
4. **Piloto cerrado con usuarios sordos reales** y ciclo de iteración UX/modelo.
5. **Versión escritorio** reutilizando el core.
6. **Fase 2**: señas dinámicas/continuas + expresiones faciales gramaticales + post-procesamiento lingüístico.
7. **Fase 3**: modo conversación bidireccional, historial, mejoras de calidad de vida.
8. **Evaluación de fase futura** (avatar firmante) solo si el producto base ya está validado y financiado para ese salto de complejidad.

---

## 11. INSTRUCCIÓN FINAL PARA LA IA/EQUIPO QUE EJECUTE ESTE PROMPT

Cuando comiences a construir:

1. Empieza por el **monorepo y el paquete `core-ml`** con un modelo TFLite de placeholder (aunque sea entrenado con el dataset abierto de Roboflow como semilla), para validar el pipeline completo cámara→landmarks→clasificación→texto→voz de punta a punta antes de invertir en precisión del modelo.
2. No optimices precisión del modelo antes de que el **pipeline end-to-end y la UX de feedback en tiempo real funcionen** — es más valioso un MVP honesto sobre sus límites que un modelo "perfecto" sin producto usable alrededor.
3. En cada decisión de UX o de alcance, pregúntate: **¿esto lo validó o lo pediría una persona sorda usuaria de LSCh?** Si la respuesta no es clara, márcalo como pendiente de validación con la comunidad antes de dar por cerrada la decisión.
4. Documenta cada decisión de arquitectura como ADR en `docs/architecture/`, y cada supuesto lingüístico como nota en `docs/product/` para que el lingüista/intérprete LSCh lo revise.

---

*Fin del mega-prompt. Puedes copiar este documento completo en tu asistente de desarrollo, o pedir que se ejecute sección por sección (ej. "genera ahora el paquete `core-ml` según la sección 5" o "genera el boilerplate de `apps/mobile` según la sección 5.2").*
