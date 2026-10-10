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
7. [Deployment](#deployment)
8. [Environment variables](#environment-variables)
9. [Data model](#data-model)
10. [API reference](#api-reference)
11. [Real-time collaboration](#real-time-collaboration)
12. [Permissions & access control](#permissions--access-control)
13. [UI/UX principles](#uiux-principles)
14. [Roadmap](#roadmap)
15. [Open decisions](#open-decisions)
16. [Contributing](#contributing)

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

<img width="1590" height="795" alt="image" src="https://github.com/user-attachments/assets/fb9abb9c-24fc-4c4a-938e-c1361443296e" />


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
| Realtime transport | WebSockets (y-websocket protocol) | Implemented in `apps/server/sync` on `pycrdt`, so every message passes through our own auth and role checks |
| API server | [FastAPI](https://fastapi.tiangolo.com/) | Async, plays well with WebSockets |
| Database | PostgreSQL | Users, documents, permissions, comments, snapshots |
| Cache / pub-sub | Redis | Active-document cache; permission-change broadcast |
| Object storage | S3-compatible (or MinIO for local dev) | Exported files, embedded images |
| Background jobs | Celery or RQ | Exports, notifications, periodic snapshotting |
| Auth | Own JWT auth (FastAPI) | Short-lived access token + Redis-backed rotating refresh token; bcrypt passwords; login rate limiting |
| Frontend state (non-doc) | Zustand + React Router | Session/UI state, kept separate from Yjs doc state |
| Local dev / hosting | Docker Compose + Caddy | Dev stack with hot reload; production stack with automatic HTTPS |

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
│   │   │   ├── components/      # Toolbar, ShareDialog, PresenceStack, StatusBadge
│   │   │   ├── editor/          # Tiptap config, Yjs bindings, cursor rendering
│   │   │   ├── hooks/           # useCollabSession (Yjs doc + provider lifecycle)
│   │   │   ├── pages/           # Login, Documents, DocumentPage
│   │   │   ├── state/           # Zustand store (session state)
│   │   │   ├── api.ts           # typed REST client with transparent token refresh
│   │   │   └── tokens.ts        # token storage + single-flight refresh
│   │   ├── Dockerfile           # builds the SPA and serves it from Caddy
│   │   └── package.json
│   └── server/
│       ├── api/                 # FastAPI REST service (auth, users, documents, sharing)
│       │   ├── routers/         # auth, users, documents
│       │   ├── models.py        # SQLAlchemy models
│       │   ├── permissions.py   # require_role() dependency
│       │   ├── roles.py         # pure role resolution (unit-tested)
│       │   └── tests/
│       └── sync/                # FastAPI realtime service (y-websocket protocol on pycrdt)
│           ├── protocol.py      # wire format helpers (unit-tested)
│           ├── access.py        # JWT validation + Postgres role/snapshot access
│           ├── rooms.py         # rooms, per-message enforcement, persistence, live revalidation
│           ├── roles.py         # copy of api/roles.py (CI checks they are identical)
│           └── tests/
├── infra/
│   ├── Caddyfile                # production edge: static SPA + /api + /sync, automatic HTTPS
│   └── migrations/              # reserved for Alembic (schema is created at API startup today)
├── docs/
│   └── requirements.md          # Full requirements & architecture spec
├── .github/workflows/ci.yml     # tests, typecheck/build, docker build
├── docker-compose.yml           # local development
├── docker-compose.prod.yml      # production hosting
├── .env.example
└── README.md
```

---

## Getting started

### Prerequisites

- Node.js 18+ (22 recommended)
- Docker & Docker Compose
- Python 3.11+ only if you want to run the backends outside Docker or run the tests

### Run locally

```bash
cp .env.example .env            # defaults work for local development

# Postgres, Redis, API (:8000) and sync server (:8001), with hot reload
docker compose up --build

# In another terminal: the client on http://localhost:5173
cd apps/client
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/sync` to the backends, so the browser only ever
talks to one origin - the same shape as production. The API creates the database tables on
startup. Optional pgAdmin: `docker compose --profile tools up -d pgadmin` (http://localhost:5050).

### Try the full flow

1. Register two accounts (use a normal window and a private one).
2. As user A: **New document**, type something, then **Share** and add user B's email as
   *Editor* - B opens the document from their list and you edit together with live cursors.
3. Change B to *Viewer*: B's editor goes read-only immediately and further writes are
   rejected server-side. *Remove* B: their session is disconnected.

### Run the tests

```bash
cd apps/server/api  && python -m unittest discover -s tests -t .
cd apps/server/sync && python -m unittest discover -s tests -t .
cd apps/client      && npm run typecheck
```

---

## Deployment

`docker-compose.prod.yml` runs the whole product behind a single exposed container. Caddy
serves the built client and reverse-proxies `/api` (FastAPI) and `/sync` (WebSockets) on the
same origin, so there is no CORS to configure. Postgres, Redis, the API and the sync server
are only reachable on the internal Docker network.

```bash
cp .env.example .env
# Set at least:
#   POSTGRES_PASSWORD, REDIS_PASSWORD   (openssl rand -hex 24 - keep them URL-safe)
#   JWT_SECRET                          (openssl rand -hex 32)
#   SITE_ADDRESS                        (your domain for automatic HTTPS; leave as :80 for plain HTTP)
docker compose -f docker-compose.prod.yml up -d --build
```

Point your domain's DNS at the host and open ports 80/443. Caddy obtains and renews the TLS
certificate itself. In `APP_ENV=production` the services refuse to start with a weak
`JWT_SECRET`, and the API's interactive docs are disabled.

Operational notes:

- **Run exactly one `sync` replica.** Document rooms live in that process's memory; the
  service flushes to Postgres every few seconds, on last-leave, and on shutdown. Scaling out
  needs sticky routing per document id (or a shared Yjs backend) - see Roadmap.
- **The `api` service scales freely** (`API_WORKERS`, or more replicas) - it is stateless.
- **Back up the `db_data` volume** (`pg_dump`); `redis_data` only holds sessions.
- **Schema changes:** tables are created with `create_all` on API start, which never alters
  existing tables. Introduce Alembic (`infra/migrations/`) before the first schema change
  against a database holding real data.
- The sync handshake takes the access token as a `?token=` query parameter (browsers can't set
  WebSocket headers). The sync server runs with access logging off so tokens never reach logs;
  keep any extra proxy in front of it from logging query strings either.

---

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | api, sync | Postgres connection string (`postgresql://user:pass@host:5432/db`) |
| `REDIS_URL` | api, sync | Redis connection string; carries refresh-token state, rate limits and permission events |
| `JWT_SECRET` | api, sync | HS256 signing secret - must match across both; 32+ random chars in production |
| `APP_ENV` | api, sync | `production` enables strict secret checks and disables API docs |
| `CORS_ORIGINS` | api | Comma-separated cross-origin browser origins (unneeded when same-origin) |
| `FLUSH_INTERVAL_SECONDS` | sync | How often dirty documents are persisted (default 5) |
| `REVALIDATE_INTERVAL_SECONDS` | sync | Safety-net re-check of every live connection's role (default 60) |
| `API_WORKERS` | prod compose | Uvicorn workers for the API (default 2) |
| `SITE_ADDRESS` | prod compose | Domain for automatic HTTPS, or `:80` |
| `POSTGRES_*`, `REDIS_PASSWORD` | compose | Database/Redis credentials |
| `VITE_API_URL`, `VITE_SYNC_SERVER_URL` | client (optional) | Only if the backends live on a different origin than the client |
| `S3_*`, `SMTP_*` | - | Reserved for V1/V2 features (exports, uploads, notifications); unused today |

Keep `.env` out of version control; `.env.example` lists every key with a placeholder.

---

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

### REST endpoints

| Method | Path | Role required | Purpose | Status |
|---|---|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` | — | Account + token lifecycle | ✅ |
| GET | `/users/me`, `/users/search?q=` | signed in | Profile; find people to share with | ✅ |
| GET | `/documents` | — (filtered by permission) | List accessible documents | ✅ |
| POST | `/documents` | — | Create a document (creator becomes owner) | ✅ |
| GET | `/documents/{id}` | viewer | Fetch metadata + caller's role | ✅ |
| PATCH | `/documents/{id}` | editor (title) / owner (link sharing) | Rename; configure link sharing | ✅ |
| DELETE | `/documents/{id}` | owner | Delete document | ✅ |
| GET | `/documents/{id}/permissions` | owner | List collaborators | ✅ |
| POST | `/documents/{id}/permissions` | owner | Grant/change a user's role (`editor`/`viewer`, by email or user id) | ✅ |
| DELETE | `/documents/{id}/permissions/{user_id}` | owner | Revoke access | ✅ |
| POST | `/documents/{id}/transfer-ownership` | owner | Transfer ownership (previous owner becomes editor) | ✅ |
| GET/POST | `/documents/{id}/comments` | viewer / commenter | Comment threads | V1 |
| POST | `/documents/{id}/export` | viewer | Queue an export job | V2 |
| GET | `/documents/{id}/versions` | viewer | List version snapshots | V1 |
| GET | `/health`, `/health/ready` | — | Liveness / readiness (Postgres + Redis) | ✅ |

Return **404, not 403**, when the caller has no permission row and the document isn't
link-shareable — this avoids revealing that a document exists to someone unauthorized.

### WebSocket protocol

- Client connects to `/sync/{document_id}?token=<access JWT>` (the stock `y-websocket` provider; `Sec-WebSocket` headers can't carry auth from a browser). Close codes: `4401` bad/expired token, `4403` no access or access revoked, `4000` role changed (client refetches its role and reconnects).
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
- **Persistence** — the live Yjs document lives in memory in the sync server and is flushed to `document_snapshots` in Postgres every few seconds, when the last user leaves, and on shutdown. Each document has one merged "live" row (`label = '__live__'`, upserted); named version snapshots (V1) will be additional rows. Single replica for now - see Deployment.
- **Offline support (V1, not yet built)** — the client will queue local Yjs updates in IndexedDB while offline; on
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

**Enforcement checklist** — each layer checks independently (the `commenter` role is modelled and enforced as read-only until comments ship in V1; only `editor`/`viewer` can be granted for now):

- [x] REST API checks role on every document-related endpoint
- [x] WebSocket handshake checks role before allowing room join
- [x] WebSocket message handler checks role on every incoming update, not just at connect
- [x] Permission changes propagate live via Redis pub/sub to kick/downgrade active sessions
- [x] Frontend reflects role (hides/disables UI) but is never the actual security boundary

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
2. **Phase 1 — MVP (done):** Postgres persistence, live co-editing via Yjs between browser
   tabs, presence cursors, document CRUD, sharing with the core roles, production hosting.
3. **Phase 2:** comments, version history, link-sharing, offline queueing.
4. **Phase 3:** suggestions mode, export (PDF/DOCX), notifications, search.
5. **Phase 4:** tables, images, folders, AI-assisted writing.

---

## Open decisions

Resolved while building the MVP:

- **Ownership:** single owner (transferable); the previous owner becomes an editor.
- **Services:** two deployables - `api` (stateless, scalable) and `sync` (stateful rooms) - behind one Caddy edge.
- **Auth:** rolled our own JWT auth rather than FastAPI-Users or a hosted provider.
- **Sync transport:** the y-websocket protocol implemented directly on `pycrdt`, instead of `pycrdt-websocket`, so that handshake auth and per-message role checks sit in our code path.

Still open:

- MinIO for local object storage, or real S3 from day one? (Needed for V2 exports/images.)
- Scaling the sync tier beyond one replica: sticky routing per document vs. a shared Yjs backend.
- When to introduce Alembic (before the first schema change against real data).

---

## Contributing

- Keep the REST and realtime layers decoupled — don't let document-content logic leak into
  REST handlers or auth logic leak into the sync server.
- Any new feature that touches permissions must update the enforcement checklist above and
  be tested at all three layers (REST, WebSocket handshake, WebSocket message handling).
- Run migrations via Alembic — no manual schema changes against a shared database.
