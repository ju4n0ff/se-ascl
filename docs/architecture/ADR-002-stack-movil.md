# ADR-002: React Native + Vision Camera como stack móvil principal

## Estado: Aceptado

## Contexto
Se necesita un framework multiplataforma que soporte cámara en tiempo real con frame processors y ejecución de modelos ML on-device.

## Decisión
Usar React Native con:
- `react-native-vision-camera` v5 (Nitro Modules) para frame processors en tiempo real
- `react-native-fast-tflite` para ejecutar modelos TFLite con aceleración GPU/CoreML/NNAPI
- TypeScript como lenguaje compartido entre mobile, desktop y packages

## Alternativas Consideradas
- **Flutter:** Buena opción, pero el ecosistema de cámara→ML en tiempo real es menos maduro
- **App nativa separada:** Más trabajo, duplica lógica de negocio

## Consecuencias
- Un solo código base para Android e iOS
- Acceso a frame processors nativos sin código extenso
- Desktop vía Tauri reutilizando lógica de negocio TypeScript
