import React from 'react';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
}

export const Toggle: React.FC<ToggleProps> = ({
  checked,
  onChange,
  label,
  description,
  disabled = false,
}) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-4)',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {(label || description) && (
        <div style={{ flex: 1 }}>
          {label && (
            <div
              style={{
                fontSize: 'var(--font-size-base)',
                fontWeight: 600,
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-family)',
              }}
            >
              {label}
            </div>
          )}
          {description && (
            <div
              style={{
                fontSize: 'var(--font-size-sm)',
                color: 'var(--color-text-secondary)',
                marginTop: '2px',
                fontFamily: 'var(--font-family)',
              }}
            >
              {description}
            </div>
          )}
        </div>
      )}
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        style={{
          position: 'relative',
          width: '52px',
          height: '28px',
          background: checked ? 'var(--color-accent)' : 'var(--color-border-light)',
          borderRadius: 'var(--radius-full)',
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'background 250ms cubic-bezier(0.4, 0, 0.2, 1)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: '3px',
            left: checked ? '27px' : '3px',
            width: '22px',
            height: '22px',
            background: 'white',
            borderRadius: '50%',
            transition: 'left 250ms cubic-bezier(0.34, 1.56, 0.64, 1)',
            boxShadow: 'var(--shadow-sm)',
          }}
        />
      </button>
    </div>
  );
};
