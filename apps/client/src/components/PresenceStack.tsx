import type { Peer } from '../hooks/useCollabSession'

const MAX_SHOWN = 5

export function PresenceStack({ peers, selfId }: { peers: Peer[]; selfId: string }) {
  const shown = peers.slice(0, MAX_SHOWN)
  const extra = peers.length - shown.length
  return (
    <div className="presence" aria-label="People in this document">
      {shown.map((p) => (
        <span
          key={p.id}
          className="avatar"
          style={{ background: p.color }}
          title={p.id === selfId ? `${p.name} (you)` : p.name}
        >
          {p.name.charAt(0).toUpperCase()}
        </span>
      ))}
      {extra > 0 && <span className="avatar avatar--more">+{extra}</span>}
    </div>
  )
}
