"""impl_code_review_gate / impl-code-review-setting 测试。

覆盖 tasks 7.1-7.4：
- 7.1 配置读取器（缺失/非bool/严格True/project-override）
- 7.2 bin/ocr_review.py 包装器（HOME改写/argv透传/execvp缺省名）
- 7.3 硬门（开关关闭零校验/开启六种失败形态/放行形态/末轮零误拦）
- 7.4 run级 ocr 配置写入（落盘JSON断言/HOME不变量/不触碰用户全局）
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigLoader


# ── 7.1 配置读取器 ─────────────────────────────────────────────────────


class TestGetImplCodeReviewEnabled:
    """ConfigLoader.get_impl_code_review_enabled 严格 bool 语义。"""

    def test_missing_verify_section(self):
        """verify 节缺失 → False"""
        assert ConfigLoader.get_impl_code_review_enabled({}) is False

    def test_missing_impl_code_review_key(self):
        """verify 存在但无 impl_code_review → False"""
        assert ConfigLoader.get_impl_code_review_enabled({"verify": {}}) is False

    def test_none_value(self):
        """impl_code_review=None → False"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": None}}
        ) is False

    def test_int_one(self):
        """impl_code_review=1（非 bool）→ False"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": 1}}
        ) is False

    def test_string_yes(self):
        """impl_code_review="yes"（非 bool）→ False"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": "yes"}}
        ) is False

    def test_false_explicit(self):
        """impl_code_review=False → False"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": False}}
        ) is False

    def test_true_explicit(self):
        """impl_code_review=True → True"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": {"impl_code_review": True}}
        ) is True

    def test_verify_not_dict(self):
        """verify 节非 dict → False"""
        assert ConfigLoader.get_impl_code_review_enabled(
            {"verify": "bogus"}
        ) is False

    def test_project_override_project_true(self):
        """项目级 true + 用户级无 → True（模拟合并后结果）"""
        merged = {"verify": {"impl_code_review": True}}
        assert ConfigLoader.get_impl_code_review_enabled(merged) is True

    def test_project_override_user_true_project_false(self):
        """用户级 true + 项目级 false → False（模拟合并后结果）"""
        merged = {"verify": {"impl_code_review": False}}
        assert ConfigLoader.get_impl_code_review_enabled(merged) is False


# ── 7.2 bin/ocr_review.py 包装器 ──────────────────────────────────────


class TestOcrReviewWrapper:
    """bin/ocr_review.py HOME 重定向包装器行为。"""

    @pytest.fixture()
    def wrapper_path(self):
        """返回 bin/ocr_review.py 的绝对路径。"""
        return Path(__file__).resolve().parent.parent / "bin" / "ocr_review.py"

    def test_executable(self, wrapper_path):
        """包装器文件存在且有执行权限。"""
        assert wrapper_path.exists()
        mode = wrapper_path.stat().st_mode
        assert mode & stat.S_IXUSR, "bin/ocr_review.py must be executable"

    def test_has_shebang(self, wrapper_path):
        """包装器有 shebang。"""
        first_line = wrapper_path.read_text().splitlines()[0]
        assert first_line.startswith("#!/usr/bin/env python3")

    def test_home_rewritten_when_set(self, wrapper_path, tmp_path):
        """FENIX_OCR_HOME 非空 → 子进程 HOME 被改写，argv 逐项透传，退出码透传。"""
        fake_ocr = tmp_path / "fake_ocr.py"
        # fake_ocr: 把 HOME / argv / 退出码写到 stdout 供断言
        fake_ocr.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys; print(json.dumps({'
            '"home": os.environ.get("HOME"),'
            '"argv": sys.argv,'
            '}))\n',
            encoding="utf-8",
        )
        fake_ocr.chmod(0o755)
        run_home = tmp_path / "run_home"
        run_home.mkdir()
        env = os.environ.copy()
        env["FENIX_OCR_HOME"] = str(run_home)
        env["FENIX_OCR_BIN"] = str(fake_ocr)
        result = subprocess.run(
            [sys.executable, str(wrapper_path), "review", "--from", "main", "--to", "HEAD"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout.strip())
        assert data["home"] == str(run_home)
        assert data["argv"] == [str(fake_ocr), "review", "--from", "main", "--to", "HEAD"]

    def test_home_not_rewritten_when_empty(self, wrapper_path, tmp_path):
        """FENIX_OCR_HOME 为空 → HOME 不被改写。"""
        original_home = os.environ.get("HOME", "/tmp")
        fake_ocr = tmp_path / "fake_ocr.py"
        fake_ocr.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, sys; print(json.dumps({'
            '"home": os.environ.get("HOME"),'
            '}))\n',
            encoding="utf-8",
        )
        fake_ocr.chmod(0o755)
        env = os.environ.copy()
        env.pop("FENIX_OCR_HOME", None)
        env["FENIX_OCR_BIN"] = str(fake_ocr)
        result = subprocess.run(
            [sys.executable, str(wrapper_path), "review"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout.strip())
        assert data["home"] == original_home

    def test_exit_code_passthrough(self, wrapper_path, tmp_path):
        """底层 ocr 非零退出 → 包装器透传同非零码。"""
        fake_ocr = tmp_path / "fail_ocr.py"
        fake_ocr.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(42)\n", encoding="utf-8")
        fake_ocr.chmod(0o755)
        env = os.environ.copy()
        env.pop("FENIX_OCR_HOME", None)
        env["FENIX_OCR_BIN"] = str(fake_ocr)
        result = subprocess.run(
            [sys.executable, str(wrapper_path)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 42

    def test_default_bin_resolves_via_path(self, wrapper_path, tmp_path):
        """FENIX_OCR_BIN 未设时包装器能通过 PATH 找到同名可执行（execvp vs execv 回归）。"""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "ocr"
        stub.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os; print(json.dumps({"ok": True}))\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        env = os.environ.copy()
        env.pop("FENIX_OCR_HOME", None)
        env.pop("FENIX_OCR_BIN", None)
        env["PATH"] = str(bin_dir) + ":" + env.get("PATH", "")
        result = subprocess.run(
            [sys.executable, str(wrapper_path), "llm", "test"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, f"execvp failed (FileNotFoundError?): {result.stderr}"
        data = json.loads(result.stdout.strip())
        assert data["ok"] is True


# ── 7.4 run级 ocr 配置写入 ────────────────────────────────────────────


class TestWriteRunOcrConfig:
    """runner._write_run_ocr_config 落盘断言。"""

    def _make_runner(self, proot: Path):
        """构造最小 AgentRunner 实例。"""
        from test_agent_runner import make_runner
        runner = make_runner(proot)
        # 注入配置（开）和 _ensure_agent_config_dir
        runner.config = {"verify": {"impl_code_review": True}}
        # 替换 _ensure_agent_config_dir 为幂等实现（直接返回目标目录）
        target = proot / ".fenix" / "agent-config" / "testprov"
        target.mkdir(parents=True, exist_ok=True)
        runner._ensure_agent_config_dir = lambda name, provider_model="": target
        return runner

    def test_config_file_written_and_home_invariant(self, tmp_path):
        """写入后 HOME 不变量：返回路径 P 满足 (P / ".opencodereview" / "config.json").is_file()。"""
        runner = self._make_runner(tmp_path)
        provider = {"name": "testprov", "apikey": "sk-abc", "baseurl": "https://llm.test/v1"}
        home_dir = runner._write_run_ocr_config(provider, "claude-3-opus")
        assert home_dir is not None
        assert isinstance(home_dir, Path)
        cfg_file = home_dir / ".opencodereview" / "config.json"
        assert cfg_file.is_file(), f"HOME invariant broken: {cfg_file} not found"
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert data["provider"] == "fenix-impl"
        assert data["custom_providers"]["fenix-impl"]["url"] == "https://llm.test/v1"
        assert data["custom_providers"]["fenix-impl"]["api_key"] == "sk-abc"
        assert data["custom_providers"]["fenix-impl"]["model"] == "claude-3-opus"
        assert data["custom_providers"]["fenix-impl"]["protocol"] == "anthropic"

    def test_model_from_param_not_provider(self, tmp_path):
        """model 取自传入参数（本轮生效模型），非 provider["model"]。"""
        runner = self._make_runner(tmp_path)
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x",
                     "model": "gpt-4"}  # provider 自带 gpt-4
        home_dir = runner._write_run_ocr_config(provider, "claude-sonnet-4")
        cfg = json.loads((home_dir / ".opencodereview" / "config.json").read_text())
        assert cfg["custom_providers"]["fenix-impl"]["model"] == "claude-sonnet-4"

    def test_provider_name_fixed_fenix_impl(self, tmp_path):
        """provider 与 custom_providers 键名恰为固定名 'fenix-impl'。"""
        runner = self._make_runner(tmp_path)
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        home_dir = runner._write_run_ocr_config(provider, "m")
        cfg = json.loads((home_dir / ".opencodereview" / "config.json").read_text())
        assert cfg["provider"] == "fenix-impl"
        assert "fenix-impl" in cfg["custom_providers"]

    def test_home_points_to_ocrcfg_not_parent(self, tmp_path):
        """返回路径是 ocrcfg/ 目录本身，不是其父目录。"""
        runner = self._make_runner(tmp_path)
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        home_dir = runner._write_run_ocr_config(provider, "m")
        assert home_dir.name == "ocrcfg"
        assert (home_dir / ".opencodereview").is_dir()

    def test_no_side_effects_on_user_global_home(self, tmp_path, monkeypatch):
        """写入不触碰用户全局 $HOME/.opencodereview/。"""
        fake_home = tmp_path / "user_home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        runner = self._make_runner(tmp_path)
        provider = {"name": "testprov", "apikey": "k", "baseurl": "http://x"}
        runner._write_run_ocr_config(provider, "m")
        # 用户全局 .opencodereview 不应存在
        assert not (fake_home / ".opencodereview").exists()


# ── 7.3 硬门 ─────────────────────────────────────────────────────────


def _mock_runner(config, wt_path=None, project_root=None):
    """构造硬门用的最小 mock runner。

    project_root 非 None 时指向真实 Path（主树回退候选载体，
    fix-impl-code-review-gate-readback）；缺省不设 → MagicMock 自动属性
    （非 Path 载体，isinstance 判定下跳过主树候选，行为等价现状）。

    _check_artifact_json_file 必须接到模块级真实实现（3.1）：裸 MagicMock
    的该方法恒回非 None mock 值（truthy），主树回退用例的 err 判定失真、
    陈旧 err 甚至不是 str，断言 `"陈旧" in err` 会 TypeError。
    """
    from core.agent_runner.result_gate import _check_artifact_json_file
    runner = MagicMock()
    runner.config = config
    runner._IMPL_RESULT_STATUSES = ("success", "partial", "error")
    if project_root is not None:
        runner.project_root = project_root
    runner._check_artifact_json_file = _check_artifact_json_file
    return runner


class TestCodeReviewArtifactGate:
    """_check_impl_code_review_artifact 各种边界。"""

    def _gate(self, config, wt_path, data, project_root=None,
              run_started_at=None, is_resumed_worktree=False):
        from core.agent_runner.result_gate import _check_impl_code_review_artifact
        runner = _mock_runner(config, wt_path, project_root=project_root)
        return _check_impl_code_review_artifact(
            runner, "demo-spec", wt_path, data,
            run_started_at=run_started_at,
            is_resumed_worktree=is_resumed_worktree,
        )

    def test_disabled_no_gate(self, tmp_path):
        """开关关闭 → 报告缺失不判失败（None 放行）。"""
        config = {"verify": {"impl_code_review": False}}
        assert self._gate(config, tmp_path, {}) is None

    def test_no_verify_section_no_gate(self, tmp_path):
        """verify 节缺失 → None（开关默认 false）"""
        assert self._gate({}, tmp_path, {}) is None

    def test_enabled_report_missing(self, tmp_path):
        """开启 + 报告缺失 → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        err = self._gate(config, tmp_path, {"status": "success"})
        assert err is not None
        assert "报告缺失" in err
        assert "code-review.json" in err

    def test_enabled_report_invalid_json(self, tmp_path):
        """开启 + 报告 JSON 非法 → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text("NOT JSON!!!", encoding="utf-8")
        data = {"status": "success"}
        err = self._gate(config, tmp_path, data)
        assert err is not None
        assert "无法解析" in err

    def test_enabled_status_out_of_range(self, tmp_path):
        """开启 + status 不在白名单（completed/unavailable）→ 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "in_progress", "findings": []}), encoding="utf-8"
        )
        err = self._gate(config, tmp_path, {"status": "success"})
        assert err is not None
        assert "status='in_progress'" in err

    def test_enabled_findings_code_review_mismatch(self, tmp_path):
        """开启 + findings 5条但 dispositions 3条 → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        findings = [{"path": f"f{i}.py"} for i in range(5)]
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": findings}), encoding="utf-8"
        )
        cr_dispositions = [{"disposition": "fixed"}] * 3
        data = {"status": "success", "code_review": {"dispositions": cr_dispositions}}
        err = self._gate(config, tmp_path, data)
        assert err is not None
        assert "不匹配" in err

    def test_enabled_rejected_missing_reason(self, tmp_path):
        """开启 + rejected 缺 reason → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        findings = [{"path": "a.py"}]
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": findings}), encoding="utf-8"
        )
        data = {
            "status": "success",
            "code_review": {"dispositions": [{"disposition": "rejected"}]},
        }
        err = self._gate(config, tmp_path, data)
        assert err is not None
        assert "reason" in err

    def test_enabled_unavailable_missing_reason(self, tmp_path):
        """开启 + unavailable 缺 reason → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "unavailable"}), encoding="utf-8"
        )
        err = self._gate(config, tmp_path, {"status": "success"})
        assert err is not None
        assert "reason" in err

    def test_enabled_unavailable_with_reason_passes(self, tmp_path):
        """开启 + unavailable + 非空 reason → 放行。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "unavailable", "reason": "ocr not installed"}),
            encoding="utf-8",
        )
        assert self._gate(config, tmp_path, {"status": "success"}) is None

    def test_enabled_completed_all_fixed_passes(self, tmp_path):
        """开启 + completed + 全部 fixed → 放行。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        findings = [{"path": "a.py"}]
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": findings}), encoding="utf-8"
        )
        data = {
            "status": "success",
            "code_review": {"dispositions": [{"disposition": "fixed"}]},
        }
        assert self._gate(config, tmp_path, data) is None

    def test_enabled_completed_rejected_with_reason_passes(self, tmp_path):
        """开启 + completed + rejected 附非空 reason → 放行。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        findings = [{"path": "a.py"}]
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": findings}), encoding="utf-8"
        )
        data = {
            "status": "success",
            "code_review": {
                "dispositions": [{"disposition": "rejected", "reason": "false positive"}]
            },
        }
        assert self._gate(config, tmp_path, data) is None

    def test_enabled_findings_summary_alias_passes(self, tmp_path):
        """键名别名：code_review 用同义键 `findings_summary` 登记逐条处置 → 放行。

        契约缺口回归（evo-spec-concurrency-flight-guard 解卡）：提示词/spec 只
        描述为「逐条处置摘要」，未固化键名，实现者自选 `findings_summary` →
        硬门读 `dispositions` 得 0 条 → 误判「条数不匹配」死循环。读侧接受别名。
        """
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        findings = [{"path": "a.py"}, {"path": "b.py"}]
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": findings}), encoding="utf-8"
        )
        data = {
            "status": "success",
            "code_review": {
                "findings_summary": [
                    {"disposition": "fixed"},
                    {"disposition": "rejected", "reason": "false positive"},
                ]
            },
        }
        assert self._gate(config, tmp_path, data) is None

    def test_enabled_findings_summary_alias_still_counts(self, tmp_path):
        """别名键仍受条数对账约束：findings_summary 2 条 vs findings 1 条 → 判失败。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": [{"path": "a.py"}]}),
            encoding="utf-8",
        )
        data = {
            "status": "success",
            "code_review": {"findings_summary": [{"disposition": "fixed"}] * 2},
        }
        err = self._gate(config, tmp_path, data)
        assert err is not None
        assert "不匹配" in err

    def test_enabled_neither_key_mismatch(self, tmp_path):
        """两个键名都缺席 → 仍按 0 条对账判失败（不因别名容错而放行缺登记）。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": [{"path": "a.py"}]}),
            encoding="utf-8",
        )
        err = self._gate(
            config, tmp_path, {"status": "success", "code_review": {"report_path": "x"}}
        )
        assert err is not None
        assert "不匹配" in err

    def test_partial_still_has_unchecked_no_gate(self, tmp_path):
        """末轮零误拦：_check_impl_result_artifact 对 status=partial 且仍有未勾任务
        （未覆盖 unattainable）的收口 MUST NOT 调审查硬门——缺失报告不放行不成问题。

        6.2 的接入条件是 ``status == "success" or not (unchecked_ids - unattainable_ids)``：
        partial + 有未勾任务 → 不满足条件，审查门不被调用。本测试钉住该边界：
        无 code-review.json 时 partial 收口仍按既有任务完成度判据处置（不因
        「审查报告缺失」而失败）。
        """
        from core.agent_runner.result_gate import _check_impl_result_artifact
        from test_agent_runner import make_runner

        config = {"verify": {"impl_code_review": True}}
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        runner.config = config
        runner._IMPL_RESULT_STATUSES = ("success", "error", "partial")
        # tasks.md：1.1 已勾，1.2 未勾
        spec_dir = proot / "spec" / "changes" / "demo-spec"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n- [x] 1.1 done\n- [ ] 1.2 todo\n", encoding="utf-8"
        )
        # 结果文件：status=partial + completed_tasks/unfinished 申报一致
        result_path = proot / ".fenix-run-result.json"
        result_path.write_text(
            json.dumps({
                "status": "partial",
                "completed_tasks": ["1.1"],
                "unfinished": ["1.2"],
            }),
            encoding="utf-8",
        )
        # 不写 code-review.json（partial 收口无审查义务）
        err = _check_impl_result_artifact(
            runner, "demo-spec", run_started_at=None, wt_path=proot,
        )
        # 审查门未被调用：失败原因 MUST NOT 含「收尾审查报告缺失」
        assert err is None or "code-review.json" not in err


# ── fix-impl-code-review-gate-readback：主树回退 + 新鲜度守卫 ─────────────


class TestCodeReviewArtifactGateMainTreeFallback:
    """_check_impl_code_review_artifact 双候选路径探测（worktree 优先、主树
    回退）+ 主树新鲜度守卫（spec「收尾审查报告产物硬门」ADDED Requirements）。"""

    def _gate(self, config, wt_path, data, project_root=None,
              run_started_at=None, is_resumed_worktree=False):
        from core.agent_runner.result_gate import _check_impl_code_review_artifact
        runner = _mock_runner(config, wt_path, project_root=project_root)
        return _check_impl_code_review_artifact(
            runner, "demo-spec", wt_path, data,
            run_started_at=run_started_at,
            is_resumed_worktree=is_resumed_worktree,
        )

    def test_worktree_report_wins(self, tmp_path):
        """① worktree 有合法报告 → 放行（以 worktree 为准，MUST NOT 因主树
        同名文件缺失/陈旧判失败）——独立钉住「worktree 优先」场景（3.1①，
        既有 7.3 用例亦覆盖放行形态，此处补主树在场景中缺席的组合）。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        (rpt_dir / "code-review.json").write_text(
            json.dumps({"status": "completed", "findings": [{"path": "a.py"}]}),
            encoding="utf-8",
        )
        proot = tmp_path / "proj"  # 主树存在但无报告
        proot.mkdir()
        data = {
            "status": "success",
            "code_review": {"dispositions": [{"disposition": "fixed"}]},
        }
        assert self._gate(config, tmp_path, data, project_root=proot) is None

    def test_main_tree_fresh_report_passes(self, tmp_path):
        """② worktree 缺失 + 主树本轮新鲜合法报告 → 放行（主树回退）。"""
        config = {"verify": {"impl_code_review": True}}
        wt = tmp_path / "wt"
        wt.mkdir()
        proot = tmp_path / "proj"
        rpt_dir = proot / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        rpt = rpt_dir / "code-review.json"
        rpt.write_text(json.dumps({"status": "completed", "findings": []}), encoding="utf-8")
        now = time.time()
        os.utime(rpt, (now + 1, now + 1))  # mtime 晚于本轮启动（新鲜）
        data = {"status": "success", "code_review": {"dispositions": []}}
        err = self._gate(config, wt, data, project_root=proot, run_started_at=now)
        assert err is None

    def test_main_tree_stale_report_fails(self, tmp_path):
        """③ worktree 缺失 + 主树报告 mtime 陈旧（早于 run_started_at - grace）
        且非 resume → 判失败，文案 MUST 指明「陈旧」（spec 场景）。"""
        config = {"verify": {"impl_code_review": True}}
        wt = tmp_path / "wt"
        wt.mkdir()
        proot = tmp_path / "proj"
        rpt_dir = proot / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        rpt = rpt_dir / "code-review.json"
        rpt.write_text(json.dumps({"status": "completed", "findings": []}), encoding="utf-8")
        now = time.time()
        os.utime(rpt, (now - 100, now - 100))  # mtime 早于本轮启动（陈旧）
        data = {"status": "success", "code_review": {"dispositions": []}}
        err = self._gate(config, wt, data, project_root=proot, run_started_at=now)
        assert err is not None
        assert "陈旧" in err
        # 陈旧归因 MUST NOT 折叠成「报告缺失」
        assert "报告缺失" not in err

    def test_main_tree_stale_report_resume_passes(self, tmp_path):
        """④ 同③但 is_resumed_worktree=True → 跳过 mtime 硬拦，按内容判据
        校验 → 放行（resume 复用 worktree 语义）。"""
        config = {"verify": {"impl_code_review": True}}
        wt = tmp_path / "wt"
        wt.mkdir()
        proot = tmp_path / "proj"
        rpt_dir = proot / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        rpt = rpt_dir / "code-review.json"
        rpt.write_text(json.dumps({"status": "completed", "findings": []}), encoding="utf-8")
        now = time.time()
        os.utime(rpt, (now - 100, now - 100))
        data = {"status": "success", "code_review": {"dispositions": []}}
        err = self._gate(
            config, wt, data, project_root=proot, run_started_at=now,
            is_resumed_worktree=True,
        )
        assert err is None

    def test_both_missing_reports_both_paths(self, tmp_path):
        """⑤ 两处皆缺 → 判失败，文案同时含「报告缺失」「code-review.json」
        与「worktree 与主树」（两个已探测位置）。"""
        config = {"verify": {"impl_code_review": True}}
        wt = tmp_path / "wt"
        wt.mkdir()
        proot = tmp_path / "proj"
        proot.mkdir()
        err = self._gate(config, wt, {"status": "success"}, project_root=proot)
        assert err is not None
        assert "报告缺失" in err
        assert "code-review.json" in err
        assert "worktree 与主树" in err

    def test_project_root_not_path_carrier_skips_main(self, tmp_path):
        """⑥ runner.project_root 非 Path 载体（None / MagicMock / 属性缺失）
        → 跳过主树候选、不抛异常、行为等价现状（worktree 缺失仍报缺失）。"""
        config = {"verify": {"impl_code_review": True}}
        wt = tmp_path / "wt"
        wt.mkdir()
        # 显式 None / MagicMock（自动属性恒 truthy，isinstance 判定拦下）
        for proot in (None, MagicMock()):
            err = self._gate(config, wt, {"status": "success"}, project_root=proot)
            assert err is not None
            assert "报告缺失" in err
        # 属性缺失（_mock_runner 缺省不设 project_root）
        err = self._gate(config, wt, {"status": "success"})
        assert err is not None
        assert "报告缺失" in err

    def test_wt_equals_project_root_dedup_worktree_semantics(self, tmp_path):
        """⑦ wt_path == project_root（tmp_path 同时充当两者）→ 候选按
        Path.resolve() 去重只保留先出现者（worktree 语义），陈旧 mtime 的
        合法报告不做硬拦 → 放行（保现状零变化）。"""
        config = {"verify": {"impl_code_review": True}}
        rpt_dir = tmp_path / ".fenix" / "verify-progress" / "demo-spec"
        rpt_dir.mkdir(parents=True)
        rpt = rpt_dir / "code-review.json"
        rpt.write_text(
            json.dumps({"status": "completed", "findings": [{"path": "a.py"}]}),
            encoding="utf-8",
        )
        now = time.time()
        os.utime(rpt, (now - 100, now - 100))  # 陈旧——但 worktree 语义不硬拦
        data = {
            "status": "success",
            "code_review": {"dispositions": [{"disposition": "fixed"}]},
        }
        err = self._gate(
            config, tmp_path, data, project_root=tmp_path, run_started_at=now,
        )
        assert err is None

    def test_no_worktree_carrier_skips_gate(self, tmp_path):
        """spec「无 worktree 载体时不误判」：wt_path 为 None 且 project_root
        不可得（非 Path 载体）→ 候选集为空 → 返回 None，MUST NOT 报缺失。"""
        config = {"verify": {"impl_code_review": True}}
        proot = tmp_path / "proj"
        proot.mkdir()
        # wt_path=None + project_root=None → 空候选集
        from core.agent_runner.result_gate import _check_impl_code_review_artifact
        runner = _mock_runner(config, wt_path=None)
        err = _check_impl_code_review_artifact(
            runner, "demo-spec", None, {"status": "success"},
            run_started_at=None, is_resumed_worktree=False,
        )
        assert err is None
        # wt_path=None + project_root=真实 Path → 仅主树候选存在，缺报告 → 缺失
        runner2 = _mock_runner(config, wt_path=None, project_root=proot)
        err2 = _check_impl_code_review_artifact(
            runner2, "demo-spec", None, {"status": "success"},
        )
        assert err2 is not None
        assert "报告缺失" in err2
