import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'success' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  icon,
  children,
  className = '',
  ...props
}) => {
  const baseStyles: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    fontFamily: 'var(--font-family)',
    fontWeight: 600,
    border: 'none',
    cursor: 'pointer',
    transition: 'all 250ms cubic-bezier(0.4, 0, 0.2, 1)',
    textDecoration: 'none',
    lineHeight: 1.2,
  };

  const sizeStyles: Record<string, React.CSSProperties> = {
    sm: {
      minHeight: '36px',
      fontSize: 'var(--font-size-sm)',
      padding: '8px 16px',
      borderRadius: 'var(--radius-md)',
    },
    md: {
      minHeight: '48px',
      fontSize: 'var(--font-size-base)',
      padding: '12px 24px',
      borderRadius: 'var(--radius-lg)',
    },
    lg: {
      minHeight: '56px',
      fontSize: 'var(--font-size-lg)',
      padding: '16px 32px',
      borderRadius: 'var(--radius-xl)',
    },
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    primary: {
      background: 'var(--color-accent-gradient)',
      color: 'var(--color-text-on-accent)',
      boxShadow: 'var(--shadow-md), var(--shadow-glow)',
    },
    secondary: {
      background: 'var(--color-bg-secondary)',
      color: 'var(--color-text-primary)',
      border: '1px solid var(--color-border-light)',
    },
    success: {
      background: 'var(--color-success)',
      color: 'var(--color-text-inverse)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--color-text-secondary)',
    },
  };

  return (
    <button
      style={{
        ...baseStyles,
        ...sizeStyles[size],
        ...variantStyles[variant],
      }}
      onMouseEnter={(e) => {
        if (variant === 'primary') {
          e.currentTarget.style.boxShadow = 'var(--shadow-lg), 0 0 30px rgba(232, 114, 92, 0.25)';
          e.currentTarget.style.transform = 'translateY(-1px)';
        } else if (variant === 'secondary') {
          e.currentTarget.style.background = 'var(--color-border-light)';
        }
      }}
      onMouseLeave={(e) => {
        if (variant === 'primary') {
          e.currentTarget.style.boxShadow = 'var(--shadow-md), var(--shadow-glow)';
          e.currentTarget.style.transform = 'translateY(0)';
        } else if (variant === 'secondary') {
          e.currentTarget.style.background = 'var(--color-bg-secondary)';
        }
      }}
      onMouseDown={(e) => {
        e.currentTarget.style.transform = 'translateY(0) scale(0.98)';
      }}
      onMouseUp={(e) => {
        e.currentTarget.style.transform = 'translateY(0) scale(1)';
      }}
      className={className}
      {...props}
    >
      {icon && <span style={{ display: 'flex', alignItems: 'center' }}>{icon}</span>}
      {children}
    </button>
  );
};
