/**
 * api.ts
 * API client functions for the Valinor SaaS backend.
 */

import type {
  JobStatus,
  AnalyzeRequest,
  ClientProfile,
  AlertThreshold,
  SSHConfig,
  DBConfig,
  UploadResult,
  PreviewData,
  SchemaData,
} from "./types"

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/** Generic fetch wrapper that throws on non-2xx responses. */
async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  })

  if (!res.ok) {
    let message = `API error ${res.status}`
    try {
      const body = await res.json()
      message = body?.detail ?? body?.message ?? message
    } catch {
      // ignore parse errors — use default message
    }
    throw new Error(message)
  }

  return res.json() as Promise<T>
}

/** Fetch the current status of a job. */
export function fetchJobStatus(jobId: string): Promise<JobStatus> {
  return apiFetch<JobStatus>(`/api/v1/jobs/${encodeURIComponent(jobId)}/status`)
}

/** Fetch the full results of a completed job. */
export function fetchJobResults(jobId: string): Promise<any> {
  return apiFetch<any>(`/api/v1/jobs/${encodeURIComponent(jobId)}/results`)
}

/** Submit a new analysis job and receive the assigned job_id. */
export function startAnalysis(req: AnalyzeRequest): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>("/api/v1/analyze", {
    method: "POST",
    body: JSON.stringify(req),
  })
}

/** Fetch the stored profile for a client. */
export function fetchClientProfile(name: string): Promise<ClientProfile> {
  return apiFetch<ClientProfile>(`/api/v1/clients/${encodeURIComponent(name)}/profile`)
}

/** Fetch aggregated KPIs for a client. */
export function fetchClientKPIs(name: string): Promise<any> {
  return apiFetch<any>(`/api/v1/clients/${encodeURIComponent(name)}/kpis`)
}

/** Fetch all alert thresholds configured for a client. */
export function fetchAlertThresholds(
  name: string
): Promise<{ thresholds: Record<string, AlertThreshold> }> {
  return apiFetch<{ thresholds: Record<string, AlertThreshold> }>(
    `/api/v1/clients/${encodeURIComponent(name)}/thresholds`
  )
}

/** Create or update a single alert threshold for a client. */
export function createAlertThreshold(
  name: string,
  threshold: AlertThreshold
): Promise<AlertThreshold> {
  return apiFetch<AlertThreshold>(
    `/api/v1/clients/${encodeURIComponent(name)}/thresholds`,
    { method: "POST", body: JSON.stringify(threshold) }
  )
}

/** Delete an alert threshold by metric name. */
export async function deleteAlertThreshold(
  name: string,
  metric: string
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/clients/${encodeURIComponent(name)}/thresholds/${encodeURIComponent(metric)}`,
    { method: "DELETE" }
  )
}

/** Test SSH and DB connectivity before submitting a full analysis. */
export function testConnection(config: {
  ssh_config: SSHConfig
  db_config: DBConfig
}): Promise<{ ssh_ok: boolean; db_ok: boolean; latency_ms: number }> {
  return apiFetch<{ ssh_ok: boolean; db_ok: boolean; latency_ms: number }>(
    "/api/v1/test-connection",
    { method: "POST", body: JSON.stringify(config) }
  )
}

// ── File Upload ──────────────────────────────────────────────────────────────

/**
 * Upload a single file to the backend for a given client.
 * Uses XMLHttpRequest instead of fetch to support upload progress events.
 */
export function uploadFile(
  clientName: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const formData = new FormData()
    formData.append("file", file)

    xhr.open("POST", `${BASE_URL}/api/upload/${encodeURIComponent(clientName)}`)

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        const percent = Math.round((event.loaded / event.total) * 100)
        onProgress(percent)
      }
    })

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText) as UploadResult
          resolve(data)
        } catch {
          reject(new Error("Invalid JSON response from upload endpoint"))
        }
      } else {
        let message = `Upload error ${xhr.status}`
        try {
          const body = JSON.parse(xhr.responseText)
          message = body?.detail ?? body?.message ?? message
        } catch {
          // use default message
        }
        reject(new Error(message))
      }
    })

    xhr.addEventListener("error", () => {
      reject(new Error("Network error during upload"))
    })

    xhr.addEventListener("abort", () => {
      reject(new Error("Upload aborted"))
    })

    xhr.send(formData)
  })
}

/** Fetch a row preview for an uploaded file. */
export function getPreview(
  uploadId: string,
  rows?: number,
  sheet?: string
): Promise<PreviewData> {
  const params = new URLSearchParams()
  if (rows !== undefined) params.set("rows", String(rows))
  if (sheet !== undefined) params.set("sheet", sheet)
  const qs = params.toString() ? `?${params.toString()}` : ""
  return apiFetch<PreviewData>(`/api/upload/${encodeURIComponent(uploadId)}/preview${qs}`)
}

/** Fetch the column schema for an uploaded file. */
export function getSchema(uploadId: string): Promise<SchemaData> {
  return apiFetch<SchemaData>(`/api/upload/${encodeURIComponent(uploadId)}/schema`)
}

// ── File-based Analysis ───────────────────────────────────────────────────────

/**
 * Submit an analysis job backed by previously-uploaded files.
 * Maps to the same /api/v1/analyze endpoint but uses source_type "sqlite"
 * so the backend reads from the uploaded SQLite snapshots instead of a
 * live database connection.
 */
export function startFileAnalysis(req: {
  client_name: string
  upload_ids: string[]
  column_mapping: Record<string, string>
  period: string
}): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>("/api/v1/analyze", {
    method: "POST",
    body: JSON.stringify({
      ...req,
      source_type: "sqlite",
      db_config: { type: "sqlite", host: "local", port: 0, name: "upload" },
    }),
  })
}
