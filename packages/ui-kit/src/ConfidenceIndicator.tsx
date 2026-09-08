import React from 'react';
import { ConfidenceLevel } from '@senascl/shared-types';
import { colors } from './theme';

interface ConfidenceIndicatorProps {
  level: ConfidenceLevel;
  message?: string;
}

export const ConfidenceIndicator: React.FC<ConfidenceIndicatorProps> = ({
  level,
  message,
}) => {
  const colorMap: Record<ConfidenceLevel, string> = {
    [ConfidenceLevel.HIGH]: colors.success,
    [ConfidenceLevel.MEDIUM]: colors.warning,
    [ConfidenceLevel.LOW]: colors.error,
  };

  const labelMap: Record<ConfidenceLevel, string> = {
    [ConfidenceLevel.HIGH]: 'Buena detección',
    [ConfidenceLevel.MEDIUM]: 'Detección regular',
    [ConfidenceLevel.LOW]: 'Detección baja',
  };

  return (
    <div
      style={{
        padding: '8px 16px',
        borderRadius: 8,
        backgroundColor: colorMap[level],
        color: colors.white,
        fontSize: 14,
        fontWeight: 600,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: colors.white,
        }}
      />
      {message || labelMap[level]}
    </div>
  );
};
