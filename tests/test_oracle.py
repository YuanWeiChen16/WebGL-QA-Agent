"""Tests for webgl_qa.oracle — invariant kinds, skip-on-None, min_occurrences,
record=False re-evaluation, and the action-signature helper used by the
post-action assertion (AD-4)."""

import pytest

from webgl_qa.oracle import Oracle, Invariant


class FakeConfig:
    """Minimal stand-in for webgl_qa.config.Config."""

    def __init__(self, invariants):
        self._inv = invariants

    def get(self, key, default=None):
        if key == "oracle.invariants":
            return self._inv
        return default


def make_oracle(invariants):
    return Oracle(config=FakeConfig(invariants))


# ---------------------------------------------------------------- kinds

class TestKinds:
    def test_increment_pass_and_fail(self):
        oc = make_oracle([{"id": "lvl", "when": "upgrade", "field": "level",
                           "kind": "increment", "delta": 1}])
        assert oc.check_action("upgrade", {"level": 2}, {"level": 3}) == []
        out = oc.check_action("upgrade", {"level": 2}, {"level": 2})
        assert len(out) == 1
        assert out[0].evidence["invariant"] == "lvl"

    def test_monotonic_increase(self):
        oc = make_oracle([{"id": "s", "field": "score", "kind": "monotonic_increase"}])
        assert oc.check_action("any", {"score": 10}, {"score": 10}) == []
        assert len(oc.check_action("any", {"score": 10}, {"score": 9})) == 1

    def test_decrease_or_flag(self):
        inv = [{"id": "c", "when": "shoot", "field": "currency",
                "kind": "decrease_or_flag", "unless_flag": "reward_detected"}]
        oc = make_oracle(inv)
        # increase without reward -> violation
        assert len(oc.check_action("shoot", {"currency": 100}, {"currency": 120})) == 1
        # increase WITH reward flag -> ok
        oc2 = make_oracle(inv)
        assert oc2.check_action("shoot", {"currency": 100}, {"currency": 120},
                                flags={"reward_detected": True}) == []

    def test_range_only_needs_after(self):
        oc = make_oracle([{"id": "r", "field": "currency", "kind": "range", "min": 0}])
        assert oc.check_action("any", {}, {"currency": 0}) == []
        assert len(oc.check_action("any", {}, {"currency": -5})) == 1

    def test_must_change(self):
        oc = make_oracle([{"id": "m", "field": "score", "kind": "must_change"}])
        assert len(oc.check_action("any", {"score": 5}, {"score": 5})) == 1
        assert oc.check_action("any", {"score": 5}, {"score": 6}) == []

    def test_unknown_kind_ignored(self):
        oc = make_oracle([{"id": "x", "field": "score", "kind": "no_such_kind"}])
        assert oc.invariants == []


# ---------------------------------------------------------------- skip on None

class TestSkipOnUnreadable:
    def test_none_values_skip(self):
        oc = make_oracle([{"id": "lvl", "field": "level", "kind": "increment"}])
        assert oc.check_action("any", {"level": None}, {"level": 3}) == []
        assert oc.check_action("any", {"level": 2}, {"level": None}) == []
        assert oc.check_action("any", {}, {}) == []

    def test_bool_is_not_numeric(self):
        oc = make_oracle([{"id": "lvl", "field": "level", "kind": "increment"}])
        assert oc.check_action("any", {"level": True}, {"level": 2}) == []

    def test_skip_does_not_reset_streak(self):
        oc = make_oracle([{"id": "s", "field": "score",
                           "kind": "monotonic_increase", "min_occurrences": 2}])
        oc.check_action("any", {"score": 10}, {"score": 9})     # streak 1
        oc.check_action("any", {"score": None}, {"score": None})  # skip — no reset
        out = oc.check_action("any", {"score": 10}, {"score": 9})  # streak 2
        assert out[0].evidence["confirmed"] is True


# ---------------------------------------------------------------- min_occurrences

class TestMinOccurrences:
    def test_candidate_until_threshold(self):
        oc = make_oracle([{"id": "c", "when": "shoot", "field": "currency",
                           "kind": "decrease_or_flag", "min_occurrences": 3}])
        v1 = oc.check_action("shoot", {"currency": 100}, {"currency": 120})[0]
        v2 = oc.check_action("shoot", {"currency": 100}, {"currency": 130})[0]
        v3 = oc.check_action("shoot", {"currency": 100}, {"currency": 140})[0]
        assert (v1.evidence["confirmed"], v2.evidence["confirmed"],
                v3.evidence["confirmed"]) == (False, False, True)
        assert (v1.evidence["occurrence"], v3.evidence["occurrence"]) == (1, 3)
        assert len(oc.candidates) == 2
        assert len(oc.violations) == 1

    def test_pass_resets_streak(self):
        oc = make_oracle([{"id": "c", "when": "shoot", "field": "currency",
                           "kind": "decrease_or_flag", "min_occurrences": 2}])
        oc.check_action("shoot", {"currency": 100}, {"currency": 120})  # streak 1
        oc.check_action("shoot", {"currency": 100}, {"currency": 90})   # pass -> reset
        out = oc.check_action("shoot", {"currency": 100}, {"currency": 120})
        assert out[0].evidence["occurrence"] == 1
        assert out[0].evidence["confirmed"] is False

    def test_default_is_immediate(self):
        oc = make_oracle([{"id": "lvl", "when": "upgrade", "field": "level",
                           "kind": "increment"}])
        out = oc.check_action("upgrade", {"level": 2}, {"level": 2})
        assert out[0].evidence["confirmed"] is True

    def test_summary_counts(self):
        oc = make_oracle([{"id": "c", "field": "currency",
                           "kind": "decrease_or_flag", "min_occurrences": 2}])
        oc.check_action("any", {"currency": 1}, {"currency": 2})
        s = oc.get_summary()
        assert s["candidate_violations"] == 1
        assert s["total_violations"] == 0


# ---------------------------------------------------------------- record=False

class TestRecordFalse:
    def test_no_side_effects(self):
        oc = make_oracle([{"id": "lvl", "when": "upgrade", "field": "level",
                           "kind": "increment", "min_occurrences": 2}])
        out = oc.check_action("upgrade", {"level": 2}, {"level": 2}, record=False)
        assert len(out) == 1
        assert out[0].evidence["occurrence"] is None
        assert oc.violations == [] and oc.candidates == []
        assert oc._streaks == {}


# ---------------------------------------------------------------- when filter

class TestWhenFilter:
    def test_when_filters_by_action_tag(self):
        oc = make_oracle([
            {"id": "lvl", "when": "upgrade", "field": "level", "kind": "increment"},
            {"id": "neg", "when": "", "field": "currency", "kind": "range", "min": 0},
        ])
        # "shoot" only triggers the always-on invariant
        out = oc.check_action("shoot", {"level": 2, "currency": 5},
                              {"level": 2, "currency": -1})
        assert [v.evidence["invariant"] for v in out] == ["neg"]
        assert oc.applicable_count("upgrade") == 2
        assert oc.applicable_count("shoot") == 1


# ---------------------------------------------------------------- action signature

class TestActionSignature:
    def test_grid_and_kinds(self):
        from webgl_qa.agent import GameSession
        sig = GameSession._action_signature
        # same 10px cell -> same signature (tolerates jitter)
        assert sig("click", {"x": 101, "y": 205}) == sig("click", {"x": 109, "y": 209})
        assert sig("click", {"x": 101, "y": 205}) != sig("click", {"x": 111, "y": 205})
        assert sig("key", {"key": "space"}) == "key@space"
        assert sig("drag", {"from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4}).startswith("drag@")
        assert sig("type", {"text": "abc"}) == "type"
