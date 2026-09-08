import React from 'react';
import { colors } from './theme';

interface StatusBannerProps {
  type: 'info' | 'warning' | 'error';
  message: string;
  onDismiss?: () => void;
}

export const StatusBanner: React.FC<StatusBannerProps> = ({
  type,
  message,
  onDismiss,
}) => {
  const bgMap = {
    info: colors.primary,
    warning: colors.warning,
    error: colors.error,
  };

  return (
    <div
      style={{
        padding: '10px 16px',
        backgroundColor: bgMap[type],
        color: colors.white,
        borderRadius: 8,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: 14,
        fontWeight: 500,
      }}
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          style={{
            background: 'none',
            border: 'none',
            color: colors.white,
            cursor: 'pointer',
            fontSize: 18,
            padding: '0 4px',
          }}
        >
          ×
        </button>
      )}
    </div>
  );
};
