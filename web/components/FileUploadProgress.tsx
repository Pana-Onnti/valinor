'use client'

/**
 * FileUploadProgress.tsx
 * Individual file upload progress row used inside FileUpload.
 */

import { T } from '@/components/d4c/tokens'
import type { UploadFileState } from '@/lib/types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function FileIcon({ type }: { type: string }) {
  const ext = type.toLowerCase()
  const isExcel = ext === 'xlsx' || ext === 'xls'
  const color = isExcel ? T.accent.teal : T.accent.blue

  return (
    <div style={{
      width: 36,
      height: 36,
      borderRadius: T.radius.sm,
      backgroundColor: T.bg.elevated,
      border: `1px solid ${color}30`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    }}>
      <span style={{
        fontSize: 10,
        fontWeight: 700,
        color,
        fontFamily: T.font.mono,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
      }}>
        {ext === 'csv' ? 'CSV' : ext === 'xlsx' ? 'XLS' : ext.slice(0, 3).toUpperCase()}
      </span>
    </div>
  )
}

function StatusBadge({ status }: { status: UploadFileState['status'] }) {
  const CONFIG: Record<UploadFileState['status'], { label: string; color: string; bg: string }> = {
    pending:    { label: 'En cola',      color: T.text.tertiary,   bg: T.bg.elevated },
    uploading:  { label: 'Subiendo',     color: T.accent.blue,     bg: `${T.accent.blue}20` },
    processing: { label: 'Procesando',   color: T.accent.yellow,   bg: `${T.accent.yellow}20` },
    ready:      { label: 'Listo',        color: T.accent.teal,     bg: `${T.accent.teal}20` },
    error:      { label: 'Error',        color: T.accent.red,      bg: `${T.accent.red}20` },
  }
  const { label, color, bg } = CONFIG[status]

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: '100px',
      fontSize: 11,
      fontWeight: 600,
      color,
      backgroundColor: bg,
      fontFamily: T.font.display,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface FileUploadProgressProps {
  item: UploadFileState
  onRemove: () => void
}

export default function FileUploadProgress({ item, onRemove }: FileUploadProgressProps) {
  const { file, progress, status, error } = item
  const ext = file.name.split('.').pop() ?? ''
  const showProgress = status === 'uploading' || status === 'processing'
  const isError = status === 'error'

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: T.space.xs,
      padding: T.space.md,
      backgroundColor: T.bg.card,
      border: isError ? `1px solid ${T.accent.red}40` : `1px solid ${T.bg.hover}`,
      borderRadius: T.radius.sm,
      transition: 'border-color 0.2s',
    }}>
      {/* Top row: icon + name + size + status + remove */}
      <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
        <FileIcon type={ext} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 13,
            fontWeight: 500,
            color: T.text.primary,
            fontFamily: T.font.display,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {file.name}
          </div>
          <div style={{
            fontSize: 11,
            color: T.text.tertiary,
            fontFamily: T.font.mono,
            marginTop: 2,
          }}>
            {formatBytes(file.size)}
          </div>
        </div>

        <StatusBadge status={status} />

        <button
          onClick={onRemove}
          title="Eliminar"
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: T.text.tertiary,
            fontSize: 16,
            lineHeight: 1,
            padding: '2px 4px',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
            transition: 'color 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = T.accent.red)}
          onMouseLeave={e => (e.currentTarget.style.color = T.text.tertiary)}
        >
          ×
        </button>
      </div>

      {/* Progress bar */}
      {showProgress && (
        <div style={{
          width: '100%',
          height: 4,
          backgroundColor: T.bg.elevated,
          borderRadius: 2,
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${progress}%`,
            backgroundColor: T.accent.teal,
            borderRadius: 2,
            transition: 'width 0.2s ease',
          }} />
        </div>
      )}

      {/* Ready: full bar */}
      {status === 'ready' && (
        <div style={{
          width: '100%',
          height: 4,
          backgroundColor: `${T.accent.teal}30`,
          borderRadius: 2,
        }}>
          <div style={{
            height: '100%',
            width: '100%',
            backgroundColor: T.accent.teal,
            borderRadius: 2,
          }} />
        </div>
      )}

      {/* Error message */}
      {isError && error && (
        <div style={{
          fontSize: 12,
          color: T.accent.red,
          fontFamily: T.font.display,
          paddingLeft: 44,
        }}>
          {error}
        </div>
      )}
    </div>
  )
}
