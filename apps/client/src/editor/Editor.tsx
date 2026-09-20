import { useEffect, useMemo } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCursor from '@tiptap/extension-collaboration-cursor'
import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'

const SYNC_SERVER_URL = import.meta.env.VITE_SYNC_SERVER_URL || 'ws://localhost:8001'

type User = { name: string; color: string }

export function Editor({ documentId, user }: { documentId: string; user: User }) {
  // One Yjs doc + provider per documentId. Recreated only if documentId
  // changes, not on every render.
  const ydoc = useMemo(() => new Y.Doc(), [documentId])
  const provider = useMemo(
    () => new WebsocketProvider(SYNC_SERVER_URL, documentId, ydoc),
    [documentId, ydoc],
  )

  const editor = useEditor(
    {
      extensions: [
        // Yjs owns undo/redo history once Collaboration is active - the
        // StarterKit history extension would fight with it otherwise.
        StarterKit.configure({ history: false }),
        Collaboration.configure({ document: ydoc }),
        CollaborationCursor.configure({ provider, user }),
      ],
    },
    [ydoc, provider],
  )

  useEffect(() => {
    return () => {
      provider.destroy()
      ydoc.destroy()
    }
  }, [provider, ydoc])

  return (
    <div className="editor-shell">
      <EditorContent editor={editor} />
    </div>
  )
}
