from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.kernels import (
    deploy_grub_kernel_copies,
    discover_grub_kernel_copies,
    verify_grub_kernel_copies,
)


class FakeSigner:
    def verify_pe(self, path: Path) -> bool:
        return path.read_bytes().endswith(b"-signed")


class KernelTests(unittest.TestCase):
    def test_uses_mkinitcpio_preset_destination_and_deploys_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "usr/lib/modules/7.1.5-1-cachyos/vmlinuz"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"kernel-signed")
            (canonical.parent / "pkgbase").write_text("linux-cachyos\n", encoding="utf-8")

            preset_dir = root / "etc/mkinitcpio.d"
            preset_dir.mkdir(parents=True)
            (preset_dir / "linux-cachyos.preset").write_text(
                'ALL_kver="/boot/custom-vmlinuz-linux-cachyos"\n',
                encoding="utf-8",
            )
            boot = root / "boot"
            deployed = boot / "custom-vmlinuz-linux-cachyos"
            deployed.parent.mkdir(parents=True)
            deployed.write_bytes(b"stale")

            copies = discover_grub_kernel_copies(
                [canonical],
                boot_path=boot,
                preset_dir=preset_dir,
            )
            changed = deploy_grub_kernel_copies(copies)
            verified = verify_grub_kernel_copies(copies, FakeSigner())

            self.assertEqual([copy.deployed for copy in copies], [deployed])
            self.assertEqual(changed, 1)
            self.assertEqual(verified, 1)
            self.assertEqual(deployed.read_bytes(), canonical.read_bytes())


if __name__ == "__main__":
    unittest.main()
