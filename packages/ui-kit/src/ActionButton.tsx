import React from 'react';
import { colors, theme } from './theme';

interface ActionButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean;
  icon?: React.ReactNode;
}

export const ActionButton: React.FC<ActionButtonProps> = ({
  label,
  onClick,
  variant = 'primary',
  disabled = false,
  icon,
}) => {
  const bgColorMap = {
    primary: colors.primary,
    secondary: colors.surfaceLight,
    danger: colors.error,
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        minHeight: theme.minTouchTarget,
        padding: '12px 24px',
        backgroundColor: bgColorMap[variant],
        color: colors.white,
        border: 'none',
        borderRadius: theme.borderRadius.lg,
        fontSize: theme.fontSize.lg,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        transition: 'opacity 0.2s, transform 0.1s',
      }}
    >
      {icon}
      {label}
    </button>
  );
};
