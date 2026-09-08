// SeñasCL Design Tokens
// Based on the visual design mega-prompt

export const tokens = {
  color: {
    // Light mode (default)
    light: {
      // Base
      bgPrimary: '#FAFAF8',        // Warm off-white (not pure white)
      bgSecondary: '#F3F2EF',      // Slightly warmer gray
      bgCard: '#FFFFFF',            // Card background
      bgOverlay: 'rgba(0, 0, 0, 0.4)',

      // Accent - Vibrant coral-orange for communication/connection
      accentPrimary: '#E8725C',    // Coral-orange
      accentPrimaryLight: '#F09A8A',
      accentPrimaryDark: '#C95A45',
      accentPrimaryGradient: 'linear-gradient(135deg, #E8725C 0%, #D4619A 100%)',

      // Accent secondary - Mint/turquoise for success
      accentSuccess: '#4ECDC4',    // Mint turquoise
      accentSuccessLight: '#7EDDD6',
      accentSuccessDark: '#36B5AD',

      // Warning - Amber/mustard (soft, not aggressive)
      accentWarning: '#E8A849',    // Warm amber
      accentWarningLight: '#F0C67A',
      accentWarningDark: '#C98E30',

      // Error - Red reserved only for real blocking errors
      accentError: '#E85A5A',      // Soft red
      accentErrorLight: '#F08A8A',
      accentErrorDark: '#C94545',

      // Text
      textPrimary: '#1A1A1A',      // Near-black (not pure black)
      textSecondary: '#6B6B6B',    // Medium gray
      textTertiary: '#9B9B9B',     // Light gray
      textInverse: '#FFFFFF',      // White text on colored backgrounds
      textOnAccent: '#FFFFFF',     // Text on accent colors

      // Borders
      borderLight: '#E8E6E3',      // Subtle warm border
      borderMedium: '#D1CEC9',     // Medium border

      // Shadows
      shadowSm: '0 1px 3px rgba(0, 0, 0, 0.06)',
      shadowMd: '0 4px 12px rgba(0, 0, 0, 0.08)',
      shadowLg: '0 8px 24px rgba(0, 0, 0, 0.10)',
      shadowGlow: '0 0 20px rgba(232, 114, 92, 0.15)',

      // Camera frame
      cameraFrame: 'rgba(232, 114, 92, 0.3)',
      cameraFrameActive: 'rgba(232, 114, 92, 0.6)',
    },

    // Dark mode
    dark: {
      bgPrimary: '#1A1B1E',        // Warm graphite (not pure black)
      bgSecondary: '#232428',      // Slightly lighter
      bgCard: '#2A2B2F',           // Card background
      bgOverlay: 'rgba(0, 0, 0, 0.6)',

      accentPrimary: '#F09A8A',    // Lighter coral for dark bg
      accentPrimaryLight: '#F5B8AD',
      accentPrimaryDark: '#E8725C',
      accentPrimaryGradient: 'linear-gradient(135deg, #F09A8A 0%, #D88AB8 100%)',

      accentSuccess: '#7EDDD6',
      accentSuccessLight: '#A3E8E2',
      accentSuccessDark: '#4ECDC4',

      accentWarning: '#F0C67A',
      accentWarningLight: '#F5D9A3',
      accentWarningDark: '#E8A849',

      accentError: '#F08A8A',
      accentErrorLight: '#F5B3B3',
      accentErrorDark: '#E85A5A',

      textPrimary: '#F0F0EE',      // Warm white
      textSecondary: '#A0A0A0',    // Medium gray
      textTertiary: '#707070',     // Darker gray
      textInverse: '#1A1A1A',
      textOnAccent: '#FFFFFF',

      borderLight: '#3A3B3F',
      borderMedium: '#4A4B4F',

      shadowSm: '0 1px 3px rgba(0, 0, 0, 0.2)',
      shadowMd: '0 4px 12px rgba(0, 0, 0, 0.3)',
      shadowLg: '0 8px 24px rgba(0, 0, 0, 0.4)',
      shadowGlow: '0 0 20px rgba(240, 154, 138, 0.2)',

      cameraFrame: 'rgba(240, 154, 138, 0.3)',
      cameraFrameActive: 'rgba(240, 154, 138, 0.5)',
    },
  },

  // Typography - Humanist sans-serif
  typography: {
    fontFamily: "'Nunito', 'Segoe UI', system-ui, sans-serif",
    fontFamilyMono: "'JetBrains Mono', 'Fira Code', monospace",

    // Scale
    fontSize: {
      xs: '0.75rem',    // 12px
      sm: '0.875rem',   // 14px
      base: '1rem',     // 16px
      lg: '1.125rem',   // 18px
      xl: '1.25rem',    // 20px
      '2xl': '1.5rem',  // 24px
      '3xl': '1.875rem', // 30px
      '4xl': '2.25rem', // 36px
      '5xl': '3rem',    // 48px
    },

    fontWeight: {
      normal: 400,
      medium: 500,
      semibold: 600,
      bold: 700,
      extrabold: 800,
    },

    lineHeight: {
      tight: 1.2,
      normal: 1.5,
      relaxed: 1.65,
    },

    letterSpacing: {
      tight: '-0.01em',
      normal: '0',
      wide: '0.025em',
    },
  },

  // Spacing scale
  spacing: {
    px: '1px',
    0: '0',
    1: '0.25rem',   // 4px
    2: '0.5rem',    // 8px
    3: '0.75rem',   // 12px
    4: '1rem',      // 16px
    5: '1.25rem',   // 20px
    6: '1.5rem',    // 24px
    8: '2rem',      // 32px
    10: '2.5rem',   // 40px
    12: '3rem',     // 48px
    16: '4rem',     // 64px
    20: '5rem',     // 80px
    24: '6rem',     // 96px
  },

  // Border radius - squircle-like generous rounding
  radius: {
    none: '0',
    sm: '8px',
    md: '12px',
    lg: '16px',
    xl: '20px',
    '2xl': '24px',
    '3xl': '32px',
    full: '9999px',
  },

  // Animations
  animation: {
    // Durations
    durationFast: '150ms',
    durationNormal: '250ms',
    durationSlow: '350ms',
    durationSlower: '500ms',

    // Easings
    easingDefault: 'cubic-bezier(0.4, 0, 0.2, 1)',
    easingIn: 'cubic-bezier(0.4, 0, 1, 1)',
    easingOut: 'cubic-bezier(0, 0, 0.2, 1)',
    easingBounce: 'cubic-bezier(0.34, 1.56, 0.64, 1)', // Spring-like
    easingElastic: 'cubic-bezier(0.68, -0.55, 0.265, 1.55)',

    // Specific animations
    pulse: {
      duration: '2s',
      timing: 'ease-in-out',
      iteration: 'infinite',
    },
    breathe: {
      duration: '3s',
      timing: 'ease-in-out',
      iteration: 'infinite',
    },
    spin: {
      duration: '8s',
      timing: 'linear',
      iteration: 'infinite',
    },
  },

  // Z-index layers
  zIndex: {
    base: 0,
    dropdown: 100,
    sticky: 200,
    overlay: 300,
    modal: 400,
    popover: 500,
    toast: 600,
    tooltip: 700,
  },

  // Breakpoints
  breakpoints: {
    sm: '640px',
    md: '768px',
    lg: '1024px',
    xl: '1280px',
  },
} as const;

export type Tokens = typeof tokens;
