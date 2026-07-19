from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DmsPackageTests(unittest.TestCase):
    def test_shared_files_have_one_owner(self):
        common = ROOT / "catos-dms-common"
        self.assertTrue((common / "PKGBUILD").is_file())

        shared_files = (
            "90-dms.conf",
            "ghostty.conf",
            "ghostty-colors.conf",
        )
        for filename in shared_files:
            self.assertTrue((common / filename).is_file(), filename)
            self.assertFalse((ROOT / "catos-niri-dms" / filename).exists(), filename)
            self.assertFalse((ROOT / "catos-hyprland-dms" / filename).exists(), filename)

    def test_compositor_presets_depend_on_common_and_can_coexist(self):
        for package in ("catos-niri-dms", "catos-hyprland-dms"):
            pkgbuild = (ROOT / package / "PKGBUILD").read_text(encoding="utf-8")
            self.assertIn("'catos-dms-common'", pkgbuild, package)
            self.assertNotIn("conflicts=", pkgbuild, package)
            self.assertNotIn("90-dms.conf", pkgbuild, package)
            self.assertNotIn("ghostty.conf", pkgbuild, package)
            self.assertNotIn("ghostty-colors.conf", pkgbuild, package)

    def test_common_package_owns_shared_defaults(self):
        pkgbuild = (ROOT / "catos-dms-common" / "PKGBUILD").read_text(encoding="utf-8")
        for dependency in ("'ghostty'", "'matugen'"):
            self.assertIn(dependency, pkgbuild)
        for destination in (
            "etc/skel/.config/environment.d/90-dms.conf",
            "etc/skel/.config/ghostty/config",
            "etc/skel/.config/ghostty/themes/dankcolors",
        ):
            self.assertIn(destination, pkgbuild)
            self.assertIn(f"'{destination}'", pkgbuild.split("backup=(", 1)[1])


if __name__ == "__main__":
    unittest.main()
