from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_installed_wrapper_adds_private_library_directory(self) -> None:
        wrapper = (ROOT / "packaging/catos-secureboot").read_text(encoding="utf-8")
        self.assertIn('sys.path.insert(0, "/usr/lib/catos-secureboot")', wrapper)

    def test_source_tree_does_not_collide_with_makepkg_srcdir(self) -> None:
        self.assertTrue((ROOT / "python/catos_secureboot").is_dir())
        self.assertFalse((ROOT / "src/catos_secureboot").exists())
        pkgbuild = (ROOT / "PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("PYTHONPATH=python", pkgbuild)
        self.assertIn("python/catos_secureboot", pkgbuild)

    def test_package_pins_vendor_boot_chain_and_runtime_tools(self) -> None:
        pkgbuild = (ROOT / "PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("shim-x64-16.1-5.x86_64.rpm", pkgbuild)
        self.assertIn("a1bbabaca8e4398b2483c678240f4be4803e91390b512a7b618da3bc88e49917", pkgbuild)
        self.assertIn("usr/share/catos-secureboot/vendor/shimx64.efi", pkgbuild)
        self.assertIn("usr/share/catos-secureboot/vendor/mmx64.efi", pkgbuild)
        self.assertNotIn("systemd-ukify", pkgbuild)
        self.assertNotIn("ukify", pkgbuild)
        self.assertIn("efibootmgr", pkgbuild)
        self.assertIn("options=('!strip')", pkgbuild)
        self.assertNotIn("git+file://", pkgbuild)

    def test_hook_runs_after_kernel_module_and_bootloader_updates(self) -> None:
        hook = (ROOT / "packaging/95-catos-secureboot.hook").read_text(encoding="utf-8")
        self.assertIn("Target = usr/lib/modules/*/vmlinuz", hook)
        self.assertIn("Target = usr/src/*/dkms.conf", hook)
        self.assertIn("Target = usr/lib/systemd/boot/efi/*.efi", hook)
        self.assertIn("Target = usr/share/limine/*.EFI", hook)
        self.assertIn("Target = grub", hook)
        self.assertIn("Operation = Remove", hook)

    def test_package_does_not_implement_or_generate_ukis(self) -> None:
        self.assertFalse((ROOT / "python/catos_secureboot/uki.py").exists())
        service = (ROOT / "python/catos_secureboot/service.py").read_text(encoding="utf-8")
        self.assertNotIn("UkiBuilder", service)
        self.assertNotIn("ukis_built", service)


if __name__ == "__main__":
    unittest.main()
