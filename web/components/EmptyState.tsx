import { T } from '@/components/d4c/tokens';

interface EmptyStateProps {
  symbol?: string;   // unicode symbol, not emoji
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
}

export default function EmptyState({
  symbol = '◌',
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: `${T.space.xxl} ${T.space.lg}`,
      textAlign: 'center',
    }}>
      <div style={{
        fontSize: 32,
        color: T.text.tertiary,
        marginBottom: T.space.md,
        fontFamily: T.font.mono,
      }}>
        {symbol}
      </div>
      <h3 style={{
        fontSize: 16,
        fontWeight: 600,
        color: T.text.primary,
        margin: 0,
        fontFamily: T.font.display,
      }}>
        {title}
      </h3>
      {description && (
        <p style={{
          marginTop: T.space.xs,
          fontSize: 13,
          color: T.text.secondary,
          maxWidth: 360,
          lineHeight: 1.5,
        }}>
          {description}
        </p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          style={{
            marginTop: T.space.md,
            padding: `${T.space.sm} ${T.space.md}`,
            backgroundColor: T.accent.teal,
            color: T.text.inverse,
            border: 'none',
            borderRadius: T.radius.sm,
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: T.font.display,
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
