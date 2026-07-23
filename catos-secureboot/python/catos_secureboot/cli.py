from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import Config
from .service import SecureBootService
from .system import CommandError, Runner


DEFAULT_CONFIG = Path("/etc/catos/secureboot.conf")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="catos-secureboot", description="Manage CatOS Secure Boot keys and signatures")
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subcommands = result.add_subparsers(dest="command", required=True)

    status = subcommands.add_parser("status", help="show Secure Boot state")
    status.add_argument("--json", action="store_true")

    enable = subcommands.add_parser("enable", help="generate a machine MOK, sign artifacts and request enrollment")
    password = enable.add_mutually_exclusive_group()
    password.add_argument("--password-file", type=Path)
    password.add_argument("--generate-enrollment-password", action="store_true")
    enable.add_argument("--no-enroll", action="store_true", help="prepare signatures without writing MokNew")
    enable.add_argument("--json", action="store_true")

    maintain = subcommands.add_parser("maintain", help="sign updated EFI images and external modules")
    maintain.add_argument("--hook", action="store_true", help=argparse.SUPPRESS)
    maintain.add_argument("--json", action="store_true")

    prepare = subcommands.add_parser("prepare", help=argparse.SUPPRESS)
    prepare.add_argument("--hook", action="store_true", help=argparse.SUPPRESS)
    prepare.add_argument("--json", action="store_true")

    finalize_efi = subcommands.add_parser("finalize-efi", help=argparse.SUPPRESS)
    finalize_efi.add_argument("--hook", action="store_true", help=argparse.SUPPRESS)
    finalize_efi.add_argument("--json", action="store_true")

    verify = subcommands.add_parser("verify", help="verify the current state")
    verify.add_argument("--json", action="store_true")
    return result


def emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main(arguments: list[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    try:
        config = Config.load(options.config)
        service = SecureBootService(config, Runner())
        if options.command in {"status", "verify"}:
            payload = service.status()
            emit(payload, options.json)
            if options.command == "verify" and payload["phase"] not in {"active", "enrollment-pending", "disabled"}:
                return 2
            return 0
        if options.command == "maintain":
            payload = service.prepare() if options.hook else service.maintain()
            emit(payload, options.json)
            return 0
        if options.command == "prepare":
            payload = service.prepare()
            emit(payload, options.json)
            return 0
        if options.command == "finalize-efi":
            payload = service.finalize_efi()
            emit(payload, options.json)
            return 0
        password = None
        if options.password_file:
            password = options.password_file.read_text(encoding="utf-8").rstrip("\n")
        payload = service.enable(
            password=password,
            generate_password=options.generate_enrollment_password,
            enroll=not options.no_enroll,
        )
        emit(payload, options.json)
        return 0
    except (CommandError, OSError, PermissionError, RuntimeError, ValueError) as error:
        print(f"catos-secureboot: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
