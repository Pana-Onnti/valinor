'use client';
import { useState, useEffect } from 'react';
import { T } from '@/components/d4c/tokens';

export default function ConnectionStatusBadge() {
  const [status, setStatus] = useState<'checking' | 'ok' | 'error'>('checking');

  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/health`, {
          signal: AbortSignal.timeout(3000),
        });
        setStatus(r.ok ? 'ok' : 'error');
      } catch {
        setStatus('error');
      }
    };
    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  if (status === 'checking') return null;

  const ok = status === 'ok';
  const dotColor = ok ? T.accent.teal : T.accent.red;

  return (
    <div style={{
      position: 'fixed',
      bottom: T.space.md,
      right: T.space.md,
      zIndex: 50,
      display: 'flex',
      alignItems: 'center',
      gap: T.space.xs,
      backgroundColor: T.bg.elevated,
      border: `1px solid ${dotColor}40`,
      borderRadius: '999px',
      padding: '4px 12px',
      fontFamily: T.font.mono,
      fontSize: 11,
      fontWeight: 500,
      color: dotColor,
    }}>
      <div style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        backgroundColor: dotColor,
        animation: ok ? 'none' : 'pulse 1.5s ease-in-out infinite',
      }} />
      {ok ? 'API conectada' : 'API desconectada'}
    </div>
  );
}
