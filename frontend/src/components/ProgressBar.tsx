import React from 'react';

interface ProgressBarProps {
  progress: number; // 0-1
  complete?: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ progress, complete = false }) => {
  return (
    <div
      style={{
        height: '4px',
        background: 'var(--color-bg-secondary)',
        borderRadius: 'var(--radius-full)',
        overflow: 'hidden',
        maxWidth: '200px',
        margin: '0 auto',
      }}
    >
      <div
        style={{
          height: '100%',
          width: `${Math.min(100, progress * 100)}%`,
          background: complete ? 'var(--color-success)' : 'var(--color-accent)',
          borderRadius: 'var(--radius-full)',
          transition: 'width 50ms linear, background 250ms ease',
        }}
      />
    </div>
  );
};
