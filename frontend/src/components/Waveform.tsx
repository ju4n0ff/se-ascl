import React from 'react';

interface WaveformProps {
  isPlaying: boolean;
  barCount?: number;
}

export const Waveform: React.FC<WaveformProps> = ({ isPlaying, barCount = 5 }) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '3px',
        height: '24px',
      }}
    >
      {Array.from({ length: barCount }).map((_, i) => (
        <div
          key={i}
          style={{
            width: '3px',
            height: isPlaying ? undefined : '4px',
            background: 'var(--color-accent)',
            borderRadius: 'var(--radius-full)',
            animation: isPlaying
              ? `waveform 0.8s ease-in-out ${i * 0.1}s infinite`
              : 'none',
            minHeight: '4px',
            maxHeight: isPlaying ? '16px' : '4px',
          }}
        />
      ))}
    </div>
  );
};
