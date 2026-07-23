from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from catos_secureboot.signing import Signer, discover_kernel_targets, ensure_sbat, read_pe_section
from catos_secureboot.system import CommandResult, Runner


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
            if len([call for call in self.calls if call[0] == "sbverify"]) == 1:
                return CommandResult(returncode=1, stdout="", stderr="not signed")
            return CommandResult(returncode=0, stdout="valid", stderr="")
        if arguments[0] == "sbsign":
            output = Path(arguments[arguments.index("--output") + 1])
            source = Path(arguments[-1])
            output.write_bytes(source.read_bytes() + b"-signed")
            return CommandResult(returncode=0, stdout="", stderr="")
        raise AssertionError(arguments)


class SigningTests(unittest.TestCase):
    def test_missing_sbat_is_injected_at_an_aligned_pe_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "limine_x64.efi"
            source = root / "limine.csv"
            write_minimal_pe(image)
            source.write_text(
                "sbat,1,SBAT Version,sbat,1,https://github.com/rhboot/shim/blob/main/SBAT.md\n"
                "limine,1,Limine Bootloader,limine,1,https://limine-bootloader.org/\n",
                encoding="utf-8",
            )

            changed = ensure_sbat(image, source, Runner())
            unchanged = ensure_sbat(image, source, Runner())

            self.assertTrue(changed)
            self.assertFalse(unchanged)
            payload = read_pe_section(image, ".sbat")
            self.assertIsNotNone(payload)
            self.assertIn(b"limine,1,", payload or b"")

    def test_missing_sbat_requires_an_explicit_metadata_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "unknown.efi"
            write_minimal_pe(image)
            signer = Signer(key=Path("key"), certificate=Path("cert"), runner=FakeRunner())

            with self.assertRaisesRegex(RuntimeError, "has no SBAT metadata"):
                signer.sign_pe(image, require_sbat=True)

    def test_pe_signing_is_atomic_and_verified_after_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "machine.key"
            cert = root / "machine.crt"
            image = root / "grubx64.efi"
            key.write_text("key", encoding="utf-8")
            cert.write_text("cert", encoding="utf-8")
            image.write_bytes(b"efi")
            runner = FakeRunner()
            signer = Signer(key=key, certificate=cert, runner=runner)

            changed = signer.sign_pe(image)

            self.assertTrue(changed)
            self.assertEqual(image.read_bytes(), b"efi-signed")
            self.assertFalse(list(root.glob("*.catos-secureboot.tmp")))
            self.assertEqual(runner.calls[0][0], "sbverify")
            self.assertEqual(runner.calls[1][0], "sbsign")
            self.assertEqual(runner.calls[2][0], "sbverify")

    def test_vendor_shim_and_mok_manager_are_never_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("shimx64.efi", "mmx64.efi", "MokManager.efi", "grubx64.efi"):
                (root / name).write_bytes(b"efi")

            selected = Signer.filter_signable_efi(root.iterdir())

        self.assertEqual([path.name for path in selected], ["grubx64.efi"])

    def test_kernel_targets_include_canonical_and_boot_copies_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "usr/lib/modules/6.12.1/vmlinuz"
            boot_copy = root / "boot/vmlinuz-linux"
            symlink = root / "boot/vmlinuz-current"
            canonical.parent.mkdir(parents=True)
            boot_copy.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical")
            boot_copy.write_bytes(b"copy")
            symlink.symlink_to(canonical)

            selected = discover_kernel_targets(
                (
                    str(root / "usr/lib/modules/*/vmlinuz"),
                    str(root / "boot/vmlinuz-*"),
                )
            )

        self.assertEqual(selected, [boot_copy, canonical])


if __name__ == "__main__":
    unittest.main()
