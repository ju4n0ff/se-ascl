export const colors = {
  primary: '#1a73e8',
  primaryDark: '#1557b0',
  background: '#0d1117',
  surface: '#161b22',
  surfaceLight: '#21262d',
  text: '#f0f6fc',
  textSecondary: '#8b949e',
  success: '#3fb950',
  warning: '#d29922',
  error: '#f85149',
  white: '#ffffff',
  black: '#000000',
  overlay: 'rgba(0, 0, 0, 0.6)',
} as const;

export const theme = {
  colors,
  spacing: {
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
  },
  fontSize: {
    sm: 14,
    md: 16,
    lg: 20,
    xl: 28,
    xxl: 36,
  },
  borderRadius: {
    sm: 4,
    md: 8,
    lg: 16,
    full: 9999,
  },
  minTouchTarget: 44,
} as const;
