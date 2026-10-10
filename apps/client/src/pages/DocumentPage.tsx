import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError, type DocumentInfo } from '../api'
import { blinkDelayForUser, colorForUser } from '../colors'
import { PresenceStack } from '../components/PresenceStack'
import { ShareDialog } from '../components/ShareDialog'
import { StatusBadge } from '../components/StatusBadge'
import { Editor } from '../editor/Editor'
import { useCollabSession } from '../hooks/useCollabSession'
import { useAuth } from '../state/auth'

export function DocumentPage() {
  const { documentId = '' } = useParams()
  const user = useAuth((s) => s.user)!
  const logout = useAuth((s) => s.logout)

  const [doc, setDoc] = useState<DocumentInfo | null>(null)
  const [lost, setLost] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [sharing, setSharing] = useState(false)

  const canEdit = doc?.role === 'editor' || doc?.role === 'owner'

  // Re-read the caller's role. Runs on load and whenever the socket closes, which
  // is how a live role change (or revoked access) reaches the UI.
  const lastRefresh = useRef(0)
  const refreshDoc = useCallback(async () => {
    const now = Date.now()
    if (now - lastRefresh.current < 1500) return
    lastRefresh.current = now
    try {
      const fresh = await api.getDocument(documentId)
      setDoc((prev) => (prev && prev.role === fresh.role && prev.title === fresh.title ? prev : fresh))
      setTitle((t) => (doc ? t : fresh.title))
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        setLost('This document doesn’t exist or you no longer have access to it.')
      }
    }
  }, [documentId, doc])

  useEffect(() => {
    setDoc(null)
    setLost(null)
    lastRefresh.current = 0
    api
      .getDocument(documentId)
      .then((d) => {
        setDoc(d)
        setTitle(d.title)
        document.title = `${d.title} · Synchronic`
      })
      .catch((err) =>
        setLost(
          err instanceof ApiError && err.status === 404
            ? 'This document doesn’t exist or you don’t have access to it.'
            : 'Could not load the document.',
        ),
      )
  }, [documentId])

  const { session, connection, saving, peers } = useCollabSession({
    documentId,
    enabled: doc !== null && lost === null,
    onClose: refreshDoc,
  })

  async function saveTitle() {
    const next = title.trim()
    if (!doc || !next || next === doc.title) return setTitle(doc?.title ?? '')
    try {
      const updated = await api.updateDocument(doc.id, { title: next })
      setDoc(updated)
      document.title = `${updated.title} · Synchronic`
    } catch {
      setTitle(doc.title)
    }
  }

  if (lost) {
    return (
      <div className="page">
        <main className="container empty">
          <p>{lost}</p>
          <Link to="/" className="btn btn--primary">Back to documents</Link>
        </main>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="topbar">
        <Link to="/" className="brand brand--small">Synchronic</Link>
        <input
          className="title-input"
          value={title}
          readOnly={!canEdit}
          maxLength={200}
          aria-label="Document title"
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => void saveTitle()}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        />
        <span className="topbar__right">
          <StatusBadge connection={connection} saving={saving} />
          <PresenceStack peers={peers} selfId={user.id} />
          {doc && !canEdit && <span className="badge">View only</span>}
          {doc?.role === 'owner' && (
            <button className="btn btn--primary" onClick={() => setSharing(true)}>Share</button>
          )}
          <button className="btn btn--ghost" onClick={() => void logout()}>Sign out</button>
        </span>
      </header>

      <main className="container container--wide">
        {session && doc ? (
          <Editor
            key={`${doc.id}`}
            ydoc={session.ydoc}
            provider={session.provider}
            canEdit={canEdit}
            user={{
              id: user.id,
              name: user.display_name,
              color: colorForUser(user.id),
              delay: blinkDelayForUser(user.id),
            }}
          />
        ) : (
          <p className="muted">Loading…</p>
        )}
      </main>

      {sharing && doc && <ShareDialog document={doc} onClose={() => setSharing(false)} />}
    </div>
  )
}
