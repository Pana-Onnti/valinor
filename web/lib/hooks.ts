/**
 * hooks.ts
 * Custom React hooks wrapping the Valinor SaaS API client.
 */

"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import {
  fetchJobStatus,
  fetchClientProfile,
  fetchAlertThresholds,
  uploadFile,
} from "./api"
import type { JobStatus, ClientProfile, AlertThreshold, UploadFileState, UploadResult } from "./types"

/** Shape returned by every hook in this file. */
interface HookResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "error"])
const POLL_INTERVAL_MS = 3000

/**
 * useJobStatus
 * Polls the job status endpoint every 3 seconds until the job reaches a
 * terminal state ("completed" or "failed").
 */
export function useJobStatus(jobId: string | null): HookResult<JobStatus> {
  const [data, setData] = useState<JobStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const fetchOnce = useCallback(async () => {
    if (!jobId) return
    try {
      const result = await fetchJobStatus(jobId)
      setData(result)
      setError(null)
      if (TERMINAL_STATUSES.has(result.status)) {
        stopPolling()
        setLoading(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
      setLoading(false)
      stopPolling()
    }
  }, [jobId, stopPolling])

  const refetch = useCallback(() => {
    if (!jobId) return
    setLoading(true)
    setError(null)
    stopPolling()
    fetchOnce().then(() => {
      // Only start polling again if still in a non-terminal state
      setData(prev => {
        if (prev && !TERMINAL_STATUSES.has(prev.status)) {
          intervalRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS)
        }
        return prev
      })
    })
  }, [jobId, fetchOnce, stopPolling])

  useEffect(() => {
    if (!jobId) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }

    setLoading(true)
    setError(null)

    // Initial fetch, then start polling if not terminal
    fetchOnce().then(() => {
      setData(prev => {
        if (prev && !TERMINAL_STATUSES.has(prev.status)) {
          intervalRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS)
        } else {
          setLoading(false)
        }
        return prev
      })
    })

    return () => stopPolling()
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error, refetch }
}

/**
 * useClientProfile
 * Fetches the client profile once; re-fetches whenever `name` changes.
 */
export function useClientProfile(name: string | null): HookResult<ClientProfile> {
  const [data, setData] = useState<ClientProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (clientName: string) => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchClientProfile(clientName)
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [])

  const refetch = useCallback(() => {
    if (name) load(name)
  }, [name, load])

  useEffect(() => {
    if (!name) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }
    load(name)
  }, [name, load])

  return { data, loading, error, refetch }
}

/**
 * useAlertThresholds
 * Fetches the alert threshold list for a client; re-fetches on name change.
 */
export function useAlertThresholds(
  name: string | null
): HookResult<Record<string, AlertThreshold>> {
  const [data, setData] = useState<Record<string, AlertThreshold> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (clientName: string) => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchAlertThresholds(clientName)
      setData(result.thresholds)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }, [])

  const refetch = useCallback(() => {
    if (name) load(name)
  }, [name, load])

  useEffect(() => {
    if (!name) {
      setData(null)
      setLoading(false)
      setError(null)
      return
    }
    load(name)
  }, [name, load])

  return { data, loading, error, refetch }
}

// ── File Upload ──────────────────────────────────────────────────────────────

const MAX_CONCURRENT_UPLOADS = 3

interface QueueEntry {
  index: number
  file: File
}

/**
 * useFileUpload
 * Manages a list of file uploads with progress tracking.
 * Up to MAX_CONCURRENT_UPLOADS files are uploaded simultaneously.
 */
export function useFileUpload(clientName: string) {
  const [uploads, setUploads] = useState<UploadFileState[]>([])
  const activeCountRef = useRef(0)
  const queueRef = useRef<QueueEntry[]>([])

  const startUploadAtIndex = useCallback((index: number, file: File) => {
    activeCountRef.current++

    setUploads(prev => {
      const updated = [...prev]
      if (!updated[index]) return prev
      updated[index] = { ...updated[index], status: 'uploading', progress: 0 }
      return updated
    })

    uploadFile(clientName, file, (percent) => {
      setUploads(curr => {
        const u = [...curr]
        if (!u[index]) return curr
        u[index] = { ...u[index], progress: percent }
        return u
      })
    })
      .then((result: UploadResult) => {
        setUploads(curr => {
          const u = [...curr]
          if (!u[index]) return curr
          u[index] = { ...u[index], status: 'ready', progress: 100, result, upload_id: result.upload_id }
          return u
        })
      })
      .catch((err: unknown) => {
        setUploads(curr => {
          const u = [...curr]
          if (!u[index]) return curr
          u[index] = {
            ...u[index],
            status: 'error',
            error: err instanceof Error ? err.message : 'Error desconocido',
          }
          return u
        })
      })
      .finally(() => {
        activeCountRef.current--
        if (queueRef.current.length > 0 && activeCountRef.current < MAX_CONCURRENT_UPLOADS) {
          const next = queueRef.current.shift()!
          startUploadAtIndex(next.index, next.file)
        }
      })
  }, [clientName]) // eslint-disable-line react-hooks/exhaustive-deps

  const upload = useCallback((files: File[]) => {
    setUploads(prev => {
      const startIndex = prev.length
      const newItems: UploadFileState[] = files.map(file => ({
        file,
        progress: 0,
        status: 'pending' as const,
      }))
      files.forEach((file, i) => {
        queueRef.current.push({ index: startIndex + i, file })
      })
      return [...prev, ...newItems]
    })
    setTimeout(() => {
      while (activeCountRef.current < MAX_CONCURRENT_UPLOADS && queueRef.current.length > 0) {
        const entry = queueRef.current.shift()!
        startUploadAtIndex(entry.index, entry.file)
      }
    }, 0)
  }, [startUploadAtIndex])

  const removeUpload = useCallback((index: number) => {
    setUploads(prev => prev.filter((_, i) => i !== index))
    queueRef.current = queueRef.current
      .filter(entry => entry.index !== index)
      .map(entry => ({
        ...entry,
        index: entry.index > index ? entry.index - 1 : entry.index,
      }))
  }, [])

  const isUploading = uploads.some(u => u.status === 'uploading' || u.status === 'pending')

  return { upload, uploads, isUploading, removeUpload }
}
