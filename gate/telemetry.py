"""Decision records.

Every admission evaluation writes exactly one record, whether it permits or
refuses. That symmetry is the whole point: a log that only records what ran
cannot show that anything was stopped, and "nothing was stopped" and "nothing
was checked" look identical in it.

Records are append-only JSONL. Concurrency matters here -- Nextflow runs tasks
in parallel, so several gate processes write the same file at once. Each record
is written with a single O_APPEND write of one line, which POSIX keeps atomic
below PIPE_BUF for regular files on local filesystems; records are small enough
that this holds.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SCHEMA_VERSION = "1.0"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"


class DecisionLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> dict:
        record = {"schema": SCHEMA_VERSION, "timestamp": _now(), **record}
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
        return record

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
