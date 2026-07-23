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
        self.assertIn("pkgver=0.1.1", pkgbuild)
        self.assertIn("pkgrel=1", pkgbuild)
        self.assertNotIn("pkgver=0.1.0", pkgbuild)
        self.assertIn("shim-x64-16.1-5.x86_64.rpm", pkgbuild)
        self.assertIn("a1bbabaca8e4398b2483c678240f4be4803e91390b512a7b618da3bc88e49917", pkgbuild)
        self.assertIn("usr/share/catos-secureboot/vendor/shimx64.efi", pkgbuild)
        self.assertIn("usr/share/catos-secureboot/vendor/mmx64.efi", pkgbuild)
        self.assertNotIn("systemd-ukify", pkgbuild)
        self.assertNotIn("ukify", pkgbuild)
        self.assertIn("efibootmgr", pkgbuild)
        self.assertIn("binutils", pkgbuild)
        self.assertIn("options=('!strip')", pkgbuild)
        self.assertNotIn("git+file://", pkgbuild)
        self.assertIn("packaging/limine.sbat.csv", pkgbuild)
        self.assertTrue((ROOT / "packaging/limine.sbat.csv").is_file())

    def test_hooks_split_kernel_preparation_from_efi_finalization(self) -> None:
        prepare = (ROOT / "packaging/75-catos-secureboot-prepare.hook").read_text(encoding="utf-8")
        finalize = (ROOT / "packaging/95-catos-secureboot-efi.hook").read_text(encoding="utf-8")

        self.assertIn("Target = usr/lib/modules/*/vmlinuz", prepare)
        self.assertIn("Target = usr/src/*/dkms.conf", prepare)
        self.assertIn("Exec = /usr/bin/catos-secureboot prepare --hook", prepare)
        self.assertNotIn("usr/share/limine", prepare)
        self.assertNotIn("EFI/", prepare)

        self.assertIn("Target = usr/lib/systemd/boot/efi/*.efi", finalize)
        self.assertIn("Target = usr/share/limine/*.EFI", finalize)
        self.assertIn("Target = grub", finalize)
        self.assertIn("Target = usr/lib/modules/*/vmlinuz", finalize)
        self.assertIn("Exec = /usr/bin/catos-secureboot finalize-efi --hook", finalize)
        self.assertFalse((ROOT / "packaging/95-catos-secureboot.hook").exists())

    def test_package_does_not_implement_or_generate_ukis(self) -> None:
        self.assertFalse((ROOT / "python/catos_secureboot/uki.py").exists())
        service = (ROOT / "python/catos_secureboot/service.py").read_text(encoding="utf-8")
        self.assertNotIn("UkiBuilder", service)
        self.assertNotIn("ukis_built", service)


if __name__ == "__main__":
    unittest.main()
