/**
 * auth.ts — Client Portal authentication utilities.
 *
 * Lightweight JWT-based auth for the client portal.
 * Token is stored in localStorage and injected into API requests.
 *
 * Refs: VAL-13
 */

const TOKEN_KEY = "valinor_portal_token"
const CLIENT_KEY = "valinor_portal_client"

export interface PortalClient {
  id: string
  name: string
  email: string
}

export interface AuthState {
  token: string | null
  client: PortalClient | null
  isAuthenticated: boolean
}

/** Get the stored auth token. */
export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(TOKEN_KEY)
}

/** Get the stored client info. */
export function getClient(): PortalClient | null {
  if (typeof window === "undefined") return null
  const raw = localStorage.getItem(CLIENT_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as PortalClient
  } catch {
    return null
  }
}

/** Store auth credentials after login. */
export function setAuth(token: string, client: PortalClient): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(CLIENT_KEY, JSON.stringify(client))
}

/** Clear auth credentials on logout. */
export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(CLIENT_KEY)
}

/** Check if the user is authenticated. */
export function isAuthenticated(): boolean {
  return !!getToken()
}

/** Get current auth state. */
export function getAuthState(): AuthState {
  const token = getToken()
  const client = getClient()
  return {
    token,
    client,
    isAuthenticated: !!token,
  }
}
