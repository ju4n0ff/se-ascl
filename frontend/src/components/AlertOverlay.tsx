import React from 'react';

interface AlertOverlayProps {
  icon: string;
  message: string;
  visible: boolean;
}

export const AlertOverlay: React.FC<AlertOverlayProps> = ({ icon, message, visible }) => {
  if (!visible) return null;

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: 'var(--color-bg-overlay)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--space-4)',
        borderRadius: 'var(--radius-3xl)',
        zIndex: 20,
        animation: 'fadeIn 250ms ease-out',
      }}
    >
      <span
        style={{
          fontSize: '48px',
          animation: 'sway 2s ease-in-out infinite',
        }}
        role="img"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span
        style={{
          color: 'var(--color-text-inverse)',
          fontSize: 'var(--font-size-lg)',
          fontWeight: 600,
          textAlign: 'center',
          maxWidth: '280px',
          fontFamily: 'var(--font-family)',
        }}
      >
        {message}
      </span>
    </div>
  );
};
