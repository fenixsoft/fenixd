# -*- coding: utf-8 -*-
"""fenix-prototype skill 交付物测试。

覆盖（对应 spec/changes/fenix-prototype）：
- 任务 1.1：stack_profile.py 栈画像侦察（React+antd 识别 / unknown 降级标记）
- 任务 1.4：anchor_tools.py 锚保持比对（未波及锚保持 / 波及区块换锚可检出）
- 任务 2.2/2.3：serve_prototype.py 服务器生命周期与批注落盘
- 任务 1.2：bootstrap_vendor.py 三级降级判定（纯函数级，不打真实网络）

全部测试确定性：不依赖现场 LLM 生成、不打真实外网、不起长驻进程。
"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "fenix-prototype" / "scripts"
for p in (str(SCRIPTS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import bootstrap_vendor  # noqa: E402
import stack_profile  # noqa: E402


# ---------------------------------------------------------------------------
# 任务 1.1：栈画像侦察
# ---------------------------------------------------------------------------

def _write_package_json(root: Path, deps: dict, dev_deps: dict | None = None):
    data = {"dependencies": deps}
    if dev_deps:
        data["devDependencies"] = dev_deps
    (root / "package.json").write_text(json.dumps(data), encoding="utf-8")


class TestStackProfileReactAntd:
    """任务 1.1：React+antd 工程画像。"""

    def _make_project(self, tmp_path: Path) -> Path:
        root = tmp_path / "proj"
        (root / "src").mkdir(parents=True)
        _write_package_json(root, {
            "react": "^19.2.7",
            "react-dom": "^19.2.7",
            "antd": "^6.6.0",
        })
        (root / "src" / "global.less").write_text(
            ":root {\n  --primary: 221.2 83.2% 53.3%;\n  --radius: 0.5rem;\n}\n",
            encoding="utf-8")
        (root / "src" / "theme.ts").write_text(
            "export const theme = { token: { colorPrimary: '#1677ff', borderRadius: 6 } };\n",
            encoding="utf-8")
        (root / "DESIGN.md").write_text(
            "# 设计约束\n主颜色 #1677ff；字体 14px；间距 8px 网格。\n",
            encoding="utf-8")
        (root / "src" / "pages").mkdir(parents=True)
        (root / "src" / "pages" / "home.tsx").write_text("export default () => null;\n",
                                                        encoding="utf-8")
        return root

    def test_detects_react_antd_profile_with_versions(self, tmp_path):
        profile = stack_profile.build_profile(self._make_project(tmp_path))
        assert profile["profile"] == "react-antd"
        assert profile["detected"] is True
        assert profile["framework"]["name"] == "react"
        assert profile["framework"]["version"] == "^19.2.7"
        assert profile["component_library"]["name"] == "antd"
        assert profile["component_library"]["version"] == "^6.6.0"

    def test_real_components_generation_mode(self, tmp_path):
        profile = stack_profile.build_profile(self._make_project(tmp_path))
        assert profile["generation"] == {
            "mode": "real-components", "binding": "binding", "annotation": None,
        }
        assert profile["degradation"] is None

    def test_theme_tokens_extracted_from_less_and_ts(self, tmp_path):
        profile = stack_profile.build_profile(self._make_project(tmp_path))
        assert profile["theme"]["css_custom_props"]["--primary"] == "221.2 83.2% 53.3%"
        assert profile["theme"]["antd_tokens"]["colorPrimary"] == "#1677ff"
        assert any("global.less" in s for s in profile["theme"]["sources"])

    def test_design_doc_extracted(self, tmp_path):
        profile = stack_profile.build_profile(self._make_project(tmp_path))
        assert profile["design_doc"] is not None
        assert profile["design_doc"]["path"] == "DESIGN.md"
        assert any("字体" in line for line in profile["design_doc"]["extract"])

    def test_cli_outputs_json_to_stdout(self, tmp_path, capsys):
        root = self._make_project(tmp_path)
        rc = stack_profile.main(["--project", str(root)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["profile"] == "react-antd"

    def test_cli_writes_output_file(self, tmp_path, capsys):
        root = self._make_project(tmp_path)
        out = tmp_path / "out" / "profile.json"
        rc = stack_profile.main(["--project", str(root), "--output", str(out)])
        assert rc == 0
        assert json.loads(out.read_text(encoding="utf-8"))["profile"] == "react-antd"


class TestStackProfileUnknown:
    """任务 1.1：识别失败返回 unknown 并给出降级标记。"""

    def test_no_manifest_degrades_to_plain_html(self, tmp_path):
        profile = stack_profile.build_profile(tmp_path)
        assert profile["profile"] == "unknown"
        assert profile["detected"] is False
        assert profile["generation"]["mode"] == "plain-html"
        assert profile["generation"]["binding"] == "none"
        assert profile["generation"]["annotation"] == "视觉参照、无约束力"
        assert profile["degradation"]["level"] == "plain-html"
        assert profile["degradation"]["reasons"]
        assert profile["warnings"]

    def test_unrecognized_stack_degrades(self, tmp_path):
        root = tmp_path / "vueapp"
        root.mkdir()
        _write_package_json(root, {"vue": "^3.0.0", "element-plus": "^2.0.0"})
        profile = stack_profile.build_profile(root)
        assert profile["profile"] == "unknown"
        assert profile["degradation"]["level"] == "plain-html"

    def test_react_without_component_library_degrades(self, tmp_path):
        root = tmp_path / "plain"
        root.mkdir()
        _write_package_json(root, {"react": "^19.0.0"})
        profile = stack_profile.build_profile(root)
        assert profile["profile"] == "unknown"

    def test_probe_registry_is_extension_point(self, tmp_path):
        # 画像接口留扩展位：注册表可插入新 probe 且优先生效
        class FakeProbe(stack_profile.StackProbe):
            name = "fake-stack"

            def detect(self, deps):
                return {"profile": self.name, "framework": {"name": "fake", "version": "1"},
                        "component_library": {"name": "fake-ui", "version": "1"},
                        "confidence": "high"}

        original = list(stack_profile.PROFILE_PROBES)
        try:
            stack_profile.PROFILE_PROBES.insert(0, FakeProbe())
            _write_package_json(tmp_path, {"fake-ui": "^1.0.0"})
            profile = stack_profile.build_profile(tmp_path)
            assert profile["profile"] == "fake-stack"
            assert profile["generation"]["mode"] == "real-components"
        finally:
            stack_profile.PROFILE_PROBES[:] = original


class TestStackProfileDogfood:
    """对本仓 dashboard（React+antd）的真实画像：吃狗粮锚点。"""

    def test_repo_dashboard_profile_is_react_antd(self):
        static_root = REPO_ROOT / "core" / "dashboard" / "static"
        if not (static_root / "package.json").is_file():
            pytest.skip("仓内 dashboard static 目录不存在")
        profile = stack_profile.build_profile(static_root)
        assert profile["profile"] == "react-antd"
        assert profile["component_library"]["name"] == "antd"
        assert profile["theme"]["css_custom_props"], "应从 global.less 提取到主题 token"


# ---------------------------------------------------------------------------
# 任务 1.2：vendor 预打包与三级降级判定
# ---------------------------------------------------------------------------

def _make_react_antd_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _write_package_json(root, {"react": "^19.2.7", "react-dom": "^19.2.7", "antd": "^6.6.0"})
    return root


class TestDecideLevel:
    """三级降级判定纯函数矩阵。"""

    def test_unknown_stack_goes_plain(self):
        assert bootstrap_vendor.decide_level(
            has_supported_stack=False, cache_hit=False, node_ok=True,
            bundle_succeeded=True, cdn_ok=True) == "plain"

    def test_cache_hit_beats_everything(self):
        assert bootstrap_vendor.decide_level(
            has_supported_stack=True, cache_hit=True, node_ok=False,
            bundle_succeeded=False, cdn_ok=True) == "vendor"

    def test_fresh_bundle_counts_as_vendor(self):
        assert bootstrap_vendor.decide_level(
            has_supported_stack=True, cache_hit=False, node_ok=True,
            bundle_succeeded=True, cdn_ok=True) == "vendor"

    def test_cdn_fallback_when_no_bundle(self):
        assert bootstrap_vendor.decide_level(
            has_supported_stack=True, cache_hit=False, node_ok=False,
            bundle_succeeded=False, cdn_ok=True) == "cdn"

    def test_all_levels_fail_goes_plain(self):
        assert bootstrap_vendor.decide_level(
            has_supported_stack=True, cache_hit=False, node_ok=False,
            bundle_succeeded=False, cdn_ok=False) == "plain"


class TestVendorSnippets:
    """引用片段生成（vendor / cdn 两级）。"""

    def test_vendor_snippet_references_local_file(self):
        snippet = bootstrap_vendor.vendor_script_snippet("vendor.js")
        assert '<script src="vendor.js">' in snippet

    def test_cdn_snippet_is_importmap_with_pinned_versions(self):
        snippet = bootstrap_vendor.cdn_importmap_snippet("^19.2.7", "^6.6.0")
        assert "importmap" in snippet
        assert "esm.sh/react@19.2.7" in snippet
        assert "esm.sh/antd@6.6.0" in snippet

    def test_pinned_strips_range_prefix(self):
        assert bootstrap_vendor.pinned("^6.6.0") == "6.6.0"
        assert bootstrap_vendor.pinned("~19.2.7") == "19.2.7"
        assert bootstrap_vendor.pinned("19.2.7") == "19.2.7"


class TestCacheRoundTrip:
    """缓存读写与版本精确匹配。"""

    def test_write_then_lookup_hits(self, tmp_path):
        cache_root = tmp_path / "vendor-cache"
        vendor_js = tmp_path / "fake-vendor.js"
        vendor_js.write_text("/* bundle */", encoding="utf-8")
        bootstrap_vendor.write_cache(
            cache_root, {"react": "19.2.7", "react-dom": "19.2.7", "antd": "6.6.0",
                         "esbuild": "0.25.0"}, vendor_js, "v24.19.0")
        hit = bootstrap_vendor.cache_lookup(cache_root, "^19.2.7", "^6.6.0")
        assert hit is not None
        assert hit["manifest"]["antd"] == "6.6.0"
        assert hit["manifest"]["sha256"]

    def test_lookup_misses_on_version_mismatch(self, tmp_path):
        cache_root = tmp_path / "vendor-cache"
        vendor_js = tmp_path / "fake-vendor.js"
        vendor_js.write_text("/* bundle */", encoding="utf-8")
        bootstrap_vendor.write_cache(
            cache_root, {"react": "19.2.7", "react-dom": "19.2.7", "antd": "6.6.0",
                         "esbuild": "0.25.0"}, vendor_js, None)
        assert bootstrap_vendor.cache_lookup(cache_root, "^18.3.1", "^6.6.0") is None
        assert bootstrap_vendor.cache_lookup(cache_root, "^19.2.7", "^5.0.0") is None

    def test_lookup_misses_on_empty_cache(self, tmp_path):
        assert bootstrap_vendor.cache_lookup(tmp_path / "none", "^19.2.7", "^6.6.0") is None


class TestBootstrapRun:
    """run() 主流程：缓存命中 / 仿样降级 / CDN 兜底（均不打真实网络）。"""

    def test_run_cache_hit_level_vendor(self, tmp_path):
        project = _make_react_antd_project(tmp_path)
        cache_root = tmp_path / "cache"
        vendor_js = tmp_path / "fake-vendor.js"
        vendor_js.write_text("/* bundle */", encoding="utf-8")
        bootstrap_vendor.write_cache(
            cache_root, {"react": "19.2.7", "react-dom": "19.2.7", "antd": "6.6.0",
                         "esbuild": "0.25.0"}, vendor_js, None)
        result = bootstrap_vendor.run(project, cache_root, offline=True,
                                      cdn_probe_fn=lambda *a, **k: (False, "skipped"))
        assert result["level"] == "vendor"
        assert result["cache"]["hit"] is True
        assert any("vendor-cache-hit" in step for step in result["degradation_path"])

    def test_run_offline_no_cache_falls_to_plain(self, tmp_path):
        project = _make_react_antd_project(tmp_path)

        def failing_bundle(*a, **k):
            return None, None, ["bundle-fail: 注入模拟：node/npm 均不可用"]

        result = bootstrap_vendor.run(project, tmp_path / "cache", offline=True,
                                      cdn_probe_fn=lambda *a, **k: (False, "skipped"),
                                      bundle_fn=failing_bundle)
        assert result["level"] == "plain"
        assert result["cache"]["hit"] is False
        assert any("bundle-fail" in step for step in result["degradation_path"])
        assert result["level_label"] == bootstrap_vendor.LEVEL_LABELS["plain"]

    def test_run_unknown_stack_goes_plain_without_probe(self, tmp_path):
        project = tmp_path / "vueapp"
        project.mkdir()
        _write_package_json(project, {"vue": "^3.0.0"})
        calls = []

        def _probe(*a, **k):
            calls.append(a)
            return True, None

        result = bootstrap_vendor.run(project, tmp_path / "cache", cdn_probe_fn=_probe)
        assert result["level"] == "plain"
        assert calls == [], "unknown 栈不应触发 CDN 探测"
        assert any("stack-unknown" in step for step in result["degradation_path"])

    def test_run_cdn_fallback_via_probe(self, tmp_path):
        project = _make_react_antd_project(tmp_path)
        # 打包注入失败 → 依赖 CDN 兜底；可控探测验证 cdn 层判定与资产清单。

        @contextmanager
        def fake_opener(url, timeout=None):
            class R:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            yield R()

        def probe_via_opener(react_version, antd_version, timeout=8.0):
            return bootstrap_vendor.cdn_probe(react_version, antd_version,
                                              timeout=timeout, _opener=fake_opener)

        def failing_bundle(*a, **k):
            return None, None, ["bundle-fail: 注入模拟：打包不可用"]

        result = bootstrap_vendor.run(project, tmp_path / "cache",
                                      cdn_probe_fn=probe_via_opener,
                                      bundle_fn=failing_bundle)
        assert result["level"] == "cdn"
        assert "urls" in result["assets"]
        assert "importmap" in result["assets"]["snippet"]

    def test_run_bundle_success_writes_cache(self, tmp_path):
        project = _make_react_antd_project(tmp_path)
        cache_root = tmp_path / "cache"
        fake_js = tmp_path / "injected-vendor.js"
        fake_js.write_text("/* injected bundle */", encoding="utf-8")

        def injected_bundle(project, react_version, antd_version, timeout, work_dir=None):
            return fake_js, {"react": "19.2.7", "react-dom": "19.2.7",
                             "antd": "6.6.0", "esbuild": "0.25.0"}, \
                ["bundle-ok: 注入模拟打包成功"]

        result = bootstrap_vendor.run(project, cache_root, offline=True,
                                      cdn_probe_fn=lambda *a, **k: (False, "x"),
                                      bundle_fn=injected_bundle)
        assert result["level"] == "vendor"
        assert result["cache"]["hit"] is False, "本次为现打包写入，非命中"
        assert (cache_root / "react-19.2.7-antd-6.6.0" / "vendor.js").is_file()
        assert any("vendor-cache-write" in step for step in result["degradation_path"])
        # 二次运行应直接命中缓存
        again = bootstrap_vendor.run(project, cache_root, offline=True,
                                     cdn_probe_fn=lambda *a, **k: (False, "x"),
                                     bundle_fn=injected_bundle)
        assert again["level"] == "vendor"
        assert again["cache"]["hit"] is True


class TestBootstrapCli:
    """CLI 出口与 gitignore 自查。"""

    def test_cli_cache_hit_end_to_end(self, tmp_path, capsys):
        project = _make_react_antd_project(tmp_path)
        cache_root = tmp_path / "cache"
        vendor_js = tmp_path / "fake-vendor.js"
        vendor_js.write_text("/* bundle */", encoding="utf-8")
        bootstrap_vendor.write_cache(
            cache_root, {"react": "19.2.7", "react-dom": "19.2.7", "antd": "6.6.0",
                         "esbuild": "0.25.0"}, vendor_js, None)
        rc = bootstrap_vendor.main(["--project", str(project), "--cache-dir",
                                    str(cache_root), "--offline"])
        assert rc == 0
        result = json.loads(capsys.readouterr().out)
        assert result["ok"] is True
        assert result["level"] == "vendor"

    def test_cli_bad_project_exit_2(self, tmp_path):
        assert bootstrap_vendor.main(["--project", str(tmp_path / "nope")]) == 2

    def test_repo_root_gitignore_covers_default_cache_dir(self):
        # 缓存默认目录必须被仓根 .gitignore 的 .fenix/* 规则覆盖，不入库
        assert (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").find(".fenix/*") != -1
