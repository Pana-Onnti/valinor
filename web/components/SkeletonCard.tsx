interface SkeletonCardProps {
  lines?: number;
  hasHeader?: boolean;
  hasStats?: boolean;
  className?: string;
}

export default function SkeletonCard({
  lines = 3,
  hasHeader = true,
  hasStats = false,
  className = '',
}: SkeletonCardProps) {
  const lineWidths = ['w-full', 'w-4/5', 'w-3/5', 'w-2/3', 'w-1/2'];

  return (
    <div className={`rounded-xl border border-gray-200 bg-white p-6 animate-pulse ${className}`}>
      {hasHeader && (
        <div className="mb-4">
          <div className="h-4 w-2/3 bg-gray-200 rounded" />
        </div>
      )}

      {hasStats && (
        <div className="flex gap-4 mb-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col items-center gap-1.5">
              <div className="h-8 w-16 bg-gray-200 rounded" />
              <div className="h-2.5 w-12 bg-gray-200 rounded" />
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={`h-3 bg-gray-200 rounded ${lineWidths[i % lineWidths.length]}`}
          />
        ))}
      </div>
    </div>
  );
}
