"""The admission gate.

`authorize()` answers one question, prospectively: may this operation, on this
dataset, in the state the descriptor says it is in, proceed right now?

It runs *before* the task's own script. If it refuses, the work does not
happen -- as distinct from a retrospective provenance bundle, which records
faithfully that the wrong thing happened.

Three refusal classes, kept separate because they mean different things to a
reader of the log:

  UNDECLARED  the descriptor does not list this action at all
  STATE       the action is declared but the dataset is in the wrong state
  CONDITION   state is fine, but a declared condition is violated
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .descriptor import Descriptor
from .policy import ConditionResult, evaluate, failures

PERMIT = "PERMIT"
REFUSE = "REFUSE"

UNDECLARED = "UNDECLARED_ACTION"
STATE = "STATE_PRECONDITION"
CONDITION = "CONDITION_VIOLATED"


@dataclass
class Decision:
    verdict: str
    dataset_id: str
    descriptor_version: str
    action: str
    reason_class: str | None = None
    reasons: list[str] = field(default_factory=list)
    conditions: list[ConditionResult] = field(default_factory=list)
    observed_state: str = ""
    eval_micros: int = 0

    @property
    def permitted(self) -> bool:
        return self.verdict == PERMIT

    def as_record(self, **extra) -> dict:
        return {
            "verdict": self.verdict,
            "datasetId": self.dataset_id,
            "descriptorVersion": self.descriptor_version,
            "action": self.action,
            "observedState": self.observed_state,
            "reasonClass": self.reason_class,
            "reasons": self.reasons,
            "conditionsChecked": [
                {
                    "name": c.name,
                    "operator": c.operator,
                    "expected": c.expected,
                    "observed": c.observed,
                    "passed": c.passed,
                }
                for c in self.conditions
            ],
            "evalMicros": self.eval_micros,
            **extra,
        }


def authorize(descriptor: Descriptor, action: str, context: dict) -> Decision:
    """Evaluate one admission request. Never raises on a policy failure --
    a refusal is a normal outcome and must produce a record like any other."""
    started = time.perf_counter()

    def finish(**kw) -> Decision:
        d = Decision(
            dataset_id=descriptor.dataset_id,
            descriptor_version=descriptor.version,
            action=action,
            observed_state=descriptor.state,
            **kw,
        )
        d.eval_micros = int((time.perf_counter() - started) * 1_000_000)
        return d

    declared = descriptor.action(action)
    if declared is None:
        return finish(
            verdict=REFUSE,
            reason_class=UNDECLARED,
            reasons=[
                f"descriptor {descriptor.dataset_id}@{descriptor.version} "
                f"declares no action {action!r}; declared: "
                f"{sorted(descriptor.actions) or '[]'}"
            ],
        )

    if declared.requires_state and descriptor.state not in declared.requires_state:
        return finish(
            verdict=REFUSE,
            reason_class=STATE,
            reasons=[
                f"action {action!r} requires state in "
                f"{list(declared.requires_state)}; dataset is {descriptor.state!r}"
            ],
        )

    results = evaluate(declared.conditions, context)
    bad = failures(results)
    if bad:
        return finish(
            verdict=REFUSE,
            reason_class=CONDITION,
            reasons=[c.detail for c in bad],
            conditions=results,
        )

    return finish(verdict=PERMIT, conditions=results)
