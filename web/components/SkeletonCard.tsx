import { T } from '@/components/d4c/tokens';

interface SkeletonCardProps {
  lines?: number;
  hasHeader?: boolean;
  hasStats?: boolean;
  style?: React.CSSProperties;
}

const shimmer: React.CSSProperties = {
  backgroundColor: T.bg.elevated,
  borderRadius: 4,
  animation: 'pulse 1.5s ease-in-out infinite',
};

const LINE_WIDTHS = ['100%', '80%', '60%', '67%', '50%'];

export default function SkeletonCard({
  lines = 3,
  hasHeader = true,
  hasStats = false,
  style,
}: SkeletonCardProps) {
  return (
    <div style={{
      backgroundColor: T.bg.card,
      border: T.border.card,
      borderRadius: T.radius.md,
      padding: T.space.lg,
      ...style,
    }}>
      {hasHeader && (
        <div style={{ marginBottom: T.space.md }}>
          <div style={{ ...shimmer, height: 14, width: '67%' }} />
        </div>
      )}

      {hasStats && (
        <div style={{ display: 'flex', gap: T.space.md, marginBottom: T.space.md }}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <div style={{ ...shimmer, height: 32, width: 64 }} />
              <div style={{ ...shimmer, height: 10, width: 48 }} />
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} style={{ ...shimmer, height: 12, width: LINE_WIDTHS[i % LINE_WIDTHS.length] }} />
        ))}
      </div>
    </div>
  );
}
