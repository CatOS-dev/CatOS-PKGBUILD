from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "catos-secureboot"


class CatOSSecureBootPackageTests(unittest.TestCase):
    def test_package_uses_versioned_source_archive_and_vendor_pin(self):
        self.assertTrue((PACKAGE / "PKGBUILD").is_file())
        self.assertFalse((PACKAGE / "python/catos_secureboot/service.py").exists())
        self.assertFalse((PACKAGE / "tests/test_service.py").exists())
        self.assertFalse((PACKAGE / "packaging").exists())
        pkgbuild = (PACKAGE / "PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("catos-secureboot/archive/refs/tags/v${pkgver}.tar.gz", pkgbuild)
        self.assertIn("2002b61c1f327d76ba629833612485cd9cfcfa82c1c4e365f642245f220035cd", pkgbuild)
        self.assertIn("shim-x64-16.1-5.x86_64.rpm", pkgbuild)
        self.assertIn("a1bbabaca8e4398b2483c678240f4be4803e91390b512a7b618da3bc88e49917", pkgbuild)
        self.assertIn("backup=('etc/catos/secureboot.conf')", pkgbuild)
        self.assertIn('cd "$srcdir/$pkgname-$pkgver"', pkgbuild)

    def test_package_keeps_uki_tools_optional(self):
        pkgbuild = (PACKAGE / "PKGBUILD").read_text(encoding="utf-8")
        self.assertNotIn("systemd-ukify", pkgbuild.split("optdepends=", 1)[0])
        self.assertIn("systemd-ukify: build systemd-boot Type #2 UKIs", pkgbuild)
        self.assertIn("catos-firmware-boot: build direct UKIs before shim deployment", pkgbuild)


if __name__ == "__main__":
    unittest.main()
