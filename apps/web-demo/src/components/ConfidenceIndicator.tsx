import React from 'react';

interface ConfidenceIndicatorProps {
  level: 'high' | 'medium' | 'low';
  handsDetected: number;
  showLabel?: boolean;
}

export const ConfidenceIndicator: React.FC<ConfidenceIndicatorProps> = ({
  level,
  handsDetected,
  showLabel = true,
}) => {
  const config = {
    high: { color: 'var(--color-success)', label: 'Buena detección', emoji: '✓' },
    medium: { color: 'var(--color-warning)', label: 'Ajusta posición', emoji: '~' },
    low: { color: 'var(--color-error)', label: 'Sin detección', emoji: '!' },
  };

  const { color, label, emoji } = config[level];

  return (
    <div
      style={{
        position: 'absolute',
        top: '12px',
        left: '12px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        padding: '8px 14px',
        borderRadius: 'var(--radius-full)',
        backdropFilter: 'blur(8px)',
        zIndex: 15,
      }}
    >
      <span
        style={{
          width: '10px',
          height: '10px',
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: `0 0 8px ${color}`,
        }}
      />
      <span
        style={{
          color: 'var(--color-text-inverse)',
          fontSize: 'var(--font-size-sm)',
          fontWeight: 600,
          fontFamily: 'var(--font-family)',
        }}
      >
        {handsDetected} mano(s)
      </span>
      {showLabel && (
        <>
          <span
            style={{
              width: '1px',
              height: '14px',
              backgroundColor: 'rgba(255, 255, 255, 0.3)',
            }}
          />
          <span
            style={{
              color: 'var(--color-text-inverse)',
              fontSize: 'var(--font-size-xs)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span style={{ color }}>{emoji}</span>
            {label}
          </span>
        </>
      )}
    </div>
  );
};
