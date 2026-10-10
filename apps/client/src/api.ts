import { API_URL } from './config'
import { getTokens, refreshAccessToken, setTokens } from './tokens'

export type Role = 'owner' | 'editor' | 'commenter' | 'viewer'

export interface User {
  id: string
  email: string
  display_name: string
  avatar_url: string | null
}

export interface DocumentInfo {
  id: string
  title: string
  owner_id: string
  role: Role
  is_link_shareable: boolean
  link_share_role: string
  created_at: string
  updated_at: string
}

export interface PermissionEntry {
  user: User
  role: Role
  granted_at: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : String(d))).join('; ')
  }
  return fallback
}

async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; auth?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, auth = true } = opts
  const send = (token: string | null) =>
    fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })

  let res: Response
  try {
    res = await send(auth ? (getTokens()?.access ?? null) : null)
    if (auth && res.status === 401) {
      const fresh = await refreshAccessToken()
      if (fresh) res = await send(fresh)
    }
  } catch {
    throw new ApiError(0, 'Network error - is the server reachable?')
  }

  if (!res.ok) {
    let detail: unknown
    try {
      detail = (await res.json()).detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, describe(detail, `Request failed (${res.status})`))
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  register: (email: string, password: string, display_name: string) =>
    request<User>('/auth/register', { method: 'POST', body: { email, password, display_name }, auth: false }),

  async login(email: string, password: string): Promise<void> {
    const data = await request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST',
      body: { email, password },
      auth: false,
    })
    setTokens({ access: data.access_token, refresh: data.refresh_token })
  },

  async logout(): Promise<void> {
    const t = getTokens()
    setTokens(null)
    if (t) {
      try {
        await request<void>('/auth/logout', { method: 'POST', body: { refresh_token: t.refresh }, auth: false })
      } catch {
        /* already revoked or offline: the local session is gone either way */
      }
    }
  },

  me: () => request<User>('/users/me'),
  searchUsers: (q: string) => request<User[]>(`/users/search?q=${encodeURIComponent(q)}`),

  listDocuments: () => request<DocumentInfo[]>('/documents'),
  createDocument: (title?: string) =>
    request<DocumentInfo>('/documents', { method: 'POST', body: title ? { title } : {} }),
  getDocument: (id: string) => request<DocumentInfo>(`/documents/${id}`),
  updateDocument: (id: string, patch: { title?: string }) =>
    request<DocumentInfo>(`/documents/${id}`, { method: 'PATCH', body: patch }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),

  listPermissions: (id: string) => request<PermissionEntry[]>(`/documents/${id}/permissions`),
  grantPermission: (id: string, target: { email: string } | { user_id: string }, role: 'editor' | 'viewer') =>
    request<PermissionEntry>(`/documents/${id}/permissions`, { method: 'POST', body: { ...target, role } }),
  revokePermission: (id: string, userId: string) =>
    request<void>(`/documents/${id}/permissions/${userId}`, { method: 'DELETE' }),
}
