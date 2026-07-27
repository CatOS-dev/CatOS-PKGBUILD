from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def srcinfo(package: str) -> str:
    return subprocess.run(
        ["makepkg", "--printsrcinfo"],
        cwd=ROOT / package,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def field_values(text: str, name: str) -> list[str]:
    prefixes = (f"{name} = ", f"\t{name} = ")
    return [
        line.removeprefix(prefix)
        for line in text.splitlines()
        for prefix in prefixes
        if line.startswith(prefix)
    ]


class NoctaliaPackageTests(unittest.TestCase):
    def test_noctalia_srcinfo_uses_tagged_source_and_complete_build_dependencies(self) -> None:
        info = srcinfo("noctalia")
        self.assertEqual(field_values(info, "pkgbase"), ["noctalia"])
        self.assertEqual(field_values(info, "pkgver"), ["5.0.0_beta.5"])
        self.assertEqual(field_values(info, "arch"), ["x86_64"])
        source = "\n".join(field_values(info, "source"))
        self.assertIn("v5.0.0-beta.5", source)
        self.assertIn("disable-source-tree-assets.patch", source)
        self.assertNotIn("SKIP", "\n".join(field_values(info, "sha256sums")))
        dependencies = set(field_values(info, "depends") + field_values(info, "makedepends"))
        required = {
            "sdbus-cpp",
            "wayland",
            "wayland-protocols",
            "freetype2",
            "fontconfig",
            "cairo",
            "pango",
            "harfbuzz",
            "librsvg",
            "libxkbcommon",
            "glib2",
            "libsecret",
            "libsodium",
            "polkit",
            "pipewire",
            "wireplumber",
            "curl",
            "libqalculate",
            "libxml2",
            "md4c",
            "nlohmann-json",
            "tomlplusplus",
            "libwebp",
            "stb",
            "meson",
            "ninja",
            "pkgconf",
            "bash",
            "gcc-libs",
            "glibc",
            "hicolor-icon-theme",
        }
        self.assertEqual(required - dependencies, set())
        self.assertIn("tomlplusplus", field_values(info, "depends"))

        with tempfile.TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "noctalia"
            shutil.copytree(ROOT / "noctalia", package_dir)
            subprocess.run(
                ["makepkg", "--nobuild", "--nodeps", "--cleanbuild"],
                cwd=package_dir,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            meson = package_dir / "src/noctalia-5.0.0-beta.5/meson.build"
            prepared = meson.read_text(encoding="utf-8")
            main_definition = next(
                line for line in prepared.splitlines() if "NOCTALIA_SOURCE_ASSETS_DIR" in line
            )
            self.assertNotIn("meson.project_source_root()", main_definition)

    def test_greeter_srcinfo_and_prepare_remove_native_cpu_flags(self) -> None:
        info = srcinfo("noctalia-greeter")
        self.assertEqual(field_values(info, "pkgbase"), ["noctalia-greeter"])
        self.assertEqual(field_values(info, "pkgver"), ["1.0.0"])
        self.assertEqual(field_values(info, "arch"), ["x86_64"])
        source = "\n".join(field_values(info, "source"))
        self.assertIn("v1.0.0", source)
        self.assertIn("disable-native-optimizations.patch", source)
        self.assertIn("disable-source-tree-assets.patch", source)
        dependencies = set(field_values(info, "depends") + field_values(info, "makedepends"))
        required = {
            "greetd",
            "dbus",
            "wayland",
            "wayland-protocols",
            "wlroots0.20",
            "libinput",
            "libglvnd",
            "freetype2",
            "fontconfig",
            "cairo",
            "pango",
            "harfbuzz",
            "libxkbcommon",
            "glib2",
            "tomlplusplus",
            "nlohmann-json",
            "stb",
            "libwebp",
            "librsvg",
            "polkit",
            "meson",
            "ninja",
            "pkgconf",
            "bash",
            "gcc-libs",
            "glibc",
        }
        self.assertEqual(required - dependencies, set())

        with tempfile.TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "noctalia-greeter"
            shutil.copytree(ROOT / "noctalia-greeter", package_dir)
            subprocess.run(
                ["makepkg", "--nobuild", "--nodeps", "--cleanbuild"],
                cwd=package_dir,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            meson = package_dir / "src/noctalia-greeter-1.0.0/meson.build"
            prepared = meson.read_text(encoding="utf-8")
            self.assertNotIn("-march=native", prepared)
            self.assertNotIn("-mtune=native", prepared)
            asset_definition = next(
                line for line in prepared.splitlines() if "NOCTALIA_GREETER_ASSETS_DIR" in line
            )
            self.assertNotIn("meson.project_source_root()", asset_definition)

    def test_built_package_contents_when_artifacts_are_supplied(self) -> None:
        artifacts = {
            "NOCTALIA_PACKAGE": {
                "usr/bin/noctalia",
                "usr/share/applications/dev.noctalia.Noctalia.desktop",
                "usr/share/icons/hicolor/scalable/apps/noctalia.svg",
                "usr/share/noctalia/assets/",
            },
            "NOCTALIA_GREETER_PACKAGE": {
                "usr/bin/noctalia-greeter",
                "usr/bin/noctalia-greeter-compositor",
                "usr/bin/noctalia-greeter-session",
                "usr/bin/noctalia-greeter-apply-appearance",
                "usr/bin/noctalia-greeter-print-greetd-config",
                "usr/share/noctalia-greeter/assets/",
                "usr/share/polkit-1/actions/org.noctalia.greeter.apply-appearance.policy",
                "usr/lib/tmpfiles.d/noctalia-greeter.conf",
            },
        }
        if not all(os.environ.get(name) for name in artifacts):
            self.skipTest("built package artifact paths were not supplied")
        for env_name, expected in artifacts.items():
            package = os.environ[env_name]
            listing = subprocess.run(
                ["bsdtar", "-tf", package],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.splitlines()
            normalized = {entry.removeprefix("./") for entry in listing}
            for path in expected:
                if path.endswith("/"):
                    self.assertTrue(any(item.startswith(path) for item in normalized), path)
                else:
                    self.assertIn(path, normalized)
            if env_name == "NOCTALIA_PACKAGE":
                pkginfo = subprocess.run(
                    ["bsdtar", "-xOf", package, ".PKGINFO"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout
                self.assertIn("depend = tomlplusplus\n", pkginfo)


if __name__ == "__main__":
    unittest.main()
