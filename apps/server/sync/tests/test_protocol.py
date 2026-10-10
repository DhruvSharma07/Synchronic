import unittest

from protocol import (
    MSG_AWARENESS,
    MSG_SYNC,
    SYNC_STEP1,
    SYNC_STEP2,
    SYNC_UPDATE,
    ProtocolError,
    awareness_removal_message,
    parse_awareness_update,
    parse_message,
    read_var_string,
    read_var_uint,
    sync_step1_message,
    sync_step2_message,
    sync_update_message,
    write_var_string,
    write_var_uint,
)


class VarIntTests(unittest.TestCase):
    def test_roundtrip(self):
        for n in (0, 1, 127, 128, 255, 300, 16384, 2**32, 2**53):
            buf = write_var_uint(n)
            self.assertEqual(read_var_uint(buf, 0), (n, len(buf)))

    def test_known_encodings(self):
        self.assertEqual(write_var_uint(127), b"\x7f")
        self.assertEqual(write_var_uint(128), b"\x80\x01")
        self.assertEqual(write_var_uint(300), b"\xac\x02")

    def test_truncated_raises(self):
        with self.assertRaises(ProtocolError):
            read_var_uint(b"\x80", 0)

    def test_string_roundtrip(self):
        buf = write_var_string("héllo")
        self.assertEqual(read_var_string(buf, 0), ("héllo", len(buf)))


class MessageTests(unittest.TestCase):
    def test_sync_messages_roundtrip(self):
        self.assertEqual(parse_message(sync_step1_message(b"\x00")), (MSG_SYNC, SYNC_STEP1, b"\x00"))
        self.assertEqual(parse_message(sync_step2_message(b"abc")), (MSG_SYNC, SYNC_STEP2, b"abc"))
        big = b"x" * 1000
        self.assertEqual(parse_message(sync_update_message(big)), (MSG_SYNC, SYNC_UPDATE, big))

    def test_malformed_raises(self):
        for bad in (b"", b"\x00", b"\x00\x02\x05ab"):
            with self.assertRaises(ProtocolError):
                parse_message(bad)

    def test_awareness_removal_roundtrip(self):
        msg = awareness_removal_message([(7, 3), (1000, 0)])
        msg_type, sub, payload = parse_message(msg)
        self.assertEqual((msg_type, sub), (MSG_AWARENESS, None))
        self.assertEqual(parse_awareness_update(payload), [(7, 4), (1000, 1)])

    def test_awareness_parse_real_shape(self):
        # one client (id 5, clock 2) with state {"a":1}
        update = write_var_uint(1) + write_var_uint(5) + write_var_uint(2) + write_var_string('{"a":1}')
        self.assertEqual(parse_awareness_update(update), [(5, 2)])


if __name__ == "__main__":
    unittest.main()
