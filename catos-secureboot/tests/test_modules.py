from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.modules import discover_external_modules


class ModuleTests(unittest.TestCase):
    def test_only_external_module_directories_are_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version = root / "6.12.1-catos"
            builtin = version / "kernel/drivers/gpu/drm/example.ko.zst"
            nvidia = version / "extramodules/nvidia.ko.zst"
            broadcom = version / "updates/wl.ko"
            builtin.parent.mkdir(parents=True)
            nvidia.parent.mkdir(parents=True)
            broadcom.parent.mkdir(parents=True)
            builtin.write_bytes(b"builtin")
            nvidia.write_bytes(b"nvidia")
            broadcom.write_bytes(b"wl")

            modules = discover_external_modules(root, ("updates", "extramodules"))

        self.assertEqual([path.name for path in modules], ["nvidia.ko.zst", "wl.ko"])


if __name__ == "__main__":
    unittest.main()
