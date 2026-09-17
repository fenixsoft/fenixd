"""supervision timeout 配置一致性（evo-supervision-timeout-config-consistency）测试。

覆盖 tasks 2.1-2.4：
- 单一派生函数 supervision_floor / supervision_config_floor 数值：运行时基础档
  15000+2×1800=18600s、fast-track higher 档 15000+4×1800=22200s、配置校验层
  最大下限 15000+4×1800=22200s（含 timeout_overrides 参与 max 派生、enabled=
  false / 缺段分支）；
- config 校验层与 liveness 兜底层调用同一派生实现（无手写常数残留）；
- 不一致时默认自动对齐（ERROR 含两侧值与下限 + 修正建议、抬升至 22200、无阻断）；
  显式关闭 auto_align → 启动/加载 fail-fast；
- 热更新：不一致 → 对齐持久化后无 ERROR；关闭对齐 → 拒绝新配置并回滚旧值。
"""

import logging
import time
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.liveness import LivenessSupervisor
from core.config import (
    ConfigLoader,
    SUPERVISION_DEFAULTS,
    SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS,
)


@pytest.fixture(autouse=True)
def _reset_supervision_state():
    """每用例前重置告警去重 / 对齐记录（进程级标记，避免跨用例串扰）。"""
    ConfigLoader.reset_stuck_threshold_state()
    yield
    ConfigLoader.reset_stuck_threshold_state()


def _cfg(
    run_timeout=15000,
    abs_max=14400,
    max_extensions=2,
    extension_seconds=1800,
    enabled=True,
    auto_align=None,
    overrides=None,
):
    """构造 ``agents.timeout_supervision`` 配置（缺省为 misaligned：15000 vs 14400）。"""
    sup = {
        "enabled": enabled,
        "extension_seconds": extension_seconds,
        "max_extensions": max_extensions,
        "absolute_max_seconds": abs_max,
        "judge_window": 600,
    }
    if auto_align is not None:
        sup["auto_align"] = auto_align
    agents = {"run_timeout_seconds": run_timeout, "timeout_supervision": sup}
    if overrides:
        agents["timeout_overrides"] = overrides
    return {"agents": agents}


def _write_project(proot: Path, cfg_dict: dict) -> Path:
    """把配置写进临时项目的 .fenix/config.yaml，返回 proot。"""
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "config.yaml").write_text(
        yaml.safe_dump(cfg_dict), encoding="utf-8"
    )
    return proot


def _make_minimal_runner(proot: Path, config: dict) -> AgentRunner:
    """构造最小 AgentRunner（__new__ 绕过 __init__），对齐既有测试基建
    （tests/test_run_lifecycle_hardening.py::make_runner_with_config）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config
    runner.worktree_manager = MagicMock()
    runner.state_machine = MagicMock()
    runner.state_machine.read_one.return_value = {}
    runner.project_root = Path(proot)
    runner.logger = MagicMock()
    runner._running_agents = {}
    runner._instant_fail = {}
    runner._daily_run_count = 0
    return runner


# ═══════════════════════════════════════════════════════════════════
# 2.1 派生值正确（单一派生函数数值）
# ═══════════════════════════════════════════════════════════════════


class TestDerivedFloorValues:
    """派生函数数值（tasks 2.1）。"""

    def test_base_tier_floor(self):
        """运行时基础档：15000 + 2×1800 = 18600s。"""
        cfg = _cfg()
        assert ConfigLoader.supervision_floor(cfg, agent_type="implementer") == 18600.0

    def test_fast_track_higher_tier_floor(self):
        """fast-track higher 档：调用方传 max_extensions + 2 = 4 → 15000 + 4×1800 = 22200s。"""
        cfg = _cfg()
        assert (
            ConfigLoader.supervision_floor(
                cfg,
                agent_type="fast-track",
                extension_budget=SUPERVISION_DEFAULTS["max_extensions"]
                + SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS,
            )
            == 22200.0
        )

    def test_config_floor_max_deployment(self):
        """配置校验层全部署最大下限：15000 + 4×1800 = 22200s。"""
        cfg = _cfg()
        assert ConfigLoader.supervision_config_floor(cfg) == 22200.0

    def test_floor_includes_timeout_overrides(self):
        """per-agent 覆盖参与派生：覆盖 7200 → 运行时 7200+2×1800=10800；
        配置层最大下限 = max(15000, 7200) + 4×1800 = 22200。"""
        cfg = _cfg(overrides={"implementer": 7200})
        assert ConfigLoader.supervision_floor(cfg, agent_type="implementer") == 10800.0
        assert ConfigLoader.supervision_config_floor(cfg) == 22200.0

    def test_floor_explicit_extension_budget_priority(self):
        """显式 extension_budget 优先于 max_extensions。"""
        cfg = _cfg()
        assert ConfigLoader.supervision_floor(cfg, extension_budget=0) == 15000.0

    def test_floor_falls_back_to_global_timeout(self):
        """agent_type 无覆盖 → 全局 run_timeout_seconds。"""
        cfg = _cfg(overrides={"planner-plan": 2700})
        assert ConfigLoader.supervision_floor(cfg, agent_type="verifier") == 15000.0 + 2 * 1800

    def test_disabled_returns_none(self):
        """enabled=false → 校验层与运行时均不校验（None）。"""
        cfg = _cfg(enabled=False)
        assert ConfigLoader.supervision_floor(cfg) is None
        assert ConfigLoader.supervision_config_floor(cfg) is None

    def test_missing_segment_validation_skips(self):
        """缺段：配置校验层不校验（None）；运行时按缺省语义派生（9000+2×1800=12600，
        与 liveness 缺段按 SUPERVISION_DEFAULTS 激活监督的既有行为一致）。"""
        cfg = {"agents": {"run_timeout_seconds": 9000}}
        assert ConfigLoader.supervision_config_floor(cfg) is None
        assert ConfigLoader.supervision_floor(cfg) == 12600.0

    def test_effective_value_raised_to_floor(self):
        """runner 消费方生效值：配置 14400 < 下限 22200 → 按 22200 兜底返回。"""
        cfg = _cfg()
        assert ConfigLoader.effective_supervision_absolute_max_seconds(cfg) == 22200.0

    def test_effective_value_passthrough_when_consistent(self):
        """一致时生效值 = 显式配置值（不抬升）。"""
        cfg = _cfg(abs_max=24000)
        assert ConfigLoader.effective_supervision_absolute_max_seconds(cfg) == 24000.0


# ═══════════════════════════════════════════════════════════════════
# 2.2 两处共用同一派生实现（无手写常数残留）
# ═══════════════════════════════════════════════════════════════════


class TestSharedDerivation:
    """config 校验层与 liveness 兜底层共用同一派生实现（tasks 2.2）。"""

    def test_liveness_base_tier_derives_via_supervision_floor(self, tmp_path):
        """liveness deadline 兜底 = supervision_floor(config, implementer, 2) = 18600。"""
        cfg = _cfg()
        runner = _make_minimal_runner(tmp_path, cfg)
        sup = LivenessSupervisor(runner)
        with patch(
            "core.config.ConfigLoader.supervision_floor",
            wraps=ConfigLoader.supervision_floor,
        ) as spy:
            action = sup._supervision_deadline_action(
                tmp_path / "impl-s-1-a1.jsonl",
                "s1",
                "run-1",
                started_at=time.time() - 20000,
                extensions_used=0,
                judge=MagicMock(return_value={"verdict": "advancing", "evidence": "x"}),
                agent_type="implementer",
            )
            assert spy.called
            call = spy.call_args
            assert call.args[0] is cfg
            assert call.kwargs["agent_type"] == "implementer"
            assert call.kwargs["extension_budget"] == 2
        # 兜底值来自同一派生函数：cap = 15000 + 2×1800 = 18600
        assert action["action"] == "kill"
        assert "absolute_max_seconds cap reached (18600s" in action["reason"]

    def test_liveness_fast_track_higher_cap(self, tmp_path):
        """fast-track higher 档 cap = 15000 + 4×1800 = 22200（运行时数值不变）。"""
        cfg = _cfg()
        runner = _make_minimal_runner(tmp_path, cfg)
        runner.state_machine.read_one.return_value = {"_fast_track_scale_tier": "higher"}
        sup = LivenessSupervisor(runner)
        action = sup._supervision_deadline_action(
            tmp_path / "impl-ft-1-a1.jsonl",
            "ft-spec",
            "run-1",
            started_at=time.time() - 30000,
            extensions_used=0,
            judge=MagicMock(return_value={"verdict": "advancing", "evidence": "x"}),
            agent_type="fast-track",
        )
        assert action["action"] == "kill"
        assert "absolute_max_seconds cap reached (22200s" in action["reason"]

    def test_no_handwritten_constant_remains(self):
        """手写常数已删除：SUPERVISION_EXTENSION_SECONDS 不再存在；
        liveness 不再手写 floor 表达式（源码断言）。"""
        import core.agent_runner.liveness as liveness_mod
        import core.config as cfg_mod

        assert not hasattr(cfg_mod, "SUPERVISION_EXTENSION_SECONDS")
        src = Path(liveness_mod.__file__).read_text(encoding="utf-8")
        assert "floor_absolute_max = run_timeout + max_extensions * extension_seconds" not in src

    def test_defaults_single_source(self):
        """SUPERVISION_DEFAULTS 单源（core.config 定义，liveness 侧 re-export 同对象）。"""
        import core.agent_runner.liveness as liveness_mod

        assert liveness_mod.SUPERVISION_DEFAULTS is SUPERVISION_DEFAULTS


# ═══════════════════════════════════════════════════════════════════
# 2.3 不一致时默认自动对齐 / 显式关闭 fail-fast（启动路径）
# ═══════════════════════════════════════════════════════════════════


class TestConsistencyCheck:
    """启动/加载一致性校验（tasks 2.3）。"""

    def test_default_auto_align_raises_and_continues(self, tmp_path, caplog):
        """absolute_max(14400) < 配置层下限(22200) → 默认自动对齐：ERROR 含两侧值
        与下限 + 修正建议；抬升至 22200；不抛异常（启动可继续）。"""
        proot = _write_project(tmp_path, _cfg())
        with patch("core.config.USER_CONFIG_DIR", tmp_path / "user"):
            with caplog.at_level(logging.ERROR, logger="fenixd.config"):
                cfg = ConfigLoader.resolve_config(proot)
        assert cfg["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "14400" in joined
        assert "22200" in joined
        assert "修正建议" in joined

    def test_auto_align_record_consumed_once(self, tmp_path):
        """对齐记录供 daemon 持久化：消费即复位。"""
        proot = _write_project(tmp_path, _cfg())
        with patch("core.config.USER_CONFIG_DIR", tmp_path / "user"):
            ConfigLoader.resolve_config(proot)
        assert ConfigLoader.take_supervision_alignment() == 22200.0
        assert ConfigLoader.take_supervision_alignment() is None

    def test_consistent_config_no_error(self, tmp_path, caplog):
        """一致（absolute_max == 下限）→ 无 ERROR、显式值生效。"""
        proot = _write_project(tmp_path, _cfg(abs_max=22200))
        with patch("core.config.USER_CONFIG_DIR", tmp_path / "user"):
            with caplog.at_level(logging.ERROR, logger="fenixd.config"):
                cfg = ConfigLoader.resolve_config(proot)
        assert cfg["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
        assert caplog.records == []

    def test_fail_fast_when_auto_align_disabled(self, tmp_path):
        """auto_align=false + 不一致 → resolve_config 抛 ValueError（启动失败）。"""
        proot = _write_project(tmp_path, _cfg(auto_align=False))
        with patch("core.config.USER_CONFIG_DIR", tmp_path / "user"):
            with pytest.raises(ValueError) as ei:
                ConfigLoader.resolve_config(proot)
        msg = str(ei.value)
        assert "auto_align" in msg
        assert "修正建议" in msg

    def test_fail_fast_load_strict_path(self, tmp_path):
        """load 严格路径同 fail-fast。"""
        cfg = _cfg(auto_align=False)
        cfg["project"] = {"name": "p", "type": "web"}
        cfg["schedule"] = {"poll_interval_minutes": 30}
        p = tmp_path / "config.yaml"
        p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with pytest.raises(ValueError):
            ConfigLoader.load(p)

    def test_disabled_supervision_skips_check(self, tmp_path):
        """enabled=false → 校验跳过：即使 absolute_max 偏低也不对齐、不阻断。"""
        proot = _write_project(tmp_path, _cfg(enabled=False, abs_max=14400))
        with patch("core.config.USER_CONFIG_DIR", tmp_path / "user"):
            cfg = ConfigLoader.resolve_config(proot)
        assert cfg["agents"]["timeout_supervision"]["absolute_max_seconds"] == 14400


# ═══════════════════════════════════════════════════════════════════
# 2.4 热更新：对齐持久化后无 ERROR；关闭对齐拒绝新配置并回滚旧值
# ═══════════════════════════════════════════════════════════════════


class TestHotReloadConsistency:
    """热更新一致性（tasks 2.4），经 fenixd 热重载路径（_maybe_reload_config）。"""

    def _daemon(self, tmp_path, monkeypatch, yaml_text):
        """构造最小 FenixDaemon（__new__ 绕过 __init__），PROJECT_ROOT 指向临时项目。"""
        import fenixd as _fenixd_mod

        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / "core").mkdir(parents=True, exist_ok=True)
        (proot / "core" / "a.py").write_text("# a\n", encoding="utf-8")
        (proot / "fenixd.py").write_text("# fenixd\n", encoding="utf-8")
        (proot / ".fenix" / "config.yaml").write_text(yaml_text, encoding="utf-8")
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        monkeypatch.setattr("core.config.USER_CONFIG_DIR", tmp_path / "user")

        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon.config = {}
        daemon.logger = MagicMock()
        daemon.admin_monitor = None
        daemon._admin_executor = None
        daemon._config_snapshot = ()
        files = _fenixd_mod.code_tracked_files(proot)
        daemon._code_files = files
        daemon._code_baseline_ns = _fenixd_mod.max_code_mtime_ns(files)
        daemon._code_stale = False
        daemon.admin_store = None
        return daemon, proot

    def test_hot_reload_aligns_persists_then_silent(self, tmp_path, monkeypatch, caplog):
        """热更新不一致 → 内存抬升 + 经写路径持久化落盘；对齐后再次加载无 ERROR。"""
        daemon, proot = self._daemon(
            tmp_path, monkeypatch, yaml.safe_dump(_cfg(abs_max=22200))
        )
        # 首次加载：一致 → 无 ERROR、不持久化
        with caplog.at_level(logging.ERROR, logger="fenixd.config"):
            daemon._maybe_reload_config()
        assert daemon.config["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
        assert caplog.records == []

        # 热更新：文件改为 misaligned（14400 < 22200）→ 默认自动对齐
        (proot / ".fenix" / "config.yaml").write_text(
            yaml.safe_dump(_cfg(abs_max=14400)), encoding="utf-8"
        )
        daemon._config_snapshot = ()
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="fenixd.config"):
            daemon._maybe_reload_config()
        # 内存抬升至 22200（共享 dict 生效）
        assert daemon.config["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
        # 对齐已持久化：磁盘文件落盘 22200
        on_disk = yaml.safe_load(
            (proot / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        )
        assert on_disk["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
        # 对齐 ERROR 留痕（含两侧值与下限、修正建议）
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "14400" in joined
        assert "22200" in joined
        assert "修正建议" in joined

        # 再次热更新（文件已对齐）：不再出现同文案对齐 ERROR
        daemon._config_snapshot = ()
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="fenixd.config"):
            daemon._maybe_reload_config()
        joined2 = "\n".join(r.getMessage() for r in caplog.records)
        assert "自动对齐" not in joined2

    def test_hot_reload_rejected_and_rolls_back(self, tmp_path, monkeypatch):
        """auto_align=false + 热更新不一致 → 拒绝新配置、共享 dict 保留旧值。"""
        daemon, proot = self._daemon(
            tmp_path,
            monkeypatch,
            yaml.safe_dump(_cfg(abs_max=22200, auto_align=False)),
        )
        daemon._maybe_reload_config()
        assert daemon.config["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200

        # 热更新：文件改为 misaligned + auto_align=false → fail-fast（ValueError 被
        # 主循环 try/except 捕获，daemon 不退出）；resolve_config_into 失败不触碰
        # 旧 dict → 共享配置保持旧值。
        (proot / ".fenix" / "config.yaml").write_text(
            yaml.safe_dump(_cfg(abs_max=14400, auto_align=False)), encoding="utf-8"
        )
        daemon._config_snapshot = ()
        try:
            daemon._maybe_reload_config()
            pytest.fail("fail-fast 应拒绝新配置（ValueError）")
        except ValueError:
            pass  # 与主循环 fenixd.py:518-521 try/except 同语义
        assert daemon.config["agents"]["timeout_supervision"]["absolute_max_seconds"] == 22200
