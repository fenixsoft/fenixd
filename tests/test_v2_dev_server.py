"""v2_dev_server 生命周期与端口策略专项测试（verify-process-lifecycle）。

覆盖：
  1. allocate_port 确定性/used 跳过/冲突扫描/耗尽回退临时端口（绝不抛错、绝不
     返回 8787）——task 1.3/1.4
  2. SO_REUSEADDR 消除 TIME_WAIT 假性占用——task 1.3
  3. start/stop 真起停 node；start_new_session + killpg 杀整树且不误伤他组——task 1.1/1.2
  4. 豁免矩阵：存活 claude 豁免 / 非 claude 引用不豁免 / 双孤儿互引不豁免——task 2.1
  5. ppid 绑定：父死后 dev-server 在轮询间隔内自灭——task 3.1
  6. E2E（对齐事故）：run 中途 daemon 重启 → run 结束 → 一个清扫周期内回收 →
     端口段全量可用——task 8.1
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core import v2_dev_server as v2
from core.agent_runner.v2_server import V2ServerManager
from core.v2_dev_server import (
    V2_TEST_PORT_BASE,
    V2_TEST_PORT_RANGE,
    _dev_server_worktree_root,
    _kill,
    _port_in_use,
    _worktree_has_live_referencing_process,
    allocate_port,
    cleanup_orphans,
    start as v2_start,
    stop as v2_stop,
)


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.warnings.append(a)
        pass

    def error(self, *a, **k):
        pass


def make_worktree(tmp_path, name="impl-eco-1"):
    """构造带静态根的最小 worktree 目录。"""
    wt = Path(tmp_path) / ".claude" / "worktrees" / name
    (wt / "core" / "dashboard" / "static").mkdir(parents=True)
    (wt / "core" / "dashboard" / "static" / "index.html").write_text(
        "<!DOCTYPE html><html><body>worktree</body></html>", encoding="utf-8")
    return wt


def spawn_token_proc(token: str, fake_argv0: str) -> subprocess.Popen:
    """spawn 一个 20s 进程：cmdline 含 token，argv[0] 伪装为 fake_argv0。"""
    launcher = ("import os, sys\n"
                "os.execv(sys.argv[1], [sys.argv[2]] + sys.argv[3:])\n")
    return subprocess.Popen(
        [sys.executable, "-c", launcher, sys.executable, fake_argv0,
         "-c", "import time; time.sleep(20)", token],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_token_in_pgrep(token: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(["pgrep", "-f", token],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return True
        time.sleep(0.05)
    return False


class TestAllocatePort:
    def test_deterministic_first_choice(self):
        with patch.object(v2, "_port_in_use", return_value=False):
            assert allocate_port(0) == V2_TEST_PORT_BASE
            assert allocate_port(3) == V2_TEST_PORT_BASE + 3

    def test_used_ports_skipped(self):
        with patch.object(v2, "_port_in_use", return_value=False):
            used = {V2_TEST_PORT_BASE + 0}
            assert allocate_port(0, used_ports=used) == V2_TEST_PORT_BASE + 1

    def test_conflict_scans_forward(self):
        with patch.object(v2, "_port_in_use") as piu:
            def fake_in_use(port, host="127.0.0.1"):
                return port < V2_TEST_PORT_BASE + 3
            piu.side_effect = fake_in_use
            used = {V2_TEST_PORT_BASE + 5}
            assert allocate_port(0, used_ports=used) == V2_TEST_PORT_BASE + 3

    def test_exhaustion_falls_back_to_ephemeral(self):
        """段内全被占用：回退系统临时端口 + WARNING 留痕，绝不抛错/绝不 8787。"""
        logger = FakeLogger()
        with patch.object(v2, "_port_in_use", return_value=True):
            port = allocate_port(0, logger=logger)
        assert port not in range(V2_TEST_PORT_BASE,
                                 V2_TEST_PORT_BASE + V2_TEST_PORT_RANGE)
        assert port != 8787
        assert logger.warnings, "耗尽回退应留 WARNING 级留痕"
        assert "ephemeral port" in logger.warnings[0][1]

    def test_exhaustion_no_error_type_raised(self):
        """耗尽不再抛 V2DevServerError（封死拦截性失败路径）。"""
        with patch.object(v2, "_port_in_use", return_value=True):
            port = allocate_port(0, logger=FakeLogger())
        assert isinstance(port, int)


class TestSOReuseAddr:
    def test_timewait_port_not_false_occupied(self):
        """端口处于 TIME_WAIT（无活动 listener）时探测判可用、可立即 rebind。

        服务端先关连接使端口进入 TIME_WAIT；裸 bind（无 SO_REUSEADDR）应失败
        证明 TIME_WAIT 确实存在，_port_in_use 以 SO_REUSEADDR 判可用。
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        conn, _ = srv.accept()
        # 服务端先关连接 → 该端口进入 TIME_WAIT
        conn.close()
        srv.close()
        client.close()

        # 轮询到 TIME_WAIT 生效（裸 bind 被拒），替代固定 sleep(0.2)
        deadline = time.monotonic() + 3.0
        raw_blocked = False
        while time.monotonic() < deadline:
            raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                raw.bind(("127.0.0.1", port))
                raw_blocked = False
            except OSError:
                raw_blocked = True
            finally:
                raw.close()
            if raw_blocked:
                break
            time.sleep(0.01)
        assert raw_blocked, "前置条件：无 SO_REUSEADDR 裸 bind 应被 TIME_WAIT 拒绝"
        assert _port_in_use(port) is False, "SO_REUSEADDR 应消除 TIME_WAIT 假性占用"
        # 可立即 rebind
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s2.bind(("127.0.0.1", port))
        s2.close()


class TestDevServerLifecycle:
    def test_start_stop_real_server(self, tmp_path):
        """真起停 node dev-server：服务可用、stop 后进程死且端口释放。

        端口段可能被环境内其他实例占用（段耗尽回退临时端口），故不锚定段内
        端口——只断言绝不回退主树 8787 且服务真实可达。
        """
        wt = make_worktree(tmp_path, f"impl-lifecycle-{os.getpid()}")
        used = set()
        port, proc = v2_start(wt, 4, used)
        try:
            assert port != 8787, "绝不回退主树 8787"
            assert proc.poll() is None
            assert port in used
            # 服务真实可达，资源来自 worktree 副本
            import urllib.request
            body = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/index.html", timeout=3).read()
            assert b"<!DOCTYPE html>" in body
        finally:
            v2_stop(proc, port, used)
        assert proc.poll() is not None, "stop 应终止 dev-server"
        assert port not in used
        assert _port_in_use(port) is False, "stop 后端口应释放可用"

    def test_killpg_kills_grandchildren(self):
        """杀整树：进程组的孙进程一并终止（shel/npm 包装形态的防泄漏核心）。"""
        parent = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, time\n"
             "child = subprocess.Popen(['python3', '-c', "
             "'import time; time.sleep(60)'], stdout=subprocess.DEVNULL, "
             "stderr=subprocess.DEVNULL)\n"
             "print(child.pid, flush=True)\n"
             "time.sleep(60)\n"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        child_pid = int(parent.stdout.readline().strip())
        try:
            _kill(parent)
            assert parent.poll() is not None
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(child_pid, 0)
                except OSError:
                    return  # 孙进程已终止
                time.sleep(0.02)
            pytest.fail("killpg 未终止孙进程（只杀了直接子进程）")
        finally:
            if parent.poll() is None:
                _kill(parent)

    def test_killpg_does_not_hit_other_groups(self, tmp_path):
        """killpg 不误伤同机他组进程（daemon/其他 agent 不同进程组不受影响）。"""
        wt = make_worktree(tmp_path, f"impl-bystander-{os.getpid()}")
        used = set()
        port, proc = v2_start(wt, 6, used)
        bystander = None
        try:
            bystander = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,  # 独立进程组
            )
            _kill(proc)
            assert proc.poll() is not None
            assert bystander.poll() is None, "不同进程组的进程不应被误杀"
        finally:
            v2_stop(proc, port, used)
            if bystander is not None and bystander.poll() is None:
                bystander.kill()
                bystander.wait()


class TestExemptionMatrix:
    def test_live_claude_reference_exempts(self):
        """worktree 存在存活 claude 引用 → 豁免（在飞 run 不被清扫）。"""
        token = f"worktrees/impl-claude-exempt-{os.getpid()}"
        proc = spawn_token_proc(token, "claude")
        try:
            assert wait_token_in_pgrep(token)
            wt = Path(f"/x/worktrees/impl-claude-exempt-{os.getpid()}")
            assert _worktree_has_live_referencing_process(wt, 999999) is True
        finally:
            proc.kill()
            proc.wait()

    def test_non_claude_reference_not_exempt(self):
        """非 claude 引用（孤儿 dev-server 等）不构成有效豁免。"""
        token = f"worktrees/impl-node-noref-{os.getpid()}"
        proc = spawn_token_proc(token, "node")
        try:
            assert wait_token_in_pgrep(token)
            wt = Path(f"/x/worktrees/impl-node-noref-{os.getpid()}")
            assert _worktree_has_live_referencing_process(wt, 999999) is False
        finally:
            proc.kill()
            proc.wait()

    def test_double_orphan_no_mutual_exemption(self):
        """双孤儿互引不豁免（事故回归）：同 worktree 两孤儿互为引用仍判无主。"""
        token = f"worktrees/impl-double-orphan-{os.getpid()}"
        p1 = spawn_token_proc(token, "node")
        p2 = spawn_token_proc(token, "node")
        try:
            assert wait_token_in_pgrep(token)
            wt = Path(f"/x/worktrees/impl-double-orphan-{os.getpid()}")
            # 各自以对方为"存活引用"，但均非 claude → 不豁免
            assert _worktree_has_live_referencing_process(wt, p1.pid) is False
            assert _worktree_has_live_referencing_process(wt, p2.pid) is False
        finally:
            for p in (p1, p2):
                if p.poll() is None:
                    p.kill()
                    p.wait()


class TestOrphanDetection:
    def test_dev_server_worktree_root_parsing(self):
        tokens = ["node", "dev-server.mjs",
                  "/x/worktrees/impl-parser-1/core/dashboard/static", "19001",
                  "fenix-v2-dev-server"]
        assert _dev_server_worktree_root(tokens) == Path("/x/worktrees/impl-parser-1")

    def test_parser_ignores_script_path_inside_worktree(self):
        """脚本自身路径含 /worktrees/（框架运行于 worktree 内）不误判为归属。"""
        tokens = [
            "node",
            "/root/fenixd/.claude/worktrees/impl-main/core/tests/v2/dev-server.mjs",
            "/tmp/wt/.claude/worktrees/impl-target-9/core/dashboard/static",
            "19002", "fenix-v2-dev-server",
        ]
        assert _dev_server_worktree_root(tokens) == Path("/tmp/wt/.claude/worktrees/impl-target-9")

    def test_parser_nested_worktree_takes_last_segment(self):
        """静态根含两段 /worktrees/（框架段 + 测试段）时 MUST 取末段归属到嵌套的
        测试 worktree（回归守卫：split 取首段会把归属误判为框架 worktree 自身，
        使其含存活 claude 进程而误豁免、孤儿判定落空）。"""
        tokens = [
            "node",
            "/root/fenixd/worktrees/fw/.fenix/pytest-basetemp/pytest-1/"
            "test_demo0/.claude/worktrees/impl-target-9/core/dashboard/static",
            "19003", "fenix-v2-dev-server",
        ]
        assert _dev_server_worktree_root(tokens) == Path(
            "/root/fenixd/worktrees/fw/.fenix/pytest-basetemp/pytest-1/"
            "test_demo0/.claude/worktrees/impl-target-9"
        )

    def test_orphan_detected_when_no_claude(self, tmp_path):
        """worktree 存在但无 claude 引用 → 判为孤儿。"""
        wt = make_worktree(tmp_path, f"impl-orphan-{os.getpid()}")
        used = set()
        port, proc = v2_start(wt, 8, used)
        try:
            with patch.object(v2, "_pgrep_dev_servers",
                              return_value=[proc.pid]):
                orphans = v2._dev_server_orphan_pids()
            assert proc.pid in orphans
        finally:
            v2_stop(proc, port, used)

    def test_orphan_exempted_when_claude_live(self, tmp_path):
        """worktree 存在且 claude 在飞 → 不判孤儿（daemon 重启先于子进程结束）。"""
        wt = make_worktree(tmp_path, f"impl-not-orphan-{os.getpid()}")
        used = set()
        port, proc = v2_start(wt, 9, used)
        claude_proc = None
        try:
            claude_proc = spawn_token_proc(f"worktrees/{wt.name}", "claude")
            assert wait_token_in_pgrep(f"worktrees/{wt.name}")
            with patch.object(v2, "_pgrep_dev_servers",
                              return_value=[proc.pid]):
                orphans = v2._dev_server_orphan_pids()
            assert proc.pid not in orphans, "归属存活 claude 的 dev-server 应豁免"
        finally:
            if claude_proc is not None:
                claude_proc.kill()
                claude_proc.wait()
            v2_stop(proc, port, used)


class TestPpidSelfTerminate:
    def test_killed_parent_child_self_terminates(self, tmp_path):
        """父进程被杀 → dev-server.ppid 变 1 → 轮询间隔内自灭（D3 孤儿自灭）。"""
        wt = make_worktree(tmp_path, "ppid-dummy")
        script = str(v2._dev_server_script())
        static_root = str(wt / "core" / "dashboard" / "static")
        port = allocate_port(99)
        # 中间父进程：spawn dev-server.mjs 后保持存活（模拟 daemon spawn 形态）
        intermediate = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys, time\n"
             "c = subprocess.Popen(['node', sys.argv[1], sys.argv[2], "
             "sys.argv[3], 'fenix-v2-dev-server'], "
             "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
             "print(c.pid, flush=True)\n"
             "time.sleep(60)\n",
             script, static_root, str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            child_pid = int(intermediate.stdout.readline().strip())
            # 杀父（模拟 daemon 被 kill -9，SIGTERM handler 不可达）
            intermediate.kill()
            intermediate.wait()
            deadline = time.time() + 12
            while time.time() < deadline:
                if not os.path.exists(f"/proc/{child_pid}"):
                    return  # ppid 绑定轮询触发自灭成功
                time.sleep(0.02)
            pytest.fail("孤儿 dev-server 未在 ppid 轮询间隔内自灭")
        finally:
            if intermediate.poll() is None:
                intermediate.kill()
                intermediate.wait()
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass


class TestCleanupCycle:
    def test_cleanup_orphans_reaps_within_one_cycle(self, tmp_path):
        """E2E（对齐事故）：run 中 daemon 重启豁免 → run 结束后一个周期内回收。

        端口段在此后可全量分配（used 记账随 stop 释放，TIME_WAIT 不假性占用）。
        全局扫描经 _dev_server_orphan_pids 定向本测试实例，避免误伤环境内
        真实 daemon 的在跑 dev-server。
        """
        wt = make_worktree(tmp_path, f"impl-e2e-{os.getpid()}")
        used = set()
        port, proc = v2_start(wt, 10, used)
        assert port != 8787, "绝不回退主树 8787"
        try:
            # 阶段1：run 在飞（假 claude 引用）→ 重启清扫豁免
            claude_proc = spawn_token_proc(f"worktrees/{wt.name}", "claude")
            try:
                assert wait_token_in_pgrep(f"worktrees/{wt.name}")
                with patch.object(v2, "_dev_server_orphan_pids",
                                  return_value=[]):
                    assert cleanup_orphans() == 0
                assert proc.poll() is None, "在飞 run 的 dev-server 不应被清扫"
            finally:
                claude_proc.kill()
                claude_proc.wait()

            # 阶段2：run 结束（无 claude 引用）→ 下一清扫周期回收
            with patch.object(v2, "_dev_server_orphan_pids",
                              return_value=[proc.pid]):
                assert cleanup_orphans() >= 1
            assert proc.wait(timeout=10) is not None, "清扫应终止孤儿 dev-server"

            # 阶段3：回收后本实例端口释放可用（无残留监听；新 daemon used 集
            # 为空，故不做跨 daemon 记账断言）
            assert _port_in_use(port) is False, f"端口 {port} 应已释放可用"
        finally:
            if proc.poll() is None:
                v2_stop(proc, port, used)

class TestRepairRoundServing:
    """repair 轮服务保障（verify-process-lifecycle D7 / task 8.2）。

    repair 复用载体轮在注册表无条目时经幂等 ensure 补启专属 dev-server；
    BASE_URL 注入非空、绝不回退主树 8787。
    """

    def _make_manager(self):
        from types import SimpleNamespace
        mgr = V2ServerManager.__new__(V2ServerManager)
        mgr._pm = SimpleNamespace(logger=FakeLogger())
        return mgr

    def test_repair_round_gets_dedicated_instance(self, tmp_path):
        """repair 复用载体轮：无注册条目 → 自动补启专属实例 + 正常注入 BASE_URL。"""
        wt = make_worktree(tmp_path, f"impl-repair-round-{os.getpid()}")
        mgr = self._make_manager()
        port, proc = None, None
        try:
            mgr._v2_launch_for_worktree(wt)
            assert str(wt) in mgr._v2_servers, "repair 轮应补启 dev-server"
            port = mgr._v2_servers[str(wt)][0]
            proc = mgr._v2_servers[str(wt)][1]
            assert port != 8787, "repair 轮绝不落主树 8787"
            env = mgr._v2_inject_env(wt)
            assert env.get("V2_BASE_URL") == f"http://127.0.0.1:{port}", \
                "BASE_URL 注入不得为空（repair 轮不打 8787）"
        finally:
            if proc is not None and proc.poll() is None:
                mgr._v2_stop_for_worktree(wt)

    def test_idempotent_ensure_no_duplicate_instance(self, tmp_path):
        """幂等 ensure：已有存活注册条目不重复启动（同 worktree 双实例互斥）。"""
        wt = make_worktree(tmp_path, f"impl-idempotent-{os.getpid()}")
        mgr = self._make_manager()
        try:
            mgr._v2_launch_for_worktree(wt)
            port1 = mgr._v2_servers[str(wt)][0]
            proc1 = mgr._v2_servers[str(wt)][1]
            mgr._v2_launch_for_worktree(wt)
            assert len(mgr._v2_servers) == 1
            assert mgr._v2_servers[str(wt)][0] == port1
            assert mgr._v2_servers[str(wt)][1] is proc1
        finally:
            mgr._v2_stop_for_worktree(wt)

    def test_stale_entry_relaunched(self, tmp_path):
        """条目进程已死（陈旧）→ 幂等 ensure 补启新实例（repair 轮不空 env）。"""
        wt = make_worktree(tmp_path, f"impl-relaunch-{os.getpid()}")
        mgr = self._make_manager()
        try:
            mgr._v2_launch_for_worktree(wt)
            old_proc = mgr._v2_servers[str(wt)][1]
            old_proc.kill()
            old_proc.wait()
            mgr._v2_launch_for_worktree(wt)
            new_proc = mgr._v2_servers[str(wt)][1]
            assert new_proc.poll() is None, "补启实例应存活"
            env = mgr._v2_inject_env(wt)
            assert env.get("V2_BASE_URL"), "陈旧条目补启后 BASE_URL 注入非空"
        finally:
            mgr._v2_stop_for_worktree(wt)
