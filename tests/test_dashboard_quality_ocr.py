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
