import type { Editor } from '@tiptap/react'

export function Toolbar({ editor }: { editor: Editor | null }) {
  if (!editor) return null
  const run = () => editor.chain().focus()

  const buttons: { label: string; title: string; active?: boolean; onClick: () => void }[] = [
    { label: 'B', title: 'Bold', active: editor.isActive('bold'), onClick: () => run().toggleBold().run() },
    { label: 'I', title: 'Italic', active: editor.isActive('italic'), onClick: () => run().toggleItalic().run() },
    { label: 'H1', title: 'Heading 1', active: editor.isActive('heading', { level: 1 }), onClick: () => run().toggleHeading({ level: 1 }).run() },
    { label: 'H2', title: 'Heading 2', active: editor.isActive('heading', { level: 2 }), onClick: () => run().toggleHeading({ level: 2 }).run() },
    { label: '• List', title: 'Bullet list', active: editor.isActive('bulletList'), onClick: () => run().toggleBulletList().run() },
    { label: '1. List', title: 'Numbered list', active: editor.isActive('orderedList'), onClick: () => run().toggleOrderedList().run() },
    { label: 'Undo', title: 'Undo', onClick: () => run().undo().run() },
    { label: 'Redo', title: 'Redo', onClick: () => run().redo().run() },
  ]

  return (
    <div className="toolbar" role="toolbar" aria-label="Formatting">
      {buttons.map((b) => (
        <button
          key={b.title}
          type="button"
          title={b.title}
          className={`toolbar__btn${b.active ? ' is-active' : ''}`}
          onMouseDown={(e) => e.preventDefault()} // keep editor focus/selection
          onClick={b.onClick}
        >
          {b.label}
        </button>
      ))}
    </div>
  )
}
