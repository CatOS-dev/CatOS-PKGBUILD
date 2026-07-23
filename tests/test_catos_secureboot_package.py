from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "catos-secureboot"


class CatOSSecureBootPackageTests(unittest.TestCase):
    def test_package_contains_source_tests_and_vendor_pin(self):
        self.assertTrue((PACKAGE / "PKGBUILD").is_file())
        self.assertTrue((PACKAGE / "python/catos_secureboot/service.py").is_file())
        self.assertTrue((PACKAGE / "tests/test_service.py").is_file())
        pkgbuild = (PACKAGE / "PKGBUILD").read_text(encoding="utf-8")
        self.assertIn("shim-x64-16.1-5.x86_64.rpm", pkgbuild)
        self.assertIn("a1bbabaca8e4398b2483c678240f4be4803e91390b512a7b618da3bc88e49917", pkgbuild)
        self.assertIn("backup=('etc/catos/secureboot.conf')", pkgbuild)
        self.assertIn("CatOS-PKGBUILD/tree/main/catos-secureboot", pkgbuild)

    def test_package_does_not_force_uki(self):
        pkgbuild = (PACKAGE / "PKGBUILD").read_text(encoding="utf-8")
        service = (PACKAGE / "python/catos_secureboot/service.py").read_text(encoding="utf-8")
        self.assertNotIn("systemd-ukify", pkgbuild)
        self.assertNotIn("UkiBuilder", service)
        self.assertFalse((PACKAGE / "python/catos_secureboot/uki.py").exists())


if __name__ == "__main__":
    unittest.main()
