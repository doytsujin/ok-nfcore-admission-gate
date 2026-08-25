"""A resident gate.

The replicated measurement attributes ~26 ms per task to `python3 -m gate`
process creation, against a policy evaluation of 11 µs -- roughly 2700-fold
between the decision and the mechanism delivering it. Attributing a cost is
not fixing it, and "start the interpreter once instead of once per task" is the
obvious fix that the artifact asserted and never demonstrated.

This is that daemon. Descriptors are loaded once at start; each request is
answered in the already-warm process.

**The client must not be Python.** A Python client would reintroduce exactly
the interpreter startup being removed. The client is bash's own `/dev/tcp`,
which spawns nothing -- the shell running `beforeScript` is already there.

Protocol, one line each way, deliberately trivial so a shell can speak it:

    request   DATASET ACTION key=value key=value ...
    response  PERMIT
              REFUSE <reasonClass> <detail>
              ERROR  <detail>

Bound to loopback by default. This carries no authentication and must not be
exposed off-host; the enforcement boundary is the task's own machine.
"""

from __future__ import annotations

import argparse
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gate.descriptor import Descriptor, DescriptorError  # noqa: E402
from gate.gate import authorize  # noqa: E402
from gate.telemetry import DecisionLog  # noqa: E402


class Registry:
    """Descriptors, read once.

    A gate that re-reads its policy per request would give back most of what
    the daemon saves, and would also make the policy able to change midway
    through a run -- which is a correctness question, not a performance one.
    The descriptor set is therefore frozen for the daemon's lifetime, and that
    is a deliberate semantic: one run, one policy.
    """

    def __init__(self, directory: Path):
        self.directory = directory
        self.by_id: dict[str, Descriptor] = {}
        for path in sorted(directory.glob("*.json")):
            try:
                d = Descriptor.load(path)
            except DescriptorError as exc:
                raise SystemExit(f"gate-daemon: {path.name}: {exc}")
            self.by_id[d.dataset_id] = d

    def get(self, dataset_id: str) -> Descriptor | None:
        return self.by_id.get(dataset_id)


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline().decode("utf-8", "replace").strip()
        if not raw:
            return
        started = time.perf_counter()
        parts = raw.split()
        if len(parts) < 2:
            self.wfile.write(b"ERROR malformed request\n")
            return

        dataset_id, action, ctx_pairs = parts[0], parts[1], parts[2:]
        context: dict = {}
        for pair in ctx_pairs:
            key, _, value = pair.partition("=")
            try:
                context[key] = int(value)
            except ValueError:
                try:
                    context[key] = float(value)
                except ValueError:
                    context[key] = value

        descriptor = self.server.registry.get(dataset_id)
        if descriptor is None:
            self.wfile.write(f"ERROR no descriptor {dataset_id}\n".encode())
            return

        decision = authorize(descriptor, action, context)
        wall = int((time.perf_counter() - started) * 1_000_000)

        with self.server.log_lock:
            self.server.log.write(decision.as_record(
                runId=self.server.run_id,
                task=context.get("task", "unknown"),
                context=context,
                dryRun=False,
                wallMicros=wall,
                transport="resident",
            ))

        if decision.permitted:
            self.wfile.write(b"PERMIT\n")
        else:
            detail = "; ".join(decision.reasons)
            self.wfile.write(f"REFUSE {decision.reason_class} {detail}\n".encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gate-daemon")
    ap.add_argument("--descriptors", default="descriptors")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--log", default="results/decisions_resident.jsonl")
    ap.add_argument("--run-id", default="resident")
    ap.add_argument("--ready-file", default="",
                    help="written once the socket is listening, so a harness "
                         "can wait on readiness instead of sleeping")
    args = ap.parse_args(argv)

    registry = Registry(Path(args.descriptors))
    server = Server((args.host, args.port), Handler)
    server.registry = registry
    server.log = DecisionLog(args.log)
    server.log_lock = threading.Lock()
    server.run_id = args.run_id

    if args.ready_file:
        Path(args.ready_file).write_text(json.dumps({
            "host": args.host, "port": args.port,
            "descriptors": sorted(registry.by_id),
        }) + "\n")

    print(f"gate-daemon: {args.host}:{args.port}, "
          f"{len(registry.by_id)} descriptors", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
