from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    DISABLED = "disabled"
    ENROLLMENT_PENDING = "enrollment-pending"
    ACTIVE = "active"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class ProbeResult:
    secure_boot_enabled: bool
    key_exists: bool
    certificate_enrolled: bool
    certificate_pending: bool
    signatures_valid: bool
    module_signature_enforced: bool


def evaluate_phase(probe: ProbeResult) -> Phase:
    if not probe.key_exists and not probe.secure_boot_enabled:
        return Phase.DISABLED
    if probe.key_exists and probe.certificate_pending and not probe.certificate_enrolled and probe.signatures_valid:
        return Phase.ENROLLMENT_PENDING
    if (
        probe.secure_boot_enabled
        and probe.key_exists
        and probe.certificate_enrolled
        and probe.signatures_valid
        and probe.module_signature_enforced
    ):
        return Phase.ACTIVE
    return Phase.DEGRADED
