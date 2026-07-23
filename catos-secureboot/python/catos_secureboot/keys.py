from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import string
import tempfile

from .config import Config
from .system import Runner


@dataclass(frozen=True)
class KeyMaterial:
    private_key: Path
    certificate_pem: Path
    certificate_der: Path
    fingerprint: str


def machine_identifier() -> str:
    path = Path("/etc/machine-id")
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value[:16]
    return "uninitialized"


def generate_key_material(config: Config, runner: Runner) -> KeyMaterial:
    config.key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config.key_dir, 0o700)
    if not (config.private_key.is_file() and config.certificate_pem.is_file() and config.certificate_der.is_file()):
        subject = f"/CN=CatOS Machine Owner Key {machine_identifier()}/"
        runner.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-sha256",
                "-nodes",
                "-days",
                str(config.certificate_days),
                "-subj",
                subject,
                "-addext",
                "keyUsage=digitalSignature",
                "-addext",
                "extendedKeyUsage=codeSigning",
                "-keyout",
                str(config.private_key),
                "-out",
                str(config.certificate_pem),
            ]
        )
        runner.run(
            [
                "openssl",
                "x509",
                "-in",
                str(config.certificate_pem),
                "-outform",
                "DER",
                "-out",
                str(config.certificate_der),
            ]
        )
    os.chmod(config.private_key, 0o600)
    os.chmod(config.certificate_pem, 0o644)
    os.chmod(config.certificate_der, 0o644)
    fingerprint_result = runner.run(
        ["openssl", "x509", "-in", str(config.certificate_pem), "-noout", "-fingerprint", "-sha256"]
    )
    fingerprint = fingerprint_result.stdout.strip().partition("=")[2].replace(":", "").upper()
    if not fingerprint:
        raise RuntimeError("openssl did not return a certificate fingerprint")
    return KeyMaterial(config.private_key, config.certificate_pem, config.certificate_der, fingerprint)


def random_enrollment_password(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def request_enrollment(certificate_der: Path, password: str, runner: Runner) -> None:
    if not 1 <= len(password) <= 256:
        raise ValueError("MOK enrollment password length is invalid")
    hash_result = runner.run(["openssl", "passwd", "-6", "-stdin"], input_text=password + "\n")
    password_hash = hash_result.stdout.strip()
    if not password_hash.startswith("$6$"):
        raise RuntimeError("openssl failed to generate a SHA-512 password hash")
    fd, name = tempfile.mkstemp(prefix="catos-mok-hash.")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(password_hash + "\n")
        os.chmod(path, 0o600)
        runner.run(["mokutil", "--import", str(certificate_der), "--hash-file", str(path)])
    finally:
        path.unlink(missing_ok=True)
