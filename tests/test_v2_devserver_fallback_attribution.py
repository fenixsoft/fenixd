"""v2 dev-server 回退形态归因专项测试（fix-v2-devserver-fallback-attribution）。

覆盖：
  1. 回退形态 argv 归因标记：start() 回退分支在 argv 尾部追加
     <wt>/core/dashboard/static 标记 token，_dev_server_worktree_root 可归因
     （真起 node 验证 cmdline）；解析器末个命中优先（框架运行于 worktree 的
     开发态下，主树静态根 token 同样含 /worktrees/，归属须让位于显式标记）。
  2. 在服 run 免于 skip 告警与收割；run 结束（无引用）后归因进程可收割。
  3. pid 记账：不可归因进程首见告警一次、后续静默计数；永不按记账 kill。
  4. 扫描面按项目收窄：他项目 worktree 基路径的进程不记账不告警不清扫
     （双 daemon 不互刷）。
  5. 重启对账：登记在册进程按「身份核对 + 归属引用判定」只收割无主——
     pid 复用不杀、有主保留、无主收割、死条目摘除。
  6. 告警文案：不含无条件「可手动 kill」建议，与归因/引用判定联动。
  7. worktree core/dashboard/static 软链供给：链接后 start() 不再回退主树
     静态根；失败静默降级不阻塞派发；幂等。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core import v2_dev_server as v2
from core.agent_runner.v2_server import V2ServerManager
from core.proc_utils import proc_start_ticks
from core.v2_dev_server import (
    _dev_server_orphan_pids,
    _dev_server_worktree_root,
    cleanup_orphans,
    load_v2_server_entries,
    reconcile_v2_servers,
    register_v2_server,
    start as v2_start,
    stop as v2_stop,
    unregister_v2_server,
    v2_servers_registry_path,
)


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        pass


def make_worktree(tmp_path, name, with_static=False):
    """构造最小 worktree 目录；默认不带 core/dashboard/static（回退形态语境）。"""
    wt = Path(tmp_path) / ".claude" / "worktrees" / name
    if with_static:
        (wt / "core" / "dashboard" / "static").mkdir(parents=True)
    else:
        wt.mkdir(parents=True)
    return wt


def spawn_token_proc(argv0, tokens, sleep=20):
    """spawn 一个 argv[0]=argv0、cmdline 依次含 tokens 的存活进程（execv 伪装）。

    返回前自旋等待 argv[0] 就位（execv 完成），替身身份未就位按夹具失败上报
    （同 tests/test_v2_dev_server.py 的既有助手口径）。

    start_new_session=True 对齐生产 spawn 语义（v2_dev_server 起停 dev-server
    均独立成组）：不独立成组时替身与 pytest 同组，收割路径的 killpg 命中的
    是调用者自身所在进程组——守卫（add-killpg-self-guard）按契约拒绝，且守卫
    落地前这正是 2026-10-07 -15 信号变体团灭全量回归的事故形态。
    """
    launcher = ("import os, sys\n"
                "os.execv(sys.argv[1], [sys.argv[2]] + sys.argv[3:])\n")
    proc = subprocess.Popen(
        [sys.executable, "-c", launcher, sys.executable, argv0,
         "-c", f"import time; time.sleep({sleep})", *tokens],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            cur_argv0 = Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(
                b"\0", 1)[0]
        except OSError:
            cur_argv0 = b""
        if os.path.basename(cur_argv0.decode("utf-8", "replace")) == argv0:
            return proc
        time.sleep(0.01)
    proc.kill()
    proc.wait()
    raise AssertionError(f"stub argv[0] never became {argv0!r} (execv 未就位)")


def fake_dev_server_proc(static_token):
    """伪装回退形态 dev-server：argv0=node、cmdline 含 marker 与静态根 token。"""
    return spawn_token_proc(
        "node", [v2.V2_DEV_SERVER_MARKER, str(static_token)]
    )


@pytest.fixture(autouse=True)
def _reset_accounting():
    """pid 记账为进程内状态：用例间清零，避免互相污染首见判定。"""
    with v2._unattributed_lock:
        v2._unattributed_seen.clear()
    yield
    with v2._unattributed_lock:
        v2._unattributed_seen.clear()


def warnings_for(logger, pid):
    """过滤出与本 pid 相关的 WARNING 文案（宿主机可能有真实 dev-server 噪音）。"""
    return [a[1] for a in logger.warnings if f"pid={pid}" in a[1]]


class TestFallbackAttribution:
    """1.1 回退形态 argv 归因标记。"""

    def test_start_fallback_appends_attribution_token(self, tmp_path):
        """真起 node：回退形态 dev-server 的 cmdline 尾部携带 worktree 静态根
        标记 token，且 _dev_server_worktree_root 能据此归因（本仓库开发态下
        框架自身运行于 worktree、回退主树静态根 token 同样含 /worktrees/，
        解析器 MUST 末个命中优先落到标记 token——开发态归因正确的直接实证）。"""
        wt = make_worktree(tmp_path, f"impl-fbattr-{os.getpid()}")
        assert not (wt / "core" / "dashboard" / "static").exists()
        logger = FakeLogger()
        used = set()
        port, proc = v2_start(wt, 4, used, logger=logger)
        try:
            tokens = [
                t.decode("utf-8", "replace")
                for t in Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")
                if t
            ]
            attribution = f"{wt}/core/dashboard/static"
            assert attribution in tokens, f"argv 缺归因标记: {tokens}"
            assert tokens[-1] == attribution, "归因标记 MUST 追加在 argv 尾部"
            assert _dev_server_worktree_root(tokens) == wt, (
                f"回退形态应归因到 {wt}，实际 {_dev_server_worktree_root(tokens)}"
            )
            assert port != 8787
            assert any("fallback to main tree" in a[1] for a in logger.warnings)
        finally:
            v2_stop(proc, port, used)

    def test_start_normal_form_unchanged(self, tmp_path):
        """常态形态（worktree 自带静态根）：argv 不追加归因标记，行为不变。"""
        wt = make_worktree(
            tmp_path, f"impl-normal-{os.getpid()}", with_static=True
        )
        (wt / "core" / "dashboard" / "static" / "index.html").write_text(
            "<html>wt</html>", encoding="utf-8"
        )
        used = set()
        port, proc = v2_start(wt, 5, used)
        try:
            tokens = [
                t.decode("utf-8", "replace")
                for t in Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")
                if t
            ]
            assert tokens[-1] == v2.V2_DEV_SERVER_MARKER, "常态形态不追加标记"
            assert _dev_server_worktree_root(tokens) == wt
        finally:
            v2_stop(proc, port, used)

    def test_parser_prefers_attribution_token_over_framework_static(self):
        """解析器末个命中优先：框架运行于 worktree（开发态）时回退静态根
        token 先命中，归属 MUST 让位于尾部显式追加的归因标记 token。"""
        fw_static = "/root/fenixd/.claude/worktrees/impl-fw/core/dashboard/static"
        attribution = "/repo/.claude/worktrees/impl-target-1/core/dashboard/static"
        tokens = [
            "node",
            "/root/fenixd/.claude/worktrees/impl-fw/tests/v2/dev-server.mjs",
            fw_static, "19001", v2.V2_DEV_SERVER_MARKER, attribution,
        ]
        assert _dev_server_worktree_root(tokens) == Path(
            "/repo/.claude/worktrees/impl-target-1"
        )

    def test_parser_unattributable_still_none(self):
        """旧版回退形态存量 argv（静态根不含 /worktrees/）：仍判不可归因。"""
        tokens = [
            "node", "dev-server.mjs",
            "/opt/fenixd/core/dashboard/static", "19002",
            v2.V2_DEV_SERVER_MARKER,
        ]
        assert _dev_server_worktree_root(tokens) is None


class TestInFlightRunProtected:
    """1.1 + 既有豁免联动：在服 run 免于 skip 告警与收割。"""

    def test_attributed_fallback_server_exempted_while_run_alive(self, tmp_path):
        """回退形态 + 归因标记：run 在飞（存活 claude 引用 worktree）→
        不产生 skip 告警、不判孤儿（既有豁免逻辑自然生效）。"""
        wt = make_worktree(tmp_path, f"impl-inflight-{os.getpid()}")
        dev = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        claude = spawn_token_proc("claude", [str(wt)])
        try:
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out = _dev_server_orphan_pids(logger=logger)
            assert dev.pid not in out, "在服 run 的 dev-server 不应判孤儿"
            assert not warnings_for(logger, dev.pid), (
                "归因后不应再有 skip 告警"
            )
        finally:
            dev.kill()
            dev.wait()
            claude.kill()
            claude.wait()

    def test_attributed_fallback_server_harvested_when_run_gone(self, tmp_path):
        """归因标记 + worktree 存在但无存活引用（run 已结束）→ 可判孤儿并
        被清扫收割（误报消失的同时清力不损失）。"""
        wt = make_worktree(tmp_path, f"impl-gone-{os.getpid()}")
        dev = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        try:
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out = _dev_server_orphan_pids(logger=logger)
            assert dev.pid in out, "无引用进程的归因 dev-server 应判孤儿"
            assert not warnings_for(logger, dev.pid)
        finally:
            dev.kill()
            dev.wait()

    def test_attributed_fallback_server_harvested_when_worktree_gone(self, tmp_path):
        """归因标记 + worktree 已消失 → 判孤儿（残留进程不阻塞端口池）。"""
        wt = make_worktree(tmp_path, f"impl-wtgone-{os.getpid()}")
        dev = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        try:
            import shutil
            shutil.rmtree(wt)
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out = _dev_server_orphan_pids(logger=FakeLogger())
            assert dev.pid in out
        finally:
            dev.kill()
            dev.wait()


class TestPidAccounting:
    """2.1 不可归因进程按 pid 记账：首见告警一次、后续静默计数。"""

    def test_unattributed_warns_once_then_silent(self, tmp_path):
        proc = fake_dev_server_proc("/tmp/fake-main-tree/core/dashboard/static")
        try:
            first = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                assert proc.pid not in _dev_server_orphan_pids(logger=first)
            assert len(warnings_for(first, proc.pid)) == 1, "首见应告警一次"

            for _ in range(2):
                later = FakeLogger()
                with patch.object(v2, "_pid_recently_started", return_value=False):
                    assert proc.pid not in _dev_server_orphan_pids(logger=later)
                assert not warnings_for(later, proc.pid), "后续应静默计数"

            with v2._unattributed_lock:
                assert v2._unattributed_seen.get(proc.pid) == 3, "见次应累计"
        finally:
            proc.kill()
            proc.wait()

    def test_unattributed_never_killed_by_sweep(self, tmp_path):
        """记账不等于清算：不可归因进程不被清扫 kill（处置以无引用进程为
        前提，而不可归因形态无法判定引用 → 保守跳过）。"""
        proc = fake_dev_server_proc("/tmp/fake-main-tree/core/dashboard/static")
        try:
            kill_log = []

            def _recording_kill(pids, logger=None):
                # 只记账不真杀：断言聚焦「不可归因 pid 不进清扫 kill 列表」，
                # 不依赖宿主机是否恰有别的孤儿 dev-server（cleanup_orphans
                # 缺省全局扫描，会撞上他项目残留进程，2026-10-14 回归
                # killed==1 环境性误报实证），也消除测试对宿主机进程的
                # 真实 kill 副作用。
                kill_log.extend(pids)
                return len(pids)

            with (
                patch.object(v2, "_pid_recently_started", return_value=False),
                patch.object(v2, "_kill_pids", side_effect=_recording_kill),
            ):
                cleanup_orphans(logger=FakeLogger())
            assert proc.poll() is None, "不可归因进程不得被清扫误杀"
            assert proc.pid not in kill_log, "不可归因进程不得进入清扫 kill 列表"
        finally:
            proc.kill()
            proc.wait()

    def test_accounting_pruned_when_pid_gone(self, tmp_path):
        proc = fake_dev_server_proc("/tmp/fake-main-tree/core/dashboard/static")
        with patch.object(v2, "_pid_recently_started", return_value=False):
            _dev_server_orphan_pids(logger=FakeLogger())
        with v2._unattributed_lock:
            assert proc.pid in v2._unattributed_seen
        proc.kill()
        proc.wait()
        with patch.object(v2, "_pid_recently_started", return_value=False):
            _dev_server_orphan_pids(logger=FakeLogger())
        with v2._unattributed_lock:
            assert proc.pid not in v2._unattributed_seen, "消亡 pid 应出簿"


class TestProjectScoping:
    """2.1 pgrep 扫描面按项目收窄：双 daemon 不互刷。"""

    def test_other_project_pid_ignored(self, tmp_path):
        """他项目 worktree 基路径的 dev-server：本项目视角不记账、不告警、
        不清扫；以他项目基路径为界则正常归因判定（各管各的）。"""
        other_base = tmp_path / "other-proj" / ".claude" / "worktrees"
        other_wt = other_base / f"impl-other-{os.getpid()}"
        other_wt.mkdir(parents=True)
        proc = fake_dev_server_proc(f"{other_wt}/core/dashboard/static")
        try:
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out = _dev_server_orphan_pids(
                    logger=logger,
                    worktree_base=tmp_path / "this-proj" / ".claude" / "worktrees",
                )
            assert proc.pid not in out
            assert not warnings_for(logger, proc.pid), "他项目进程不告警不记账"
            with v2._unattributed_lock:
                assert proc.pid not in v2._unattributed_seen

            # 换以他项目基路径为界：归因判定照常工作（不因收窄而失明）
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out_other = _dev_server_orphan_pids(
                    logger=FakeLogger(), worktree_base=other_base
                )
            assert proc.pid in out_other, "本域内进程仍应被正常判定"
        finally:
            proc.kill()
            proc.wait()

    def test_own_project_pid_still_judged_under_scoping(self, tmp_path):
        """本项目域内进程不受收窄影响：正常判孤儿（收割清力不损失）。"""
        base = tmp_path / "proj-a" / ".claude" / "worktrees"
        wt = base / f"impl-own-{os.getpid()}"
        wt.mkdir(parents=True)
        proc = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        try:
            with patch.object(v2, "_pid_recently_started", return_value=False):
                out = _dev_server_orphan_pids(logger=FakeLogger(), worktree_base=base)
            assert proc.pid in out
        finally:
            proc.kill()
            proc.wait()


class TestWarningWording:
    """2.2 告警文案纠偏：无条件「可手动 kill」建议移除。"""

    def test_skip_warning_no_unconditional_kill_advice(self, tmp_path):
        proc = fake_dev_server_proc("/tmp/fake-main-tree/core/dashboard/static")
        try:
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                _dev_server_orphan_pids(logger=logger)
            msgs = warnings_for(logger, proc.pid)
            assert len(msgs) == 1
            msg = msgs[0]
            assert "可手动 kill" not in msg and "手动 kill" not in msg, (
                "文案不得含无条件手动 kill 建议"
            )
            assert "记账" in msg, "文案应说明按 pid 记账（首见一次后续静默）"
            assert "引用" in msg, "文案应与引用判定联动"
            assert "勿按存活时长" in msg, "文案应警示勿按存活时长 kill"
        finally:
            proc.kill()
            proc.wait()


class TestRestartReconcile:
    """2.3 daemon 重启对账：只收割无主进程。"""

    def _proj(self, tmp_path):
        return tmp_path / "proj"

    def test_reconcile_harvests_unowned_registered(self, tmp_path):
        """登记在册 + worktree 已消失（无主）→ 收割并摘登记。"""
        proj = self._proj(tmp_path)
        wt = make_worktree(tmp_path, f"impl-unowned-{os.getpid()}")
        proc = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        try:
            register_v2_server(proj, wt, proc.pid, 19005)
            import shutil
            shutil.rmtree(wt)  # worktree 消失 → 无主
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                killed = reconcile_v2_servers(proj, logger=logger)
            assert killed == 1
            assert proc.poll() is not None, "无主登记进程应被收割"
            assert load_v2_server_entries(proj) == [], "条目应摘除"
            assert any("reconcile harvested" in a[1] for a in logger.warnings)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_reconcile_keeps_owned_registered(self, tmp_path):
        """登记在册 + worktree 存活 + 存活 claude 引用（在服 run 跨重启）→
        进程与登记都保留。"""
        proj = self._proj(tmp_path)
        wt = make_worktree(tmp_path, f"impl-owned-{os.getpid()}")
        proc = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        claude = spawn_token_proc("claude", [str(wt)])
        try:
            register_v2_server(proj, wt, proc.pid, 19006)
            logger = FakeLogger()
            with patch.object(v2, "_pid_recently_started", return_value=False):
                killed = reconcile_v2_servers(proj, logger=logger)
            assert killed == 0
            assert proc.poll() is None, "有主进程 MUST 保留"
            entries = load_v2_server_entries(proj)
            assert [e.get("pid") for e in entries] == [proc.pid], "登记保留"
        finally:
            proc.kill()
            proc.wait()
            claude.kill()
            claude.wait()

    def test_reconcile_pid_reuse_removed_without_killing(self, tmp_path):
        """starttime 快照失配（pid 已被复用）→ 仅摘登记不杀（防误杀无关进程）。"""
        proj = self._proj(tmp_path)
        wt = make_worktree(tmp_path, f"impl-reuse-{os.getpid()}")
        proc = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        try:
            register_v2_server(proj, wt, proc.pid, 19007)
            # 篡改快照模拟 pid 复用（现进程 starttime 必然不同于登记值）
            entries = load_v2_server_entries(proj)
            entries[0]["start_ticks"] = (
                proc_start_ticks(proc.pid) + 999999
            )
            proj_reg = v2_servers_registry_path(proj)
            proj_reg.write_text(json.dumps(entries), encoding="utf-8")

            killed = reconcile_v2_servers(proj, logger=FakeLogger())
            assert killed == 0
            assert proc.poll() is None, "pid 复用场景 MUST NOT 误杀现进程"
            assert load_v2_server_entries(proj) == [], "失配条目应摘除"
        finally:
            proc.kill()
            proc.wait()

    def test_reconcile_dead_pid_pruned(self, tmp_path):
        """登记 pid 已消亡 → 仅摘登记，无进程可收割（返回 0）。"""
        proj = self._proj(tmp_path)
        wt = make_worktree(tmp_path, f"impl-dead-{os.getpid()}")
        proc = fake_dev_server_proc(f"{wt}/core/dashboard/static")
        proc.kill()
        proc.wait()
        register_v2_server(proj, wt, proc.pid, 19008)
        assert reconcile_v2_servers(proj) == 0
        assert load_v2_server_entries(proj) == []

    def test_manager_registers_on_launch_unregisters_on_stop(self, tmp_path):
        """V2ServerManager 装配面：launch 成功登记（含 starttime 快照）、终态
        回收移除登记；回退形态 worktree 走真实 node 启停。"""

        class FakePm:
            def __init__(self, project_root, logger):
                self.project_root = project_root
                self.logger = logger

        proj = self._proj(tmp_path)
        proj.mkdir(parents=True, exist_ok=True)
        wt = make_worktree(tmp_path, f"impl-mgr-{os.getpid()}")
        mgr = V2ServerManager(FakePm(proj, FakeLogger()))
        mgr._v2_launch_for_worktree(wt)
        try:
            entries = load_v2_server_entries(proj)
            assert len(entries) == 1, "launch 成功应登记"
            assert entries[0]["wt_path"] == str(wt)
            assert isinstance(entries[0]["start_ticks"], int)
            port, proc = mgr._v2_servers[str(wt)]
        finally:
            mgr._v2_stop_for_worktree(wt)
        assert load_v2_server_entries(proj) == [], "终态回收应移除登记"

    def test_unregister_idempotent_and_filtered(self, tmp_path):
        """unregister 按 (wt_path, pid) 精确匹配、幂等安全；他条目不受影响。"""
        proj = self._proj(tmp_path)
        wt_a = make_worktree(tmp_path, f"impl-ua-{os.getpid()}")
        wt_b = make_worktree(tmp_path, f"impl-ub-{os.getpid()}")
        register_v2_server(proj, wt_a, 111, 19010)
        register_v2_server(proj, wt_b, 222, 19011)
        unregister_v2_server(proj, wt_a, 111)
        unregister_v2_server(proj, wt_a, 111)  # 幂等
        entries = load_v2_server_entries(proj)
        assert [e.get("pid") for e in entries] == [222]

    def test_registry_write_failure_non_blocking(self, tmp_path, monkeypatch):
        """登记写盘失败（_rewrite 返回 False，OSError 契约形态）不抛错：
        best-effort，漏登记只损失对账覆盖，仅 WARNING 留痕。"""
        proj = self._proj(tmp_path)
        wt = make_worktree(tmp_path, f"impl-wfail-{os.getpid()}")
        monkeypatch.setattr(v2, "_rewrite_v2_server_entries", lambda r, e: False)
        logger = FakeLogger()
        register_v2_server(proj, wt, 333, 19012, logger=logger)
        assert any("registry write failed" in a[1] for a in logger.warnings)


class TestStaticSymlinkProvisioning:
    """1.2 / 3.3 worktree core/dashboard/static 软链供给。"""

    def _manager(self, tmp_path):
        from core.worktree_manager import WorktreeManager

        return WorktreeManager(
            tmp_path / "wt-base", tmp_path / "proj", FakeLogger()
        )

    def test_symlink_created_and_start_no_longer_falls_back(self, tmp_path):
        """worktree 缺 static 时软链创建；链接后 start() 走 worktree 静态根
        （服务内容落到 worktree 路径，无 fallback 告警）——回退形态消除。"""
        mgr = self._manager(tmp_path)
        wt = make_worktree(tmp_path, f"impl-sym-{os.getpid()}")
        mgr._provision_worktree_static_root(wt)
        link = wt / "core" / "dashboard" / "static"
        assert link.is_symlink() and link.is_dir()
        framework_static = (
            Path(v2.__file__).absolute().parent.parent
            / "core" / "dashboard" / "static"
        )
        assert Path(os.path.realpath(link)) == Path(
            os.path.realpath(framework_static)
        )

        used = set()
        port, proc = v2_start(wt, 6, used, logger=FakeLogger())
        try:
            tokens = [
                t.decode("utf-8", "replace")
                for t in Path(f"/proc/{proc.pid}/cmdline").read_bytes().split(b"\0")
                if t
            ]
            assert str(link) in tokens, "静态根应取 worktree 软链路径"
            assert tokens[-1] == v2.V2_DEV_SERVER_MARKER, "不再回退、无归因标记"
            assert _dev_server_worktree_root(tokens) == wt
        finally:
            v2_stop(proc, port, used)

    def test_symlink_idempotent_when_static_tracked(self, tmp_path):
        """worktree 已带跟踪 static 目录（框架目标项目常态）：幂等跳过，
        目录不被替换。"""
        mgr = self._manager(tmp_path)
        wt = make_worktree(
            tmp_path, f"impl-symkeep-{os.getpid()}", with_static=True
        )
        marker = wt / "core" / "dashboard" / "static" / "keep.txt"
        marker.write_text("x", encoding="utf-8")
        mgr._provision_worktree_static_root(wt)
        assert not (wt / "core" / "dashboard" / "static").is_symlink()
        assert marker.exists(), "既有目录内容不得被动"

    def test_symlink_failure_degrades_without_blocking(self, tmp_path, monkeypatch):
        """软链失败仅 WARNING 静默降级：不抛错、不阻塞 _provision_worktree_deps
        （派发供给链照常走完 node_modules 段）。"""
        import core.worktree_manager.lifecycle as lifecycle_mod

        mgr = self._manager(tmp_path)
        wt = make_worktree(tmp_path, f"impl-symfail-{os.getpid()}")

        def _boom(src, dst, **kw):
            raise OSError("cross-device link")

        monkeypatch.setattr(lifecycle_mod.os, "symlink", _boom)
        # 不抛错即「不阻塞」：整个供给链（含 node_modules 段）走完
        mgr._provision_worktree_static_root(wt)
        mgr._provision_worktree_deps(wt)
        assert not (wt / "core" / "dashboard" / "static").exists()
        assert any("symlink failed" in a[1] for a in mgr.logger.warnings), (
            "失败应留 WARNING 级降级留痕"
        )

    def test_symlink_eexist_race_tolerated(self, tmp_path):
        """并发 provision 竞态（目标已是软链）：按已存在处理，不留失败告警。"""
        mgr = self._manager(tmp_path)
        wt = make_worktree(tmp_path, f"impl-symrace-{os.getpid()}")
        link = wt / "core" / "dashboard" / "static"
        framework_static = (
            Path(v2.__file__).absolute().parent.parent
            / "core" / "dashboard" / "static"
        )
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(framework_static, link)
        logger = FakeLogger()
        mgr._provision_worktree_static_root(wt)
        assert link.is_symlink()
        assert not logger.warnings

    def test_symlink_git_invisible_in_real_repo(self, tmp_path):
        """真实 git 仓库 worktree：软链落地且对 git 不可见（status 干净）。

        回归守卫：未跟踪软链会击穿空变更 WIP checkpoint 的幂等跳过契约
        （tests/test_impl_wip_checkpoint 3 例空变更断言失败的实证根因）——
        provisioning 必须经 info/exclude 建立忽略后再落链。
        """
        import subprocess as sp

        root = tmp_path / "repo"
        root.mkdir(parents=True)

        def git(*a, cwd=None):
            return sp.run(
                ["git", "-C", str(cwd or root), *a],
                capture_output=True, text=True, check=True,
            )

        git("init", "-q")
        git("config", "user.email", "test@fenix.local")
        git("config", "user.name", "Fenix Test")
        git("config", "commit.gpgsign", "false")
        (root / "shared.py").write_text("BASE\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "[fenix] base")

        from core.worktree_manager import WorktreeManager

        base = root / ".claude" / "worktrees"
        base.mkdir(parents=True)
        mgr = WorktreeManager(base, root, FakeLogger())
        wt = mgr.create(f"demo-{os.getpid()}", "implementer")
        link = wt / "core" / "dashboard" / "static"
        assert link.is_symlink() and link.is_dir(), "软链应经闸门落地"
        status = sp.run(
            ["git", "-C", str(wt), "status", "--porcelain"],
            capture_output=True, text=True,
        )
        assert status.stdout == "", (
            f"worktree 不得因软链变脏（WIP checkpoint 会被未跟踪软链击穿）: "
            f"{status.stdout!r}"
        )

    def test_symlink_skipped_when_git_invisibility_unreachable(
        self, tmp_path, monkeypatch
    ):
        """仓库语境下无法保证软链对 git 不可见（exclude 建不成/被反杀）：
        跳过软链静默降级（仅 WARNING），不弄脏 worktree、不阻塞派发。"""
        import core.worktree_manager.lifecycle as lifecycle_mod

        mgr = self._manager(tmp_path)
        wt = make_worktree(tmp_path, f"impl-symvis-{os.getpid()}")
        monkeypatch.setattr(
            lifecycle_mod, "_wt_repo_common_dir",
            lambda root: tmp_path / "proj" / ".git",
        )
        monkeypatch.setattr(
            lifecycle_mod, "_path_git_ignored", lambda wt_, rel: False
        )
        attempts = {}
        monkeypatch.setattr(
            lifecycle_mod, "_ensure_git_exclude",
            lambda cd, rel: attempts.setdefault("exclude", True),
        )
        mgr._provision_worktree_static_root(wt)
        assert not (wt / "core" / "dashboard" / "static").exists(), (
            "无法保证 git 不可见时必须跳过软链"
        )
        assert attempts.get("exclude"), "降级前应先尝试建立 exclude"
        assert any("skipped" in a[1] for a in mgr.logger.warnings), (
            "降级应留 WARNING 级留痕"
        )
