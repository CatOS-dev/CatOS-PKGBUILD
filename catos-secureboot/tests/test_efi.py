from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.efi import deploy_boot_chain, select_second_stage


class EfiTests(unittest.TestCase):
    def test_deploys_vendor_chain_and_signed_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            shim = root / "shimx64.efi"
            mok_manager = root / "mmx64.efi"
            payload = root / "systemd-bootx64.efi"
            certificate = root / "machine.der"
            shim.write_bytes(b"shim")
            mok_manager.write_bytes(b"mok")
            payload.write_bytes(b"payload")
            certificate.write_bytes(b"certificate")

            deployed = deploy_boot_chain(
                esp=esp,
                shim=shim,
                mok_manager=mok_manager,
                second_stage=payload,
                certificate=certificate,
            )

            self.assertEqual((esp / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"shim")
            self.assertEqual((esp / "EFI/BOOT/mmx64.efi").read_bytes(), b"mok")
            self.assertEqual((esp / "EFI/BOOT/grubx64.efi").read_bytes(), b"payload")
            self.assertEqual((esp / "EFI/CatOS/shimx64.efi").read_bytes(), b"shim")
            self.assertEqual((esp / "EFI/CatOS/catos-machine.cer").read_bytes(), b"certificate")
            self.assertIn(esp / "EFI/CatOS/shimx64.efi", deployed)

    def test_selects_only_a_configured_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grub = root / "EFI/CatOS/grubx64.efi"
            grub.parent.mkdir(parents=True)
            grub.write_bytes(b"grub")

            selected = select_second_stage(root, ("EFI/CatOS/grubx64.efi",))

        self.assertEqual(selected, grub)


if __name__ == "__main__":
    unittest.main()
