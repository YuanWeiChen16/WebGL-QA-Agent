"""Oracle — functional-correctness checks (test oracle) for black-box games.

The target game is treated as an unmodifiable black box, so there is no engine
hook to read ground-truth state from. Instead the ground truth is whatever the
screen shows, read by Vision into the ``game_state`` field
(score / currency / level / lives). See vision.CORE_SCHEMA_PROPERTIES.

This module deliberately does NOT call Vision. It is a pure, deterministic
evaluator over the numeric state that the caller already obtained from
``vision.analyze_screenshot_structured``. Keeping it I/O-free makes it unit
testable and keeps the (expensive, non-deterministic) Vision calls under the
caller's control — the caller decides *when* to read state before/after an
action; the oracle only decides whether the transition was correct.

Invariants are declared per game in ``knowledge/<game>/game_info.yaml`` under
``oracle.invariants`` and describe an expected relationship between the state
BEFORE and AFTER an action:

    oracle:
      invariants:
        - id: level_up_on_upgrade
          when: upgrade          # action tag this invariant applies to ("" = always)
          field: level
          kind: increment        # after == before + delta
          delta: 1
          severity: high
          description: 升級成功後等級應 +1

Supported ``kind`` values:
    increment           after == before + delta
    monotonic_increase  after >= before
    non_increasing      after <= before
    decrease_or_flag    after <= before, unless flags[unless_flag] is truthy
    must_change         after != before
    range               min <= after <= max   (only needs the AFTER value)

A value read as ``None`` (Vision could not see it) makes that check *skip*
rather than pass or fail — an unread number is never reported as a bug.
"""

from dataclasses import dataclass, field
from typing import Optional

from .detector import Anomaly


@dataclass
class Invariant:
    """A single declarative expectation about a state transition."""
    id: str
    field: str
    kind: str
    when: str = ""              # action tag; "" means always applicable
    delta: int = 1
    min: Optional[int] = None
    max: Optional[int] = None
    unless_flag: str = ""
    severity: str = "medium"
    description: str = ""
    # RNG-noise guard: how many CONSECUTIVE violation observations are needed
    # before the violation is considered confirmed (a real bug). A passing
    # check resets the streak. 1 = report immediately (deterministic checks);
    # use 2-3 for checks racing against live-server randomness (payouts, etc.).
    min_occurrences: int = 1


_VALID_KINDS = {
    "increment", "monotonic_increase", "non_increasing",
    "decrease_or_flag", "must_change", "range",
}


class Oracle:
    """Evaluates functional invariants over Vision-read numeric game state.

    Args:
        config: Optional Config instance. Invariants are read from
            ``oracle.invariants`` (config/default.yaml + game_info.yaml).
    """

    def __init__(self, config=None):
        self.invariants: list[Invariant] = []
        self.violations: list[Anomaly] = []   # confirmed (streak >= min_occurrences)
        self.candidates: list[Anomaly] = []   # observed but below min_occurrences
        self._streaks: dict = {}              # invariant id -> consecutive violation count

        raw = []
        if config is not None and hasattr(config, "get"):
            raw = config.get("oracle.invariants", []) or []

        for item in raw:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind", "must_change")
            if kind not in _VALID_KINDS:
                # Unknown kind in config — ignore rather than crash a QA run.
                continue
            self.invariants.append(Invariant(
                id=item.get("id", "unnamed"),
                field=item.get("field", ""),
                kind=kind,
                when=item.get("when", ""),
                delta=item.get("delta", 1),
                min=item.get("min"),
                max=item.get("max"),
                unless_flag=item.get("unless_flag", ""),
                severity=item.get("severity", "medium"),
                description=item.get("description", ""),
                min_occurrences=max(1, int(item.get("min_occurrences", 1) or 1)),
            ))

    @staticmethod
    def _read(state: dict, field_name: str):
        """Read a numeric field from a game_state dict, tolerating None/missing."""
        if not isinstance(state, dict):
            return None
        val = state.get(field_name)
        if isinstance(val, bool):  # guard: bools are ints in Python
            return None
        if isinstance(val, (int, float)):
            return val
        return None

    def check(self, invariant: Invariant, before: dict, after: dict,
              flags: dict = None, record: bool = True) -> Optional[Anomaly]:
        """Evaluate one invariant. Returns an Anomaly on violation, else None.

        Returns None (skip) when the values needed for the check were not read
        by Vision — an unreadable number is never treated as a bug.

        Args:
            record: When True (default), a violation increments the invariant's
                consecutive-violation streak and a pass resets it; the returned
                Anomaly carries evidence["confirmed"] (streak >= min_occurrences)
                and is appended to self.violations or self.candidates.
                When False, this is a pure re-evaluation (e.g. the second read of
                a double-check): no streak change, no list append.
        """
        flags = flags or {}
        b = self._read(before, invariant.field)
        a = self._read(after, invariant.field)

        # Decide whether we have enough data to judge.
        if invariant.kind == "range":
            if a is None:
                return None
        else:
            if a is None or b is None:
                return None

        ok = True
        detail = ""
        k = invariant.kind

        if k == "increment":
            ok = (a == b + invariant.delta)
            detail = f"{invariant.field}: {b} → {a}（預期 {b + invariant.delta}）"
        elif k == "monotonic_increase":
            ok = (a >= b)
            detail = f"{invariant.field}: {b} → {a}（不應減少）"
        elif k == "non_increasing":
            ok = (a <= b)
            detail = f"{invariant.field}: {b} → {a}（不應增加）"
        elif k == "decrease_or_flag":
            ok = (a <= b) or bool(flags.get(invariant.unless_flag))
            detail = (f"{invariant.field}: {b} → {a}"
                      f"（應減少，除非 {invariant.unless_flag or 'reward'}）")
        elif k == "must_change":
            ok = (a != b)
            detail = f"{invariant.field}: 停留在 {a} 未變化"
        elif k == "range":
            lo = invariant.min if invariant.min is not None else float("-inf")
            hi = invariant.max if invariant.max is not None else float("inf")
            ok = (lo <= a <= hi)
            detail = f"{invariant.field}={a} 超出範圍 [{invariant.min}, {invariant.max}]"

        if ok:
            if record:
                self._streaks[invariant.id] = 0   # a clean pass resets the streak
            return None

        # Violation observed.
        if record:
            streak = self._streaks.get(invariant.id, 0) + 1
            self._streaks[invariant.id] = streak
            confirmed = streak >= invariant.min_occurrences
        else:
            streak = None
            confirmed = None   # pure re-evaluation; caller decides

        anomaly = Anomaly(
            type="oracle_violation",
            severity=invariant.severity,
            description=f"[{invariant.id}] {invariant.description or invariant.field} — {detail}",
            evidence={
                "invariant": invariant.id,
                "field": invariant.field,
                "kind": k,
                "before": b,
                "after": a,
                "flags": flags,
                "occurrence": streak,
                "min_occurrences": invariant.min_occurrences,
                "confirmed": confirmed,
            },
        )
        if record:
            if confirmed:
                self.violations.append(anomaly)
            else:
                self.candidates.append(anomaly)
        return anomaly

    def check_action(self, action_tag: str, before: dict, after: dict,
                     flags: dict = None, record: bool = True) -> list[Anomaly]:
        """Run every invariant whose ``when`` matches action_tag (or is empty).

        Args:
            action_tag: A label for what just happened, e.g. "upgrade", "shoot".
            before: game_state dict read before the action.
            after: game_state dict read after the action.
            flags: Optional context flags, e.g. {"reward_detected": True}.
            record: Pass False for a pure re-evaluation (no streak/list updates).

        Returns:
            List of Anomaly objects for violated invariants (possibly empty).
            With record=True each anomaly's evidence["confirmed"] tells whether
            the consecutive-violation streak reached min_occurrences.
        """
        results = []
        for inv in self.invariants:
            if inv.when and inv.when != action_tag:
                continue
            res = self.check(inv, before, after, flags, record=record)
            if res:
                results.append(res)
        return results

    def applicable_count(self, action_tag: str) -> int:
        """How many invariants apply to a given action tag."""
        return sum(1 for inv in self.invariants
                   if not inv.when or inv.when == action_tag)

    def get_summary(self) -> dict:
        """Summary of violations seen this session."""
        by_severity: dict = {}
        for v in self.violations:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
        return {
            "total_invariants": len(self.invariants),
            "total_violations": len(self.violations),
            "candidate_violations": len(self.candidates),
            "by_severity": by_severity,
        }
