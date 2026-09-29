"""test_main_tree_deps_provision.py — ensure_main_tree_deps 主树供给测试。

覆盖 add-main-tree-deps-provision SPEC 全部场景（tasks.md 3.1）：
  1. 缺 node_modules 触发安装（mock npm 供给原语 _run_npm_provision）
  2. 已存在跳过零调用
  3. 无 package.json 跳过
  4. 安装失败记 warning 不抛异常
  5. 三处调用点在 contract.prepare 存在时被调用（patch 断言）
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.verify_contract import ensure_main_tree_deps


def _write(root: Path, rel: str, content: str = ""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class _FakeRunResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestEnsureMainTreeDeps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.logger = MagicMock()

    # ── 场景 1：缺 node_modules 触发安装 ──────────────────────────────────────

    def test_missing_node_modules_triggers_install(self):
        _write(self.tmp, "pkg/package.json", "{}")
        calls = []

        # item 79741f3caf63：npm 供给改经 _run_npm_provision（Popen+进程组清扫），
        # 替身缝从 subprocess.run 同步到该原语，断言意图（命令行构造）不变
        def fake_provision(cmd, cwd):
            calls.append(cmd)
            return _FakeRunResult(returncode=0)

        with patch("core.verify_contract._run_npm_provision",
                    side_effect=fake_provision):
            done = ensure_main_tree_deps(self.tmp, ["pkg"], logger=self.logger)
        self.assertEqual(done, ["pkg"])
        self.assertEqual(calls[0][:2], ["npm", "ci"])
        self.assertIn("--prefer-offline", calls[0])
        # 成功应记录 INFO（mode 缺省＝DEFAULT_DEPS_MODE＝hardlink；主树自装仍是 npm ci）
        self.logger.info.assert_any_call(
            "verify_contract",
            "主树依赖预装完成（pkg，deps_mode=hardlink）: "
            "npm ci --prefer-offline",
        )

    # ── 场景 2：已存在跳过零调用 ─────────────────────────────────────────────

    def test_existing_node_modules_skipped(self):
        _write(self.tmp, "pkg/package.json", "{}")
        (self.tmp / "pkg" / "node_modules").mkdir()
        done = ensure_main_tree_deps(self.tmp, ["pkg"], logger=self.logger)
        self.assertEqual(done, [])
        self.logger.info.assert_not_called()
        self.logger.warning.assert_not_called()

    # ── 场景 3：无 package.json 跳过 ──────────────────────────────────────────

    def test_missing_package_json_skipped(self):
        (self.tmp / "nopkg").mkdir()
        done = ensure_main_tree_deps(self.tmp, ["nopkg"], logger=self.logger)
        self.assertEqual(done, [])

    # ── 场景 4：安装失败记 warning 不抛 ──────────────────────────────────────

    def test_install_failure_records_warning(self):
        _write(self.tmp, "pkg/package.json", "{}")
        with patch("core.verify_contract._run_npm_provision",
                    side_effect=[_FakeRunResult(1, "", "ERR! network"),
                                 _FakeRunResult(1, "", "ERR! network")]):
            done = ensure_main_tree_deps(self.tmp, ["pkg"], logger=self.logger)
        self.assertEqual(done, [])
        self.logger.warning.assert_called_with(
            "verify_contract",
            "主树依赖预装失败（pkg）: ERR! network",
        )

    def test_install_exception_records_warning(self):
        _write(self.tmp, "pkg/package.json", "{}")
        with patch("core.verify_contract._run_npm_provision",
                    side_effect=OSError("permission denied")):
            done = ensure_main_tree_deps(self.tmp, ["pkg"], logger=self.logger)
        self.assertEqual(done, [])
        self.logger.warning.assert_called_with(
            "verify_contract",
            "主树依赖预装异常（pkg）: permission denied",
        )

    # ── npm ci 失败后回退 npm install ─────────────────────────────────────────

    def test_fallback_to_npm_install_on_ci_failure(self):
        _write(self.tmp, "pkg/package.json", "{}")
        calls = []

        def fake_provision(cmd, cwd):
            calls.append(cmd)
            if cmd[1] == "ci":
                return _FakeRunResult(1)
            return _FakeRunResult(0)

        with patch("core.verify_contract._run_npm_provision",
                    side_effect=fake_provision):
            done = ensure_main_tree_deps(self.tmp, ["pkg"], logger=self.logger)
        self.assertEqual(done, ["pkg"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "ci")
        self.assertEqual(calls[1][1], "install")

    # ── 混合场景：多目录部分供给 ──────────────────────────────────────────────

    def test_mixed_directories(self):
        _write(self.tmp, "a/package.json", "{}")
        _write(self.tmp, "b/package.json", "{}")
        (self.tmp / "b" / "node_modules").mkdir()
        calls = []

        def fake_provision(cmd, cwd):
            calls.append(cmd)
            return _FakeRunResult(returncode=0)

        with patch("core.verify_contract._run_npm_provision",
                    side_effect=fake_provision):
            done = ensure_main_tree_deps(self.tmp, ["a", "b", "c"],
                                          logger=self.logger)
        self.assertEqual(done, ["a"])
        # b 已存在跳过，c 无 package.json 跳过，只调用一次
        self.assertEqual(len(calls), 1)

    # ── dep_mode 参数影响日志但不改变安装方式 ─────────────────────────────────

    def test_mode_reflected_in_log(self):
        _write(self.tmp, "pkg/package.json", "{}")
        with patch("core.verify_contract._run_npm_provision",
                    return_value=_FakeRunResult(0)):
            ensure_main_tree_deps(self.tmp, ["pkg"],
                                  mode="hardlink", logger=self.logger)
        self.logger.info.assert_called_with(
            "verify_contract",
            "主树依赖预装完成（pkg，deps_mode=hardlink）: "
            "npm ci --prefer-offline",
        )


class TestEnsureMainTreeDepsIntegration(unittest.TestCase):
    """验证三处调用点在 contract.prepare 存在时调用 ensure_main_tree_deps（tasks 3.1 patch 断言）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.logger = MagicMock()

    def test_ensure_main_tree_deps_called_in_ensure_app_reachable_cli(self):
        """纯 cli 分支：contract.prepare 存在时 ensure_main_tree_deps 被调用（patch 断言）。"""
        (self.tmp / ".fenix").mkdir()
        from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
        contract = VerifyContract(
            prepare=[PrepareStep(run="echo ok", cwd=".")],
            serve=None, ready=ReadyProbe(),
        )
        with patch("core.pm_engine.verification.ensure_main_tree_deps") as mock_ensure, \
             patch("core.pm_engine.verification.run_prepare_steps", return_value=None):
            from core.pm_engine.verification import VerificationPipeline
            from unittest.mock import PropertyMock
            pm = MagicMock()
            pm.project_root = self.tmp
            pm.logger = self.logger
            pm._get_config = MagicMock(return_value="")
            pipeline = VerificationPipeline(pm)

            # 模拟纯 cli 场景
            scenarios = [{"kind": "cli", "steps": []}]
            scenarios_path = self.tmp / ".fenix" / "verify-progress" / "test-spec" / "test_scenarios.json"
            scenarios_path.parent.mkdir(parents=True)
            scenarios_path.write_text(
                __import__("json").dumps(scenarios), encoding="utf-8")

            with patch("core.pm_engine.verification.load_verify_contract", return_value=contract):
                pipeline._ensure_app_reachable("test-spec")

            mock_ensure.assert_called_once()

    def test_ensure_main_tree_deps_called_in_ensure_app_reachable_main_scope(self):
        """主树作用域分支：contract.prepare 存在且 not wt_scope 时被调用。"""
        (self.tmp / ".fenix").mkdir()
        from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
        contract = VerifyContract(
            prepare=[PrepareStep(run="echo ok", cwd=".")],
            serve=ServeSpec(kind="static", root="."),
            ready=ReadyProbe(),
        )
        with patch("core.pm_engine.verification.ensure_main_tree_deps") as mock_ensure, \
             patch("core.pm_engine.verification.run_prepare_steps", return_value=None):
            from core.pm_engine.verification import VerificationPipeline
            pm = MagicMock()
            pm.project_root = self.tmp
            pm.logger = self.logger
            pm._get_config = MagicMock(return_value="main")  # static_scope=main
            pipeline = VerificationPipeline(pm)

            scenarios = [{"kind": "web", "steps": [{"action": "navigate", "value": "http://localhost/"}]}]
            scenarios_path = self.tmp / ".fenix" / "verify-progress" / "test-spec" / "test_scenarios.json"
            scenarios_path.parent.mkdir(parents=True)
            scenarios_path.write_text(
                __import__("json").dumps(scenarios), encoding="utf-8")

            with patch("core.pm_engine.verification.load_verify_contract", return_value=contract):
                pipeline._ensure_app_reachable("test-spec")

            mock_ensure.assert_called_once()

    def test_ensure_main_tree_deps_called_in_run_dist_build(self):
        """worktree_manager._run_dist_build：contract.prepare 存在时被调用。"""
        (self.tmp / ".fenix").mkdir()
        from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
        contract = VerifyContract(
            prepare=[PrepareStep(run="echo ok")],
            serve=None, ready=ReadyProbe(),
        )
        with patch("core.verify_contract.ensure_main_tree_deps") as mock_ensure, \
             patch("core.verify_contract.run_prepare_steps", return_value=None), \
             patch("core.verify_contract.load_verify_contract", return_value=contract):
            from core.worktree_manager import WorktreeManager
            wm = WorktreeManager.__new__(WorktreeManager)
            wm.project_root = self.tmp
            wm.logger = self.logger

            wm._run_dist_build()

            mock_ensure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
