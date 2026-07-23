from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.config import Config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_do_not_include_fallback_shim_path(self) -> None:
        config = Config.defaults()

        self.assertEqual(config.esp_path, Path("/boot/efi"))
        self.assertIn("EFI/Linux/*.efi", config.efi_globs)
        self.assertIn("/boot/efi/*/*/linux", config.kernel_globs)
        self.assertIn("/boot/efi/*/*/vmlinuz", config.kernel_globs)
        self.assertNotIn("EFI/BOOT/BOOT*.EFI", config.efi_globs)
        self.assertEqual(config.key_dir, Path("/var/lib/catos-secureboot/keys"))

    def test_toml_overrides_paths_and_module_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secureboot.conf"
            path.write_text(
                """
[secureboot]
esp_path = "/efi"
key_dir = "/keys"
efi_globs = ["EFI/CatOS/*.efi", "EFI/Linux/*.efi"]
module_directories = ["updates", "extramodules", "weak-updates"]
""".strip()
                + "\n",
                encoding="utf-8",
            )

            config = Config.load(path)

        self.assertEqual(config.esp_path, Path("/efi"))
        self.assertEqual(config.key_dir, Path("/keys"))
        self.assertEqual(config.efi_globs, ("EFI/CatOS/*.efi", "EFI/Linux/*.efi"))
        self.assertEqual(config.module_directories, ("updates", "extramodules", "weak-updates"))


if __name__ == "__main__":
    unittest.main()
