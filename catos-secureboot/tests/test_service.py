from __future__ import annotations

from dataclasses import replace
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catos_secureboot.config import Config
from catos_secureboot.service import SecureBootService
from catos_secureboot.system import CommandResult


def write_minimal_pe(path: Path) -> None:
    data = bytearray(0x400)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    offset = 0x80
    data[offset : offset + 4] = b"PE\0\0"
    offset += 4
    struct.pack_into("<HHIIIHH", data, offset, 0x8664, 1, 0, 0, 0, 0xF0, 0x2022)
    offset += 20
    optional = offset
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 16, 0x1000)
    struct.pack_into("<Q", data, optional + 24, 0)
    struct.pack_into("<I", data, optional + 32, 0x1000)
    struct.pack_into("<I", data, optional + 36, 0x200)
    struct.pack_into("<I", data, optional + 56, 0x2000)
    struct.pack_into("<I", data, optional + 60, 0x200)
    struct.pack_into("<H", data, optional + 68, 10)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 0xF0
    data[section : section + 8] = b".text\0\0\0"
    struct.pack_into("<IIIIIIHHI", data, section + 8, 1, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    data[0x200] = 0xC3
    path.write_bytes(data)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: list[str], *, check: bool = True, input_text: str | None = None) -> CommandResult:
        del check, input_text
        self.calls.append(tuple(arguments))
        if arguments[0] == "sbverify":
            if arguments[1] == "--list":
                return CommandResult(0, "vendor signature", "")
            path = Path(arguments[-1])
            valid = path.is_file() and path.read_bytes().endswith(b"-signed")
            return CommandResult(0 if valid else 1, "", "")
        if arguments[0] == "sbsign":
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(Path(arguments[-1]).read_bytes() + b"-signed")
            return CommandResult(0, "", "")
        if arguments[0] == "objcopy":
            completed = subprocess.run(arguments, check=False, text=True, capture_output=True)
            if completed.returncode != 0:
                raise AssertionError(completed.stderr)
            return CommandResult(completed.returncode, completed.stdout, completed.stderr)
        if arguments[0] == "mkinitcpio":
            return CommandResult(0, "", "")
        raise AssertionError(arguments)


class ServiceTests(unittest.TestCase):
    def test_maintain_builds_and_deploys_complete_machine_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            boot = root / "boot"
            modules = root / "modules"
            keys = root / "keys"
            vendor = root / "vendor"
            version = modules / "6.12.1-catos"
            for path in (esp / "EFI/CatOS", boot, keys, vendor, version):
                path.mkdir(parents=True, exist_ok=True)
            (version / "pkgbase").write_text("linux\n", encoding="utf-8")
            (version / "vmlinuz").write_bytes(b"kernel")
            deployed_kernel = esp / "machine-id/6.12.1-catos/linux"
            deployed_kernel.parent.mkdir(parents=True)
            deployed_kernel.write_bytes(b"deployed-kernel")
            (boot / "initramfs-linux.img").write_bytes(b"initramfs")
            second_stage = esp / "EFI/CatOS/grubx64.efi"
            write_minimal_pe(second_stage)
            sbat_source = root / "grub.sbat.csv"
            sbat_source.write_text(
                "sbat,1,SBAT Version,sbat,1,https://github.com/rhboot/shim/blob/main/SBAT.md\n"
                "grub,4,Free Software Foundation,grub,2.14,https://www.gnu.org/software/grub/\n",
                encoding="utf-8",
            )
            (keys / "machine.key").write_bytes(b"key")
            (keys / "machine.crt").write_bytes(b"certificate")
            (keys / "machine.der").write_bytes(b"certificate-der")
            (vendor / "shimx64.efi").write_bytes(b"shim")
            (vendor / "mmx64.efi").write_bytes(b"mok-manager")
            cmdline = root / "cmdline"
            cmdline.write_text("root=UUID=test quiet\n", encoding="utf-8")
            config = replace(
                Config.defaults(),
                esp_path=esp,
                boot_path=boot,
                cmdline_path=cmdline,
                grub_dropin_path=root / "grub-secureboot.cfg",
                key_dir=keys,
                module_root=modules,
                kernel_globs=(str(version / "vmlinuz"), str(deployed_kernel)),
                vendor_shim=vendor / "shimx64.efi",
                vendor_mok_manager=vendor / "mmx64.efi",
                register_efi=False,
            )
            runner = FakeRunner()
            service = SecureBootService(config, runner)

            with (
                patch("catos_secureboot.service.os.geteuid", return_value=0),
                patch("catos_secureboot.service.second_stage_sbat_source", return_value=sbat_source),
            ):
                result = service.maintain()

            self.assertEqual(result["deployed"], 8)
            self.assertFalse(result["efi_registered"])
            self.assertEqual(result["kernels_signed"], 2)
            self.assertTrue((version / "vmlinuz").read_bytes().endswith(b"-signed"))
            self.assertTrue(deployed_kernel.read_bytes().endswith(b"-signed"))
            self.assertEqual((esp / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"shim")
            self.assertTrue((esp / "EFI/BOOT/grubx64.efi").read_bytes().endswith(b"-signed"))
            self.assertTrue(any(call[0] == "objcopy" for call in runner.calls))
            self.assertFalse(any(call[0] == "ukify" for call in runner.calls))
            enforced = cmdline.read_text(encoding="utf-8")
            self.assertIn("module.sig_enforce=1", enforced)
            self.assertIn("lockdown=integrity", enforced)


if __name__ == "__main__":
    unittest.main()
