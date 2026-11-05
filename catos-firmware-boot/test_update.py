from contextlib import contextmanager
from dataclasses import replace
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(os.environ["FIRMWARE_BOOT_SCRIPT"]) if "FIRMWARE_BOOT_SCRIPT" in os.environ else Path(__file__).resolve().parent / "catos-firmware-boot-update"
loader = SourceFileLoader("catos_firmware_boot_update", str(SCRIPT))
spec = spec_from_loader(loader.name, loader)
module = module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)


class Programs:
    def __init__(self):
        self.calls = []
        self.entries = {"0001": "Existing system\tHD(1,GPT,foreign,0,0)/File(\\EFI\\other.efi)"}
        self.order = ["0001"]
        self.current = "0001"
        self.next_boot = ""
        self.serial = 2
        self.initrd_suffix = b""
        self.fail_create = False
        self.fail_order = False
        self.allow_firmware = False

    def run(self, arguments, *, capture=False):
        self.calls.append(list(arguments))
        program = arguments[0]
        if program == "mkinitcpio":
            version = arguments[arguments.index("--kernel") + 1]
            output = Path(arguments[arguments.index("--generate") + 1])
            output.write_bytes(b"initrd:" + version.encode() + self.initrd_suffix)
            return subprocess.CompletedProcess(arguments, 0, "")
        if program == "ukify":
            output = Path(arguments[arguments.index("--output") + 1])
            kernel = Path(arguments[arguments.index("--linux") + 1])
            initrd = Path(arguments[arguments.index("--initrd") + 1])
            output.write_bytes(b"UKI:" + kernel.read_bytes() + b":" + initrd.read_bytes())
            return subprocess.CompletedProcess(arguments, 0, "")
        if program != "efibootmgr" or not self.allow_firmware:
            raise AssertionError(f"unexpected external operation: {arguments}")
        if arguments == ["efibootmgr", "--verbose"]:
            lines = ["BootCurrent: " + self.current, "BootNext: " + self.next_boot, "BootOrder: " + ",".join(self.order)]
            lines.extend(f"Boot{number}* {identity}" for number, identity in self.entries.items())
            return subprocess.CompletedProcess(arguments, 0, "\n".join(lines))
        if "--create-only" in arguments:
            if self.fail_create:
                raise subprocess.CalledProcessError(1, arguments)
            number = f"{self.serial:04X}"
            self.serial += 1
            label = arguments[arguments.index("--label") + 1]
            path = arguments[arguments.index("--loader") + 1]
            self.entries[number] = f"{label}\tHD(1,GPT,owned,0,0)/File({path}) {arguments[-1]}"
            return subprocess.CompletedProcess(arguments, 0, "")
        if "--bootorder" in arguments:
            if self.fail_order:
                raise subprocess.CalledProcessError(1, arguments)
            self.order = arguments[-1].split(",")
            return subprocess.CompletedProcess(arguments, 0, "")
        if "--delete-bootnum" in arguments:
            number = arguments[arguments.index("--bootnum") + 1]
            del self.entries[number]
            self.order = [item for item in self.order if item != number]
            return subprocess.CompletedProcess(arguments, 0, "")
        raise AssertionError(f"unexpected firmware operation: {arguments}")


class FirmwareBootUpdateTests(unittest.TestCase):
    @contextmanager
    def environment(self, method="uki", register=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            modules = root / "modules"
            version = modules / "7.3.test"
            version.mkdir(parents=True)
            (version / "vmlinuz").write_bytes(b"kernel one")
            (version / "pkgbase").write_text("linux\n")
            cmdline = root / "cmdline"
            cmdline.write_text("root=UUID=test rw\n")
            config = module.Configuration(method, root / "ordinary directory/output", "/dev/test" if register else "", 1 if register else 0, "CatOS", "linux")
            programs = Programs()
            programs.allow_firmware = register
            with (
                mock.patch.object(module, "MODULES_PATH", modules),
                mock.patch.object(module, "CMDLINE_PATH", cmdline),
                mock.patch.object(module, "machine_secure_boot_managed", return_value=False),
                mock.patch.object(module, "run", side_effect=programs.run),
            ):
                yield root, config, programs

    def test_configuration_allows_plain_output_directory_without_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "firmware-boot.conf"
            config_path.write_text("[boot]\nmethod=uki\nesp_path=/tmp/ordinary-output\n")
            config = module.load_configuration(config_path)
            self.assertEqual(config.esp_path, Path("/tmp/ordinary-output"))
            self.assertEqual(config.efi_disk, "")
            self.assertEqual(config.efi_partition, 0)
            self.assertFalse(config.install_fallback)

    def test_discovery_requires_only_installed_kernel(self):
        with self.environment() as (root, config, programs):
            kernels = module.discover_kernels()
            self.assertEqual(len(kernels), 1)
            self.assertEqual(kernels[0].image, root / "modules/7.3.test/vmlinuz")
            (root / "modules/7.3.test/pkgbase").unlink()
            self.assertEqual(module.discover_kernels()[0].package, "7.3.test")
            self.assertFalse(config.esp_path.exists())
            self.assertEqual(programs.calls, [])

    def test_multiple_versions_receive_their_own_initramfs(self):
        with self.environment("uki") as (root, config, programs):
            second = root / "modules/7.4.test"
            second.mkdir()
            (second / "pkgbase").write_text("linux\n")
            (second / "vmlinuz").write_bytes(b"kernel two")
            module.update(config)
            self.assertEqual((config.esp_path / "EFI/Linux/catos-linux-7.3.test.efi").read_bytes(), b"UKI:kernel one:initrd:7.3.test")
            self.assertEqual((config.esp_path / "EFI/Linux/catos-linux-7.4.test.efi").read_bytes(), b"UKI:kernel two:initrd:7.4.test")
            generations = [call for call in programs.calls if call[0] == "mkinitcpio"]
            self.assertEqual(len(generations), 2)
            self.assertEqual(generations[0][2], "7.3.test")
            self.assertEqual(generations[1][2], "7.4.test")

    def test_uki_deployment_to_unmounted_new_directory(self):
        with self.environment("uki") as (root, config, programs):
            module.update(config)
            self.assertEqual((config.esp_path / "EFI/Linux/catos-linux.efi").read_bytes(), b"UKI:kernel one:initrd:7.3.test")
            module.verify(config, module.discover_kernels(), require_entries=False)
            self.assertEqual([call[0] for call in programs.calls], ["mkinitcpio", "ukify"])
            self.assertIn("--nopost", programs.calls[0])
            self.assertFalse((config.esp_path / "EFI/BOOT").exists())
            self.assertFalse((root / "boot").exists())

    def test_stub_deployment_to_unmounted_new_directory(self):
        with self.environment("efistub") as (root, config, programs):
            module.update(config)
            state = module.load_state(config)
            kernel, initrd = [config.esp_path / relative for relative in state["kernels"]["linux"]]
            self.assertEqual(kernel.read_bytes(), b"kernel one")
            self.assertEqual(initrd.read_bytes(), b"initrd:7.3.test")
            self.assertEqual(kernel.parent, initrd.parent)
            self.assertEqual([call[0] for call in programs.calls], ["mkinitcpio"])
            module.verify(config, module.discover_kernels(), require_entries=False)

    def test_no_variables_avoids_all_firmware_access_even_with_disk(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            programs.allow_firmware = False
            module.update(config, no_variables=True)
            self.assertEqual([call[0] for call in programs.calls], ["mkinitcpio"])
            self.assertEqual(module.load_state(config)["entries"], [])

    def test_registration_reuses_owned_entry_and_preserves_existing_default(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            self.assertEqual(programs.order, ["0001", "0002"])
            module.update(config)
            self.assertEqual(programs.order, ["0001", "0002"])
            creates = [call for call in programs.calls if "--create-only" in call]
            self.assertEqual(len(creates), 1)
            self.assertIn("initrd=\\EFI\\CatOS\\linux\\", creates[0][-1])
            self.assertTrue(creates[0][-1].endswith(" root=UUID=test rw"))
            self.assertEqual(len(module.load_state(config)["entries"]), 1)

    def test_failed_creation_preserves_previous_entry_order_and_files(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            old = module.load_state(config)
            entries = dict(programs.entries)
            programs.initrd_suffix = b"updated"
            programs.fail_create = True
            with self.assertRaises(subprocess.CalledProcessError):
                module.update(config)
            self.assertEqual(programs.entries, entries)
            self.assertEqual(programs.order, ["0001", "0002"])
            for relative in old["kernels"]["linux"]:
                self.assertTrue((config.esp_path / relative).is_file())
            self.assertEqual([call for call in programs.calls if "--delete-bootnum" in call], [])

    def test_failed_order_update_can_be_retried_without_duplicate_creation(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            programs.fail_order = True
            with self.assertRaises(subprocess.CalledProcessError):
                module.update(config)
            self.assertEqual(programs.order, ["0001"])
            self.assertIn("0002", programs.entries)
            programs.fail_order = False
            module.update(config)
            self.assertEqual(programs.order, ["0001", "0002"])
            self.assertEqual(len([call for call in programs.calls if "--create-only" in call]), 1)

    def test_failed_stub_pair_preparation_leaves_previous_pair_unchanged(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            before = module.load_state(config)
            old_files = {relative: (config.esp_path / relative).read_bytes() for relative in before["kernels"]["linux"]}
            programs.initrd_suffix = b"updated"
            original = module.shutil.copyfile
            def fail_initrd(source, destination):
                if Path(destination).name == "initramfs.img":
                    raise OSError("simulated initramfs copy failure")
                return original(source, destination)
            with mock.patch.object(module.shutil, "copyfile", side_effect=fail_initrd):
                with self.assertRaises(OSError):
                    module.update(config)
            self.assertEqual(module.load_state(config), before)
            for relative, content in old_files.items():
                self.assertEqual((config.esp_path / relative).read_bytes(), content)
            self.assertEqual(programs.order, ["0001", "0002"])

    def test_unchanged_failure_does_not_publish_incomplete_uki(self):
        with self.environment("uki") as (root, config, programs):
            module.update(config)
            output = config.esp_path / "EFI/Linux/catos-linux.efi"
            original = output.read_bytes()
            def fail_build(arguments, *, capture=False):
                if arguments[0] == "ukify":
                    Path(arguments[arguments.index("--output") + 1]).write_bytes(b"partial")
                    raise subprocess.CalledProcessError(1, arguments)
                return programs.run(arguments, capture=capture)
            with mock.patch.object(module, "run", side_effect=fail_build):
                with self.assertRaises(subprocess.CalledProcessError):
                    module.update(config)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(list(output.parent.glob(".uki-*")), [])

    def test_successful_update_creates_entry_before_retiring_old_entry(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            previous = module.load_state(config)["kernels"]["linux"]
            programs.calls.clear()
            programs.initrd_suffix = b"updated"
            module.update(config)
            self.assertEqual(programs.order, ["0001", "0003"])
            self.assertNotIn("0002", programs.entries)
            creation = next(i for i, call in enumerate(programs.calls) if "--create-only" in call)
            deletion = next(i for i, call in enumerate(programs.calls) if "--delete-bootnum" in call)
            self.assertLess(creation, deletion)
            for relative in previous:
                self.assertFalse((config.esp_path / relative).exists())
            self.assertEqual(len(module.load_state(config)["entries"]), 1)

    def test_current_entry_and_its_kernel_pair_are_preserved(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            previous = module.load_state(config)["kernels"]["linux"]
            programs.current = "0002"
            programs.initrd_suffix = b"updated"
            module.update(config)
            self.assertIn("0002", programs.entries)
            for relative in previous:
                self.assertTrue((config.esp_path / relative).is_file())
            programs.current = "0003"
            module.update(config)
            self.assertNotIn("0002", programs.entries)
            for relative in previous:
                self.assertFalse((config.esp_path / relative).exists())

    def test_foreign_same_label_entries_and_untracked_files_are_untouched(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            foreign = "CatOS linux\tHD(1,GPT,foreign,0,0)/File(\\EFI\\CatOS\\linux\\vmlinuz.efi)"
            programs.entries["0001"] = foreign
            untracked = config.esp_path / "EFI/CatOS/another-system/vmlinuz.efi"
            untracked.parent.mkdir(parents=True)
            untracked.write_bytes(b"other OS")
            module.update(config)
            programs.initrd_suffix = b"updated"
            module.update(config)
            self.assertEqual(programs.entries["0001"], foreign)
            self.assertEqual(untracked.read_bytes(), b"other OS")
            self.assertEqual(programs.order[0], "0001")

    def test_changed_firmware_identity_is_not_deleted(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            previous = module.load_state(config)["kernels"]["linux"]
            programs.entries["0002"] = "Reassigned entry\tHD(2,GPT,foreign,0,0)/File(\\EFI\\other.efi)"
            programs.initrd_suffix = b"updated"
            module.update(config)
            self.assertTrue(programs.entries["0002"].startswith("Reassigned entry"))
            self.assertEqual(programs.order, ["0001", "0002", "0003"])
            for relative in previous:
                self.assertTrue((config.esp_path / relative).is_file())

    def test_no_variables_retains_existing_firmware_and_referenced_files(self):
        with self.environment("efistub", register=True) as (root, config, programs):
            module.update(config)
            previous = module.load_state(config)["kernels"]["linux"]
            programs.calls.clear()
            programs.allow_firmware = False
            programs.initrd_suffix = b"updated"
            module.update(config, no_variables=True)
            self.assertEqual([call[0] for call in programs.calls], ["mkinitcpio"])
            for relative in previous:
                self.assertTrue((config.esp_path / relative).is_file())

    def test_uki_and_stub_records_do_not_prune_each_other(self):
        with self.environment("uki") as (root, config, programs):
            module.update(config)
            uki = config.esp_path / "EFI/Linux/catos-linux.efi"
            stub_config = replace(config, method="efistub")
            module.update(stub_config)
            stub = module.load_state(stub_config)["kernels"]["linux"]
            module.update(config)
            self.assertTrue(uki.is_file())
            for relative in stub:
                self.assertTrue((config.esp_path / relative).is_file())
            self.assertTrue(module.state_path(config).is_file())
            self.assertTrue(module.state_path(stub_config).is_file())

    def test_invalid_record_cannot_delete_outside_output_directory(self):
        with self.environment("uki") as (root, config, programs):
            outside = root / "other-file"
            outside.write_bytes(b"keep")
            record = module.state_path(config)
            record.parent.mkdir(parents=True)
            record.write_text(json.dumps({"version": 1, "files": {"../../other-file": "0" * 64}, "entries": []}))
            with self.assertRaises(module.FirmwareBootError):
                module.update(config)
            self.assertEqual(outside.read_bytes(), b"keep")
            self.assertEqual(programs.calls, [])

    def test_fallback_output_is_explicit(self):
        with self.environment("uki") as (root, config, programs):
            config = replace(config, install_fallback=True)
            module.update(config)
            fallback = config.esp_path / "EFI/BOOT/BOOTX64.EFI"
            self.assertEqual(fallback.read_bytes(), (config.esp_path / "EFI/Linux/catos-linux.efi").read_bytes())
            self.assertIn("EFI/BOOT/BOOTX64.EFI", module.load_state(config)["files"])

    def test_machine_secure_boot_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "machine.key"
            key.write_bytes(b"key")
            uki = module.Configuration("uki", Path("/output"), "", 0, "CatOS", "linux")
            self.assertTrue(module.machine_secure_boot_managed(uki, key))
            self.assertFalse(module.machine_secure_boot_managed(replace(uki, method="efistub"), key))

    def test_signed_uki_is_verified_by_secureboot_owner(self):
        with self.environment("uki", register=True) as (root, config, programs):
            programs.allow_firmware = False
            with mock.patch.object(module, "machine_secure_boot_managed", return_value=True):
                module.update(config)
                output = config.esp_path / "EFI/Linux/catos-linux.efi"
                output.write_bytes(output.read_bytes() + b"signature")
                module.verify(config, module.discover_kernels(), require_entries=False)
            self.assertEqual([call[0] for call in programs.calls], ["mkinitcpio", "ukify"])


if __name__ == "__main__":
    unittest.main()
