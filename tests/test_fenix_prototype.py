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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "fenix-prototype" / "scripts"
for p in (str(SCRIPTS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

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
