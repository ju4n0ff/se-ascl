import React from 'react';

interface CardProps {
  children: React.ReactNode;
  variant?: 'default' | 'elevated' | 'outlined';
  padding?: 'sm' | 'md' | 'lg';
  className?: string;
}

export const Card: React.FC<CardProps> = ({
  children,
  variant = 'default',
  padding = 'md',
  className = '',
}) => {
  const paddingStyles: Record<string, string> = {
    sm: 'var(--space-4)',
    md: 'var(--space-6)',
    lg: 'var(--space-8)',
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    default: {
      background: 'var(--color-bg-card)',
      boxShadow: 'var(--shadow-md)',
    },
    elevated: {
      background: 'var(--color-bg-card)',
      boxShadow: 'var(--shadow-lg)',
    },
    outlined: {
      background: 'var(--color-bg-card)',
      border: '1px solid var(--color-border-light)',
    },
  };

  return (
    <div
      style={{
        borderRadius: 'var(--radius-xl)',
        padding: paddingStyles[padding],
        ...variantStyles[variant],
      }}
      className={className}
    >
      {children}
    </div>
  );
};
