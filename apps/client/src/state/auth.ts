import { create } from 'zustand'
import { api, type User } from '../api'
import { getTokens, onSessionExpired } from '../tokens'

interface AuthState {
  user: User | null
  status: 'loading' | 'authed' | 'anon'
  init: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string) => Promise<void>
  logout: () => Promise<void>
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: 'loading',

  async init() {
    if (!getTokens()) return set({ user: null, status: 'anon' })
    try {
      set({ user: await api.me(), status: 'authed' })
    } catch {
      // Stored tokens are kept (api.ts clears them on a real auth failure), so a
      // reload while the server is briefly unreachable doesn't sign the user out.
      set({ user: null, status: 'anon' })
    }
  },

  async login(email, password) {
    await api.login(email, password)
    set({ user: await api.me(), status: 'authed' })
  },

  async register(email, password, displayName) {
    await api.register(email, password, displayName)
    await api.login(email, password)
    set({ user: await api.me(), status: 'authed' })
  },

  async logout() {
    await api.logout()
    set({ user: null, status: 'anon' })
  },
}))

// A failed refresh means the session is over: drop to the login screen.
onSessionExpired(() => useAuth.setState({ user: null, status: 'anon' }))
