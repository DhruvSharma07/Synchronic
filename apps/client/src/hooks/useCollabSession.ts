import { useEffect, useRef, useState } from 'react'
import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'
import { SYNC_URL } from '../config'
import { getFreshAccessToken } from '../tokens'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export interface Peer {
  clientId: number
  id: string
  name: string
  color: string
}

interface Options {
  documentId: string
  enabled: boolean
  /** Called whenever the socket closes - the page re-checks its role/access. */
  onClose: () => void
}

/** Owns one Yjs doc + y-websocket provider for the lifetime of a document view. */
export function useCollabSession({ documentId, enabled, onClose }: Options) {
  const [session, setSession] = useState<{ ydoc: Y.Doc; provider: WebsocketProvider } | null>(null)
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [saving, setSaving] = useState(false)
  const [peers, setPeers] = useState<Peer[]>([])
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let cleanup = () => {}

    ;(async () => {
      const token = await getFreshAccessToken()
      if (cancelled) return

      const ydoc = new Y.Doc()
      const provider = new WebsocketProvider(SYNC_URL, documentId, ydoc, {
        params: { token: token ?? '' },
      })

      // Access tokens live 15 minutes. y-websocket rebuilds the URL from
      // provider.params on every reconnect, so keep the token in there fresh.
      const refreshToken = async () => {
        const fresh = await getFreshAccessToken()
        if (fresh) provider.params.token = fresh
      }
      const tokenTimer = window.setInterval(refreshToken, 4 * 60 * 1000)

      provider.on('status', (e: { status: ConnectionStatus }) => setConnection(e.status))
      provider.on('connection-close', () => {
        void refreshToken()
        onCloseRef.current()
      })
      provider.on('connection-error', () => {
        void refreshToken()
        onCloseRef.current()
      })

      // "Saving…" while local edits are fresh; the server flushes to Postgres
      // every few seconds and on last-leave, so a short quiet period = saved.
      let savingTimer: number | undefined
      const onUpdate = (_update: Uint8Array, origin: unknown) => {
        if (origin === provider) return // remote edit
        setSaving(true)
        window.clearTimeout(savingTimer)
        savingTimer = window.setTimeout(() => setSaving(false), 1500)
      }
      ydoc.on('update', onUpdate)

      const readPeers = () => {
        const seen = new Map<string, Peer>()
        provider.awareness.getStates().forEach((state, clientId) => {
          const u = state.user as { id?: string; name?: string; color?: string } | undefined
          if (u?.id && u.name && u.color && !seen.has(u.id)) {
            seen.set(u.id, { clientId, id: u.id, name: u.name, color: u.color })
          }
        })
        setPeers(Array.from(seen.values()))
      }
      provider.awareness.on('change', readPeers)

      setSession({ ydoc, provider })

      cleanup = () => {
        window.clearInterval(tokenTimer)
        window.clearTimeout(savingTimer)
        ydoc.off('update', onUpdate)
        provider.awareness.off('change', readPeers)
        provider.destroy()
        ydoc.destroy()
      }
    })()

    return () => {
      cancelled = true
      cleanup()
      setSession(null)
      setPeers([])
      setConnection('connecting')
    }
  }, [documentId, enabled])

  return { session, connection, saving, peers }
}
