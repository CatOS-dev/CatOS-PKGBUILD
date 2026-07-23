from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.grub import discover_grub_modules, rebuild_grub_core
from catos_secureboot.system import CommandResult


class FakeRunner:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: list[str], *, check: bool = True, input_text: str | None = None) -> CommandResult:
        del check, input_text
        self.calls.append(tuple(arguments))
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(b"rebuilt-grub-core")
        return CommandResult(0, "", "")


class GrubTests(unittest.TestCase):
    def test_discovers_every_platform_module_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            modules = Path(directory)
            for name in ("zfs.mod", "normal.mod", "linux.mod", "test.mod"):
                (modules / name).write_bytes(b"module")
            (modules / "moddep.lst").write_text("", encoding="utf-8")

            self.assertEqual(
                discover_grub_modules(modules),
                ("linux", "normal", "test", "zfs"),
            )

    def test_rebuilds_installed_grub_with_all_modules_inside_the_signed_core(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            boot = root / "boot"
            modules = root / "grub-modules"
            sbat = root / "sbat.csv"
            output = esp / "EFI/CatOS/grubx64.efi"
            modules.mkdir()
            for name in ("normal.mod", "linux.mod", "btrfs.mod", "luks2.mod"):
                (modules / name).write_bytes(b"module")
            sbat.write_text("sbat,1,SBAT Version,sbat,1,https://example.invalid\n", encoding="utf-8")
            runner = FakeRunner(output)

            module_count = rebuild_grub_core(
                esp_path=esp,
                boot_path=boot,
                second_stage=output,
                module_directory=modules,
                sbat_path=sbat,
                runner=runner,
            )

            self.assertEqual(module_count, 4)
            self.assertEqual(output.read_bytes(), b"rebuilt-grub-core")
            command = runner.calls[0]
            self.assertEqual(command[0], "grub-install")
            self.assertIn("--target=x86_64-efi", command)
            self.assertIn(f"--directory={modules}", command)
            self.assertIn(f"--efi-directory={esp}", command)
            self.assertIn(f"--boot-directory={boot}", command)
            self.assertIn("--bootloader-id=CatOS", command)
            self.assertIn("--no-nvram", command)
            self.assertIn("--recheck", command)
            self.assertIn(f"--sbat={sbat}", command)
            self.assertIn("--modules=btrfs linux luks2 normal", command)
            self.assertNotIn("--disable-shim-lock", command)


if __name__ == "__main__":
    unittest.main()
