import type { ConnectionStatus } from '../hooks/useCollabSession'

// A quiet status line instead of blocking spinners: editing never waits on the network.
export function StatusBadge({ connection, saving }: { connection: ConnectionStatus; saving: boolean }) {
  let label = 'Saved'
  let tone = 'ok'
  if (connection === 'connecting') {
    label = 'Connecting…'
    tone = 'wait'
  } else if (connection === 'disconnected') {
    label = 'Offline'
    tone = 'off'
  } else if (saving) {
    label = 'Saving…'
    tone = 'wait'
  }
  return (
    <span className={`status status--${tone}`} role="status">
      <span className="status__dot" />
      {label}
    </span>
  )
}
