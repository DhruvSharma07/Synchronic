import unittest

from roles import compute_role, has_role


class ComputeRoleTests(unittest.TestCase):
    def test_owner_by_owner_id(self):
        self.assertEqual(compute_role("u1", "u1", None, False, "viewer"), "owner")

    def test_no_row_no_link_is_no_access(self):
        self.assertIsNone(compute_role("u1", "u2", None, False, "viewer"))

    def test_explicit_role(self):
        self.assertEqual(compute_role("u1", "u2", "editor", False, "viewer"), "editor")
        self.assertEqual(compute_role("u1", "u2", "viewer", False, "viewer"), "viewer")

    def test_link_share_grants_role_only_when_enabled(self):
        self.assertEqual(compute_role("u1", "u2", None, True, "viewer"), "viewer")
        self.assertIsNone(compute_role("u1", "u2", None, False, "editor"))

    def test_highest_of_explicit_and_link_wins(self):
        self.assertEqual(compute_role("u1", "u2", "viewer", True, "editor"), "editor")
        self.assertEqual(compute_role("u1", "u2", "editor", True, "viewer"), "editor")

    def test_stray_owner_row_never_grants_ownership(self):
        self.assertEqual(compute_role("u1", "u2", "owner", False, "viewer"), "editor")

    def test_unknown_role_is_ignored(self):
        self.assertIsNone(compute_role("u1", "u2", "admin", False, "viewer"))

    def test_uuid_and_str_compare_equal(self):
        import uuid

        u = uuid.uuid4()
        self.assertEqual(compute_role(u, str(u), None, False, "viewer"), "owner")


class HasRoleTests(unittest.TestCase):
    def test_ranking(self):
        self.assertTrue(has_role("owner", "editor"))
        self.assertTrue(has_role("editor", "viewer"))
        self.assertFalse(has_role("viewer", "editor"))
        self.assertFalse(has_role(None, "viewer"))


if __name__ == "__main__":
    unittest.main()
