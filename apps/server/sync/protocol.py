"""
Minimal y-protocols wire format (the subset a y-websocket client speaks).

Message layout (lib0 varint encoding):
  [0=sync]      [0=step1|1=step2|2=update] [varuint len][payload]
  [1=awareness] [varuint len][awareness update]
  [3=queryAwareness]

No third-party imports, so it is unit-testable without the server stack.
"""
from __future__ import annotations

MSG_SYNC = 0
MSG_AWARENESS = 1
MSG_AUTH = 2
MSG_QUERY_AWARENESS = 3

SYNC_STEP1 = 0
SYNC_STEP2 = 1
SYNC_UPDATE = 2

EMPTY_UPDATE = b"\x00\x00"  # an update that carries no structs and no deletes


class ProtocolError(ValueError):
    pass


def write_var_uint(n: int) -> bytes:
    if n < 0:
        raise ProtocolError("negative varuint")
    out = bytearray()
    while n > 0x7F:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    out.append(n)
    return bytes(out)


def read_var_uint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ProtocolError("truncated varuint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ProtocolError("varuint too long")


def write_var_bytes(data: bytes) -> bytes:
    return write_var_uint(len(data)) + data


def read_var_bytes(buf: bytes, pos: int) -> tuple[bytes, int]:
    length, pos = read_var_uint(buf, pos)
    end = pos + length
    if end > len(buf):
        raise ProtocolError("truncated bytes")
    return buf[pos:end], end


def write_var_string(s: str) -> bytes:
    return write_var_bytes(s.encode("utf-8"))


def read_var_string(buf: bytes, pos: int) -> tuple[str, int]:
    raw, pos = read_var_bytes(buf, pos)
    try:
        return raw.decode("utf-8"), pos
    except UnicodeDecodeError as exc:
        raise ProtocolError("invalid utf-8") from exc


def sync_step1_message(state_vector: bytes) -> bytes:
    return bytes([MSG_SYNC, SYNC_STEP1]) + write_var_bytes(state_vector)


def sync_step2_message(update: bytes) -> bytes:
    return bytes([MSG_SYNC, SYNC_STEP2]) + write_var_bytes(update)


def sync_update_message(update: bytes) -> bytes:
    return bytes([MSG_SYNC, SYNC_UPDATE]) + write_var_bytes(update)


def parse_message(data: bytes) -> tuple[int, int | None, bytes]:
    """Return (message_type, sync_subtype or None, payload)."""
    if not data:
        raise ProtocolError("empty message")
    msg_type = data[0]
    if msg_type == MSG_SYNC:
        if len(data) < 2:
            raise ProtocolError("truncated sync message")
        payload, _ = read_var_bytes(data, 2)
        return msg_type, data[1], payload
    if msg_type == MSG_AWARENESS:
        payload, _ = read_var_bytes(data, 1)
        return msg_type, None, payload
    return msg_type, None, b""


def parse_awareness_update(payload: bytes) -> list[tuple[int, int]]:
    """(client_id, clock) pairs from an awareness update payload."""
    count, pos = read_var_uint(payload, 0)
    entries = []
    for _ in range(count):
        client_id, pos = read_var_uint(payload, pos)
        clock, pos = read_var_uint(payload, pos)
        _state, pos = read_var_string(payload, pos)
        entries.append((client_id, clock))
    return entries


def awareness_removal_message(entries: list[tuple[int, int]]) -> bytes:
    """Awareness message marking each (client_id, clock) offline (state 'null').

    Clock is bumped by one so receivers accept it as newer. This is what lets
    other users' cursors disappear the moment someone disconnects instead of
    after the client-side 30s awareness timeout.
    """
    update = write_var_uint(len(entries))
    for client_id, clock in entries:
        update += write_var_uint(client_id) + write_var_uint(clock + 1) + write_var_string("null")
    return bytes([MSG_AWARENESS]) + write_var_bytes(update)
