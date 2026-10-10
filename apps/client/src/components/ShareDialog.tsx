import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, type DocumentInfo, type PermissionEntry, type User } from '../api'

type GrantRole = 'editor' | 'viewer'

export function ShareDialog({ document: doc, onClose }: { document: DocumentInfo; onClose: () => void }) {
  const [entries, setEntries] = useState<PermissionEntry[]>([])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<GrantRole>('editor')
  const [suggestions, setSuggestions] = useState<User[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setEntries(await api.listPermissions(doc.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load collaborators')
    }
  }, [doc.id])

  useEffect(() => {
    void load()
  }, [load])

  // Debounced user search feeding the email field's suggestions.
  useEffect(() => {
    const q = email.trim()
    if (q.length < 2) {
      setSuggestions([])
      return
    }
    const t = window.setTimeout(() => {
      api.searchUsers(q).then(setSuggestions).catch(() => setSuggestions([]))
    }, 250)
    return () => window.clearTimeout(t)
  }, [email])

  async function guard(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  async function onAdd(e: React.FormEvent) {
    e.preventDefault()
    const target = email.trim()
    if (!target) return
    await guard(async () => {
      await api.grantPermission(doc.id, { email: target }, role)
      setEmail('')
    })
  }

  return (
    <div className="dialog-backdrop" onMouseDown={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Share document" onMouseDown={(e) => e.stopPropagation()}>
        <div className="dialog__head">
          <h2>Share “{doc.title}”</h2>
          <button className="btn btn--ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form className="share-form" onSubmit={onAdd}>
          <input
            type="email"
            list="share-suggestions"
            placeholder="Add people by email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <datalist id="share-suggestions">
            {suggestions.map((u) => (
              <option key={u.id} value={u.email}>{u.display_name}</option>
            ))}
          </datalist>
          <select value={role} onChange={(e) => setRole(e.target.value as GrantRole)} aria-label="Role">
            <option value="editor">Editor</option>
            <option value="viewer">Viewer</option>
          </select>
          <button className="btn btn--primary" disabled={busy}>Share</button>
        </form>

        {error && <p className="form-error">{error}</p>}

        <ul className="people">
          {entries.map((p) => {
            const isOwner = p.user.id === doc.owner_id
            return (
              <li key={p.user.id}>
                <div>
                  <strong>{p.user.display_name}</strong>
                  <span className="muted"> {p.user.email}</span>
                </div>
                {isOwner ? (
                  <span className="badge">Owner</span>
                ) : (
                  <span className="people__actions">
                    <select
                      value={p.role}
                      disabled={busy}
                      aria-label={`Role for ${p.user.display_name}`}
                      onChange={(e) =>
                        guard(() => api.grantPermission(doc.id, { user_id: p.user.id }, e.target.value as GrantRole))
                      }
                    >
                      <option value="editor">Editor</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button className="btn btn--ghost" disabled={busy} onClick={() => guard(() => api.revokePermission(doc.id, p.user.id))}>
                      Remove
                    </button>
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
