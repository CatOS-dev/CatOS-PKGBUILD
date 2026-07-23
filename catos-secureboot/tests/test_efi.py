from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catos_secureboot.efi import (
    deploy_boot_chain,
    deploy_uki_boot_chains,
    register_boot_entry,
    select_second_stage,
)
from catos_secureboot.system import CommandResult


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: list[str], *, check: bool = True, input_text: str | None = None) -> CommandResult:
        del check, input_text
        self.calls.append(tuple(arguments))
        if arguments == ["findmnt", "-n", "-o", "SOURCE", "--target", "/efi"]:
            return CommandResult(0, "/dev/nvme0n1p1\n", "")
        if arguments == ["lsblk", "-nro", "PKNAME", "/dev/nvme0n1p1"]:
            return CommandResult(0, "nvme0n1\n", "")
        if arguments == ["lsblk", "-nro", "PARTN", "/dev/nvme0n1p1"]:
            return CommandResult(0, "1\n", "")
        if arguments == ["efibootmgr"]:
            return CommandResult(0, "Boot0007* CatOS linux\tHD(...)\n", "")
        return CommandResult(0, "", "")


class EfiTests(unittest.TestCase):
    def test_deploys_vendor_chain_and_signed_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            shim = root / "shimx64.efi"
            mok_manager = root / "mmx64.efi"
            payload = root / "systemd-bootx64.efi"
            certificate = root / "machine.der"
            shim.write_bytes(b"shim")
            mok_manager.write_bytes(b"mok")
            payload.write_bytes(b"payload")
            certificate.write_bytes(b"certificate")

            deployed = deploy_boot_chain(
                esp=esp,
                shim=shim,
                mok_manager=mok_manager,
                second_stage=payload,
                certificate=certificate,
            )

            self.assertEqual((esp / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"shim")
            self.assertEqual((esp / "EFI/BOOT/mmx64.efi").read_bytes(), b"mok")
            self.assertEqual((esp / "EFI/BOOT/grubx64.efi").read_bytes(), b"payload")
            self.assertEqual((esp / "EFI/CatOS/shimx64.efi").read_bytes(), b"shim")
            self.assertEqual((esp / "EFI/CatOS/catos-machine.cer").read_bytes(), b"certificate")
            self.assertIn(esp / "EFI/CatOS/shimx64.efi", deployed)

    def test_selects_only_a_configured_second_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grub = root / "EFI/CatOS/grubx64.efi"
            grub.parent.mkdir(parents=True)
            grub.write_bytes(b"grub")

            selected = select_second_stage(root, ("EFI/CatOS/grubx64.efi",))

        self.assertEqual(selected, grub)

    def test_deploys_one_shim_chain_per_uki_and_uses_default_for_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            shim = root / "shimx64.efi"
            mok_manager = root / "mmx64.efi"
            certificate = root / "machine.der"
            linux = root / "catos-linux.efi"
            linux_lts = root / "catos-linux-lts.efi"
            shim.write_bytes(b"shim")
            mok_manager.write_bytes(b"mok")
            certificate.write_bytes(b"certificate")
            linux.write_bytes(b"linux-uki-signed")
            linux_lts.write_bytes(b"linux-lts-uki-signed")

            deployed, loaders = deploy_uki_boot_chains(
                esp=esp,
                shim=shim,
                mok_manager=mok_manager,
                certificate=certificate,
                ukis={"linux": linux, "linux-lts": linux_lts},
                default_package="linux",
            )

            self.assertEqual((esp / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"shim")
            self.assertEqual((esp / "EFI/BOOT/grubx64.efi").read_bytes(), b"linux-uki-signed")
            self.assertEqual((esp / "EFI/CatOS/grubx64.efi").read_bytes(), b"linux-uki-signed")
            self.assertEqual(
                (esp / "EFI/CatOS/UKI/linux-lts/grubx64.efi").read_bytes(),
                b"linux-lts-uki-signed",
            )
            self.assertEqual(loaders["linux"], "\\EFI\\CatOS\\UKI\\linux\\shimx64.efi")
            self.assertEqual(loaders["linux-lts"], "\\EFI\\CatOS\\UKI\\linux-lts\\shimx64.efi")
            self.assertIn(esp / "EFI/CatOS/UKI/linux/shimx64.efi", deployed)

    def test_registers_uki_label_to_per_kernel_shim_instead_of_direct_uki(self) -> None:
        runner = FakeRunner()

        register_boot_entry(
            esp=Path("/efi"),
            label="CatOS linux",
            loader="\\EFI\\CatOS\\UKI\\linux\\shimx64.efi",
            runner=runner,
        )

        self.assertIn(("efibootmgr", "--bootnum", "0007", "--delete-bootnum"), runner.calls)
        create = next(call for call in runner.calls if "--create" in call)
        self.assertEqual(create[create.index("--loader") + 1], "\\EFI\\CatOS\\UKI\\linux\\shimx64.efi")
        self.assertNotIn("\\EFI\\Linux\\catos-linux.efi", create)


if __name__ == "__main__":
    unittest.main()
