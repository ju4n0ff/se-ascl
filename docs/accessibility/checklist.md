# Accesibilidad — Checklist SeñasCL

## WCAG 2.2 AA (piso mínimo)

### Contraste
- [ ] Texto sobre fondo: ratio ≥ 4.5:1 (normal), ≥ 3:1 (grande)
- [ ] Componentes interactivos: ratio ≥ 3:1 contra fondo adyacente
- [ ] Indicadores de estado (confianza) usan color + texto/ícono (no solo color)

### Tamaños de toque
- [ ] Todos los botones interactivos ≥ 44×44 px
- [ ] Espaciado entre targets interactivos ≥ 8 px

### Texto
- [ ] Texto escalable sin pérdida de funcionalidad
- [ ] Tamaño mínimo de fuente: 14px
- [ ] Soporte para "reduce motion" del SO

### Navegación
- [ ] Toda la UI (excepto cámara) navegable por teclado/lector de pantalla
- [ ] Labels explícitos en todos los controles interactivos
- [ ] Focus visible en todos los elementos interactivos

### Cámara
- [ ] Feedback visual claro de estado de cámara (activa/inactiva)
- [ ] Indicador de confianza siempre visible cuando hay baja detección
- [ ] Nunca depender solo de audio para estado
- [ ] Vibración como feedback complementario

### Privacidad
- [ ] Indicador visible de cuándo la cámara está activa
- [ ] Consentimiento explícito antes de activar cámara
- [ ] Texto claro sobre procesamiento local vs nube
