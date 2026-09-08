import React from 'react';
import { colors } from './theme';

interface EncuadreGuideProps {
  isVisible: boolean;
  message?: string;
}

export const EncuadreGuide: React.FC<EncuadreGuideProps> = ({
  isVisible,
  message,
}) => {
  if (!isVisible) return null;

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          width: 280,
          height: 360,
          border: `3px dashed ${colors.primary}`,
          borderRadius: 16,
          opacity: 0.7,
        }}
      />
      {message && (
        <div
          style={{
            marginTop: 12,
            padding: '8px 16px',
            backgroundColor: colors.overlay,
            color: colors.white,
            borderRadius: 8,
            fontSize: 14,
            textAlign: 'center',
          }}
        >
          {message}
        </div>
      )}
    </div>
  );
};
