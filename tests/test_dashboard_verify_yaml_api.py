"""Dashboard /api/verify-yaml 端点测试（设置页「项目简介」面板 verify.yaml 查看与编辑）。

verify.yaml 为项目级文件（<项目根>/.fenix/verify.yaml），端点路径固定、
不接受任意路径参数：缺 project 400、项目未知 404、content 非字符串 400。
与 todo.md 的差异：保存时做 YAML 语法校验（坏 YAML 会令框架按「无契约」
静默回退，编辑器必须挡住）；顶层必须为字段映射（列表/标量 = 契约静默失效）。
另覆盖 GET /api/verify-yaml-template（模板端点）与 fenix-init 模板生成。
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestVerifyYamlAPI:
    """GET/POST /api/verify-yaml — verify.yaml 读取与整文件覆写。"""

    def test_get_missing_file_returns_empty(self, server_fx):
        proot, srv = server_fx
        status, data = srv.get("/api/verify-yaml?project=proj-a")
        assert status == 200
        assert data["project"] == "proj-a"
        assert data["content"] == ""
        assert data["exists"] is False

    def test_get_returns_saved_content(self, server_fx):
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: npm run build\n", encoding="utf-8")
        status, data = srv.get("/api/verify-yaml?project=proj-a")
        assert status == 200
        assert data["exists"] is True
        assert "npm run build" in data["content"]

    def test_post_creates_and_saves(self, server_fx):
        proot, srv = server_fx
        content = "serve:\n  kind: static\n  root: dist\n"
        status, data = srv.post_json("/api/verify-yaml?project=proj-a", {"content": content})
        assert status == 200 and data["ok"] is True
        saved = proot / ".fenix" / "verify.yaml"
        assert saved.is_file()
        assert saved.read_text(encoding="utf-8") == content

    def test_post_overwrites_existing(self, server_fx):
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text("ready:\n  url: /\n", encoding="utf-8")
        srv.post_json("/api/verify-yaml?project=proj-a", {"content": "ready:\n  url: /x\n"})
        saved = proot / ".fenix" / "verify.yaml"
        assert saved.read_text(encoding="utf-8") == "ready:\n  url: /x\n"

    def test_post_all_comments_is_valid(self, server_fx):
        """全注释模板 = 无契约（safe_load 得 None），保存合法。"""
        proot, srv = server_fx
        status, data = srv.post_json("/api/verify-yaml?project=proj-a", {"content": "# 仅注释\n"})
        assert status == 200 and data["ok"] is True
        assert yaml.safe_load((proot / ".fenix" / "verify.yaml").read_text(encoding="utf-8")) is None

    def test_post_invalid_yaml_rejected(self, server_fx):
        """坏 YAML 会被框架按「无契约」静默回退，保存端点必须 400 拦截。"""
        _, srv = server_fx
        for bad in ("foo: [unclosed\n", "a: 1\n b: 2\n", "\t- bad:\n  x"):
            status, data = srv.post_json("/api/verify-yaml?project=proj-a", {"content": bad})
            assert status == 400, f"坏 YAML {bad!r} 应被拒绝"
            assert "YAML" in data.get("error", "")

    def test_post_non_mapping_rejected(self, server_fx):
        """顶层非映射（列表/标量）= 契约静默失效，同样 400 拦截。"""
        _, srv = server_fx
        for bad in ("- a\n- b\n", "42\n", "just a string\n"):
            status, data = srv.post_json("/api/verify-yaml?project=proj-a", {"content": bad})
            assert status == 400, f"顶层非映射 {bad!r} 应被拒绝"
            assert "映射" in data.get("error", "")

    def test_get_requires_project(self, server_fx):
        _, srv = server_fx
        status, _ = srv.get("/api/verify-yaml")
        assert status == 400

    def test_post_requires_project(self, server_fx):
        _, srv = server_fx
        status, _ = srv.post_json("/api/verify-yaml", {"content": "a: 1\n"})
        assert status == 400

    def test_unknown_project_404(self, server_fx):
        _, srv = server_fx
        status, _ = srv.get("/api/verify-yaml?project=ghost")
        assert status == 404
        status, _ = srv.post_json("/api/verify-yaml?project=ghost", {"content": "a: 1\n"})
        assert status == 404

    def test_post_content_must_be_string(self, server_fx):
        _, srv = server_fx
        for bad in (123, None, ["x"], {"c": 1}):
            status, _ = srv.post_json("/api/verify-yaml?project=proj-a", {"content": bad})
            assert status == 400, f"content={bad!r} 应被拒绝"


class TestVerifyYamlTemplateAPI:
    """GET /api/verify-yaml-template — 模板读取（core/verify_contract_template.yaml）。"""

    def test_template_served_from_core(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/verify-yaml-template")
        assert status == 200
        template = data["template"]
        assert template.strip()
        # 模板是文档：含字段说明与用法指引，且全部配置行注释（保持无契约安全）
        assert "prepare" in template and "serve" in template and "ready" in template
        assert "verify.yaml" in template

    def test_template_is_inert_yaml(self, server_fx):
        """模板整体 safe_load 必须为 None——生成即安全回退，不猜测项目形态。"""
        _, srv = server_fx
        status, data = srv.get("/api/verify-yaml-template")
        assert status == 200
        assert yaml.safe_load(data["template"]) is None


class TestFenixInitGeneratesVerifyYaml:
    """fenix-init 对新项目生成 .fenix/verify.yaml（全注释模板），已存在则跳过。"""

    FENIX_INIT = Path(__file__).resolve().parents[1] / "fenix-init"

    def _run_init(self, target: Path):
        return subprocess.run(
            [sys.executable, str(self.FENIX_INIT), str(target), "--name", "tpl-proj"],
            capture_output=True, text=True, timeout=60,
        )

    def test_init_generates_template(self, tmp_path):
        target = tmp_path / "fresh-proj"
        target.mkdir()
        result = self._run_init(target)
        assert result.returncode == 0, result.stderr
        generated = target / ".fenix" / "verify.yaml"
        assert generated.is_file(), "fenix-init 应生成 .fenix/verify.yaml"
        content = generated.read_text(encoding="utf-8")
        assert "verify.yaml" in content
        assert yaml.safe_load(content) is None  # 全注释模板：无契约，安全回退

    def test_init_skips_existing(self, tmp_path):
        target = tmp_path / "existing-proj"
        target.mkdir()
        fenix_dir = target / ".fenix"
        fenix_dir.mkdir()
        (fenix_dir / "verify.yaml").write_text("ready:\n  url: /custom\n", encoding="utf-8")
        result = self._run_init(target)
        assert result.returncode == 0, result.stderr
        assert (fenix_dir / "verify.yaml").read_text(encoding="utf-8") == "ready:\n  url: /custom\n"
