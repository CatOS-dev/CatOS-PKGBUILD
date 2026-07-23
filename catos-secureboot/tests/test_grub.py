from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.grub import GRUB_PRELOAD_MODULES, rebuild_grub_core, select_grub_modules
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
    def test_preload_set_covers_supported_boot_paths_without_native_disk_drivers(self) -> None:
        required = {
            "normal",
            "configfile",
            "linux",
            "btrfs",
            "ext2",
            "fat",
            "xfs",
            "zfs",
            "cryptodisk",
            "luks",
            "luks2",
            "lvm",
            "mdraid1x",
            "search",
            "probe",
            "efi_gop",
            "tpm",
            "tpm2_key_protector",
            "zstd",
            "xzio",
        }
        prohibited = {
            "nativedisk",
            "ahci",
            "ata",
            "pata",
            "usbms",
            "uhci",
            "ohci",
            "ehci",
            "memdisk",
            "memrw",
            "iorw",
            "functional_test",
            "argon2_test",
            "testload",
            "testspeed",
            "usbtest",
            "videotest",
        }

        self.assertTrue(required.issubset(GRUB_PRELOAD_MODULES))
        self.assertTrue(prohibited.isdisjoint(GRUB_PRELOAD_MODULES))
        self.assertEqual(tuple(sorted(set(GRUB_PRELOAD_MODULES))), GRUB_PRELOAD_MODULES)

    def test_selects_only_the_curated_modules_and_rejects_incomplete_grub_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            modules = Path(directory)
            for name in GRUB_PRELOAD_MODULES:
                (modules / f"{name}.mod").write_bytes(b"module")
            (modules / "nativedisk.mod").write_bytes(b"must-not-preload")
            (modules / "normal.mod").unlink()

            with self.assertRaisesRegex(RuntimeError, "normal"):
                select_grub_modules(modules)

            (modules / "normal.mod").write_bytes(b"module")
            self.assertEqual(select_grub_modules(modules), GRUB_PRELOAD_MODULES)

    def test_rebuilds_installed_grub_with_curated_modules_inside_the_signed_core(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            boot = root / "boot"
            modules = root / "grub-modules"
            sbat = root / "sbat.csv"
            output = esp / "EFI/CatOS/grubx64.efi"
            modules.mkdir()
            for name in GRUB_PRELOAD_MODULES:
                (modules / f"{name}.mod").write_bytes(b"module")
            (modules / "nativedisk.mod").write_bytes(b"must-not-preload")
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

            self.assertEqual(module_count, len(GRUB_PRELOAD_MODULES))
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
            self.assertIn(f"--modules={' '.join(GRUB_PRELOAD_MODULES)}", command)
            self.assertNotIn("nativedisk", command[-1].split("=", 1)[1].split())
            self.assertNotIn("--disable-shim-lock", command)


if __name__ == "__main__":
    unittest.main()
