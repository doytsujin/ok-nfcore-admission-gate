"""Dataset descriptors.

A descriptor is a versioned, per-dataset declaration of what the dataset is,
what state it is in, and which operations are permissible on it under which
conditions. It declares; it does not enforce. Enforcement is the gate's job
(see gate.py), which keeps the "declare vs enforce" split explicit rather than
implied.

This is deliberately a small, dependency-free JSON model. The point of the
artifact is that the *execution* is real, not that the descriptor format is
elaborate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class DescriptorError(Exception):
    """Raised when a descriptor is malformed or missing."""


@dataclass(frozen=True)
class Action:
    """One permissible operation, with the preconditions that admit it."""

    name: str
    requires_state: tuple[str, ...]
    conditions: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, obj: dict) -> "Action":
        try:
            return cls(
                name=obj["name"],
                requires_state=tuple(obj.get("requiresState", [])),
                conditions=obj.get("conditions", {}),
            )
        except KeyError as exc:
            raise DescriptorError(f"action missing field {exc}") from exc


@dataclass
class Descriptor:
    """A dataset as a control-plane object."""

    dataset_id: str
    version: str
    data_type: str
    state: str
    schema: dict
    provenance: dict
    policy: dict
    actions: dict[str, Action]
    source_path: Path | None = None

    # ---- construction -------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Descriptor":
        p = Path(path)
        if not p.exists():
            raise DescriptorError(f"no descriptor at {p}")
        try:
            obj = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            raise DescriptorError(f"{p} is not valid JSON: {exc}") from exc
        return cls.from_json(obj, source_path=p)

    @classmethod
    def from_json(cls, obj: dict, source_path: Path | None = None) -> "Descriptor":
        required = ("datasetId", "version", "dataType", "state")
        missing = [k for k in required if k not in obj]
        if missing:
            raise DescriptorError(f"descriptor missing {missing}")
        actions = {
            a["name"]: Action.from_json(a) for a in obj.get("permissibleActions", [])
        }
        return cls(
            dataset_id=obj["datasetId"],
            version=obj["version"],
            data_type=obj["dataType"],
            state=obj["state"],
            schema=obj.get("schema", {}),
            provenance=obj.get("provenance", {}),
            policy=obj.get("policy", {}),
            actions=actions,
            source_path=source_path,
        )

    # ---- queries ------------------------------------------------------

    def action(self, name: str) -> Action | None:
        return self.actions.get(name)

    def declares(self, name: str) -> bool:
        return name in self.actions

    def as_json(self) -> dict:
        return {
            "datasetId": self.dataset_id,
            "version": self.version,
            "dataType": self.data_type,
            "state": self.state,
            "schema": self.schema,
            "provenance": self.provenance,
            "policy": self.policy,
            "permissibleActions": [
                {
                    "name": a.name,
                    "requiresState": list(a.requires_state),
                    "conditions": a.conditions,
                }
                for a in self.actions.values()
            ],
        }


def load_all(directory: str | Path) -> dict[str, Descriptor]:
    """Load every *.json descriptor in a directory, keyed by datasetId."""
    out: dict[str, Descriptor] = {}
    for p in sorted(Path(directory).glob("*.json")):
        d = Descriptor.load(p)
        out[d.dataset_id] = d
    return out
