"""add-verify-evidence-placement-contract 单测（tasks.md 3.1）。

覆盖：
- evidence_dir 缺省/覆盖/非法回退（加载层 warning + 回退缺省）
- 模板 evidence_dir 注释化声明与示例解析
- untracked 信号 entry 级判定（混合目录 tracked 条目不报）、tracked 空集 +
  纯 untracked 场景信号仍触发（_sweep_locked tracked 空集早退插桩回归点）、
  .fenix/ negation 放行项与 ignored 路径豁免、同指纹一次性（内容演化不重告）、
  指纹消失复位、阈值/宽限配置解析
- admin_monitor 断言（severity=info 与文案两表登记在册、STORED_SIGNAL_TYPES
  不含 maintree_untracked_stray_stale）
- prompt_builder 证据落位契约段（绝对路径渲染/契约覆盖/非法回退）
- untracked 注册表持久化（evo-persist-stray-escalation-clock 2.1）：重启
  模拟（清内存→重载注册表→elapsed 连续累计并命中升级）、合成旧时间戳
  驱动升级路径、同指纹跨重启不重复告警、已升级集合跨重启不重复发升级
  信号（escalated_signal_at 持久化）、持久化文件损坏回退降级、失效路径
  惰性清理后不复燃
"""

import inspect
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import yaml

from core.admin_monitor import (
    SIGNAL_RECOMMENDATION,
    SIGNAL_SEVERITY,
    STORED_SIGNAL_TYPES,
)
from core.admin_store import AdminStore, SIGNAL
from core.verify_contract import (
    DEFAULT_EVIDENCE_MAX_BINARY_BYTES,
    VerifyContract,
    default_evidence_dir,
    load_verify_contract,
)
from core.worktree_manager.stray_wip import (
    SIGNAL_TYPE,
    UNTRACKED_ESCALATED_SIGNAL_TYPE,
    UNTRACKED_REGISTRY_RELPATH,
    UNTRACKED_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
    grace_minutes,
    untracked_stray_threshold,
)

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款规避）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _status(repo) -> str:
    """主树工作区状态原文（零触碰对账基准，逐字节比较）。"""
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


class _WmProbe:
    """WorktreeManager 探针壳（test_maintree_stray_wip_sweep 同款装配）。"""

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _make_repo(ignore_rules: str = ".fenix/*\n!.fenix/verify.yaml\n") -> Path:
    """主树仓：a/b.tsx 已提交；.gitignore=``.fenix/*`` + ``!.fenix/verify.yaml``

    （negation 放行项 + 忽略目录的生产形态，豁免判定的判据现场）。
    """
    base = Path(_mkdtemp("evidence-scene-"))
    repo = base / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(ignore_rules, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def _make_sweeper(repo, grace=30.0, threshold=None) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": grace}}
    if threshold is not None:
        cfg["admin"]["maintree_untracked_stray_threshold"] = threshold
    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=None)


def _untracked_alerts(repo) -> list:
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == UNTRACKED_SIGNAL_TYPE
    ]


class _LoggerProbe:
    """capture warning 的日志探针（加载层「告警＋回退」断言用）。"""

    def __init__(self):
        self.warnings = []

    def warning(self, tag, msg):
        self.warnings.append((tag, msg))

    def info(self, tag, msg):
        pass


def _write_strays(repo, names):
    for n in names:
        p = repo / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"stray {n}\n", encoding="utf-8")


class TestEvidenceDirContract(unittest.TestCase):
    """evidence_dir 缺省/覆盖/非法回退（1.1）。"""

    def test_default_template_and_relative(self):
        self.assertEqual(
            default_evidence_dir("spec-a"), ".fenix/verify-evidence/spec-a"
        )
        resolved = VerifyContract().resolve_evidence_dir("spec-a")
        self.assertEqual(resolved, ".fenix/verify-evidence/spec-a")
        self.assertFalse(resolved.startswith("/"))  # 报告只引用相对路径

    def test_contract_override_wins(self):
        c = VerifyContract(evidence_dir="docs/evidence")
        self.assertEqual(c.resolve_evidence_dir("spec-a"), "docs/evidence")

    def test_load_declared_value(self):
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "evidence_dir: custom/evidence\n", encoding="utf-8"
        )
        c = load_verify_contract(repo)
        self.assertIsNotNone(c)
        self.assertEqual(c.evidence_dir, "custom/evidence")
        self.assertEqual(c.resolve_evidence_dir("spec-a"), "custom/evidence")

    def test_load_absent_field_falls_back_to_default(self):
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "deps_mode: hardlink\n", encoding="utf-8"
        )
        c = load_verify_contract(repo)
        self.assertEqual(c.evidence_dir, "")
        self.assertEqual(
            c.resolve_evidence_dir("spec-a"), ".fenix/verify-evidence/spec-a"
        )

    def test_load_illegal_values_warn_and_fall_back(self):
        for bad in ("/abs/path", "../escape", "a/../../b", "123"):
            with self.subTest(bad=bad):
                repo = _make_repo()
                (repo / ".fenix").mkdir(exist_ok=True)
                (repo / ".fenix" / "verify.yaml").write_text(
                    f"evidence_dir: {bad}\n", encoding="utf-8"
                )
                logger = _LoggerProbe()
                c = load_verify_contract(repo, logger=logger)
                self.assertEqual(c.evidence_dir, "")
                self.assertEqual(
                    c.resolve_evidence_dir("spec-a"),
                    ".fenix/verify-evidence/spec-a",
                )
                self.assertTrue(
                    any("evidence_dir" in msg for _, msg in logger.warnings),
                    f"非法值 {bad!r} 未记 warning",
                )


class TestTemplateDeclaration(unittest.TestCase):
    """模板 evidence_dir 注释化声明与示例（1.2）。"""

    TEMPLATE = (
        Path(__file__).resolve().parent.parent
        / "core" / "verify_contract_template.yaml"
    )

    def test_template_declares_evidence_dir_in_comments(self):
        text = self.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("evidence_dir", text)
        self.assertIn(".fenix/verify-evidence", text)
        # 注释化声明：不存在未注释的顶层 evidence_dir 键（缺省=未声明）
        for line in text.splitlines():
            self.assertFalse(
                line.startswith("evidence_dir:"),
                f"模板出现了未注释的 evidence_dir 声明: {line}",
            )

    def test_uncommented_example_parses_and_loads(self):
        """用户取消注释示例行后，契约以声明值逐字为准（声明即逐字语义）。"""
        text = self.TEMPLATE.read_text(encoding="utf-8")
        patched = text.replace(
            "# evidence_dir: .fenix/verify-evidence/<spec>/",
            "evidence_dir: .fenix/verify-evidence/<spec>/",
        )
        data = yaml.safe_load(patched)
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("evidence_dir"), ".fenix/verify-evidence/<spec>/")
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(patched, encoding="utf-8")
        c = load_verify_contract(repo)
        self.assertEqual(c.evidence_dir, ".fenix/verify-evidence/<spec>/")
        self.assertEqual(c.resolve_evidence_dir("spec-a"), ".fenix/verify-evidence/<spec>/")

    def test_template_as_is_loads_with_default(self):
        """模板保持注释原样（缺省形态）加载：字段为空、resolve 走缺省。"""
        text = self.TEMPLATE.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        self.assertIsNone(data)  # 全注释 = 空文档 = 无契约（load 层回退旧行为）
        self.assertEqual(
            VerifyContract().resolve_evidence_dir("spec-a"),
            ".fenix/verify-evidence/spec-a",
        )

    def test_template_declares_evidence_retention_tiering(self):
        """分级留存声明（verify-evidence-tiered-retention 1.1）：注释化字段
        + 分级规则注释在案；缺省 10485760；取消注释后按声明值加载。"""
        text = self.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("evidence_retention", text)
        self.assertIn("max_binary_bytes", text)
        self.assertIn("10485760", text)
        # 分级规则注释：文本直接入库 + 超阈值二进制以 sidecar/登记替代
        self.assertIn("sha256", text)
        for line in text.splitlines():
            self.assertFalse(
                line.startswith("evidence_retention:"),
                f"模板出现了未注释的 evidence_retention 声明: {line}",
            )
        patched = text.replace(
            "# evidence_retention:",
            "evidence_retention:",
        ).replace(
            "#   max_binary_bytes: 10485760",
            "  max_binary_bytes: 10485760",
        )
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(patched, encoding="utf-8")
        c = load_verify_contract(repo)
        self.assertEqual(c.evidence_max_binary_bytes, DEFAULT_EVIDENCE_MAX_BINARY_BYTES)


class TestUntrackedSignal(unittest.TestCase):
    """untracked 散件盘点信号（2.1）：entry 级/早退插桩/豁免/一次性/复位。"""

    STRAYS = [f"stray_{i}.tmp" for i in range(5)]

    def test_pure_untracked_fires_before_tracked_empty_early_exit(self):
        """:163-165 早退插桩回归点——tracked 零改动时 untracked 信号仍触发。"""
        repo = _make_repo()
        _write_strays(repo, self.STRAYS)
        sw = _make_sweeper(repo, grace=0.0)
        before = _status(repo)
        r = sw.sweep()
        after = _status(repo)
        # tracked 口径现行行为不变：仍返回 clean 形态（零 untracked 附加前键）
        self.assertEqual(r["status"], "clean")
        self.assertEqual(r["files"], [])
        self.assertEqual(r["fingerprint"], "")
        # 纯 untracked 场景信号照常触发（早退前已盘点）
        self.assertEqual(r["untracked"]["status"], "alerted")
        self.assertEqual(r["untracked"]["count"], 5)
        # 一次性 info 告警落 store
        alerts = _untracked_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].get("severity"), "info")
        self.assertIsNone(alerts[0].get("spec"))
        # 零触碰：盘点/告警前后 porcelain 逐字节一致
        self.assertEqual(before, after)

    def test_below_threshold_no_alert(self):
        repo = _make_repo()
        _write_strays(repo, self.STRAYS[:4])
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["untracked"]["status"], "below-threshold")
        self.assertEqual(r["untracked"]["threshold"], 5)
        self.assertEqual(_untracked_alerts(repo), [])

    def test_threshold_config_lowers_gate(self):
        repo = _make_repo()
        _write_strays(repo, self.STRAYS[:3])
        sw = _make_sweeper(repo, grace=0.0, threshold=2)
        r = sw.sweep()
        self.assertEqual(r["untracked"]["status"], "alerted")
        self.assertEqual(r["untracked"]["threshold"], 2)

    def test_exempt_negation_allow_and_ignored_paths(self):
        """.fenix/ negation 放行项与已 ignore 路径不误报（entry 级豁免）。"""
        repo = _make_repo(ignore_rules=".fenix/*\n!.fenix/verify.yaml\n*.log\n")
        # .fenix/verify.yaml = negation 放行项（porcelain 以 ?? 在场但有意放行）
        fenix = repo / ".fenix"
        fenix.mkdir(exist_ok=True)
        (fenix / "verify.yaml").write_text("ready:\n  url: /\n", encoding="utf-8")
        # debug.log = 已 ignore 路径（*.log 规则覆盖）
        (repo / "debug.log").write_text("ignored\n", encoding="utf-8")
        # 4 个真散件：4 < 5 → below-threshold（放行项与 ignored 未被计入）
        _write_strays(repo, self.STRAYS[:4])
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["untracked"]["status"], "below-threshold")
        self.assertNotIn(".fenix/verify.yaml", r["untracked"]["files"])
        self.assertNotIn("debug.log", r["untracked"]["files"])
        # 第 5 个真散件入场 → 恰 5 个真散件越过阈值
        _write_strays(repo, ["stray_9.tmp"])
        r2 = sw.sweep()
        self.assertEqual(r2["untracked"]["status"], "alerted")
        evidence = _untracked_alerts(repo)[0].get("evidence") or ""
        self.assertNotIn(".fenix/verify.yaml", evidence)
        self.assertNotIn("debug.log", evidence)
        self.assertIn("stray_0.tmp", evidence)

    def test_entry_level_mixed_dir_tracked_entries_not_counted(self):
        """混合目录 entry 级判定：verify-evidence/ 内已 tracked 条目不误报。"""
        repo = _make_repo()
        ev = repo / "evidence"
        ev.mkdir()
        (ev / "committed.log").write_text("tracked\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "evidence baseline", cwd=repo)
        # 目录内混入 5 个 untracked 散件（已 tracked 条目不出现 untracked 清单）
        _write_strays(repo, [f"evidence/dump_{i}.json" for i in range(5)])
        sw = _make_sweeper(repo, grace=0.0)
        r = sw.sweep()
        self.assertEqual(r["status"], "clean")  # tracked 零改动
        u = r["untracked"]
        self.assertEqual(u["status"], "alerted")
        self.assertEqual(len(u["files"]), 5)
        self.assertNotIn("evidence/committed.log", u["files"])
        # 目录不被整体豁免：散件逐个计入（无忽略规则项目的兜底可见性）
        self.assertIn("evidence/dump_0.json", u["files"])

    def test_same_fingerprint_one_shot_and_evolution_no_realert(self):
        """同指纹一次性；内容演化产生新指纹、宽限未到不重告。"""
        repo = _make_repo()
        _write_strays(repo, self.STRAYS)
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        self.assertEqual(r1["untracked"]["status"], "timed")  # 宽限未到
        # 回拨 first_seen 模拟滞留耗尽（内容指纹口径不依赖 mtime）
        sw._untracked_registry[r1["untracked"]["fingerprint"]]["first_seen"] -= 3600
        r2 = sw.sweep()
        self.assertEqual(r2["untracked"]["status"], "alerted")
        self.assertEqual(len(_untracked_alerts(repo)), 1)
        # 同指纹重复盘点不重复告警
        r3 = sw.sweep()
        self.assertEqual(r3["untracked"]["status"], "timed")
        self.assertEqual(len(_untracked_alerts(repo)), 1)
        # 内容演化 → 新指纹 → 新 first_seen → 宽限未到不重告
        (repo / "stray_0.tmp").write_text("evolved\n", encoding="utf-8")
        r4 = sw.sweep()
        self.assertNotEqual(r4["untracked"]["fingerprint"], r2["untracked"]["fingerprint"])
        self.assertEqual(r4["untracked"]["status"], "timed")
        self.assertEqual(len(_untracked_alerts(repo)), 1)
        # 新指纹滞留耗尽后照常升级（新状态不被旧指纹 escalated_at 拖住）
        sw._untracked_registry[r4["untracked"]["fingerprint"]]["first_seen"] -= 3600
        r5 = sw.sweep()
        self.assertEqual(r5["untracked"]["status"], "alerted")
        self.assertEqual(len(_untracked_alerts(repo)), 2)

    def test_fingerprint_disappearance_resets_state(self):
        """指纹消失自动复位；同指纹再现时重新起算并可再告警。"""
        repo = _make_repo()
        _write_strays(repo, self.STRAYS)
        sw = _make_sweeper(repo, grace=0.0)
        self.assertEqual(sw.sweep()["untracked"]["status"], "alerted")
        self.assertEqual(len(_untracked_alerts(repo)), 1)
        # 散件全部消失 → 注册表复位（untracked 键不出现）
        for n in self.STRAYS:
            (repo / n).unlink()
        r2 = sw.sweep()
        self.assertNotIn("untracked", r2)
        self.assertEqual(sw._untracked_registry, {})
        # 同一指纹再现 → 复位后重新起算，宽限 0 下再告警（未被旧 escalated_at 拖住）
        _write_strays(repo, self.STRAYS)
        r3 = sw.sweep()
        self.assertEqual(r3["untracked"]["status"], "alerted")
        self.assertEqual(len(_untracked_alerts(repo)), 2)

    def test_tracked_and_untracked_streams_merge_additively(self):
        """双流并存：tracked 口径行为不变，untracked 结果以附加键并入。"""
        repo = _make_repo()
        (repo / "a.tsx").write_text("main wip", encoding="utf-8")  # tracked 散件
        _write_strays(repo, self.STRAYS)
        sw = _make_sweeper(repo, grace=0.0)
        before = _status(repo)
        r = sw.sweep()
        # tracked 流形态不变（宽限 0 → 无主升级 major）
        self.assertIn(r["status"], ("alerted", "orphan-timed"))
        self.assertEqual(r["files"], ["a.tsx"])
        # untracked 流以附加键并入，互不干扰
        self.assertEqual(r["untracked"]["status"], "alerted")
        self.assertEqual(r["untracked"]["count"], 5)
        # 两类告警各落各的 signal_type，severity 各归各（major/info）
        store = AdminStore(repo).read_all()
        by_type = {r_.get("signal_type"): r_ for r_ in store if r_.get("kind") == SIGNAL}
        self.assertEqual(by_type[SIGNAL_TYPE].get("severity"), "major")
        self.assertEqual(by_type[UNTRACKED_SIGNAL_TYPE].get("severity"), "info")
        self.assertEqual(before, _status(repo))  # 零触碰

    def test_check_ignore_failure_abandons_round(self):
        """check-ignore 不可用 → 放弃本轮（保守，条目保留不告警）。"""
        repo = _make_repo()
        _write_strays(repo, self.STRAYS)
        sw = _make_sweeper(repo, grace=0.0)
        sw._git_check_ignore_detail = lambda paths: None
        self.assertIsNone(sw.sweep())
        self.assertEqual(_untracked_alerts(repo), [])


class TestThresholdAndGraceConfig(unittest.TestCase):
    """阈值/宽限配置解析（ConfigLoader 点号键，守卫回退对齐 grace_minutes）。"""

    def test_threshold_default_and_fallbacks(self):
        self.assertEqual(untracked_stray_threshold({}), 5)
        self.assertEqual(untracked_stray_threshold(None), 5)
        self.assertEqual(untracked_stray_threshold({"admin": {}}, ), 5)
        for bad in (0, -1, "abc", None, float("inf"), float("nan"), 0.5):
            self.assertEqual(
                untracked_stray_threshold({"admin": {"maintree_untracked_stray_threshold": bad}}),
                5,
                f"非法阈值 {bad!r} 未回退缺省",
            )

    def test_threshold_valid_values(self):
        self.assertEqual(
            untracked_stray_threshold({"admin": {"maintree_untracked_stray_threshold": 8}}), 8
        )
        self.assertEqual(
            untracked_stray_threshold({"admin": {"maintree_untracked_stray_threshold": "3"}}), 3
        )
        self.assertEqual(
            untracked_stray_threshold({"admin": {"maintree_untracked_stray_threshold": 5.9}}), 5
        )

    def test_grace_reused_for_untracked(self):
        """宽限复用 admin.maintree_stray_wip_grace_minutes（同族同语义）。"""
        self.assertEqual(grace_minutes({}), 30.0)
        self.assertEqual(
            grace_minutes({"admin": {"maintree_stray_wip_grace_minutes": 7}}), 7.0
        )


class TestAdminMonitorRegistration(unittest.TestCase):
    """admin_monitor 两表登记在册、STORED_SIGNAL_TYPES 不收录（2.2）。"""

    def test_severity_registered_as_info(self):
        self.assertEqual(SIGNAL_SEVERITY.get(UNTRACKED_SIGNAL_TYPE), "info")

    def test_recommendation_registered_alert_only(self):
        text = SIGNAL_RECOMMENDATION.get(UNTRACKED_SIGNAL_TYPE)
        self.assertIsInstance(text, str) and self.assertTrue(text)
        self.assertIn("只告警不处置", text)

    def test_not_in_stored_signal_types(self):
        """MUST NOT 收录 STORED_SIGNAL_TYPES：收录即把 info 留痕升级为人工唤起。"""
        self.assertNotIn(UNTRACKED_SIGNAL_TYPE, STORED_SIGNAL_TYPES)
        # 姊妹信号（tracked 口径）收录形态不回退
        self.assertIn(SIGNAL_TYPE, STORED_SIGNAL_TYPES)

    def test_alert_record_shape(self):
        """盘点落盘的记录形态：kind=signal、severity=info、无 spec、证据含清单。"""
        repo = _make_repo()
        _write_strays(repo, [f"stray_{i}.tmp" for i in range(5)])
        sw = _make_sweeper(repo, grace=0.0)
        sw.sweep()
        rec = _untracked_alerts(repo)[0]
        self.assertEqual(rec.get("kind"), SIGNAL)
        self.assertEqual(rec.get("severity"), "info")
        self.assertIsNone(rec.get("spec"))
        self.assertEqual(rec.get("source"), "maintree-stray-wip-sweep")
        for frag in ("项目名=", "文件清单", "零触碰注记", "豁免注记"):
            self.assertIn(frag, rec.get("evidence") or "")


class _PmStub:
    def __init__(self, root):
        self.project_root = Path(root)


class TestEvidencePlacementPrompt(unittest.TestCase):
    """prompt_builder 证据落位契约段（1.3）。"""

    def test_default_renders_maintree_absolute_path(self):
        repo = _make_repo()
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn(str(repo / ".fenix" / "verify-evidence" / "spec-a"), section)
        self.assertIn(".fenix/verify-evidence/spec-a", section)
        self.assertIn("MUST NOT", section)
        self.assertIn("worktree", section)  # 禁止落 worktree 相对路径的明示

    def test_contract_override_rendered(self):
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "evidence_dir: custom/evidence\n", encoding="utf-8"
        )
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn(str(repo / "custom" / "evidence"), section)

    def test_illegal_contract_value_falls_back_to_default(self):
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "evidence_dir: /abs\n", encoding="utf-8"
        )
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn(str(repo / ".fenix" / "verify-evidence" / "spec-a"), section)

    def test_retention_clause_rendered_with_declared_threshold(self):
        """契约声明自定义阈值 → 指引含分级条款且阈值取声明值（tiered-retention
        Acceptance Scenario 4）。"""
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "evidence_retention:\n  max_binary_bytes: 2048\n", encoding="utf-8"
        )
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn("分级留存", section)
        self.assertIn("sha256 sidecar", section)
        self.assertIn("MUST NOT", section)
        self.assertIn("2048", section)  # 阈值取契约声明值

    def test_retention_clause_rendered_with_default_threshold(self):
        """契约未声明阈值（缺省 10MB）→ 指引同样含分级条款（Scenario 5）。"""
        repo = _make_repo()
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "deps_mode: hardlink\n", encoding="utf-8"
        )
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn("分级留存", section)
        self.assertIn("sha256 sidecar", section)
        self.assertIn(str(DEFAULT_EVIDENCE_MAX_BINARY_BYTES // (1024 * 1024)), section)

    def test_retention_clause_survives_contract_load_failure(self):
        """契约整体缺失（软约束 fail-open）→ 分级条款以缺省阈值照常渲染。"""
        repo = _make_repo()  # 无 .fenix/verify.yaml
        from core.agent_runner.prompt_builder import PromptBuilder

        section = PromptBuilder(_PmStub(repo))._evidence_placement_section("spec-a")
        self.assertIn("分级留存", section)
        self.assertIn("10MB", section)

    def test_injection_wiring_covers_impl_and_verify_lanes(self):
        """注入点在案：implementer/fast-track/verifier 三车道统一收尾处。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        src = inspect.getsource(PromptBuilder._build_prompt)
        self.assertIn("_evidence_placement_section", src)
        self.assertIn('"implementer", "fast-track", "verifier"', src)


class TestUntrackedRegistryPersistence(unittest.TestCase):
    """untracked 注册表持久化（evo-persist-stray-escalation-clock 2.1）。

    重启以「新 sweeper 实例＝新进程内存态」模拟：内存注册表清零，持久化
    文件是跨重启唯一时钟载体——与 daemon 重启后 sweeper 重新装配的形态
    同构。旧时间戳注入落点为持久化文件（spec 验收口径：合成旧时间戳的
    注册表驱动升级路径命中）。
    """

    def _registry_path(self, repo) -> Path:
        return repo / UNTRACKED_REGISTRY_RELPATH

    def _inject_first_seen(self, repo, fp: str, epoch: float) -> None:
        """向持久化文件注入旧 first_seen（spec「合成时钟命中升级」口径）。

        持久化文件顶层两分区（evo-stray-first-sight-prevention 1.2）：
        ``untracked``＝指纹注册表，时钟注入落在该分区的指纹条目上。
        """
        data = json.loads(self._registry_path(repo).read_text(encoding="utf-8"))
        self.assertIn(fp, data["untracked"])
        data["untracked"][fp]["first_seen"] = epoch
        data["untracked"][fp]["first_seen_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)
        )
        self._registry_path(repo).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _escalated_alerts(self, repo) -> list:
        return [
            r
            for r in AdminStore(repo).read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == UNTRACKED_ESCALATED_SIGNAL_TYPE
        ]

    def test_restart_continuity_hits_escalation(self):
        """重启模拟：清内存→重载注册表→elapsed 连续累计命中升级信号。

        first_seen 自持久化文件恢复（注入早于 24h），重启后首轮盘点即以
        恢复时钟计算 elapsed ≥1440 分钟并触发 maintree_untracked_stray_
        escalated——不因中途重启而重新宽限（Requirement 重启后滞留计时
        连续 + 滞留升级触发有效性）。
        """
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        r1 = sw.sweep()
        fp = r1["untracked"]["fingerprint"]
        # 首轮已把注册表落盘（first_seen≈now、无任何升级标记）
        persisted = json.loads(
            self._registry_path(repo).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(persisted), {"untracked", "first_sight_dirs"}
        )  # 顶层两分区（evo-stray-first-sight-prevention 1.2）
        self.assertIn(fp, persisted["untracked"])
        self.assertEqual(set(persisted["untracked"][fp]), {
            "first_seen", "first_seen_iso", "files",
            "escalated_at", "escalated_signal_at",
        })  # 白名单同构：sizes_bytes/total_bytes 现采值不持久化
        # 合成旧时间戳注入持久化注册表 → 新 sweeper＝daemon 重启
        self._inject_first_seen(
            repo, fp, time.time() - (24 * 60 + 5) * 60
        )
        sw2 = _make_sweeper(repo, grace=30.0)
        r2 = sw2.sweep()
        self.assertGreaterEqual(
            r2["untracked"]["elapsed_minutes"], 24 * 60
        )  # 时钟连续：以恢复的 first_seen 计时
        self.assertEqual(r2["untracked"]["status"], "escalated")
        self.assertTrue(r2["untracked"]["escalated_signal"])
        alerts = self._escalated_alerts(repo)
        self.assertEqual(len(alerts), 1)
        self.assertIn("项目名=proj", alerts[0].get("evidence") or "")

    def test_same_fingerprint_no_duplicate_info_alert_across_restart(self):
        """同指纹跨重启不重复告警：重启后集合未变化不产生第二条新告警。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        fp = sw.sweep()["untracked"]["fingerprint"]
        self.assertEqual(_untracked_alerts(repo), [])
        # 注入超宽限但未达 24h 升级的旧时钟 → 重启后首轮触发一次性 info
        self._inject_first_seen(repo, fp, time.time() - 2 * 3600)
        r2 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r2["untracked"]["status"], "alerted")
        self.assertEqual(len(_untracked_alerts(repo)), 1)
        # 第二次重启：escalated_at 已随注册表恢复，同指纹不再重复告警
        r3 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r3["untracked"]["status"], "timed")
        self.assertEqual(len(_untracked_alerts(repo)), 1)

    def test_escalated_marker_persists_no_reescalation(self):
        """已升级集合跨重启不重复发升级信号（escalated_signal_at 持久化）。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        fp = sw.sweep()["untracked"]["fingerprint"]
        self._inject_first_seen(
            repo, fp, time.time() - (24 * 60 + 5) * 60
        )
        r2 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertEqual(r2["untracked"]["status"], "escalated")
        self.assertEqual(len(self._escalated_alerts(repo)), 1)
        # 重启后恢复的条目带 escalated_signal_at → 再次命中滞留阈值也不重发
        persisted = json.loads(
            self._registry_path(repo).read_text(encoding="utf-8")
        )
        self.assertTrue(persisted["untracked"][fp]["escalated_signal_at"])
        r3 = _make_sweeper(repo, grace=30.0).sweep()
        self.assertNotEqual(r3["untracked"]["status"], "escalated")
        self.assertEqual(len(self._escalated_alerts(repo)), 1)
        self.assertEqual(len(_untracked_alerts(repo)), 1)

    def test_corrupt_registry_file_falls_back_without_blocking(self):
        """持久化文件损坏 → 回退空表＋留一条告警，主盘点不阻断。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        self._registry_path(repo).parent.mkdir(parents=True, exist_ok=True)
        self._registry_path(repo).write_text(
            "{not-valid-json!!", encoding="utf-8"
        )
        logger = _LoggerProbe()
        cfg = {"admin": {"maintree_stray_wip_grace_minutes": 30.0}}
        sw = MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=logger)
        r = sw.sweep()  # 不抛异常＝主盘点未阻断
        self.assertIsNotNone(r)
        self.assertEqual(r["untracked"]["status"], "timed")  # 重新宽限起算
        registry_warnings = [
            m for _, m in logger.warnings if "回退空表" in m
        ]
        self.assertEqual(len(registry_warnings), 1)  # 恰留一条告警
        # 后续轮次不再重复告警（每进程一次载入），且落盘自愈为合法形态
        sw.sweep()
        registry_warnings_after = [
            m for _, m in logger.warnings if "回退空表" in m
        ]
        self.assertEqual(len(registry_warnings_after), 1)
        json.loads(self._registry_path(repo).read_text(encoding="utf-8"))

    def test_corrupt_registry_bytes_falls_back_without_blocking(self):
        """字节层损坏（非法 UTF-8）→ 回退空表＋留一条告警，主盘点不阻断。

        半截写入/磁盘错误的典型损坏形态：读码层（read_text utf-8 解码）即
        抛 UnicodeDecodeError，先于 json.loads 发生——异常处理须在读取段
        显式捕获（ValueError 子类、非 OSError），否则上穿 sweep() 主盘点
        整体崩溃（验证轮 BUG-01 回归钉子）。
        """
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        self._registry_path(repo).parent.mkdir(parents=True, exist_ok=True)
        self._registry_path(repo).write_bytes(
            b"\xff\xfe{not-utf8-at-all:\x00\xff}"
        )
        logger = _LoggerProbe()
        cfg = {"admin": {"maintree_stray_wip_grace_minutes": 30.0}}
        sw = MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=logger)
        r = sw.sweep()  # 不抛异常＝主盘点未阻断（BUG-01 曾在此 exit 1）
        self.assertIsNotNone(r)
        self.assertEqual(r["untracked"]["status"], "timed")  # 重新宽限起算
        registry_warnings = [
            m for _, m in logger.warnings if "回退空表" in m
        ]
        self.assertEqual(len(registry_warnings), 1)  # 恰留一条降级告警
        # 后续轮次不再重复告警，且落盘自愈为合法形态
        sw.sweep()
        registry_warnings_after = [
            m for _, m in logger.warnings if "回退空表" in m
        ]
        self.assertEqual(len(registry_warnings_after), 1)
        json.loads(self._registry_path(repo).read_text(encoding="utf-8"))

    def test_stale_paths_pruned_and_no_reignition(self):
        """失效路径惰性清理：已删除散件条目载入即清、指纹不复燃。

        条目整条删除（集合为空）与部分剔除（存活文件保留）两形态都覆盖；
        清理后的历史指纹不参与后续去重与升级（Requirement 失效路径惰性
        清理：已清理散件不复燃）。
        """
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        sw = _make_sweeper(repo, grace=30.0)
        live_fp = sw.sweep()["untracked"]["fingerprint"]
        # 注入历史条目：gone_fp 全部文件已消失（已被处置删除/归档形态）
        gone_fp = "a" * 64
        data = json.loads(
            self._registry_path(repo).read_text(encoding="utf-8")
        )
        data["untracked"][gone_fp] = {
            "first_seen": time.time() - (24 * 60 + 5) * 60,
            "first_seen_iso": "2026-10-01T00:00:00Z",
            "files": ["verify-evidence/gone-a.md", "verify-evidence/gone-b.md"],
            "escalated_at": "",
            "escalated_signal_at": "",
        }
        self._registry_path(repo).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sw2 = _make_sweeper(repo, grace=30.0)
        r2 = sw2.sweep()
        self.assertEqual(r2["untracked"]["fingerprint"], live_fp)
        self.assertEqual(r2["untracked"]["status"], "timed")  # 历史时钟不复燃
        self.assertNotIn(gone_fp, sw2._untracked_registry)  # 载入即清
        after = json.loads(
            self._registry_path(repo).read_text(encoding="utf-8")
        )
        self.assertNotIn(gone_fp, after["untracked"])  # 清理结果随落盘收敛
        self.assertEqual(set(after["untracked"]), {live_fp})

    def test_prune_partial_removal_keeps_alive_paths(self):
        """部分剔除形态：条目内消失路径剔除、存活文件保留（集合非空不删）。"""
        repo = _make_repo()
        _write_strays(repo, ["verify-evidence/keep.md"])
        sw = _make_sweeper(repo, grace=30.0)
        sw._untracked_registry["f" * 64] = {
            "first_seen": time.time() - 3600,
            "first_seen_iso": "2026-10-02T00:00:00Z",
            "files": ["verify-evidence/keep.md", "verify-evidence/gone.md"],
            "escalated_at": "",
            "escalated_signal_at": "",
        }
        sw._prune_untracked_registry_stale_paths()
        self.assertEqual(
            sw._untracked_registry["f" * 64]["files"],
            ["verify-evidence/keep.md"],
        )
        # 全部消失 → 整条删除
        sw._untracked_registry["f" * 64]["files"] = ["verify-evidence/gone.md"]
        sw._prune_untracked_registry_stale_paths()
        self.assertNotIn("f" * 64, sw._untracked_registry)

    def test_persist_failure_fails_open(self):
        """落盘失败（目录不可写）仅告警 fail-open，盘点结果不受影响。"""
        repo = _make_repo()
        _write_strays(repo, [f"verify-evidence/r{i}.md" for i in range(6)])
        # 预建同名目录占位：os.replace 到目录路径必失败（OSError）
        self._registry_path(repo).mkdir(parents=True)
        logger = _LoggerProbe()
        cfg = {"admin": {"maintree_stray_wip_grace_minutes": 30.0}}
        sw = MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=logger)
        r = sw.sweep()
        self.assertIsNotNone(r)  # 盘点照常完成
        self.assertIn("untracked", r)
        self.assertTrue(
            any("持久化写入失败" in m for _, m in logger.warnings)
        )


if __name__ == "__main__":
    unittest.main()
