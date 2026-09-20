"""
Phase 0 realtime sync server.

Wires pycrdt-websocket into a plain ASGI app so a Tiptap/Yjs client can open
a WebSocket per document and sync live edits. pycrdt-websocket implements
the same sync protocol as the JS `y-websocket` package, so the client side
(see apps/client/src/editor/Editor.tsx) can use the standard y-websocket
provider against this server without a custom protocol.

pycrdt-websocket's import path has moved between recent releases (older
releases exposed a standalone `pycrdt_websocket` package; newer ones nest it
under `pycrdt.websocket`) - this tries both so the scaffold keeps working
either way. If neither import works, check the installed version's docs at
https://github.com/y-crdt/pycrdt-websocket for the current API.

NOT production-safe yet - there is no auth or permission check on connect.
Before Phase 1 ships, this needs:
  - Reading a token off the connection and resolving the caller's role
    against document_permissions in Postgres before allowing the room join.
  - Rejecting the handshake outright (not just restricting afterwards) for
    anyone with no role and no link-sharing on the document.
  - Persisting each room's Yjs state to `document_snapshots` on an interval,
    instead of only holding it in memory (a restart currently loses all
    unsaved documents).
  - Subscribing to the Redis pub/sub channel described in the README so a
    live permission downgrade can disconnect or restrict a session
    immediately, not just on next reconnect.
"""

try:
    from pycrdt_websocket import ASGIServer, WebsocketServer
except ImportError:
    from pycrdt.websocket import ASGIServer, WebsocketServer  # newer releases

websocket_server = WebsocketServer()
app = ASGIServer(websocket_server)
