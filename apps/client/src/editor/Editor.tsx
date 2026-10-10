import { useEffect } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Collaboration from '@tiptap/extension-collaboration'
import CollaborationCursor from '@tiptap/extension-collaboration-cursor'
import type * as Y from 'yjs'
import type { WebsocketProvider } from 'y-websocket'
import { Toolbar } from '../components/Toolbar'

export interface CollabUser {
  id: string
  name: string
  color: string
  delay: number
}

// Caret blinks via border-color so the name tag stays solid (see styles.css);
// each user gets a different animation-delay so carets don't flash in sync.
function renderCursor(user: Record<string, unknown>): HTMLElement {
  const caret = document.createElement('span')
  caret.classList.add('collaboration-cursor__caret')
  caret.style.setProperty('--cursor-color', String(user.color))
  caret.style.animationDelay = `${Number(user.delay) || 0}s`

  const label = document.createElement('div')
  label.classList.add('collaboration-cursor__label')
  label.style.backgroundColor = String(user.color)
  label.textContent = String(user.name)

  caret.appendChild(label)
  return caret
}

export function Editor({
  ydoc,
  provider,
  user,
  canEdit,
}: {
  ydoc: Y.Doc
  provider: WebsocketProvider
  user: CollabUser
  canEdit: boolean
}) {
  const editor = useEditor(
    {
      editable: canEdit,
      extensions: [
        // Yjs owns undo/redo once Collaboration is active; StarterKit's history would fight it.
        StarterKit.configure({ history: false }),
        Collaboration.configure({ document: ydoc }),
        CollaborationCursor.configure({ provider, user, render: renderCursor }),
      ],
    },
    [ydoc, provider],
  )

  // Role can change while the document is open (the server also enforces this).
  useEffect(() => {
    editor?.setEditable(canEdit)
  }, [editor, canEdit])

  return (
    <div className="editor-wrap">
      {canEdit && <Toolbar editor={editor} />}
      <div className={`editor-shell${canEdit ? '' : ' editor-shell--readonly'}`}>
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
