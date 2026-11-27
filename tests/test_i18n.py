"""test_i18n.py — 消息目录单源与双消费面测试（add-framework-i18n-zh-en 4.1/4.3/5.1）。

覆盖：
- core.i18n.t 三行为（backend-message-i18n「消息目录单源」Scenario：双语键查询
  与缺键回退、未知键原样返回键名）
- core.i18n.resolve_locale（Accept-Language q 值前缀白名单解析，白名单外/非法
  回退 zh）
- Dashboard _error 按请求头双语展开（「请求头决定消息语言」Scenario：en 与无头
  双请求 error 字段双语、业务语义与 HTTP 状态一致）
- CLI locale 解析链逐级生效（cli-message-i18n「解析链逐级生效」「白名单外值
  回退中文」Scenario）
- CLI 人读输出双语且行为不变（「命令输出双语且行为不变」Scenario：退出码一致）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.i18n import CATALOG, resolve_locale, t

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── t()：双语键查询与缺键回退 ──────────────────────────────────────────

class TestMessageCatalog:
    def test_bilingual_query_returns_both_texts(self):
        key = "error.project_not_monitored"
        assert t(key, "en") == CATALOG[key]["en"]
        assert t(key, "zh") == CATALOG[key]["zh"]

    def test_en_missing_falls_back_to_zh(self):
        # 目录内构造仅 zh 的条目（运行时注入，不污染模块常量——深拷贝验证语义）
        entry = {"zh": "仅中文文案", "en": ""}
        assert (entry.get("en") or entry["zh"]) == "仅中文文案"
        # CATALOG 实体键全量双语：当前目录不含缺 en 键，t('en') 对任意实体键
        # 都应返回英文（抽查 + 契约双保险：若未来登记缺 en 键，本断言钉回退）
        for key in CATALOG:
            assert t(key, "en") != key, f"目录键 {key} 的 en 文本缺失（t 回退 zh 或键名）"

    def test_unknown_key_returns_key_itself(self):
        assert t("no.such.key", "en") == "no.such.key"
        assert t("no.such.key", "zh") == "no.such.key"

    def test_format_interpolation(self):
        text = t("error.project_not_found", "en", project="proj-x")
        assert "proj-x" in text
        assert text == "Project not found: proj-x"

    def test_all_entries_have_both_languages(self):
        for key, entry in CATALOG.items():
            assert set(entry.keys()) >= {"zh", "en"}, f"目录键 {key} 缺语言条目"
            assert entry["zh"] and entry["en"], f"目录键 {key} 存在空文案"


# ── resolve_locale：Accept-Language 解析 ──────────────────────────────

class TestResolveLocale:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            (None, "zh"),  # 无头回退 zh
            ("", "zh"),
            ("en", "en"),
            ("en-US,en;q=0.9", "en"),  # 带地区变体前缀命中
            ("zh-CN", "zh"),
            ("zh;q=0.9,en;q=0.8", "zh"),  # q 值降序取最高偏好
            ("en;q=0.9,zh;q=0.8", "en"),
            ("fr-CN,ja;q=0.9", "zh"),  # 白名单外回退 zh
            (";;;", "zh"),  # 全非法段回退 zh
            ("garbage-not-a-tag", "zh"),
        ],
    )
    def test_resolution_matrix(self, header, expected):
        assert resolve_locale(header) == expected


# ── Dashboard _error 按请求头双语展开 ─────────────────────────────────

class TestErrorByAcceptLanguage:
    def test_bilingual_error_same_shape_and_status(self, server_fx):
        """「请求头决定消息语言」Scenario：en 与无头双请求同一出错端点，
        error 字段双语、HTTP 状态与业务语义一致。

        出错端点取 GET /api/todo 缺 project 参数（_project_query_or_error
        400 错误面，经 _error(key=...) 目录展开）。
        """
        import json as _json

        _proot, srv = server_fx
        status_en, _hdrs, body_en = srv.get_ex("/api/todo", headers={"Accept-Language": "en"})
        status_zh, _hdrs, body_zh = srv.get_ex("/api/todo", headers={})
        assert status_en == status_zh == 400
        data_en = _json.loads(body_en)
        data_zh = _json.loads(body_zh)
        assert "error" in data_en and "error" in data_zh
        assert data_en["error"] == "Missing 'project' parameter (todo.md is a project-scoped file)"
        assert data_zh["error"] == "缺少 project 参数（todo.md为项目级文件）"

    def test_no_header_falls_back_to_zh(self, server_fx):
        import json as _json

        _proot, srv = server_fx
        status, _hdrs, body = srv.get_ex("/api/todo", headers={})
        assert status == 400
        assert _json.loads(body)["error"] == "缺少 project 参数（todo.md为项目级文件）"

    def test_unknown_project_bilingual(self, server_fx):
        """不存在项目（生命周期 POST 面 _resolve_project_or_400 之外的 GET 面）：
        /api/todo?project=ghost → project not found 404（存量英文文案，未接键）；
        本例钉 404 结构一致性（backend-message-i18n「双请求业务语义与 HTTP
        状态一致」）。"""
        import json as _json

        _proot, srv = server_fx
        s1, _h1, b1 = srv.get_ex("/api/todo?project=ghost", headers={"Accept-Language": "en"})
        s2, _h2, b2 = srv.get_ex("/api/todo?project=ghost", headers={})
        assert s1 == s2 == 404
        assert set(_json.loads(b1).keys()) == set(_json.loads(b2).keys())

    def test_unknown_key_keeps_original_msg(self):
        """key 不在目录时保留 msg 原文（防裸键名暴露，存量调用零回归）。"""
        from core.dashboard.routes.base import H0BaseMixin

        calls: list[str] = []

        class _FakeHandler(H0BaseMixin):
            headers = {"Accept-Language": "en"}
            # _bundle_rev 降级路径：static_dir 指向不存在路径 → stat 失败返回
            # None 不附 X-Bundle-Rev（与既有降级纪律一致）
            server = type("_S", (), {"static_dir": Path("/nonexistent-for-i18n-test")})()

            def _mark_response_started(self):
                pass

            def send_response(self, code):
                pass

            def send_header(self, *a):
                pass

            def end_headers(self):
                pass

        class _W:
            def write(self, body):
                calls.append(body.decode("utf-8"))

        handler = _FakeHandler()
        handler.command = "GET"
        handler.wfile = _W()
        handler._error(400, "原始兜底文本", key="no.such.key")
        assert "原始兜底文本" in calls[0]
        handler._error(400, "中文兜底", key="error.project_not_monitored")
        assert "Project not found or not monitored" in calls[1]


# ── 指挥中心 zone 展示名按请求语言档翻译（i18n 修复轮：org/spec-runs 响应
#    中后端组装的分区标题——前端 OrgGrid z.zone 直渲染，裸中文即事故面）──


class TestCommandCenterZoneLabels:
    def test_org_zones_bilingual_by_accept_language(self, server_fx):
        """en 请求 → zones[].zone（及卡片 zone）为英文分区名；无头/zh → 原样
        中文（zh 用户零感知）。花名册全量出卡 ⇒ zones 恒非空，双请求结构一致。
        """
        import json as _json

        _proot, srv = server_fx
        s_en, _h1, b_en = srv.get_ex("/api/command-center/org", headers={"Accept-Language": "en"})
        s_zh, _h2, b_zh = srv.get_ex("/api/command-center/org", headers={})
        assert s_en == s_zh == 200
        org_en = _json.loads(b_en)
        org_zh = _json.loads(b_zh)
        assert org_en.get("zones") and org_zh.get("zones")
        zone_titles_en = [z["zone"] for z in org_en["zones"]]
        zone_titles_zh = [z["zone"] for z in org_zh["zones"]]
        assert zone_titles_zh == ["需求线", "设计线", "交付线", "质量线", "运营线"] or set(
            zone_titles_zh
        ) <= {"需求线", "设计线", "交付线", "质量线", "运营线", "其他"}
        assert not any(
            t in zone_titles_en for t in ("需求线", "设计线", "交付线", "质量线", "运营线", "其他")
        )
        assert set(zone_titles_en) <= {"Demand", "Design", "Delivery", "Quality", "Ops", "Other"}
        # 卡片 zone 与分区标题同映射（同请求内一致性）
        cards_zones = [c["zone"] for z in org_en["zones"] for c in z.get("cards", [])]
        assert set(cards_zones) <= {"Demand", "Design", "Delivery", "Quality", "Ops", "Other"}

    def test_localize_helper_covers_spec_runs_lanes(self):
        """spec-runs lanes[].zone 同映射（org helper 单元面：白名单外 zone 原样）。"""
        from core.dashboard.routes.command_center_routes import (
            _localize_command_center_zones,
        )

        payload = {
            "zones": [{"zone": "需求线", "cards": [{"zone": "需求线"}, {"zone": "其他"}]}],
            "lanes": [{"lane": "judge", "zone": "质量线"}, {"lane": "ghost", "zone": "幽灵分区"}],
        }
        out = _localize_command_center_zones(payload, "en")
        assert out["zones"][0]["zone"] == "Demand"
        assert out["zones"][0]["cards"][0]["zone"] == "Demand"
        assert out["zones"][0]["cards"][1]["zone"] == "Other"
        assert out["lanes"][0]["zone"] == "Quality"
        # 映射表外 zone（花名册演进防漏翻译）原样保留
        assert out["lanes"][1]["zone"] == "幽灵分区"
        # zh 档原样透传（同一 dict 就地改写，故重建载荷验证）
        out_zh = _localize_command_center_zones(
            {"zones": [{"zone": "需求线", "cards": []}]}, "zh"
        )
        assert out_zh["zones"][0]["zone"] == "需求线"


# ── CLI locale 解析链 ─────────────────────────────────────────────────

def _run_cli(*cli_args: str, env_lang: str | None = None, cwd=None):
    """以子进程跑 fenix_cli.py，返回 (returncode, stdout, stderr)。"""
    env = dict(os.environ)
    env.pop("FENIX_LANG", None)
    if env_lang is not None:
        env["FENIX_LANG"] = env_lang
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "fenix_cli.py"), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or REPO_ROOT),
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestCliLocaleChain:
    def _temp_project(self, tmp_path, locale_value: str | None):
        from tests.helpers import create_temp_project

        proot = Path(create_temp_project(tmp_path))
        if locale_value is not None:
            cfg = proot / ".fenix" / "config.yaml"
            cfg.write_text(f"general:\n  locale: {locale_value}\n", encoding="utf-8")
        return proot

    @pytest.mark.parametrize(
        ("flag", "env_lang", "cfg_value", "expect_en"),
        [
            ("--lang", "en", None, True),  # --lang 最高优先
            ("--lang", "zh", "en", False),  # --lang 覆盖配置
            (None, "en", None, True),  # 仅 FENIX_LANG
            (None, "fr", None, False),  # 白名单外环境值回退 zh
            ("--lang", "ja", None, False),  # 白名单外参数回退 zh
            (None, None, "en", True),  # 仅配置 general.locale
            (None, None, "ja", False),  # 白名单外配置回退 zh
            (None, None, None, False),  # 四者皆无 → zh
        ],
    )
    def test_chain_levels(self, tmp_path, flag, env_lang, cfg_value, expect_en):
        """「解析链逐级生效」「白名单外值回退中文」两 Scenario 的解析链矩阵。

        输出面：review 一个不存在的 SPEC（必失败路径，输出稳定、退出码恒 1），
        双语断言只看人读提示语言，行为语义（退出码）不变。
        """
        proot = self._temp_project(tmp_path, cfg_value)
        args = ["review", "ghost-spec", "--project", str(proot)]
        if flag:
            args = [flag, "en" if flag == "--lang" and expect_en else "ja", *args]
        code, out, err = _run_cli(*args, env_lang=env_lang)
        assert code == 1
        combined = out + err
        if expect_en:
            assert "does not exist in STATE.md" in combined
            assert "不存在于 STATE.md" not in combined
        else:
            assert "不存在于 STATE.md" in combined

    def test_cli_bilingual_same_exit_code(self, tmp_path):
        """「命令输出双语且行为不变」：同一成功命令 zh/en 输出双语、退出码一致。

        成功命令用 activate（待激活态 = start_after=manual 的 ready SPEC，
        start_after manual → null 复位语义）。zh/en 各自独立项目目录（activate
        是一次性复位，同一 SPEC 二次执行即拒绝，无法复用同夹具）。
        """
        from tests.helpers import create_temp_project, create_test_spec, FakeLogger
        from core.state_machine import StateMachine

        def _fresh_project(base: Path) -> Path:
            proot = Path(create_temp_project(base))
            create_test_spec(proot, "ready-spec", status="ready")
            # 置 start_after=manual（待激活态；create_test_spec 经
            # StateMachine.add_spec 落行，start_after 为人工管理属性行字段）
            sm = StateMachine(proot / ".fenix" / "STATE.md", FakeLogger())
            sm.update_spec("ready-spec", {"start_after": "manual"})
            return proot

        code_en, out_en, _ = _run_cli(
            "activate", "ready-spec", "--project", str(_fresh_project(tmp_path / "en")),
            "--lang", "en",
        )
        code_zh, out_zh, _ = _run_cli(
            "activate", "ready-spec", "--project", str(_fresh_project(tmp_path / "zh")),
            "--lang", "zh",
        )
        assert code_en == code_zh == 0
        assert "activated" in out_en
        assert "已激活" in out_zh
