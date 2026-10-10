"""Enforcement + persistence logic of rooms.py, driven with in-memory fakes."""
import asyncio
import unittest
import uuid

from protocol import (
    MSG_AWARENESS,
    MSG_SYNC,
    SYNC_STEP2,
    SYNC_UPDATE,
    parse_message,
    sync_step1_message,
    sync_step2_message,
    sync_update_message,
    write_var_string,
    write_var_uint,
)
from rooms import CLOSE_FORBIDDEN, CLOSE_ROLE_CHANGED, Connection, Room, RoomManager

UPDATE = b"\x01\x01\x05\x00"  # opaque bytes; the fake doc doesn't interpret them


class FakeDoc:
    def __init__(self):
        self.applied = []

    def apply_update(self, update):
        if update == b"BAD":
            raise ValueError("malformed")
        self.applied.append(update)

    def get_update(self, state=None):
        return b"full-state" if state is None else b"diff-for-" + state

    def get_state(self):
        return b"sv"


class FakeWS:
    def __init__(self):
        self.closed = None

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


def make_conn(role):
    return Connection(ws=FakeWS(), user_id=uuid.uuid4(), role=role)


def drain(conn):
    out = []
    while not conn.queue.empty():
        out.append(conn.queue.get_nowait())
    return out


class FakeStore:
    def __init__(self, role="editor"):
        self.role = role
        self.saved = []
        self.exists = True
        self.fail = False

    async def resolve_role(self, document_id, user_id):
        return self.role

    async def save_state(self, document_id, state):
        if self.fail:
            raise RuntimeError("db down")
        if not self.exists:
            return False
        self.saved.append(state)
        return True


class WriteEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.room = Room(uuid.uuid4(), FakeDoc())
        self.editor, self.viewer, self.other = make_conn("editor"), make_conn("viewer"), make_conn("owner")
        self.room.connections.update({self.editor, self.viewer, self.other})

    def test_editor_update_applied_and_broadcast_to_others_only(self):
        self.room.handle_message(self.editor, sync_update_message(UPDATE))
        self.assertEqual(self.room.doc.applied, [UPDATE])
        self.assertTrue(self.room.dirty)
        for peer in (self.viewer, self.other):
            self.assertEqual(parse_message(drain(peer)[0]), (MSG_SYNC, SYNC_UPDATE, UPDATE))
        self.assertEqual(drain(self.editor), [])

    def test_step2_from_editor_is_applied_too(self):
        self.room.handle_message(self.editor, sync_step2_message(UPDATE))
        self.assertEqual(self.room.doc.applied, [UPDATE])

    def test_viewer_writes_are_dropped(self):
        for msg in (sync_update_message(UPDATE), sync_step2_message(UPDATE)):
            self.room.handle_message(self.viewer, msg)
        self.assertEqual(self.room.doc.applied, [])
        self.assertFalse(self.room.dirty)
        self.assertEqual(drain(self.editor) + drain(self.other), [])

    def test_commenter_cannot_write_in_mvp(self):
        c = make_conn("commenter")
        self.room.handle_message(c, sync_update_message(UPDATE))
        self.assertEqual(self.room.doc.applied, [])

    def test_downgrade_takes_effect_on_next_message(self):
        self.room.handle_message(self.editor, sync_update_message(UPDATE))
        self.editor.role = "viewer"
        self.room.handle_message(self.editor, sync_update_message(b"\x09\x09"))
        self.assertEqual(self.room.doc.applied, [UPDATE])

    def test_viewer_can_still_read(self):
        self.room.handle_message(self.viewer, sync_step1_message(b"abc"))
        self.assertEqual(parse_message(drain(self.viewer)[0]), (MSG_SYNC, SYNC_STEP2, b"diff-for-abc"))

    def test_malformed_and_bad_updates_never_crash_or_dirty(self):
        self.room.handle_message(self.editor, b"")
        self.room.handle_message(self.editor, b"\x00")
        self.room.handle_message(self.editor, sync_update_message(b"BAD"))
        self.room.handle_message(self.editor, sync_update_message(b"\x00\x00"))  # empty update
        self.assertEqual(self.room.doc.applied, [])
        self.assertFalse(self.room.dirty)

    def test_awareness_relayed_even_from_viewers_and_removed_on_leave(self):
        update = write_var_uint(1) + write_var_uint(42) + write_var_uint(5) + write_var_string('{"user":{}}')
        frame = bytes([MSG_AWARENESS]) + write_var_uint(len(update)) + update
        self.room.handle_message(self.viewer, frame)
        self.assertEqual(drain(self.editor), [frame])
        self.assertEqual(self.viewer.last_awareness, frame)

        self.room.announce_departure(self.viewer)
        removal = drain(self.editor)[0]
        self.assertEqual(parse_message(removal)[0], MSG_AWARENESS)


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_flush_only_when_dirty(self):
        store = FakeStore()
        mgr, room = RoomManager(store), Room(uuid.uuid4(), FakeDoc())
        await mgr.flush(room)
        self.assertEqual(store.saved, [])
        room.dirty = True
        await mgr.flush(room)
        self.assertEqual(store.saved, [b"full-state"])
        self.assertFalse(room.dirty)

    async def test_flush_failure_keeps_room_dirty_for_retry(self):
        store = FakeStore()
        store.fail = True
        mgr, room = RoomManager(store), Room(uuid.uuid4(), FakeDoc())
        room.dirty = True
        await mgr.flush(room)
        self.assertTrue(room.dirty)

    async def test_flush_marks_deleted_documents(self):
        store = FakeStore()
        store.exists = False
        mgr, room = RoomManager(store), Room(uuid.uuid4(), FakeDoc())
        room.dirty = True
        await mgr.flush(room)
        self.assertTrue(room.deleted)

    async def test_leave_flushes_and_drops_empty_room(self):
        store = FakeStore()
        mgr = RoomManager(store)
        room, conn = Room(uuid.uuid4(), FakeDoc()), make_conn("editor")
        room.connections.add(conn)
        room.dirty = True
        mgr.rooms[room.document_id] = room
        await mgr.leave(room, conn)
        self.assertEqual(store.saved, [b"full-state"])
        self.assertNotIn(room.document_id, mgr.rooms)

    async def test_revoked_access_disconnects(self):
        store = FakeStore(role=None)
        mgr, room, conn = RoomManager(store), Room(uuid.uuid4(), FakeDoc()), make_conn("editor")
        room.connections.add(conn)
        await mgr.revalidate(room, conn)
        self.assertEqual(conn.ws.closed[0], CLOSE_FORBIDDEN)

    async def test_role_change_updates_role_and_forces_reconnect(self):
        store = FakeStore(role="viewer")
        mgr, room, conn = RoomManager(store), Room(uuid.uuid4(), FakeDoc()), make_conn("editor")
        room.connections.add(conn)
        await mgr.revalidate(room, conn)
        self.assertEqual(conn.role, "viewer")
        self.assertEqual(conn.ws.closed[0], CLOSE_ROLE_CHANGED)

    async def test_unchanged_role_leaves_connection_alone(self):
        store = FakeStore(role="editor")
        mgr, room, conn = RoomManager(store), Room(uuid.uuid4(), FakeDoc()), make_conn("editor")
        await mgr.revalidate(room, conn)
        self.assertIsNone(conn.ws.closed)

    async def test_permission_event_targets_only_that_user(self):
        store = FakeStore(role=None)
        mgr, room = RoomManager(store), Room(uuid.uuid4(), FakeDoc())
        a, b = make_conn("editor"), make_conn("editor")
        room.connections.update({a, b})
        mgr.rooms[room.document_id] = room
        await mgr.handle_permission_event({"document_id": str(room.document_id), "user_id": str(a.user_id)})
        self.assertIsNotNone(a.ws.closed)
        self.assertIsNone(b.ws.closed)

    async def test_document_deleted_event_closes_everyone_and_blocks_persist(self):
        store = FakeStore()
        mgr, room = RoomManager(store), Room(uuid.uuid4(), FakeDoc())
        a = make_conn("owner")
        room.connections.add(a)
        room.dirty = True
        mgr.rooms[room.document_id] = room
        await mgr.handle_permission_event({"document_id": str(room.document_id), "deleted": True})
        self.assertEqual(a.ws.closed[0], CLOSE_FORBIDDEN)
        await mgr.flush(room)
        self.assertEqual(store.saved, [])


if __name__ == "__main__":
    unittest.main()
