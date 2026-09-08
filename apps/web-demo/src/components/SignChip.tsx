import React from 'react';

interface SignChipProps {
  letter: string;
  confidence?: number;
  animate?: boolean;
}

export const SignChip: React.FC<SignChipProps> = ({
  letter,
  confidence,
  animate = true,
}) => {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        background: 'var(--color-bg-card)',
        padding: 'var(--space-3) var(--space-5)',
        borderRadius: 'var(--radius-xl)',
        boxShadow: 'var(--shadow-md)',
        animation: animate ? 'chipEnter 0.35s cubic-bezier(0.34, 1.56, 0.64, 1)' : 'none',
      }}
    >
      <span
        style={{
          fontSize: 'var(--font-size-4xl)',
          fontWeight: 700,
          color: 'var(--color-accent)',
          minWidth: '56px',
          textAlign: 'center',
          fontFamily: 'var(--font-family)',
        }}
      >
        {letter}
      </span>
      {confidence !== undefined && (
        <span
          style={{
            fontSize: 'var(--font-size-xs)',
            color: 'var(--color-text-tertiary)',
            fontFamily: 'var(--font-family)',
          }}
        >
          {Math.round(confidence * 100)}%
        </span>
      )}
    </div>
  );
};
