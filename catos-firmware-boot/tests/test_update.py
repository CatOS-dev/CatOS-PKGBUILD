from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "catos-firmware-boot-update"
loader = SourceFileLoader("catos_firmware_boot_update", str(SCRIPT))
spec = spec_from_loader(loader.name, loader)
module = module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)


class FirmwareBootUpdateTests(unittest.TestCase):
    def test_embedded_microcode_disables_legacy_ucode_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "mkinitcpio.conf"
            boot = root / "boot"
            boot.mkdir()
            (boot / "amd-ucode.img").write_bytes(b"ucode")
            config.write_text("HOOKS=(base udev microcode filesystems)\n", encoding="utf-8")
            self.assertEqual(module.microcode_images(config, boot), [])
            config.write_text("HOOKS=(base udev filesystems)\n", encoding="utf-8")
            self.assertEqual(module.microcode_images(config, boot), [boot / "amd-ucode.img"])

    def test_artifact_paths_use_standard_catos_names(self):
        configuration = module.Configuration(
            method="uki",
            esp_path=Path("/boot/efi"),
            efi_disk="/dev/nvme0n1",
            efi_partition=1,
            label_prefix="CatOS",
            default_kernel="linux",
        )
        kernel = module.Kernel(
            version="6.18.0",
            package="linux",
            image=Path("/usr/lib/modules/6.18.0/vmlinuz"),
            initramfs=Path("/boot/initramfs-linux.img"),
        )
        self.assertEqual(
            module.uki_output_path(configuration, kernel),
            Path("/boot/efi/EFI/Linux/catos-linux.efi"),
        )
        self.assertEqual(
            module.efistub_directory(configuration, kernel),
            Path("/boot/efi/EFI/CatOS/linux"),
        )

    def test_loader_path(self):
        self.assertEqual(module.loader_path("EFI/Linux/catos-linux.efi"), "\\EFI\\Linux\\catos-linux.efi")

    def test_entry_matching_does_not_confuse_kernel_names(self):
        self.assertTrue(module.entry_matches("CatOS linux HD(1,GPT,...)", "CatOS linux"))
        self.assertFalse(module.entry_matches("CatOS linux-lts HD(1,GPT,...)", "CatOS linux"))

    def test_configuration_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firmware-boot.conf"
            path.write_text(
                "[boot]\nmethod = uki\nesp_path = /boot/efi\n"
                "efi_disk = /dev/nvme0n1\nefi_partition = 1\n"
                "label_prefix = CatOS\n"
                "default_kernel = linux\n",
                encoding="utf-8",
            )
            config = module.load_configuration(path)
            self.assertEqual(config.method, "uki")
            self.assertEqual(config.efi_disk, "/dev/nvme0n1")
            self.assertEqual(config.efi_partition, 1)

    def test_invalid_method_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "firmware-boot.conf"
            path.write_text("[boot]\nmethod = grub\n", encoding="utf-8")
            with self.assertRaises(module.FirmwareBootError):
                module.load_configuration(path)

    def test_machine_secure_boot_management_applies_only_to_uki(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "machine.key"
            key.write_bytes(b"key")
            uki = module.Configuration("uki", Path("/efi"), "/dev/nvme0n1", 1, "CatOS", "linux")
            efistub = module.Configuration("efistub", Path("/efi"), "/dev/nvme0n1", 1, "CatOS", "linux")

            self.assertTrue(module.machine_secure_boot_managed(uki, key))
            self.assertFalse(module.machine_secure_boot_managed(efistub, key))
            key.unlink()
            self.assertFalse(module.machine_secure_boot_managed(uki, key))

    def test_managed_uki_build_does_not_register_direct_firmware_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration = module.Configuration(
                method="uki",
                esp_path=root / "efi",
                efi_disk="/dev/nvme0n1",
                efi_partition=1,
                label_prefix="CatOS",
                default_kernel="linux",
            )
            kernel = module.Kernel(
                version="7.1.4-test",
                package="linux",
                image=root / "vmlinuz",
                initramfs=root / "initramfs.img",
            )
            kernel.image.write_bytes(b"kernel")
            kernel.initramfs.write_bytes(b"initrd")

            def fake_run(arguments, *, capture=False):
                del capture
                output = Path(arguments[arguments.index("--output") + 1])
                output.write_bytes(b"uki")
                return mock.Mock(stdout="")

            with (
                mock.patch.object(module, "run", side_effect=fake_run),
                mock.patch.object(module, "replace_entry") as replace_entry,
                mock.patch.object(module, "microcode_images", return_value=[]),
            ):
                output = module.build_uki(
                    configuration,
                    kernel,
                    "quiet",
                    register_firmware=False,
                )

            self.assertEqual(output.read_bytes(), b"uki")
            replace_entry.assert_not_called()

    def test_managed_uki_verification_does_not_require_direct_firmware_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration = module.Configuration(
                method="uki",
                esp_path=root / "efi",
                efi_disk="/dev/nvme0n1",
                efi_partition=1,
                label_prefix="CatOS",
                default_kernel="linux",
            )
            kernel = module.Kernel(
                version="7.1.4-test",
                package="linux",
                image=root / "vmlinuz",
                initramfs=root / "initramfs.img",
            )
            output = module.uki_output_path(configuration, kernel)
            output.parent.mkdir(parents=True)
            output.write_bytes(b"uki")

            with mock.patch.object(module, "efi_entries", return_value=[]):
                module.verify(configuration, [kernel], require_entries=False)
                with self.assertRaises(module.FirmwareBootError):
                    module.verify(configuration, [kernel], require_entries=True)


if __name__ == "__main__":
    unittest.main()
