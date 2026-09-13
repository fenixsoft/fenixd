"""tests for spec-review-gate skip whitelist and transition validation.

Covers:
- Skip whitelist: all 4 criteria must match to skip; evo- hard veto
- Conservative: missing mode / missing deliverables → does not skip
- never mode: all channels go straight to ready
- reviewing transitions valid/invalid
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, SpecStatus, VALID_TRANSITIONS
from core.pm_engine.promotion import should_skip_review


def _mk_spec_dir(proot: Path, name: str, mode="fast-track", cap_dirs=1,
                 deliverables=2, is_evo=False) -> Path:
    """Create a spec dir with controllable mode / capability dirs / deliverables count."""
    name = f"evo-{name}" if is_evo else name
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    # .spec.yaml
    (d / ".spec.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")
    # capabilities
    if cap_dirs >= 0:
        specs_dir = d / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        for i in range(cap_dirs):
            (specs_dir / f"cap{i}").mkdir()
    # tasks.md with deliverables count
    entries = "\n".join(
        f"- path: core/file{i}.py\n  kind: modify\n" for i in range(deliverables)
    ) if deliverables >= 0 else ""
    (d / "tasks.md").write_text(
        f"# Tasks\n\n## Deliverables\n\n```yaml\n{entries}```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )
    return d


class TestSkipWhitelist(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self, mode="auto"):
        return {"gates": {"promote_mode": "auto", "spec_review_mode": mode}}

    def test_all_four_match_skips(self):
        """fast-track + 1 cap + <=3 deliverables + non-evo → skip."""
        _mk_spec_dir(self.proot, "simple", cap_dirs=1, deliverables=2)
        self.assertTrue(should_skip_review(self.proot, "simple", self._cfg(), MagicMock()))

    def test_evo_hard_veto(self):
        """evo- prefix → never skip even if all other criteria match."""
        _mk_spec_dir(self.proot, "evo-simple", cap_dirs=1, deliverables=2, is_evo=True)
        self.assertFalse(should_skip_review(self.proot, "evo-simple", self._cfg(), MagicMock()))

    def test_non_fast_track_no_skip(self):
        """mode=full → not skipped."""
        _mk_spec_dir(self.proot, "fullspec", mode="full", cap_dirs=1, deliverables=2)
        self.assertFalse(should_skip_review(self.proot, "fullspec", self._cfg(), MagicMock()))

    def test_cap_count_over_threshold_no_skip(self):
        """2 capability dirs → not skipped."""
        _mk_spec_dir(self.proot, "multicap", cap_dirs=2, deliverables=2)
        self.assertFalse(should_skip_review(self.proot, "multicap", self._cfg(), MagicMock()))

    def test_deliverables_over_threshold_no_skip(self):
        """4 deliverables → not skipped."""
        _mk_spec_dir(self.proot, "bigdeliv", cap_dirs=1, deliverables=4)
        self.assertFalse(should_skip_review(self.proot, "bigdeliv", self._cfg(), MagicMock()))

    def test_missing_mode_conservative_no_skip(self):
        """No mode field → not skipped."""
        d = self.proot / "spec" / "changes" / "nomode"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text("name: x\n", encoding="utf-8")
        (d / "tasks.md").write_text("# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertFalse(should_skip_review(self.proot, "nomode", self._cfg(), MagicMock()))

    def test_missing_deliverables_conservative_no_skip(self):
        """No Deliverables section → not skipped."""
        d = self.proot / "spec" / "changes" / "nodecl"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text("mode: fast-track\n", encoding="utf-8")
        (d / "tasks.md").write_text("# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertFalse(should_skip_review(self.proot, "nodecl", self._cfg(), MagicMock()))

    def test_never_mode_always_skip(self):
        """spec_review_mode=never → skip regardless of criteria."""
        _mk_spec_dir(self.proot, "evo-never", cap_dirs=5, deliverables=10, is_evo=True)
        self.assertTrue(should_skip_review(self.proot, "evo-never", {"gates": {"spec_review_mode": "never"}}, MagicMock()))


class TestReviewingTransitions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add(self, name="spec", status="drafted"):
        self.sm.add_spec(name, {"status": status})
        return name

    def test_drafted_can_enter_reviewing(self):
        self._add()
        self.assertTrue(self.sm.transition("spec", "reviewing"))
        self.assertEqual(self.sm.read_one("spec")["status"], "reviewing")

    def test_reviewing_to_ready(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertTrue(self.sm.transition("spec", "ready"))

    def test_reviewing_to_blocked(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertTrue(self.sm.transition("spec", "blocked"))

    def test_blocked_to_reviewing(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.sm.transition("spec", "blocked")
        self.assertTrue(self.sm.transition("spec", "reviewing"))

    def test_illegal_transition_rejected(self):
        """reviewing → implementing is illegal and keeps state."""
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertFalse(self.sm.transition("spec", "implementing"))
        self.assertEqual(self.sm.read_one("spec")["status"], "reviewing")

    def test_all_statuses_contains_reviewing(self):
        self.assertIn(SpecStatus.REVIEWING, SpecStatus.ALL)
        self.assertEqual(len(SpecStatus.ALL), 11)

    def test_gate_transitions_excludes_reviewing(self):
        """Gate escape-hatch MUST NOT include reviewing."""
        from core.state_machine import GATE_TRANSITIONS
        for targets in GATE_TRANSITIONS.values():
            self.assertNotIn(SpecStatus.REVIEWING, targets)

    def test_interrupted_includes_reviewing(self):
        from core.state_machine import INTERRUPTED_STATES
        self.assertIn(SpecStatus.REVIEWING, INTERRUPTED_STATES)


if __name__ == "__main__":
    unittest.main()