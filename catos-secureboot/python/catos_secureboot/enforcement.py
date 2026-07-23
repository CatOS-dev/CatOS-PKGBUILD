from __future__ import annotations

import os
from pathlib import Path
import shlex
import tempfile


REQUIRED_KERNEL_PARAMETERS = ("module.sig_enforce=1", "lockdown=integrity")


def atomic_write_text(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_cmdline_tokens(path: Path, required: tuple[str, ...] = REQUIRED_KERNEL_PARAMETERS) -> bool:
    current = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    tokens = shlex.split(current)
    changed = False
    for token in required:
        key = token.partition("=")[0]
        matching = [entry for entry in tokens if entry == key or entry.startswith(key + "=")]
        if matching == [token]:
            continue
        tokens = [entry for entry in tokens if entry != key and not entry.startswith(key + "=")]
        tokens.append(token)
        changed = True
    normalized = " ".join(tokens).strip() + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != normalized:
        atomic_write_text(path, normalized)
        changed = True
    return changed


def _read_grub_assignment(path: Path, variable: str) -> str:
    if not path.is_file():
        return ""
    prefix = variable + "="
    value = ""
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        raw_value = line[len(prefix) :].strip()
        try:
            parsed = shlex.split(raw_value)
        except ValueError:
            continue
        if parsed:
            value = parsed[0]
    return value


def resolve_cmdline(cmdline_path: Path) -> str:
    if cmdline_path.is_file():
        value = cmdline_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    for path in (Path("/etc/default/grub.d/00-catos.cfg"), Path("/etc/default/grub")):
        value = _read_grub_assignment(path, "GRUB_CMDLINE_LINUX_DEFAULT")
        if value:
            return value
    raise FileNotFoundError("kernel command line is not configured")


def configure_enforcement(cmdline_path: Path, grub_dropin_path: Path) -> str:
    if not cmdline_path.is_file():
        atomic_write_text(cmdline_path, resolve_cmdline(cmdline_path).strip() + "\n")
    ensure_cmdline_tokens(cmdline_path)
    dropin = (
        '# Managed by catos-secureboot.\n'
        'GRUB_CMDLINE_LINUX_DEFAULT="${GRUB_CMDLINE_LINUX_DEFAULT} module.sig_enforce=1 lockdown=integrity"\n'
    )
    if not grub_dropin_path.is_file() or grub_dropin_path.read_text(encoding="utf-8") != dropin:
        atomic_write_text(grub_dropin_path, dropin)
    return cmdline_path.read_text(encoding="utf-8").strip()
