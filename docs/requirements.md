# Collaborative document editor — requirements & architecture

A Google Docs–style collaborative editor, built on a Python backend with a Yjs/CRDT-based
real-time layer. This document is the reference for scope, architecture, and sequencing before
implementation starts.

---

## 1. Project overview

**Goal:** a web app where multiple users can create, edit, and share rich-text documents with
live simultaneous editing, comments, version history, and role-based access control.

**Non-goal (for now):** full parity with Google Docs (tables with merged cells, embedded
spreadsheets, add-ons, org-wide admin console). Scope is deliberately staged — see section 11.

---

## 2. Feature scope by phase

| Phase | Features |
|---|---|
| **MVP** | Rich-text editing (bold/italic/headings/lists), single-doc live co-editing, presence + cursors, basic auth, doc CRUD, per-user sharing (viewer/editor/owner) |
| **V1** | Comments with anchored positions, version history, link-sharing, offline editing, role: commenter |
| **V2** | Suggestions ("track changes") mode, export to PDF/DOCX, notifications/email, @mentions, search |
| **V3** | Tables, images, folders/organization, AI writing assistance, activity feed |

Build MVP end-to-end before adding V1+ features — a working co-editor with basic sharing is a
complete, demonstrable product on its own.

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Editor UI | React + Tiptap (ProseMirror-based) | Best-in-class rich text editing, first-class Yjs binding |
| CRDT layer | Yjs (client) + pycrdt (server) | Conflict-free merges, no custom OT algorithm needed |
| Real-time transport | WebSockets via `pycrdt-websocket` | Speaks the Yjs sync protocol natively from Python |
| API server | FastAPI | Async, plays well with WebSockets, fast to iterate |
| Database | PostgreSQL | Users, documents, permissions, comments, version snapshots |
| Cache / pub-sub | Redis | Active-document cache, permission-change broadcast |
| Object storage | S3-compatible | Exported files, embedded images |
| Background jobs | Celery or RQ | Exports, notification emails, periodic snapshotting |
| Auth | FastAPI-Users or Authlib | JWT/session auth, OAuth if needed |
| Frontend state (non-doc) | Zustand or Redux | UI state separate from the Yjs document state |
| Local dev | Docker Compose | Postgres + Redis + API + WS server in one command |

The editor surface itself (Tiptap) is unavoidably JS — everything else in the stack is Python.

---

## 4. System architecture

```
Browser client (React + Tiptap + Yjs)
        |                        |
        v                        v
   REST API                Realtime sync server
 (FastAPI: auth,           (FastAPI + pycrdt-websocket:
  docs, sharing)             Yjs rooms, presence)
        |                        |
        +----------+  +----------+
                   v  v
            Postgres + Redis
        (metadata, permissions, cache)
                    |
                    v
            Background workers
        (exports, notifications, snapshots)
```

- **REST API** handles anything that isn't live document content: auth, document metadata,
  sharing/permissions, comment threads, triggering exports.
- **Realtime sync server** is a separate concern from the REST API even though it may live in the
  same codebase — it owns Yjs "rooms" (one per open document) and the awareness/presence channel.
- **Redis pub/sub** connects the two: when a permission changes via the REST API, an event is
  published so the sync server can immediately downgrade or disconnect an active session.
- **Background workers** handle anything slow or non-interactive: DOCX/PDF export, sending
  notification emails, periodically flushing Yjs update logs into durable Postgres snapshots.

---

## 5. Data model

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY,
    owner_id UUID REFERENCES users(id) NOT NULL,
    title TEXT NOT NULL,
    is_link_shareable BOOLEAN DEFAULT FALSE,
    link_share_role TEXT CHECK (link_share_role IN ('viewer','commenter','editor')) DEFAULT 'viewer',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE document_permissions (
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role TEXT CHECK (role IN ('owner','editor','commenter','viewer')) NOT NULL,
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (document_id, user_id)
);

CREATE TABLE document_snapshots (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    yjs_state BYTEA NOT NULL,          -- binary Yjs update/state vector
    created_at TIMESTAMPTZ DEFAULT now(),
    label TEXT                          -- optional, for named versions
);

CREATE TABLE comments (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    author_id UUID REFERENCES users(id),
    anchor JSONB NOT NULL,              -- Yjs RelativePosition, serialized
    body TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

Notes:
- `owner_id` lives directly on `documents`, not only as a permissions row — avoids ambiguity if a
  permission row is ever deleted.
- `document_snapshots.yjs_state` stores incremental Yjs updates; version history is a replay of
  this table, not a copy of the rendered document.
- `comments.anchor` uses a relative position so it survives edits elsewhere in the document.

---

## 6. API surface

### REST endpoints (indicative, not exhaustive)

| Method | Path | Role required | Purpose |
|---|---|---|---|
| POST | `/auth/login` | — | Authenticate, issue token |
| GET | `/documents` | — (filtered by permission) | List accessible documents |
| POST | `/documents` | — | Create a document (creator becomes owner) |
| GET | `/documents/{id}` | viewer | Fetch metadata + caller's role |
| DELETE | `/documents/{id}` | owner | Delete document |
| POST | `/documents/{id}/permissions` | owner | Grant/change a user's role |
| POST | `/documents/{id}/transfer-ownership` | owner | Transfer ownership |
| GET | `/documents/{id}/comments` | viewer | List comment threads |
| POST | `/documents/{id}/comments` | commenter | Add a comment |
| POST | `/documents/{id}/export` | viewer | Queue an export job |
| GET | `/documents/{id}/versions` | viewer | List version snapshots |

Return `404` (not `403`) when the caller has no permission row and the document isn't
link-shareable — this avoids confirming a document's existence to someone unauthorized.

### WebSocket protocol

- Client connects to `/sync/{document_id}` with an auth token in the handshake.
- Server resolves the caller's role **independently of any REST call** before allowing the Yjs
  room join.
- `viewer`/`commenter` roles: subscribed read-only to document content, full read-write on the
  separate comments channel (for commenter).
- `editor`/`owner`: full read-write.
- Awareness messages (cursor position, selection, user color) are broadcast but never persisted
  or merged into document state.
- On a permission-change pub/sub event, the server re-validates the affected connection's role
  and either downgrades its write access or force-disconnects it.

---

## 7. Real-time collaboration design

- **CRDT, not OT.** Yjs assigns stable, position-independent IDs to content, so merges from any
  number of concurrent editors converge without a central transform step.
- **Persistence model:** the server keeps the live Yjs document in memory (backed by Redis for
  multi-instance deployments), and periodically flushes update batches to
  `document_snapshots` in Postgres. Version history is reconstructed by replaying snapshots up to
  a timestamp.
- **Offline support:** client queues local Yjs updates (in IndexedDB) while disconnected; on
  reconnect, updates are sent and merge automatically — no manual conflict resolution needed,
  since CRDT merges are order-independent.
- **Comments as an overlay:** stored separately from document content (see schema above), anchored
  via `RelativePosition` so they track the surrounding text across edits.

---

## 8. Permissions & access control

| Role | View | Edit | Comment | Manage sharing | Delete |
|---|---|---|---|---|---|
| Owner | ✅ | ✅ | ✅ | ✅ | ✅ |
| Editor | ✅ | ✅ | ✅ | ❌ | ❌ |
| Commenter | ✅ | ❌ | ✅ | ❌ | ❌ |
| Viewer | ✅ | ❌ | ❌ | ❌ | ❌ |
| *(no row)* | ❌ | ❌ | ❌ | ❌ | ❌ |

**Enforcement checklist** — every layer checks independently, none inherits trust from another:

- [ ] REST API checks role on every document-related endpoint
- [ ] WebSocket handshake checks role before allowing room join
- [ ] WebSocket message handler checks role on every incoming update (not just at connect time)
- [ ] Permission changes propagate live via Redis pub/sub to kick or downgrade active sessions
- [ ] Frontend reflects role (hides/disables UI) but is never the actual security boundary

---

## 9. UI/UX requirements

- **Visual language:** minimal chrome, generous whitespace, the document itself is the focal
  point — toolbar and sidebar use muted colors and thin borders.
- **Presence:** avatar stack showing currently-active collaborators; colors are stable per user
  (derived from user ID) and reused consistently across cursor, avatar, and comment highlights.
- **Collaborator cursors:** colored caret + name tag, positioned via Yjs awareness data mapped to
  screen coordinates. The caret blinks (`step-end` animation, ~1s interval) with a per-user
  delay offset so multiple cursors don't flash in sync; the name tag itself does not blink.
  Cursors fade out after several seconds of inactivity.
- **Status over spinners:** a small "saved / saving… / offline" indicator rather than blocking
  spinners — editing should never feel gated on network round-trips.
- **Role-driven rendering:** viewer mode renders Tiptap as non-editable and hides edit affordances
  entirely, rather than showing disabled buttons.

---

## 10. Non-functional requirements

- **Latency:** local edits apply optimistically and instantly; remote edits should typically
  appear within ~100–300ms on a reasonable connection.
- **Scalability:** REST API and WebSocket sync server scale independently (different load
  profiles — the WS server holds long-lived connections and in-memory document state).
- **Durability:** no data loss on server restart — Yjs state must be recoverable from Postgres
  snapshots at all times, not just held in memory.
- **Security:** all three enforcement layers in section 8 must independently reject
  unauthorized access; WebSocket auth tokens must be validated per-connection, not just at
  initial page load.
- **Offline resilience:** the client must function (read + queue writes) with no network
  connection and reconcile automatically on reconnect.

---

## 11. Build roadmap

1. **Phase 0 — setup:** Docker Compose skeleton (Postgres, Redis, FastAPI, WS server), basic
   auth, empty Tiptap editor with no persistence.
2. **Phase 1 — MVP:** persistence to Postgres, Yjs + pycrdt-websocket wired for live co-editing
   between two browser tabs, awareness/presence cursors, document CRUD, per-user sharing with
   the three core roles.
3. **Phase 2:** comments, version history, link-sharing, offline queueing.
4. **Phase 3:** suggestions mode, export (PDF/DOCX), notifications, search.
5. **Phase 4:** tables, images, folders, AI-assisted writing.

Each phase should be independently demoable — resist folding phase 2+ features into the MVP.

---

## 12. Open questions to resolve before coding

- Single-owner model, or allow co-owners? (Spec above assumes single owner, matching Google Docs.)
- Self-hosted object storage (MinIO) for local dev, or straight to S3 from day one?
- Should the REST API and WebSocket sync server be one FastAPI app or two separate deployables?
  (Two is cleaner for scaling later, but adds deployment overhead early on.)
- Auth: roll your own with FastAPI-Users, or use a hosted provider (Clerk/Auth0) to save time?
