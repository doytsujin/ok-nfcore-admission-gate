"""A thin `aws` CLI wrapper, so this arm stays dependency-free like the rest.

The repository deliberately has no third-party dependencies -- see the comment
in bench/aggregate.py about not acquiring scipy to look up 2.045. The same rule
applies here: boto3 would be more comfortable and would make the artifact
unrunnable for anyone who has the CLI and nothing else.
"""

from __future__ import annotations

import json
import os
import subprocess


class AwsError(RuntimeError):
    """A failed AWS call, carrying the service's own message.

    The message matters: 'AccessDeniedException' and 'ValidationException' are
    different findings when the thing under test is whether the service accepts
    a directive at all.
    """

    def __init__(self, argv: list[str], stderr: str, code: int):
        self.argv = argv
        self.stderr = stderr.strip()
        self.code = code
        super().__init__(f"{' '.join(argv[:4])}... exited {code}: {self.stderr[:400]}")

    @property
    def error_code(self) -> str:
        """The AWS error code, e.g. 'ValidationException', or '' if unparseable."""
        marker = "An error occurred ("
        if marker in self.stderr:
            return self.stderr.split(marker, 1)[1].split(")", 1)[0]
        return ""


def aws(*args: str, profile: str | None = None, region: str | None = None,
        parse: bool = True):
    """Run one aws CLI call. Returns parsed JSON, or raw text when parse=False."""
    argv = ["aws"]
    profile = profile or os.environ.get("AWS_PROFILE")
    if profile:
        argv += ["--profile", profile]
    if region:
        argv += ["--region", region]
    argv += list(args)
    if parse and "--output" not in args:
        argv += ["--output", "json"]

    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AwsError(argv, proc.stderr, proc.returncode)
    if not parse:
        return proc.stdout
    out = proc.stdout.strip()
    return json.loads(out) if out else {}
