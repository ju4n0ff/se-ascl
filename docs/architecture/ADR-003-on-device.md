# ADR-003: Procesamiento 100% on-device por defecto

## Estado: Aceptado

## Contexto
Los usuarios sordos necesitan una app que funcione sin dependencia de conectividad y que proteja su privacidad (video de cámara como dato biométrico sensible).

## Decisión
El reconocimiento de señas se ejecuta completamente en el dispositivo:
- Modelo TFLite local
- Landmarks procesados en device
- Texto-a-voz usando motor nativo del SO

## Excepciones
- Backend opcional para: cuentas, sync de historial, distribución de actualizaciones del modelo
- Nunca subir video a servidores
- Modo "mejorar modelo con mis datos" debe ser opt-in explícito

## Consecuencias
- Funciona offline (crítico para uso en zonas sin conectividad)
- Privacidad por diseño
- Latencia mínima (sin round-trip de red)
