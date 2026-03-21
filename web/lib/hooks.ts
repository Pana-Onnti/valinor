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
} from "./api"
import type { JobStatus, ClientProfile, AlertThreshold } from "./types"

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
