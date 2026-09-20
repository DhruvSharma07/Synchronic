import { useMemo } from 'react'
import { Editor } from './editor/Editor'

const COLORS = ['#e64980', '#12b886', '#4263eb', '#f76707']

function randomUser() {
  const id = Math.floor(Math.random() * 1000)
  return {
    name: `Guest ${id}`,
    color: COLORS[id % COLORS.length],
  }
}

export default function App() {
  // One user identity per browser tab, so opening two tabs looks like two
  // different collaborators - replace with the real logged-in user once
  // auth is wired up in Phase 1.
  const user = useMemo(randomUser, [])

  // Hardcoded for Phase 0 - there's no document list/routing yet, so every
  // tab joins the same room. Swap for a real document id once /documents
  // has a UI.
  const documentId = 'phase-0-demo-doc'

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-title">Syncronix</span>
        <span className="app-user" style={{ color: user.color }}>
          {user.name}
        </span>
      </header>
      <Editor documentId={documentId} user={user} />
    </div>
  )
}
