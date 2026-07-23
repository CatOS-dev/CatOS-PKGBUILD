from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.enforcement import ensure_cmdline_tokens


class EnforcementTests(unittest.TestCase):
    def test_required_kernel_parameters_are_added_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cmdline"
            path.write_text("root=UUID=test quiet\n", encoding="utf-8")

            first = ensure_cmdline_tokens(path, ("module.sig_enforce=1", "lockdown=integrity"))
            second = ensure_cmdline_tokens(path, ("module.sig_enforce=1", "lockdown=integrity"))

            content = path.read_text(encoding="utf-8")
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(content.count("module.sig_enforce=1"), 1)
        self.assertEqual(content.count("lockdown=integrity"), 1)


if __name__ == "__main__":
    unittest.main()
