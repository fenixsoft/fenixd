"""ocr_status / 质量页签 ocr 安装端点测试。

覆盖 core.dashboard.ocr_status（探测与安装，mock 外部命令）与
GET /api/quality/ocr-status、POST /api/quality/ocr-install 两个 HTTP 端点。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer, make_project  # noqa: E402

from core.dashboard import ocr_status  # noqa: E402
from core.dashboard.ocr_status import check_ocr_installed, install_ocr  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402


# ── check_ocr_installed ───────────────────────────────────────────────


class TestCheckOcrInstalled:
    def test_not_installed(self, monkeypatch):
        """shutil.which 返回 None → installed=False，bin/version 均为 None。"""
        monkeypatch.setattr(ocr_status.shutil, "which", lambda _: None)
        assert check_ocr_installed() == {"installed": False, "bin": None, "version": None}

    def test_installed_parses_version_first_line(self, monkeypatch):
        """已装：which 命中 + ocr --version 首行作为 version。"""
        monkeypatch.setattr(ocr_status.shutil, "which", lambda _: "/usr/bin/ocr")

        def fake_run(argv, **kwargs):
            assert argv[0] == "/usr/bin/ocr"
            r = MagicMock()
            r.returncode = 0
            r.stdout = "open-code-review v1.12.5 (189be5b0) linux/amd64\nbuilt at: ...\n"
            return r

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        out = check_ocr_installed()
        assert out["installed"] is True
        assert out["bin"] == "/usr/bin/ocr"
        assert out["version"] == "open-code-review v1.12.5 (189be5b0) linux/amd64"

    def test_installed_but_version_command_fails(self, monkeypatch):
        """已装但 --version 非零退出 → installed 仍 True，version=None。"""
        monkeypatch.setattr(ocr_status.shutil, "which", lambda _: "/usr/bin/ocr")

        def fake_run(argv, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            return r

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        out = check_ocr_installed()
        assert out["installed"] is True
        assert out["version"] is None

    def test_installed_but_version_command_raises(self, monkeypatch):
        """已装但 --version 抛 OSError → installed 仍 True，version=None。"""
        monkeypatch.setattr(ocr_status.shutil, "which", lambda _: "/usr/bin/ocr")

        def fake_run(argv, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        assert check_ocr_installed()["installed"] is True


# ── install_ocr ───────────────────────────────────────────────────────


class TestInstallOcr:
    def test_success(self, monkeypatch):
        """npm 安装成功 → ok=True + 重新探测得到的 version。"""
        calls = {}

        def fake_run(argv, **kwargs):
            calls["argv"] = argv
            r = MagicMock()
            r.returncode = 0
            r.stdout = "added 1 package"
            r.stderr = ""
            return r

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        monkeypatch.setattr(
            ocr_status, "check_ocr_installed",
            lambda: {"installed": True, "bin": "/usr/bin/ocr", "version": "v9"},
        )
        out = install_ocr()
        assert out["ok"] is True
        assert out["version"] == "v9"
        # 命令为固定字面量：npm install -g <包名>
        assert calls["argv"] == ["npm", "install", "-g", ocr_status.OCR_NPM_PACKAGE]

    def test_nonzero_exit(self, monkeypatch):
        """npm 非零退出（如 EACCES）→ ok=False，output 含原始报错尾部。"""
        def fake_run(argv, **kwargs):
            r = MagicMock()
            r.returncode = 243
            r.stdout = ""
            r.stderr = "npm ERR! code EACCES\nnpm ERR! permission denied"
            return r

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        out = install_ocr()
        assert out["ok"] is False
        assert "非零退出码" in out["error"]
        assert "EACCES" in out["output"]

    def test_timeout(self, monkeypatch):
        """npm 超时 → ok=False + 可读错误。"""
        def fake_run(argv, **kwargs):
            raise ocr_status.subprocess.TimeoutExpired(cmd="npm", timeout=1)

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        out = install_ocr(timeout=1)
        assert out["ok"] is False
        assert "超时" in out["error"]

    def test_npm_missing(self, monkeypatch):
        """npm 不可执行（OSError）→ ok=False + 可读错误。"""
        def fake_run(argv, **kwargs):
            raise OSError("npm not found")

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        out = install_ocr()
        assert out["ok"] is False
        assert "npm" in out["error"]

    def test_success_but_still_missing_from_path(self, monkeypatch):
        """npm 报成功但 PATH 上仍无 ocr → ok=False（提示检查全局前缀）。"""
        def fake_run(argv, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "added 1 package"
            r.stderr = ""
            return r

        monkeypatch.setattr(ocr_status.subprocess, "run", fake_run)
        monkeypatch.setattr(
            ocr_status, "check_ocr_installed",
            lambda: {"installed": False, "bin": None, "version": None},
        )
        out = install_ocr()
        assert out["ok"] is False
        assert "PATH" in out["error"]


# ── HTTP 端点 ─────────────────────────────────────────────────────────


class TestQualityOcrAPI:
    def _server(self, tmp_path, registry):
        static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
        return _TestServer(registry, static)

    def _registry(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        return reg

    def test_status_installed(self, tmp_path, monkeypatch):
        import core.dashboard.routes.settings_routes as mod

        monkeypatch.setattr(
            mod, "check_ocr_installed",
            lambda: {"installed": True, "bin": "/usr/bin/ocr", "version": "v1"},
        )
        srv = self._server(tmp_path, self._registry(tmp_path))
        try:
            status, body = srv.get("/api/quality/ocr-status")
            assert status == 200
            assert body == {"installed": True, "bin": "/usr/bin/ocr", "version": "v1"}
        finally:
            srv.stop()

    def test_status_not_installed(self, tmp_path, monkeypatch):
        import core.dashboard.routes.settings_routes as mod

        monkeypatch.setattr(
            mod, "check_ocr_installed",
            lambda: {"installed": False, "bin": None, "version": None},
        )
        srv = self._server(tmp_path, self._registry(tmp_path))
        try:
            status, body = srv.get("/api/quality/ocr-status")
            assert status == 200 and body["installed"] is False
        finally:
            srv.stop()

    def test_install_success(self, tmp_path, monkeypatch):
        import core.dashboard.routes.settings_routes as mod

        monkeypatch.setattr(
            mod, "install_ocr",
            lambda: {"ok": True, "error": None, "output": "added 1 package", "version": "v2"},
        )
        srv = self._server(tmp_path, self._registry(tmp_path))
        try:
            status, body = srv.post_json("/api/quality/ocr-install", {})
            assert status == 200
            assert body["ok"] is True and body["version"] == "v2"
        finally:
            srv.stop()

    def test_install_failure_returns_400(self, tmp_path, monkeypatch):
        import core.dashboard.routes.settings_routes as mod

        monkeypatch.setattr(
            mod, "install_ocr",
            lambda: {
                "ok": False,
                "error": "npm install 返回非零退出码 243",
                "output": "npm ERR! code EACCES",
                "version": None,
            },
        )
        srv = self._server(tmp_path, self._registry(tmp_path))
        try:
            status, body = srv.post_json("/api/quality/ocr-install", {})
            assert status == 400
            assert "EACCES" in body["error"]
        finally:
            srv.stop()


# ── add-impl-code-review-tuning：config_admin 三键登记 / sources / 回显 / 写读 ──


class TestImplCodeReviewTuningConfigAdmin:
    """verify.impl_code_review_* 三键在 config_admin 的登记 / sources / 回显 /
    写读回环 / 非法值拒绝 / 同步白名单（tasks 7.4）。"""

    def _write(self, root: Path, patch: dict) -> dict:
        from core.dashboard.data import write_config
        return write_config(root, patch)

    def test_source_keys_registered(self):
        """三键登记进 _SOURCE_KEYS（缺省 sources == "user"）。"""
        from core.dashboard.data import _SOURCE_KEYS

        assert "verify.impl_code_review_timeout_sec" in _SOURCE_KEYS
        assert "verify.impl_code_review_concurrency" in _SOURCE_KEYS
        assert "verify.impl_code_review_effort" in _SOURCE_KEYS
        # 未登记子键进 _MANAGED_KEYS（节级仅 "verify"）
        from core.dashboard.data import _MANAGED_KEYS

        assert "verify" in _MANAGED_KEYS
        assert "verify.impl_code_review_timeout_sec" not in _MANAGED_KEYS

    def test_sync_page_keys_include_three(self):
        """_SYNC_PAGE_KEYS["quality"]["verify"] 含三新键与既有开关键。"""
        from core.dashboard.data import _SYNC_PAGE_KEYS

        qv = _SYNC_PAGE_KEYS["quality"]["verify"]
        assert "impl_code_review" in qv
        assert "impl_code_review_timeout_sec" in qv
        assert "impl_code_review_concurrency" in qv
        assert "impl_code_review_effort" in qv
        # add-impl-ocr-parallel-lane：join 双档模式随质量页签同步
        assert "impl_code_review_mode" in qv

    def test_default_echo_both_sides(self, tmp_path):
        """缺省恒回显：read_config 侧含 600/4/low/gate（add-impl-ocr-parallel-lane：
        并发缺省 2→4、新增 mode 键缺省 gate）。
        项目级 read_config 侧既有 impl_code_review 开关仍缺席（5.4「缺省不回显」
        约定不变）；read_effective_config 侧是合并用户级后的有效值（数值随环境
        的用户级显式配置漂移）——只断参数键恒出且值合法。"""
        from core.dashboard.data import read_config, read_effective_config

        rc = read_config(tmp_path)
        assert rc["verify"]["impl_code_review_timeout_sec"] == 600
        assert rc["verify"]["impl_code_review_concurrency"] == 4
        assert rc["verify"]["impl_code_review_effort"] == "low"
        assert rc["verify"]["impl_code_review_mode"] == "gate"
        assert "impl_code_review" not in rc["verify"]

        eff = read_effective_config(tmp_path)
        # eff 侧是合并用户级后的有效值：本环境用户级显式配置了 600/2/low，
        # 数值随环境漂移（显式压过缺省），只断键恒出 + 值合法（类型契约）。
        assert eff["verify"]["impl_code_review_timeout_sec"] >= 1
        assert eff["verify"]["impl_code_review_concurrency"] >= 1
        assert eff["verify"]["impl_code_review_effort"] in ("low", "medium", "high")
        assert eff["verify"]["impl_code_review_mode"] in ("gate", "advisory")
        # 缺省 sources == "user"
        assert rc["sources"]["verify.impl_code_review_timeout_sec"] == "user"
        assert rc["sources"]["verify.impl_code_review_concurrency"] == "user"
        assert rc["sources"]["verify.impl_code_review_effort"] == "user"
        assert rc["sources"]["verify.impl_code_review_mode"] == "user"

    def test_write_read_roundtrip(self, tmp_path):
        """写 900/4/high → 读回同值（sources 标注 project）。"""
        from core.dashboard.data import read_config, read_effective_config

        res = self._write(
            tmp_path,
            {
                "verify": {
                    "impl_code_review_timeout_sec": 900,
                    "impl_code_review_concurrency": 4,
                    "impl_code_review_effort": "high",
                }
            },
        )
        assert res["ok"], res.get("error")

        rc = read_config(tmp_path)
        assert rc["verify"]["impl_code_review_timeout_sec"] == 900
        assert rc["verify"]["impl_code_review_concurrency"] == 4
        assert rc["verify"]["impl_code_review_effort"] == "high"
        assert rc["sources"]["verify.impl_code_review_timeout_sec"] == "project"
        assert rc["sources"]["verify.impl_code_review_concurrency"] == "project"
        assert rc["sources"]["verify.impl_code_review_effort"] == "project"

        eff = read_effective_config(tmp_path)
        assert eff["verify"]["impl_code_review_timeout_sec"] == 900
        assert eff["verify"]["impl_code_review_concurrency"] == 4
        assert eff["verify"]["impl_code_review_effort"] == "high"

    def test_does_not_overwrite_other_keys(self, tmp_path):
        """只改力度保存 → verify.deps_mode 值不变（spec「不覆写其它键」Scenario）。"""
        from core.dashboard.data import read_config

        res = self._write(
            tmp_path,
            {"verify": {"deps_mode": "hardlink", "impl_code_review_effort": "medium"}},
        )
        assert res["ok"], res.get("error")

        res = self._write(tmp_path, {"verify": {"impl_code_review_effort": "low"}})
        assert res["ok"], res.get("error")

        rc = read_config(tmp_path)
        assert rc["verify"]["deps_mode"] == "hardlink"  # 未被覆写
        assert rc["verify"]["impl_code_review_effort"] == "low"

    def test_invalid_values_rejected(self, tmp_path):
        """非法值拒绝（正整数与枚举）：不落盘、保留旧值。"""
        from core.dashboard.data import read_config

        # 预写合法值
        res = self._write(
            tmp_path,
            {
                "verify": {
                    "impl_code_review_timeout_sec": 900,
                    "impl_code_review_concurrency": 4,
                    "impl_code_review_effort": "high",
                }
            },
        )
        assert res["ok"], res.get("error")

        # 超时：bool / 0 / 负 / 字符串 / float → 拒绝
        for bad in (True, 0, -5, "abc", 60.5):
            bad_res = self._write(
                tmp_path, {"verify": {"impl_code_review_timeout_sec": bad}}
            )
            assert not bad_res["ok"], f"{bad!r} 应被拒绝"
            assert "impl_code_review_timeout_sec" in bad_res["error"]

        # 并发：bool / 0 / 负 / 字符串 → 拒绝
        for bad in (True, 0, -1, "2"):
            bad_res = self._write(
                tmp_path, {"verify": {"impl_code_review_concurrency": bad}}
            )
            assert not bad_res["ok"], f"{bad!r} 应被拒绝"
            assert "impl_code_review_concurrency" in bad_res["error"]

        # 力度：非法枚举 / 大小写不匹配 → 拒绝
        for bad in ("extreme", "LOW", "Medium", 1):
            bad_res = self._write(tmp_path, {"verify": {"impl_code_review_effort": bad}})
            assert not bad_res["ok"], f"{bad!r} 应被拒绝"
            assert "impl_code_review_effort" in bad_res["error"]

        # 拒绝后旧值保留（读回归显式值）
        rc = read_config(tmp_path)
        assert rc["verify"]["impl_code_review_timeout_sec"] == 900
        assert rc["verify"]["impl_code_review_concurrency"] == 4
        assert rc["verify"]["impl_code_review_effort"] == "high"

    def test_switch_absent_when_not_configured(self, tmp_path):
        """三键缺省回显不应把 impl_code_review 开关带出（5.4 约定）。"""
        from core.dashboard.data import read_config

        rc = read_config(tmp_path)
        assert "impl_code_review" not in rc["verify"]
        assert rc["sources"]["verify.impl_code_review"] == "user"

    def test_lane_timeout_admin_surface(self, tmp_path):
        """ocr 审查 finding#1 回归锁：车道级硬超时全 admin 链路纳管。

        lane_timeout_sec 与三运行参数同款七触点：_SOURCE_KEYS 登记 /
        sources 标注 / 两缺省回显块 / 提取处生效回显 / 合并白名单 /
        write_config 前置校验 / _SYNC_PAGE_KEYS 同步白名单。"""
        from core.dashboard.data import (
            _SOURCE_KEYS,
            _SYNC_PAGE_KEYS,
            read_config,
            read_effective_config,
        )

        assert "verify.impl_code_review_lane_timeout_sec" in _SOURCE_KEYS
        assert "impl_code_review_lane_timeout_sec" in _SYNC_PAGE_KEYS["quality"]["verify"]

        # 缺省回显 2400（经读取器取，与 ConfigLoader 缺省同源）
        rc = read_config(tmp_path)
        assert rc["verify"]["impl_code_review_lane_timeout_sec"] == 2400
        assert rc["sources"]["verify.impl_code_review_lane_timeout_sec"] == "user"

        # 写 1800 → 读回 project 标注；eff 侧同值
        from core.dashboard.data import write_config

        res = write_config(
            tmp_path, {"verify": {"impl_code_review_lane_timeout_sec": 1800}}
        )
        assert res["ok"], res.get("error")
        rc = read_config(tmp_path)
        assert rc["verify"]["impl_code_review_lane_timeout_sec"] == 1800
        assert rc["sources"]["verify.impl_code_review_lane_timeout_sec"] == "project"
        eff = read_effective_config(tmp_path)
        assert eff["verify"]["impl_code_review_lane_timeout_sec"] == 1800

        # 非法值拒绝：bool / 0 / 负 / 字符串 / float → 不落盘
        for bad in (True, 0, -5, "abc", 60.5):
            bad_res = write_config(
                tmp_path, {"verify": {"impl_code_review_lane_timeout_sec": bad}}
            )
            assert not bad_res["ok"], f"{bad!r} 应被拒绝"
            assert "impl_code_review_lane_timeout_sec" in bad_res["error"]
