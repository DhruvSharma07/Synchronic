# Synchronic

> Write together, in real time.

A Google Docs–style collaborative document editor: multiple people can edit the same
document simultaneously, see each other's cursors live, comment, and control who can view,
comment, or edit — powered by a CRDT sync engine so edits never conflict, even offline.


---

## Table of contents

1. [Overview](#overview)
2. [Feature scope](#feature-scope)
3. [Tech stack](#tech-stack)
4. [Architecture](#architecture)
5. [Project structure](#project-structure)
6. [Getting started](#getting-started)
7. [Environment variables](#environment-variables)
8. [Data model](#data-model)
9. [API reference](#api-reference)
10. [Real-time collaboration](#real-time-collaboration)
11. [Permissions & access control](#permissions--access-control)
12. [UI/UX principles](#uiux-principles)
13. [Roadmap](#roadmap)
14. [Open decisions](#open-decisions)
15. [Contributing](#contributing)

---

## Overview

Synchronic lets multiple users write in the same document at once, the same way Google Docs
does, without needing Google's infrastructure to do it. The editor uses **CRDTs (via Yjs)**
rather than a custom Operational Transformation engine, which means:

- Merges between concurrent edits are automatic and mathematically guaranteed to converge —
  no custom conflict-resolution logic to write or debug.
- Offline editing works for free: local changes queue and merge cleanly on reconnect.
- The backend can be Python end-to-end (FastAPI), while the editor surface itself
  (unavoidably) runs in the browser via Tiptap/ProseMirror.

This README is the single reference for scope, architecture, and setup. Keep it up to date
as decisions change — see [Open decisions](#open-decisions) for things still unresolved.

---

## Feature scope

| Phase | Features |
|---|---|
| **MVP** | Rich text editing (bold/italic/headings/lists), live co-editing between clients, presence + colored cursors, auth, document CRUD, sharing with owner/editor/viewer roles |
| **V1** | Comments anchored to text, version history, link-sharing, offline editing, commenter role |
| **V2** | Suggestions ("track changes") mode, export to PDF/DOCX, email notifications, @mentions, search |
| **V3** | Tables, images, folders, AI writing assistance, activity feed |

Ship each phase as a fully working, demoable increment — don't let V1+ features creep into
the MVP.

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Editor UI | React + [Tiptap](https://tiptap.dev/) | ProseMirror-based; first-class Yjs binding |
| CRDT engine | [Yjs](https://github.com/yjs/yjs) (client) + [pycrdt](https://github.com/y-crdt/pycrdt) (server) | Same CRDT semantics on both ends |
| Realtime transport | WebSockets via `pycrdt-websocket` | Implements the Yjs sync protocol in Python |
| API server | [FastAPI](https://fastapi.tiangolo.com/) | Async, plays well with WebSockets |
| Database | PostgreSQL | Users, documents, permissions, comments, snapshots |
| Cache / pub-sub | Redis | Active-document cache; permission-change broadcast |
| Object storage | S3-compatible (or MinIO for local dev) | Exported files, embedded images |
| Background jobs | Celery or RQ | Exports, notifications, periodic snapshotting |
| Auth | FastAPI-Users or Authlib | JWT/session-based; OAuth optional |
| Frontend state (non-doc) | Zustand or Redux | UI state, kept separate from Yjs doc state |
| Local dev | Docker Compose | One command to bring up Postgres, Redis, both servers |

---

## Architecture

```
                 Browser client (React + Tiptap + Yjs)
                          |                  |
                   REST calls|            |WebSocket
                       v                      v
                   REST API                Realtime sync server
               (FastAPI: auth,          (FastAPI + pycrdt-websocket:
                docs, sharing)            Yjs rooms, presence)
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

- **REST API** — everything that isn't live document content: auth, metadata, sharing,
  comment threads, triggering exports.
- **Realtime sync server** — owns Yjs "rooms" (one per open document) and the
  presence/awareness channel. Kept conceptually separate from the REST API even if deployed
  in the same codebase initially, since the two scale differently (long-lived connections
  and in-memory state vs. stateless request/response).
- **Redis pub/sub** bridges the two: a permission change made via REST publishes an event
  the sync server listens for, so an active session can be downgraded or disconnected
  immediately rather than on next reconnect.
- **Background workers** handle anything slow: DOCX/PDF export, notification emails,
  periodic flushing of the in-memory Yjs state into durable Postgres snapshots.

---

## Project structure

```
Synchronic/
├── apps/
│   ├── client/                  # React + Tiptap + Yjs frontend
│   │   ├── src/
│   │   │   ├── components/
│   │   │   ├── editor/          # Tiptap config, Yjs bindings, cursor rendering
│   │   │   ├── hooks/
│   │   │   └── state/           # Zustand/Redux store (non-document UI state)
│   │   └── package.json
│   └── server/
│       ├── api/                 # FastAPI REST service
│       │   ├── routers/         # documents, auth, permissions, comments, export
│       │   ├── models/          # SQLAlchemy models
│       │   └── main.py
│       └── sync/                 # FastAPI + pycrdt-websocket realtime service
│           ├── rooms.py
│           └── main.py
├── packages/
│   └── shared/                   # Shared types/schemas between client and server
├── infra/
│   ├── docker-compose.yml
│   └── migrations/               # Alembic migrations
├── docs/
│   └── requirements.md           # Full requirements & architecture spec
├── .env.example
└── README.md
```

---

## Getting started

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker & Docker Compose

### Setup

```bash
# 1. Clone and configure
git clone <repo-url> Synchronic
cd Synchronic
cp .env.example .env   # fill in secrets locally

# 2. Bring up infrastructure
docker compose up -d db redis

# 3. Run database migrations
cd apps/server/api
alembic upgrade head

# 4. Start the REST API
uvicorn apps.server.api.main:app --reload --port 8000

# 5. Start the realtime sync server (separate terminal)
uvicorn apps.server.sync.main:app --reload --port 8001

# 6. Start the client (separate terminal)
cd apps/client
npm install
npm run dev
```

The client should now be running locally with the editor pointed at both the REST API and
the sync server.

---

## Environment variables

| Variable | Purpose | Example |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | `postgresql://user:pass@localhost:5432/Synchronic` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET` | Signing secret for auth tokens | (generate a long random value) |
| `S3_ENDPOINT` | Object storage endpoint (or MinIO for local dev) | `http://localhost:9000` |
| `S3_BUCKET` | Bucket for exports/uploads | `Synchronic-files` |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Object storage credentials | — |
| `SYNC_SERVER_URL` | URL the client uses for the WebSocket connection | `ws://localhost:8001` |
| `SMTP_*` | Outbound email settings for notifications (V2) | — |

Keep `.env` out of version control; `.env.example` should list every key with a placeholder.

---

## Data model

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
    yjs_state BYTEA NOT NULL,           -- binary Yjs update/state vector
    created_at TIMESTAMPTZ DEFAULT now(),
    label TEXT                           -- optional, for named versions
);

CREATE TABLE comments (
    id UUID PRIMARY KEY,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    author_id UUID REFERENCES users(id),
    anchor JSONB NOT NULL,               -- Yjs RelativePosition, serialized
    body TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**Design notes:**
- `owner_id` lives directly on `documents`, not only as a permissions row, so ownership
  can't be lost if a permission row is deleted.
- Version history is a replay of `document_snapshots`, not a copy of rendered content.
- `comments.anchor` uses a relative position so a comment stays attached to the right text
  even as edits happen elsewhere in the document.

---

## API reference

### REST endpoints (indicative)

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

Return **404, not 403**, when the caller has no permission row and the document isn't
link-shareable — this avoids revealing that a document exists to someone unauthorized.

### WebSocket protocol

- Client connects to `/sync/{document_id}`, passing an auth token in the handshake.
- Server resolves the caller's role **independently of any REST call** before allowing the
  Yjs room join — no inherited trust between layers.
- `viewer` / `commenter`: read-only on document content; `commenter` gets full read-write on
  the separate comments channel.
- `editor` / `owner`: full read-write on document content.
- Awareness messages (cursor position, selection, color) broadcast over the same connection
  but are never persisted or merged into document state.
- On a permission-change pub/sub event, the server re-validates the affected connection and
  either downgrades its write access or force-disconnects it.

---

## Real-time collaboration

- **CRDT, not OT** — Yjs assigns stable, position-independent IDs to content, so edits from
  any number of concurrent users converge without a central transform step.
- **Persistence** — the live Yjs document lives in memory (backed by Redis for
  multi-instance deployments) and is periodically flushed to `document_snapshots` in
  Postgres.
- **Offline support** — the client queues local Yjs updates in IndexedDB while offline; on
  reconnect, updates sync and merge automatically since CRDT merges are order-independent.
- **Comments as an overlay** — stored separately from document content, anchored via
  `RelativePosition` so they track the surrounding text through edits.

---

## Permissions & access control

| Role | View | Edit | Comment | Manage sharing | Delete |
|---|---|---|---|---|---|
| Owner | ✅ | ✅ | ✅ | ✅ | ✅ |
| Editor | ✅ | ✅ | ✅ | ❌ | ❌ |
| Commenter | ✅ | ❌ | ✅ | ❌ | ❌ |
| Viewer | ✅ | ❌ | ❌ | ❌ | ❌ |
| *(no permission row)* | ❌ | ❌ | ❌ | ❌ | ❌ |

**Enforcement checklist** — each layer checks independently:

- [ ] REST API checks role on every document-related endpoint
- [ ] WebSocket handshake checks role before allowing room join
- [ ] WebSocket message handler checks role on every incoming update, not just at connect
- [ ] Permission changes propagate live via Redis pub/sub to kick/downgrade active sessions
- [ ] Frontend reflects role (hides/disables UI) but is never the actual security boundary

---

## UI/UX principles

- **Minimal chrome** — muted toolbar and sidebar, the document is the visual focus.
- **Presence** — an avatar stack shows active collaborators; each user gets a stable color
  (derived from user ID) reused consistently across their cursor, avatar, and comment
  highlights.
- **Collaborator cursors** — a colored caret + name tag positioned via Yjs awareness data
  mapped to screen coordinates. The caret blinks (`step-end` animation, ~1s interval) with a
  per-user delay offset so cursors don't flash in sync; the name tag itself stays static.
  Cursors fade out after a few seconds of inactivity.
- **Status over spinners** — a small "saved / saving… / offline" indicator rather than
  blocking UI; editing should never feel gated on a network round-trip.
- **Role-driven rendering** — a viewer's Tiptap instance is simply non-editable with edit
  controls hidden, not shown-but-disabled.

---

## Roadmap

1. **Phase 0 — setup:** Docker Compose skeleton, basic auth, empty Tiptap editor with no
   persistence.
2. **Phase 1 — MVP:** Postgres persistence, live co-editing via Yjs + pycrdt-websocket
   between two browser tabs, presence cursors, document CRUD, sharing with the three core
   roles.
3. **Phase 2:** comments, version history, link-sharing, offline queueing.
4. **Phase 3:** suggestions mode, export (PDF/DOCX), notifications, search.
5. **Phase 4:** tables, images, folders, AI-assisted writing.

---

## Open decisions

- Single-owner model, or allow co-owners? (Current spec assumes a single owner.)
- MinIO for local object storage, or connect to real S3 from day one?
- REST API and realtime sync server as one FastAPI app or two separate deployables? (Two
  scales more cleanly later; one is simpler to run early on.)
- Roll auth with FastAPI-Users, or use a hosted provider (Clerk/Auth0)?

Resolve these before Phase 0 — they affect how the initial scaffold is laid out.

---

## Contributing

- Keep the REST and realtime layers decoupled — don't let document-content logic leak into
  REST handlers or auth logic leak into the sync server.
- Any new feature that touches permissions must update the enforcement checklist above and
  be tested at all three layers (REST, WebSocket handshake, WebSocket message handling).
- Run migrations via Alembic — no manual schema changes against a shared database.
