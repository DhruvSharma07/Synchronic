import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, type DocumentInfo } from '../api'
import { useAuth } from '../state/auth'

export function Documents() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    document.title = 'Documents · Synchronic'
    api.listDocuments().then(setDocs).catch((e) => setError(e instanceof ApiError ? e.message : 'Could not load documents'))
  }, [])

  async function onCreate() {
    setCreating(true)
    try {
      const doc = await api.createDocument()
      navigate(`/d/${doc.id}`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create document')
      setCreating(false)
    }
  }

  async function onDelete(doc: DocumentInfo) {
    if (!window.confirm(`Delete “${doc.title}” for everyone? This can't be undone.`)) return
    try {
      await api.deleteDocument(doc.id)
      setDocs((d) => d?.filter((x) => x.id !== doc.id) ?? null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not delete document')
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <span className="brand brand--small">Synchronic</span>
        <span className="topbar__right">
          <span className="muted">{user?.display_name}</span>
          <button className="btn btn--ghost" onClick={() => void logout()}>Sign out</button>
        </span>
      </header>

      <main className="container">
        <div className="row">
          <h1>Your documents</h1>
          <button className="btn btn--primary" onClick={onCreate} disabled={creating}>
            {creating ? 'Creating…' : '+ New document'}
          </button>
        </div>

        {error && <p className="form-error">{error}</p>}
        {docs === null && !error && <p className="muted">Loading…</p>}
        {docs?.length === 0 && (
          <div className="empty">
            <p>No documents yet.</p>
            <p className="muted">Create one to start writing - share it and edit together live.</p>
          </div>
        )}

        <ul className="doclist">
          {docs?.map((d) => (
            <li key={d.id}>
              <Link to={`/d/${d.id}`} className="doclist__title">{d.title}</Link>
              <span className="badge">{d.role}</span>
              <span className="muted doclist__date">{new Date(d.updated_at).toLocaleString()}</span>
              {d.role === 'owner' && (
                <button className="btn btn--ghost" onClick={() => void onDelete(d)}>Delete</button>
              )}
            </li>
          ))}
        </ul>
      </main>
    </div>
  )
}
