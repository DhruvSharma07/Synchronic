"""
Synchronic realtime sync server.

Speaks the y-websocket protocol (so the stock JS WebsocketProvider works
unchanged) on /sync/{document_id}?token=<access JWT>. Unlike an off-the-shelf
relay, every layer here enforces access itself:

  * Handshake: the JWT is validated and the caller's role resolved from
    Postgres *before* the socket is accepted; no role -> rejected (HTTP 403).
  * Messages: viewer/commenter writes are dropped on every incoming frame.
  * Live changes: the REST API publishes to Redis when access changes and the
    affected sessions are re-validated (downgraded or disconnected) at once.
  * Durability: room state is flushed to document_snapshots on an interval and
    when the last user leaves, and reloaded from Postgres on the next join.

Run ONE replica: rooms live in this process's memory. Scaling out needs sticky
routing per document id (or a shared Yjs backend), see README.
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect

from access import AuthError, Store, decode_access_token
from protocol import sync_step1_message
from rooms import Connection, RoomManager, listen_permission_events

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("synchronic.sync")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://synchronic:synchronic@127.0.0.1:5432/synchronic")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PERMISSION_CHANNEL = "synchronic:permissions"
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL_SECONDS", "5"))
REVALIDATE_INTERVAL = float(os.getenv("REVALIDATE_INTERVAL_SECONDS", "60"))

store = Store(DATABASE_URL)
manager = RoomManager(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(manager.flush_loop(FLUSH_INTERVAL)),
        asyncio.create_task(manager.revalidate_loop(REVALIDATE_INTERVAL)),
        asyncio.create_task(listen_permission_events(manager, REDIS_URL, PERMISSION_CHANNEL)),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await manager.shutdown()  # final flush so a restart loses nothing
    await store.dispose()


app = FastAPI(title="Synchronic Sync Server", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    try:
        await store.ping()
    except Exception:
        raise HTTPException(503, "Not ready")
    return {"status": "ok", "rooms": len(manager.rooms)}


async def _writer(conn: Connection) -> None:
    while True:
        data = await conn.queue.get()
        await conn.ws.send_bytes(data)


@app.websocket("/sync/{document_id}")
async def sync_endpoint(websocket: WebSocket, document_id: str):
    # Reject BEFORE accepting: closing pre-accept answers the upgrade with HTTP 403.
    try:
        doc_uuid = uuid.UUID(document_id)
        user_id = decode_access_token(websocket.query_params.get("token"))
        role = await store.resolve_role(doc_uuid, user_id)
    except (ValueError, AuthError):
        await websocket.close(code=4401)
        return
    except Exception:
        logger.exception("Handshake failed")
        await websocket.close(code=1011)
        return
    if role is None:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    conn = Connection(ws=websocket, user_id=user_id, role=role)
    try:
        room = await manager.join(doc_uuid, conn)
    except Exception:
        logger.exception("Could not load document %s", doc_uuid)
        await conn.close(1011, "could not load document")
        return

    writer = asyncio.create_task(_writer(conn))
    try:
        conn.send(sync_step1_message(room.doc.get_state()))
        for other in room.connections:
            if other is not conn and other.last_awareness:
                conn.send(other.last_awareness)
        while True:
            data = await websocket.receive_bytes()
            room.handle_message(conn, data)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info("Connection closed abnormally", exc_info=True)
    finally:
        writer.cancel()
        conn.closing = True
        await manager.leave(room, conn)
