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


# ---------------------------------------------------------------------------
# 任务 1.4：锚保持比对（确定性 fixture，MUST NOT 依赖现场 LLM 生成）
# ---------------------------------------------------------------------------

import anchor_tools  # noqa: E402

V1_PROTOTYPE = """
<html><body>
  <header data-proto-id="order-list-header"><h1>订单列表</h1></header>
  <aside data-proto-id="order-list-sidebar"><nav>筛选</nav></aside>
  <main data-proto-id="order-list-table">
    <table><tr><td>A-1001</td><td>张三</td></tr></table>
  </main>
  <div data-proto-id="order-list-toolbar">
    <button>新建</button><img src="x.png" alt="icon">
  </div>
</body></html>
"""

# v2：未波及区块（header/sidebar/table）沿用原锚；受波及的工具栏区块换锚
# （toolbar → actions）；另新增一个空态锚。
V2_PROTOTYPE = """
<html><body>
  <header data-proto-id="order-list-header"><h1>订单列表</h1></header>
  <aside data-proto-id="order-list-sidebar"><nav>筛选</nav></aside>
  <main data-proto-id="order-list-table">
    <table><tr><td>A-1001</td><td>张三</td></tr></table>
    <div data-proto-id="order-list-empty">暂无更多数据</div>
  </main>
  <div data-proto-id="order-list-actions">
    <button>新建</button><img src="x.png" alt="icon">
  </div>
</body></html>
"""


class TestExtractAnchors:
    def test_extracts_all_anchor_ids_in_order(self):
        anchors = anchor_tools.extract_anchors(V1_PROTOTYPE)
        assert list(anchors.keys()) == [
            "order-list-header", "order-list-sidebar",
            "order-list-table", "order-list-toolbar"]

    def test_records_tag_and_text_snapshot(self):
        anchors = anchor_tools.extract_anchors(V1_PROTOTYPE)
        assert anchors["order-list-header"]["tag"] == "header"
        assert "订单列表" in anchors["order-list-header"]["text"]
        assert anchors["order-list-table"]["tag"] == "main"
        assert "A-1001" in anchors["order-list-table"]["text"]

    def test_duplicate_anchor_counts_tracked(self):
        html = ('<div data-proto-id="dup-a">一</div>'
                '<div data-proto-id="dup-a">二</div>')
        anchors = anchor_tools.extract_anchors(html)
        assert anchors["dup-a"]["count"] == 2

    def test_no_anchor_returns_empty(self):
        assert anchor_tools.extract_anchors("<p>plain</p>") == {}


class TestDiffAnchors:
    def test_unaffected_anchors_reported_kept(self):
        report = anchor_tools.diff_anchors(V1_PROTOTYPE, V2_PROTOTYPE)
        for anchor_id in ("order-list-header", "order-list-sidebar", "order-list-table"):
            assert anchor_id in report["kept"]
        assert report["verdict"] == "anchors-changed"

    def test_affected_block_reanchor_detectable_as_dropped(self):
        report = anchor_tools.diff_anchors(V1_PROTOTYPE, V2_PROTOTYPE)
        assert "order-list-toolbar" in report["dropped"]
        assert "order-list-actions" in report["added"]
        assert 0 < report["kept_ratio"] < 1

    def test_rename_guess_pairs_by_text_snapshot(self):
        report = anchor_tools.diff_anchors(V1_PROTOTYPE, V2_PROTOTYPE)
        guesses = {(g["old"], g["new"]) for g in report["rename_guesses"]}
        assert ("order-list-toolbar", "order-list-actions") in guesses

    def test_identical_prototype_is_all_kept(self):
        report = anchor_tools.diff_anchors(V1_PROTOTYPE, V1_PROTOTYPE)
        assert report["verdict"] == "all-kept"
        assert report["kept_ratio"] == 1.0
        assert report["dropped"] == []


class TestVerifyUnaffected:
    def test_declared_affected_passes(self):
        result = anchor_tools.verify_unaffected(
            V1_PROTOTYPE, V2_PROTOTYPE, ["order-list-toolbar"])
        assert result["ok"] is True
        assert result["violations"] == []

    def test_undeclared_drop_is_violation(self):
        result = anchor_tools.verify_unaffected(V1_PROTOTYPE, V2_PROTOTYPE, [])
        assert result["ok"] is False
        assert "order-list-toolbar" in result["violations"]

    def test_partial_declaration_still_flags_others(self):
        result = anchor_tools.verify_unaffected(
            V1_PROTOTYPE, V2_PROTOTYPE, ["order-list-header"])
        assert result["ok"] is False
        assert "order-list-toolbar" in result["violations"]


class TestAnchorToolsCli:
    def test_extract_cli(self, capsys):
        import json as _json
        with pytest.raises(SystemExit) as exc_info:
            anchor_tools.main(["extract", "-"])
        assert exc_info.value.code == 2  # "-" 不是文件，用法错误出口
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as f:
            f.write(V1_PROTOTYPE)
            path = f.name
        rc = anchor_tools.main(["extract", path])
        assert rc == 0
        payload = _json.loads(capsys.readouterr().out)
        assert len(payload["anchors"]) == 4

    def test_diff_with_affected_gate_exit_codes(self, capsys):
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "v1.html"
            new = Path(d) / "v2.html"
            old.write_text(V1_PROTOTYPE, encoding="utf-8")
            new.write_text(V2_PROTOTYPE, encoding="utf-8")
            rc = anchor_tools.main(["diff", str(old), str(new),
                                    "--affected", "order-list-toolbar"])
            assert rc == 0
            ok_payload = _json.loads(capsys.readouterr().out)
            assert ok_payload["ok"] is True
            rc = anchor_tools.main(["diff", str(old), str(new)])
            assert rc == 0
            report = _json.loads(capsys.readouterr().out)
            assert report["verdict"] == "anchors-changed"


# ---------------------------------------------------------------------------
# 任务 2.2 / 2.3：serve_prototype.py 生命周期与批注落盘（真实子进程全链路）
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import serve_prototype  # noqa: E402

SERVE_SCRIPT = str(SCRIPTS_DIR / "serve_prototype.py")


def _make_proto_dir(tmp_path: Path) -> Path:
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / "index.html").write_text(
        '<html><body data-proto-id="page-root"><h1>原型</h1></body></html>',
        encoding="utf-8")
    return proto


def _start_server(proto: Path, *extra):
    out_path = proto / f".start-{int(time.time() * 1000)}.out"
    out_f = open(out_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, SERVE_SCRIPT, str(proto), "--json", *extra],
                            stdout=out_f, stderr=subprocess.STDOUT)
    return proc, out_f, out_path


def _wait_result(out_path: Path, timeout: float = 5.0) -> dict:
    """轮询启动输出直至出现结果 JSON（server 就绪后打印）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for line in out_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    if "action" in data or "error" in data:
                        return data
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"服务器启动超时（{timeout}s）：{out_path.read_text(encoding='utf-8') if out_path.exists() else '<无输出>'}")


def _stop_server(proto: Path):
    subprocess.run([sys.executable, SERVE_SCRIPT, str(proto), "--stop"],
                   capture_output=True, text=True, timeout=10)


class TestServePrototypeLifecycle:
    """任务 2.3：启动→POST 落盘→复用→残留接管→回收，全链路钉死。"""

    def test_start_post_feedback_and_recycle(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        proc, out_f, out_path = _start_server(proto)
        try:
            result = _wait_result(out_path)
            assert result["ok"] is True and result["action"] == "started"
            port = result["url"].rsplit(":", 1)[1].strip("/")

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/feedback",
                data=json.dumps({"anchor": "page-root", "text": "标题再大一点",
                                 "timestamp": "2026-10-29T08:00:00Z", "round": 1}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode())
            assert payload["ok"] is True

            entries = json.loads((proto / "feedback.json").read_text(encoding="utf-8"))
            assert len(entries) == 1
            assert entries[0]["anchor"] == "page-root"
            assert entries[0]["text"] == "标题再大一点"
            assert entries[0]["round"] == 1
            assert entries[0]["timestamp"]
        finally:
            _stop_server(proto)
            proc.wait(timeout=8)
            out_f.close()
        # 回收：PID 文件不留存
        assert not (proto / ".proto-server.json").exists()

    def test_feedback_rejects_invalid_payload(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        proc, out_f, out_path = _start_server(proto)
        try:
            result = _wait_result(out_path)
            port = result["url"].rsplit(":", 1)[1].strip("/")

            # 缺 anchor → 400
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/feedback",
                data=json.dumps({"text": "没有锚"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 400

            # 非法 JSON → 400
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/feedback", data=b"not-json{",
                headers={"Content-Type": "application/json"}, method="POST")
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 400
        finally:
            _stop_server(proto)
            proc.wait(timeout=8)
            out_f.close()

    def test_second_start_reuses_live_instance(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        proc, out_f, out_path = _start_server(proto)
        try:
            first = _wait_result(out_path)
            proc2, out_f2, out_path2 = _start_server(proto)
            try:
                second = _wait_result(out_path2)
                assert second["action"] == "reused"
                assert second["url"] == first["url"], "复用必须同端口"
                assert second["pid"] == first["pid"]
                # 复用后原进程仍存活
                assert proc.poll() is None
            finally:
                out_f2.close()
        finally:
            _stop_server(proto)
            proc.wait(timeout=8)
            out_f.close()

    def test_stale_pid_takeover_after_kill(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        proc, out_f, out_path = _start_server(proto)
        first = _wait_result(out_path)
        first_pid = first["pid"]
        # SIGKILL：无清理机会，PID 文件残留成陈旧记录
        proc.kill()
        proc.wait(timeout=8)
        out_f.close()
        assert (proto / ".proto-server.json").exists()
        assert serve_prototype.read_pid_file(proto)["pid"] == first_pid

        # 再启动：探测残留 → 接管，新实例新端口
        proc2, out_f2, out_path2 = _start_server(proto)
        try:
            second = _wait_result(out_path2)
            assert second["action"] == "started", "残留必须被接管而非复用"
            assert second["pid"] != first_pid
            # 接管后 PID 文件指向新实例
            assert serve_prototype.read_pid_file(proto)["pid"] == second["pid"]
        finally:
            _stop_server(proto)
            proc2.wait(timeout=8)
            out_f2.close()

    def test_stop_reports_not_running_when_fresh(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        done = subprocess.run([sys.executable, SERVE_SCRIPT, str(proto), "--stop", "--json"],
                              capture_output=True, text=True, timeout=10)
        assert done.returncode == 1
        assert json.loads(done.stdout.strip().splitlines()[-1])["action"] == "not-running"

    def test_stale_stop_only_cleans_pid_file(self, tmp_path):
        # PID 文件残留但进程已死：--stop 清理文件、不误报停止
        proto = _make_proto_dir(tmp_path)
        serve_prototype.write_pid_file(proto, 999999, "127.0.0.1", 59999)
        result = serve_prototype.stop_server(proto, SERVE_SCRIPT)
        assert result["action"] == "cleaned-stale"
        assert not (proto / ".proto-server.json").exists()

    def test_pid_reuse_by_innocent_process_is_not_killed(self, tmp_path):
        # PID 被无辜进程复用：判定 stale 接管，MUST NOT 杀掉无辜进程
        proto = _make_proto_dir(tmp_path)
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            serve_prototype.write_pid_file(proto, victim.pid, "127.0.0.1", 59998)
            probe = serve_prototype.probe_existing(proto, SERVE_SCRIPT)
            assert probe["state"] == "stale"
            assert victim.poll() is None, "无辜进程必须存活"
        finally:
            victim.kill()
            victim.wait(timeout=5)


class TestServeStaticServing:
    def test_serves_index_and_blocks_traversal(self, tmp_path):
        proto = _make_proto_dir(tmp_path)
        (proto / "annotator.js").write_text("window.__x = 1;", encoding="utf-8")
        proc, out_f, out_path = _start_server(proto)
        try:
            result = _wait_result(out_path)
            port = result["url"].rsplit(":", 1)[1].strip("/")
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/index.html", timeout=5) as resp:
                assert b"page-root" in resp.read()
            with urllib.request.urlopen(f"{base}/annotator.js", timeout=5) as resp:
                assert b"__x" in resp.read()
            # 路径穿越被拒（SimpleHTTPRequestHandler 目录收敛）
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"{base}/..%2f..%2fetc%2fpasswd", timeout=5)
            assert exc_info.value.code in (301, 404)
        finally:
            _stop_server(proto)
            proc.wait(timeout=8)
            out_f.close()


# ---------------------------------------------------------------------------
# 任务 3.4：契约段双向推演验证（条件开关的结构钉死，防回归为无条件段）
# ---------------------------------------------------------------------------

IMPLEMENTER_MD = (REPO_ROOT / "agents" / "implementer.md").read_text(encoding="utf-8")
CODE_REVIEW_MD = (REPO_ROOT / "agents" / "code-review.md").read_text(encoding="utf-8")


class TestPrototypeBindingContractSections:
    """带声明 SPEC 触发两处契约段义务；无原型 SPEC 零影响（双向推演的结构化落库）。"""

    def test_implementer_section_is_conditional_and_binding(self):
        assert "## UI 原型绑定契约（条件式，prototype-binding-contract）" in IMPLEMENTER_MD
        assert "开关条件" in IMPLEMENTER_MD
        assert "specs/<spec>/prototype/" in IMPLEMENTER_MD
        assert "实现前必读原型" in IMPLEMENTER_MD
        assert "MUST NOT 擅自偏离" in IMPLEMENTER_MD
        assert "零影响" in IMPLEMENTER_MD
        assert "无约束力" in IMPLEMENTER_MD, "仿样原型须豁免"

    def test_code_review_section_is_conditional_and_binding(self):
        assert "## UI 原型对照契约（条件式，prototype-binding-contract）" in CODE_REVIEW_MD
        assert "开关条件" in CODE_REVIEW_MD
        assert "specs/<spec>/prototype/" in CODE_REVIEW_MD
        assert "对照原型检查" in CODE_REVIEW_MD
        assert "data-proto-id" in CODE_REVIEW_MD
        assert "需升级项" in CODE_REVIEW_MD
        assert "零影响" in CODE_REVIEW_MD

    def test_switch_clause_mentions_both_signal_keys(self):
        # 开关 = SPEC 正文引用 prototype/ + Scenario 声明「界面以 prototype/ 为准」
        for text in (IMPLEMENTER_MD, CODE_REVIEW_MD):
            assert "Scenario 声明" in text
            assert "界面以 prototype/ 为准" in text

    def test_drill_samples_resolve_as_expected(self):
        # 与 run 内双向推演同源的最小判定：声明样例命中开关、对照样例不命中
        declared = ("界面原型（UI 真相源）：specs/order-board/prototype/index.html\n"
                    "界面以 prototype/ 为准")
        undeclared = "## Scenario: 重试次数上限\n- **THEN** 任务标记为 blocked"
        assert "specs/order-board/prototype/" in declared and "界面以 prototype/ 为准" in declared
        assert "prototype/" not in undeclared and "界面以 prototype/ 为准" not in undeclared


class TestJsLiteralAnchorExtraction:
    """React createElement/setAttribute 形态的原型锚（渲染前在 script 字面量里）。"""

    V1_JS = ("<html><body><div id=root></div><script>\n"
             "var header = h('div', { 'data-proto-id': 'panel-header' }, '标题');\n"
             "var table = h('div', { 'data-proto-id': 'panel-table' }, rows);\n"
             "el.setAttribute('data-proto-id', 'panel-footer');\n"
             "</script></body></html>\n")
    V2_JS = ("<html><body><div id=root></div><script>\n"
             "var header = h('div', { 'data-proto-id': 'panel-header' }, '标题');\n"
             "var table = h('div', { 'data-proto-id': 'panel-table' }, rows);\n"
             "var stats = h('div', { 'data-proto-id': 'panel-stats' }, stat);\n"
             "el.setAttribute('data-proto-id', 'panel-footer');\n"
             "</script></body></html>\n")

    def test_extracts_js_literal_anchors(self):
        anchors = anchor_tools.extract_anchors(self.V1_JS)
        assert set(anchors) == {"panel-header", "panel-table", "panel-footer"}
        assert anchors["panel-header"]["source"] == "js-literal"

    def test_js_literal_diff_reports_addition_as_kept(self):
        report = anchor_tools.diff_anchors(self.V1_JS, self.V2_JS)
        assert report["verdict"] == "all-kept"
        assert set(report["added"]) == {"panel-stats"}
        assert report["dropped"] == []

    def test_mixed_static_and_js_anchors_union(self):
        html = ('<div data-proto-id="static-anchor">静态</div>\n'
                "<script>h('div', { 'data-proto-id': 'js-anchor' })</script>")
        anchors = anchor_tools.extract_anchors(html)
        assert set(anchors) == {"static-anchor", "js-anchor"}
        assert anchors["static-anchor"]["text"] == "静态"
        assert "source" not in anchors["static-anchor"]
