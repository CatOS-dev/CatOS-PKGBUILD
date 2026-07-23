from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class State:
    version: int = 1
    enrollment_pending: bool = False
    certificate_fingerprint: str = ""
    last_error: str = ""
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=int(data.get("version", 1)),
            enrollment_pending=bool(data.get("enrollment_pending", False)),
            certificate_fingerprint=str(data.get("certificate_fingerprint", "")),
            last_error=str(data.get("last_error", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(payload, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
