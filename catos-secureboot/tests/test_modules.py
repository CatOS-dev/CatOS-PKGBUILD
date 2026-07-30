from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.modules import discover_external_modules


class ModuleTests(unittest.TestCase):
    def test_discovers_dkms_modules_at_their_installed_kernel_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module_root = root / "usr/lib/modules"
            dkms_root = root / "var/lib/dkms"
            version = "7.1.5-1-cachyos"

            builtin = module_root / version / "kernel/drivers/gpu/drm/amd/amdgpu.ko.zst"
            nvidia = module_root / version / "kernel/drivers/video/nvidia.ko.zst"
            vbox = module_root / version / "kernel/misc/vboxdrv.ko.zst"
            legacy = module_root / version / "updates/wl.ko"
            for path in (builtin, nvidia, vbox, legacy):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(path.name.encode())

            for package, release, module in (
                ("nvidia", "610.43.03", "nvidia.ko.zst"),
                ("vboxhost", "7.2.14_OSE", "vboxdrv.ko.zst"),
            ):
                record = dkms_root / package / release / version / "x86_64/module" / module
                record.parent.mkdir(parents=True, exist_ok=True)
                record.write_bytes(b"dkms build output")

            modules = discover_external_modules(
                module_root,
                ("updates", "extramodules"),
                dkms_root=dkms_root,
            )

        self.assertEqual(modules, sorted((legacy, nvidia, vbox), key=str))
        self.assertNotIn(builtin, modules)


if __name__ == "__main__":
    unittest.main()
