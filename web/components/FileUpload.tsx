'use client'

/**
 * FileUpload.tsx
 * Drag-and-drop file upload zone with multi-file support and per-file progress.
 */

import { useRef, useState, useCallback, DragEvent, ChangeEvent } from 'react'
import { T } from '@/components/d4c/tokens'
import { useFileUpload } from '@/lib/hooks'
import FileUploadProgress from './FileUploadProgress'
import type { UploadResult } from '@/lib/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls']
const ACCEPTED_MIME = [
  'text/csv',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
]
const MAX_FILE_SIZE_MB = 50
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

// ── Helpers ──────────────────────────────────────────────────────────────────

function getFileExtension(name: string): string {
  return name.slice(name.lastIndexOf('.')).toLowerCase()
}

function validateFile(file: File): string | null {
  const ext = getFileExtension(file.name)
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return `Tipo no permitido: ${ext}. Usar .csv, .xlsx o .xls`
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `Archivo demasiado grande (máx. ${MAX_FILE_SIZE_MB} MB)`
  }
  return null
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface FileUploadProps {
  clientName: string
  onUploadComplete: (uploads: UploadResult[]) => void
  maxFiles?: number
}

export default function FileUpload({
  clientName,
  onUploadComplete,
  maxFiles = 10,
}: FileUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [validationErrors, setValidationErrors] = useState<string[]>([])

  const { upload, uploads, removeUpload } = useFileUpload(clientName)

  // Notify parent when all non-errored uploads are ready
  const handleFiles = useCallback((rawFiles: File[]) => {
    setValidationErrors([])
    const errors: string[] = []
    const valid: File[] = []

    const remaining = maxFiles - uploads.length
    const candidates = rawFiles.slice(0, remaining)

    if (rawFiles.length > remaining) {
      errors.push(`Límite de ${maxFiles} archivos. Se ignoraron ${rawFiles.length - remaining} archivo(s).`)
    }

    for (const file of candidates) {
      const err = validateFile(file)
      if (err) {
        errors.push(`${file.name}: ${err}`)
      } else {
        valid.push(file)
      }
    }

    if (errors.length > 0) setValidationErrors(errors)
    if (valid.length > 0) {
      upload(valid)
    }
  }, [upload, uploads.length, maxFiles])

  // Notify parent when all pending uploads finish
  const readyUploads = uploads.filter(u => u.status === 'ready' && u.result)
  const prevReadyCount = useRef(0)
  if (readyUploads.length !== prevReadyCount.current && readyUploads.length > 0) {
    prevReadyCount.current = readyUploads.length
    // Call outside render
    setTimeout(() => {
      onUploadComplete(readyUploads.map(u => u.result!))
    }, 0)
  }

  // ── Drag handlers ────────────────────────────────────────────────────────

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const onDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    // Only leave if exiting the zone entirely
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false)
    }
  }, [])

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) handleFiles(files)
  }, [handleFiles])

  const onInputChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) handleFiles(files)
    // Reset input so same file can be re-selected
    e.target.value = ''
  }, [handleFiles])

  const openFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  // ── Styles ───────────────────────────────────────────────────────────────

  const zoneStyle = {
    border: `2px dashed ${isDragging ? T.accent.teal : T.bg.hover}`,
    borderRadius: T.radius.md,
    backgroundColor: isDragging ? `${T.accent.teal}08` : T.bg.card,
    padding: T.space.xl,
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    gap: T.space.sm,
    cursor: 'pointer',
    transition: 'border-color 0.2s, background-color 0.2s',
    userSelect: 'none' as const,
    textAlign: 'center' as const,
    minHeight: 140,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        style={zoneStyle}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={openFilePicker}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openFilePicker() }}
      >
        {/* Upload icon */}
        <div style={{
          width: 40,
          height: 40,
          borderRadius: '50%',
          backgroundColor: `${T.accent.teal}15`,
          border: `1px solid ${T.accent.teal}30`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 18,
          color: T.accent.teal,
        }}>
          ↑
        </div>

        <div>
          <div style={{
            fontSize: 14,
            fontWeight: 600,
            color: T.text.primary,
            fontFamily: T.font.display,
          }}>
            Arrastrá tus archivos aquí o{' '}
            <span style={{ color: T.accent.teal }}>hacé click para seleccionar</span>
          </div>
          <div style={{
            fontSize: 12,
            color: T.text.tertiary,
            fontFamily: T.font.display,
            marginTop: T.space.xs,
          }}>
            CSV, XLSX, XLS — máx. {MAX_FILE_SIZE_MB} MB por archivo · hasta {maxFiles} archivos
          </div>
        </div>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(',') + ',' + ACCEPTED_MIME.join(',')}
        style={{ display: 'none' }}
        onChange={onInputChange}
      />

      {/* Validation errors */}
      {validationErrors.length > 0 && (
        <div style={{
          padding: T.space.sm,
          borderRadius: T.radius.sm,
          backgroundColor: `${T.accent.red}10`,
          border: `1px solid ${T.accent.red}30`,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}>
          {validationErrors.map((err, i) => (
            <div key={i} style={{
              fontSize: 12,
              color: T.accent.red,
              fontFamily: T.font.display,
            }}>
              {err}
            </div>
          ))}
        </div>
      )}

      {/* File list */}
      {uploads.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
          <div style={{
            fontSize: 12,
            fontWeight: 600,
            color: T.text.tertiary,
            fontFamily: T.font.display,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}>
            Archivos ({uploads.length})
          </div>

          {uploads.map((item, index) => (
            <FileUploadProgress
              key={`${item.file.name}-${index}`}
              item={item}
              onRemove={() => removeUpload(index)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
