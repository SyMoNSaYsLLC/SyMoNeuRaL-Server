#!/usr/bin/env python3
"""Focused security contracts for both accounts routers.

These checks are intentionally small and stdlib-only.  They can run on a host that does
not have FastAPI installed: the route source is inspected as Python syntax, while the
password policy is exercised through the account core.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from apps import accounts  # noqa: E402


class TestPasswordSecurityContract(unittest.TestCase):
    def test_single_factor_passwords_use_the_current_minimum(self):
        self.assertGreaterEqual(accounts.MIN_PASSWORD_CHARS, 15)

    def test_new_scrypt_hashes_meet_the_current_memory_cost(self):
        self.assertGreaterEqual(accounts.SCRYPT_N, 1 << 17)
        self.assertEqual(accounts.SCRYPT_R, 8)
        self.assertEqual(accounts.SCRYPT_P, 1)

    def test_memory_hard_hashing_has_a_process_concurrency_cap(self):
        self.assertGreaterEqual(accounts.SCRYPT_MAX_CONCURRENT, 1)
        self.assertLessEqual(accounts.SCRYPT_MAX_CONCURRENT, 2)


class TestRouteSecurityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "backend" / "apps" / "accounts" / "routes.py"
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(cls.path))

    def _async_body(self, name: str) -> str:
        matches = [node for node in ast.walk(self.tree)
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == name]
        self.assertEqual(len(matches), 1, f"expected one async function named {name}")
        return ast.unparse(matches[0])

    def test_expensive_main_account_work_is_awaited(self):
        self.assertIn("await create_account_async(", self._async_body("signup"))
        self.assertIn("await verify_async(", self._async_body("login"))
        self.assertIn("await change_password_async(", self._async_body("password"))

    def test_expensive_bound_router_work_is_awaited(self):
        self.assertIn("await create_account_async(", self._async_body("_signup"))
        self.assertIn("await verify_async(", self._async_body("_login"))

    def test_account_responses_are_marked_no_store(self):
        self.assertIn("dependencies=[Depends(_no_store)]", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
