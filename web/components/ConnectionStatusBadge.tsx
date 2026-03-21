'use client';
import { useState, useEffect } from 'react';

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

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium shadow-md transition-all ${
        status === 'ok'
          ? 'bg-green-50 text-green-700 border border-green-200'
          : 'bg-red-50 text-red-700 border border-red-200'
      }`}
    >
      <div
        className={`h-1.5 w-1.5 rounded-full ${
          status === 'ok' ? 'bg-green-500' : 'bg-red-500 animate-pulse'
        }`}
      />
      {status === 'ok' ? 'API conectada' : 'API desconectada'}
    </div>
  );
}
