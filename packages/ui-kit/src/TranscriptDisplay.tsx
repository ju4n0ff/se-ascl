import React from 'react';
import { TranscriptEntry } from '@senascl/shared-types';
import { colors } from './theme';

interface TranscriptDisplayProps {
  entries: TranscriptEntry[];
  isLive?: boolean;
}

export const TranscriptDisplay: React.FC<TranscriptDisplayProps> = ({
  entries,
  isLive = false,
}) => {
  return (
    <div
      style={{
        flex: 1,
        padding: 16,
        backgroundColor: colors.surface,
        borderRadius: 12,
        overflow: 'auto',
        minHeight: 120,
      }}
    >
      {entries.length === 0 ? (
        <p
          style={{
            color: colors.textSecondary,
            textAlign: 'center',
            margin: 0,
            padding: 24,
            fontSize: 16,
          }}
        >
          {isLive ? 'Esperando señas...' : 'No hay transcripciones aún'}
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {entries.map((entry) => (
            <div
              key={entry.id}
              style={{
                padding: '8px 12px',
                backgroundColor: colors.surfaceLight,
                borderRadius: 8,
                fontSize: 18,
                lineHeight: 1.5,
                color: colors.text,
              }}
            >
              {entry.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
