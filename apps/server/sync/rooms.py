"""
Yjs rooms: one in-memory pycrdt Doc per open document, with connection
tracking, per-message write enforcement, periodic persistence, and live
permission re-validation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from protocol import (
    EMPTY_UPDATE,
    MSG_AWARENESS,
    MSG_QUERY_AWARENESS,
    MSG_SYNC,
    SYNC_STEP1,
    SYNC_STEP2,
    SYNC_UPDATE,
    ProtocolError,
    awareness_removal_message,
    parse_awareness_update,
    parse_message,
    sync_step2_message,
    sync_update_message,
)
from roles import ROLE_RANK

if TYPE_CHECKING:  # keep runtime imports light so this module is unit-testable
    from pycrdt import Doc
    from starlette.websockets import WebSocket

    from access import Store

logger = logging.getLogger("synchronic.sync")

CLOSE_ROLE_CHANGED = 4000  # client should refetch its role and reconnect
CLOSE_FORBIDDEN = 4403
CLOSE_SLOW_CONSUMER = 1013
WRITE_ROLES = ("editor", "owner")


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    user_id: uuid.UUID
    role: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2000))
    awareness_clients: dict[int, int] = field(default_factory=dict)  # client_id -> last clock
    last_awareness: bytes | None = None
    closing: bool = False

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    def send(self, data: bytes) -> None:
        """Queue a frame; never blocks the room on a slow client."""
        if self.closing:
            return
        try:
            self.queue.put_nowait(data)
        except asyncio.QueueFull:
            asyncio.create_task(self.close(CLOSE_SLOW_CONSUMER, "slow consumer"))

    async def close(self, code: int, reason: str = "") -> None:
        if self.closing:
            return
        self.closing = True
        try:
            await self.ws.close(code=code, reason=reason)
        except Exception:
            pass  # already closed


class Room:
    def __init__(self, document_id: uuid.UUID, doc: Doc):
        self.document_id = document_id
        self.doc = doc
        self.connections: set[Connection] = set()
        self.dirty = False
        self.deleted = False
        self.flush_lock = asyncio.Lock()

    def broadcast(self, data: bytes, exclude: Connection | None = None) -> None:
        for conn in list(self.connections):
            if conn is not exclude:
                conn.send(data)

    def handle_message(self, conn: Connection, data: bytes) -> None:
        try:
            msg_type, sub_type, payload = parse_message(data)
        except ProtocolError:
            return  # malformed frame: ignore, never crash the room

        if msg_type == MSG_SYNC:
            if sub_type == SYNC_STEP1:
                # Reading is allowed for every role that passed the handshake.
                try:
                    conn.send(sync_step2_message(self.doc.get_update(payload)))
                except Exception:
                    logger.warning("Bad state vector from client", exc_info=True)
            elif sub_type in (SYNC_STEP2, SYNC_UPDATE):
                # Role is re-checked on EVERY incoming write, not just at connect.
                if not conn.can_write:
                    return
                if payload == EMPTY_UPDATE:
                    return
                try:
                    self.doc.apply_update(payload)
                except Exception:
                    logger.warning("Rejected malformed update", exc_info=True)
                    return
                self.dirty = True
                self.broadcast(sync_update_message(payload), exclude=conn)

        elif msg_type == MSG_AWARENESS:
            try:
                entries = parse_awareness_update(payload)
            except ProtocolError:
                return
            for client_id, clock in entries:
                conn.awareness_clients[client_id] = clock
            conn.last_awareness = data
            self.broadcast(data, exclude=conn)  # presence is relayed, never persisted

        elif msg_type == MSG_QUERY_AWARENESS:
            for other in self.connections:
                if other is not conn and other.last_awareness:
                    conn.send(other.last_awareness)

    def announce_departure(self, conn: Connection) -> None:
        if conn.awareness_clients:
            self.broadcast(awareness_removal_message(list(conn.awareness_clients.items())), exclude=conn)


class RoomManager:
    def __init__(self, store: Store):
        self.store = store
        self.rooms: dict[uuid.UUID, Room] = {}
        self._lock = asyncio.Lock()  # guards room load / teardown

    async def join(self, document_id: uuid.UUID, conn: Connection) -> Room:
        async with self._lock:
            room = self.rooms.get(document_id)
            if room is None:
                from pycrdt import Doc

                doc = Doc()
                state = await self.store.load_state(document_id)
                if state:
                    doc.apply_update(state)
                room = Room(document_id, doc)
                self.rooms[document_id] = room
            room.connections.add(conn)
            return room

    async def leave(self, room: Room, conn: Connection) -> None:
        room.announce_departure(conn)
        async with self._lock:
            room.connections.discard(conn)
            if not room.connections:
                await self.flush(room)  # durable before the in-memory copy is dropped
                if self.rooms.get(room.document_id) is room:
                    del self.rooms[room.document_id]

    async def flush(self, room: Room) -> None:
        if room.deleted or not room.dirty:
            return
        async with room.flush_lock:
            if room.deleted or not room.dirty:
                return
            room.dirty = False
            try:
                saved = await self.store.save_state(room.document_id, room.doc.get_update())
                if not saved:
                    room.deleted = True  # document was deleted; nothing to persist
            except Exception:
                room.dirty = True  # retry on the next tick
                logger.exception("Failed to persist document %s", room.document_id)

    async def flush_loop(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            for room in list(self.rooms.values()):
                await self.flush(room)

    async def revalidate(self, room: Room, conn: Connection) -> None:
        try:
            role = await self.store.resolve_role(room.document_id, conn.user_id)
        except Exception:
            logger.exception("Role re-validation failed")
            return
        if role is None:
            await conn.close(CLOSE_FORBIDDEN, "access revoked")
        elif role != conn.role:
            conn.role = role  # takes effect on the very next message
            await conn.close(CLOSE_ROLE_CHANGED, "role changed")  # client refetches role, reconnects

    async def revalidate_loop(self, interval: float) -> None:
        """Safety net in case a pub/sub message is ever missed."""
        while True:
            await asyncio.sleep(interval)
            for room in list(self.rooms.values()):
                for conn in list(room.connections):
                    await self.revalidate(room, conn)

    async def handle_permission_event(self, event: dict) -> None:
        try:
            document_id = uuid.UUID(event["document_id"])
        except (KeyError, ValueError):
            return
        room = self.rooms.get(document_id)
        if room is None:
            return
        if event.get("deleted"):
            room.deleted = True
            for conn in list(room.connections):
                await conn.close(CLOSE_FORBIDDEN, "document deleted")
            return
        user_id = event.get("user_id")
        for conn in list(room.connections):
            if user_id is None or str(conn.user_id) == user_id:
                await self.revalidate(room, conn)

    async def shutdown(self) -> None:
        for room in list(self.rooms.values()):
            for conn in list(room.connections):
                await conn.close(1001, "server shutting down")
            await self.flush(room)


async def listen_permission_events(manager: RoomManager, redis_url: str, channel: str) -> None:
    import redis.asyncio as redis

    while True:
        client = redis.from_url(redis_url, decode_responses=True)
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    await manager.handle_permission_event(json.loads(message["data"]))
                except Exception:
                    logger.exception("Bad permission event")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Permission listener lost Redis; retrying")
            await asyncio.sleep(2)
        finally:
            try:
                await client.aclose()
            except Exception:
                pass
