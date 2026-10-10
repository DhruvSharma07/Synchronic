import { API_URL } from './config'

type Tokens = { access: string; refresh: string }

const KEY = 'synchronic.tokens'
let tokens: Tokens | null = load()
const expiredListeners = new Set<() => void>()

function load(): Tokens | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Tokens) : null
  } catch {
    return null
  }
}

export function getTokens(): Tokens | null {
  return tokens
}

export function setTokens(next: Tokens | null) {
  tokens = next
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next))
    else localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

export function onSessionExpired(fn: () => void): () => void {
  expiredListeners.add(fn)
  return () => expiredListeners.delete(fn)
}

let refreshing: Promise<string | null> | null = null

/** Exchange the refresh token for a new access token (single-flight). */
export function refreshAccessToken(): Promise<string | null> {
  const current = tokens
  if (!current) return Promise.resolve(null)
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: current.refresh }),
        })
        if (res.status === 401) {
          setTokens(null)
          expiredListeners.forEach((fn) => fn())
          return null
        }
        if (!res.ok) return null
        const data = (await res.json()) as { access_token: string }
        setTokens({ access: data.access_token, refresh: current.refresh })
        return data.access_token
      } catch {
        return null // network trouble: keep the session, try again later
      } finally {
        refreshing = null
      }
    })()
  }
  return refreshing
}

function expiresInSeconds(jwt: string): number {
  try {
    const payload = JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return payload.exp - Date.now() / 1000
  } catch {
    return 0
  }
}

/** An access token with at least a minute of life left, refreshing if needed. */
export async function getFreshAccessToken(): Promise<string | null> {
  if (!tokens) return null
  if (expiresInSeconds(tokens.access) > 60) return tokens.access
  return refreshAccessToken()
}
