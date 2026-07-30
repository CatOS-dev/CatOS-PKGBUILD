from __future__ import annotations

import unittest

from catos_secureboot.cli import parser


class CliTests(unittest.TestCase):
    def test_enable_accepts_an_explicit_boot_provider(self) -> None:
        options = parser().parse_args(["enable", "--provider", "grub", "--no-enroll"])

        self.assertEqual(options.command, "enable")
        self.assertEqual(options.provider, "grub")
        self.assertTrue(options.no_enroll)


if __name__ == "__main__":
    unittest.main()
