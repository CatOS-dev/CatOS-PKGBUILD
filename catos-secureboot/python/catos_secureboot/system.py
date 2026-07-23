from __future__ import annotations

from dataclasses import dataclass
import subprocess


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    def __init__(self, arguments: list[str], result: CommandResult):
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        super().__init__(f"{' '.join(arguments)}: {detail}")
        self.arguments = tuple(arguments)
        self.result = result


class Runner:
    def run(self, arguments: list[str], *, check: bool = True, input_text: str | None = None) -> CommandResult:
        completed = subprocess.run(
            arguments,
            check=False,
            text=True,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            raise CommandError(arguments, result)
        return result
