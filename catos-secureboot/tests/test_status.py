from __future__ import annotations

import unittest

from catos_secureboot.model import Phase, ProbeResult, evaluate_phase


class StatusTests(unittest.TestCase):
    def test_package_can_remain_disabled_while_secure_boot_is_off(self) -> None:
        phase = evaluate_phase(
            ProbeResult(
                secure_boot_enabled=False,
                key_exists=False,
                certificate_enrolled=False,
                certificate_pending=False,
                signatures_valid=False,
                module_signature_enforced=False,
            )
        )

        self.assertEqual(phase, Phase.DISABLED)

    def test_prepared_machine_waits_for_second_mok_enrollment(self) -> None:
        phase = evaluate_phase(
            ProbeResult(
                secure_boot_enabled=True,
                key_exists=True,
                certificate_enrolled=False,
                certificate_pending=True,
                signatures_valid=True,
                module_signature_enforced=True,
            )
        )

        self.assertEqual(phase, Phase.ENROLLMENT_PENDING)

    def test_active_requires_enrollment_signatures_and_module_enforcement(self) -> None:
        phase = evaluate_phase(
            ProbeResult(
                secure_boot_enabled=True,
                key_exists=True,
                certificate_enrolled=True,
                certificate_pending=False,
                signatures_valid=True,
                module_signature_enforced=True,
            )
        )

        self.assertEqual(phase, Phase.ACTIVE)

    def test_missing_module_enforcement_is_degraded(self) -> None:
        phase = evaluate_phase(
            ProbeResult(
                secure_boot_enabled=True,
                key_exists=True,
                certificate_enrolled=True,
                certificate_pending=False,
                signatures_valid=True,
                module_signature_enforced=False,
            )
        )

        self.assertEqual(phase, Phase.DEGRADED)


if __name__ == "__main__":
    unittest.main()
