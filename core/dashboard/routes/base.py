"""base.py — H0 HTTP 底座（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的 HTTP 底座方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin
（MRO 中资源组排在 BaseHTTPRequestHandler 之前）。

D3 patch 缝隙：
- `MAX_POST_BODY` 常量仍定义在 `core.dashboard.server` 命名空间（测试
  monkeypatch 该命名空间属性）——本模块经 `core.dashboard.server`
  命名空间延迟解析；
- `_GZIP_EXT`/`_GZIP_MIN` 类常量随本 mixin 迁移（无外部 patch 依赖）。

H1 路由分派链（`_handle_api`/`_handle_api_post`/`_handle_api_delete`）
随各资源子路由摘出后收敛为表驱动（design D1 表 C H1，task 4.5）——
本模块即承载 H0 HTTP 底座**与**该 H1 表驱动分派链（三张路由表 + 全部适配
函数），二者同处本文件。
"""

from __future__ import annotations

import gzip
import json
import logging
import re as _re
import urllib.parse

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.base")


# ── H1 路由分派链（design D1 表 C H1，task 4.5）──────────────────────
# 表驱动 + 按资源委派。路由表条目含可扫描 pattern 字面量（design D4
# task 4.6 gen-route-map 扫描源），按注册顺序匹配。精确路由优先于
# 前缀/后缀（表序即优先级），MUST NOT 让裸后缀 matcher 前置精确 matcher。
# POST 链 4 个裸 endswith（/start /stop /restart /install-hosting）
# 是方法**最后 4 个分支**，须排在 /api/project/describe 之后（保留陷阱）。
# DELETE 的 /api/projects/<name> 在独立方法中。
#
# 条目结构: (kind, pattern, handler)  —— 3 元组（code-review item 46526caaf62f：
# 旧注释写作 4 元组含 json_flag，但 _dispatch_table 实际按 3 值解包，照旧注释
# 写 4 元组会在请求期 ValueError: too many values to unpack）
#   kind   ∈ {"exact", "regex", "suffix"}
#   pattern: 路由字面量（精确匹配串 / 正则 pattern / 后缀串）
#   handler: handler 函数引用（self, path, query, m） → None（handler 自写响应）
#
# 参数化路径用 regex capture group（/api/specs/<spec>、/api/runs/<id>、
# /api/alerts/<id>/handled、/api/projects/<name>）。


# ── GET 路由适配函数 ──────────────────────────────────────────────────

# ── ETag 签名函数（add-dashboard-paging-and-etag 1.2/1.3）────────────
# 约定：(s, q, m) → str | None。None = 该请求不参与协商（数据源无法廉价/
# 完整签名，或项目缺失——其响应本就是错误体），适配层既不协商也不挂 ETag
# 头（宁缺 304 不假 304）。304 短路发生在 route handler 调用之前（兼容
# _api_config_get 等自含响应 handler），见 _dispatch_table。
#
# ?project=X 变体的签名只依赖 X 的数据源（spec 契约）；跨项目聚合端点的
# 签名叠加 registry 项目清单（聚合集合本身是响应形状的一部分）。

def _resolve_project_for_sig(s, query):
    """签名函数共用的只读项目解析：缺失/未知/不存在项目返回 None。

    不复用 _project_or_user_scope / _project_from_query：那些助手在失败分支
    自写 404 响应，签名阶段绝不能写响应（协商可能命中 304 短路）。
    """
    name = query.get("project", [None])[0]
    if not name:
        return None
    project = s.server.project_by_name(name)
    if project is None or not project.get("exists"):
        return None
    return project


def _sig_overview(s, q, m):
    from pathlib import Path

    from core.dashboard import data as dashboard_data
    from core.dashboard.data import signature as _sig

    parts = []
    for p in s.server.projects():
        # 项目清单本身（name/path/discovered/fixture 标记）参与哈希：
        # registry 列表变化必翻签名（聚合集合是响应形状的一部分）
        parts.append(
            (p.get("name"), p.get("path"), p.get("discovered"), p.get("fixture"))
        )
        if not p.get("exists"):
            continue
        proot = Path(p["path"])
        parts.append(_sig.project_signature(proot))
        # daemon/托管态探针的 TTL memo 值直接参与哈希（宁多勿漏）：memo 翻转
        # 必须翻转 ETag，否则概览 daemon/hosting 列假 304
        parts.append(dashboard_data.daemon_health(proot))
        parts.append(dashboard_data.hosting_state(proot))
    parts.append(_sig.registry_signature(s.server.registry))
    return _sig.combine(parts)


def _sig_specs(s, q, m):
    from pathlib import Path

    from core.dashboard.data import signature as _sig

    project = _resolve_project_for_sig(s, q)
    if project is None:
        return None
    return s.server.summary_index.invalidation_signature(Path(project["path"]))


def _sig_spec_detail(s, q, m):
    from pathlib import Path

    from core.dashboard import data as dashboard_data
    from core.dashboard.data import signature as _sig

    project = _resolve_project_for_sig(s, q)
    if project is None:
        return None
    spec = urllib.parse.unquote(m.group(1))
    proot = Path(project["path"])
    # spec 不存在（活跃 STATE、归档清单、归档目录均无命中）→ 响应恒为
    # 错误体，不参与协商（错误响应不挂 ETag）
    entry = s.server.summary_index.state_snapshot(proot).get(spec)
    if entry is None:
        entry = dashboard_data.parse_archived_state(proot).get(spec)
    if entry is None and dashboard_data.resolve_spec_dir(proot, spec) is None:
        return None
    return _sig.spec_detail_signature(proot, spec)


def _sig_alerts(s, q, m):
    from pathlib import Path

    from core.dashboard.data import signature as _sig

    project = _resolve_project_for_sig(s, q)
    if project is not None:
        return _sig.admin_alerts_signature(Path(project["path"]))
    # 跨项目聚合：与 _api_alerts 同口径跳过 fixture/不存在项目，聚合集合
    #（registry）参与哈希
    parts = [_sig.registry_signature(s.server.registry)]
    for p in s.server.projects():
        if p.get("fixture") or not p.get("exists"):
            continue
        parts.append(_sig.admin_alerts_signature(Path(p["path"])))
    return _sig.combine(parts)


def _sig_admin_activities(s, q, m):
    # ?archived=1 数据源切换为归档旁路文件（admin_alerts_archive.jsonl，见
    # _api_admin_activities），签名须与响应数据源对齐（code-review item
    # 3da93afce0c9）：归档文件独立变化（活跃写回失败、人工/外部改动归档）
    # 时 ETag 必须翻转，否则携带 If-None-Match 的归档页假 304。archived
    # 判定与 _api_admin_activities 同一字面口径，两处不得分叉。
    if (q.get("archived", [None])[0] or "").lower() in ("1", "true"):
        from pathlib import Path

        from core.dashboard.data import signature as _sig

        project = _resolve_project_for_sig(s, q)
        if project is not None:
            return _sig.admin_alerts_archive_signature(Path(project["path"]))
        # 跨项目聚合：与 _sig_alerts 聚合分支同口径跳过 fixture/不存在项目，
        # 聚合集合（registry）参与哈希
        parts = [_sig.registry_signature(s.server.registry)]
        for p in s.server.projects():
            if p.get("fixture") or not p.get("exists"):
                continue
            parts.append(_sig.admin_alerts_archive_signature(Path(p["path"])))
        return _sig.combine(parts)
    # 活跃路径：数据源与 /api/alerts 同一文件（admin_alerts.json）；?spec=
    # 过滤发生在读取之后，不改变签名源
    return _sig_alerts(s, q, m)


def _sig_config(s, q, m):
    from core.dashboard.data import signature as _sig

    project = _resolve_project_for_sig(s, q)
    if project is None:
        # 缺 project 参数 = 合法用户级作用域（_api_config_get 契约），签名
        # 只依赖用户级 config.yaml
        return _sig.config_signature(None)
    return _sig.config_signature(project["path"])


def _if_none_match_hit(header_value: str, etag: str) -> bool:
    """RFC 7232 If-None-Match 比对：`*` 命中任意；列表逐项比对；弱化符 W/ 剥离。"""
    for candidate in header_value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == etag:
            return True
    return False


def _get_projects(s, p, q, m):
    s._json(s._api_projects())

def _get_overview(s, p, q, m):
    s._json(s._api_overview())

def _get_specs(s, p, q, m):
    s._json(s._api_specs(q))

def _get_spec_detail(s, p, q, m):
    spec = urllib.parse.unquote(m.group(1))
    s._json(s._api_spec_detail(spec, q))

def _get_runs_watch(s, p, q, m):
    rest = urllib.parse.unquote(m.group(1))
    if rest.endswith("/watch"):
        s._json(s._api_run_watch(rest[: -len("/watch")], q, watch=True))
    else:
        s._json(s._api_run(rest, q))

def _get_events(s, p, q, m):
    s._json(s._api_events(q))

def _get_alerts(s, p, q, m):
    s._json(s._api_alerts(q))

def _get_admin_activities(s, p, q, m):
    s._json(s._api_admin_activities(q))

def _get_config(s, p, q, m):
    # _api_config_get 是自含响应 handler（code-review item 89d191770258）：未知
    # 项目自写 _error（404）、成功路径自写 _json——不得再包 _json 双重写响应
    # （keep-alive 下残留第二响应 200+null 污染下一请求，同 _get_prompts 注记）
    s._api_config_get(q)

def _get_hooks_audit(s, p, q, m):
    s._json(s._api_hooks_audit(q))

def _get_prompts(s, p, q, m):
    # _api_prompts_get 是自含响应 handler：读失败自写 _error（可读 500）——
    # 不得再包 _json 双重写响应（keep-alive 下残留第二响应 200+null 污染
    # 下一请求，同 _get_spec_doc 注记）
    s._api_prompts_get(q)

def _get_todo(s, p, q, m):
    s._api_todo_get(q)

def _get_verify_yaml(s, p, q, m):
    s._api_verify_yaml_get(q)

def _get_verify_yaml_template(s, p, q, m):
    s._api_verify_yaml_template()

def _get_spec_doc(s, p, q, m):
    # _api_spec_doc 是自含响应 handler：成功写 _json、错误分支自写 _error——
    # 不得再包 _json 双重写响应（keep-alive 下残留第二响应 200+null 污染
    # 下一请求，BUG-01 修复合入）
    s._api_spec_doc(q)

def _get_help_docs(s, p, q, m):
    s._json(s._api_help_docs())

def _get_help_doc(s, p, q, m):
    s._api_help_doc(q)

def _get_evolution_items(s, p, q, m):
    s._api_evolution_items(q)

def _get_evolution_analysis(s, p, q, m):
    s._api_evolution_analysis(q)

def _get_evolution_draft(s, p, q, m):
    s._api_evolution_draft(q)

def _get_session(s, p, q, m):
    s._api_session_get(q)

# add-session-composer 1.2/1.3：会话补全数据源只读端点
def _get_session_files(s, p, q, m):
    s._api_session_files(q)

def _get_session_commands(s, p, q, m):
    s._api_session_commands(q)

def _get_quality_ocr_status(s, p, q, m):
    s._json(s._api_quality_ocr_status_get(q))

def _get_code_review_items(s, p, q, m):
    s._api_code_review_items(q)

def _get_code_review_progress(s, p, q, m):
    s._api_code_review_progress(q)

def _get_code_review_fix_progress(s, p, q, m):
    s._api_code_review_fix_progress(q)

def _get_code_review_fix_run_result(s, p, q, m):
    s._api_code_review_fix_run_result(q)

def _get_code_review_run_result(s, p, q, m):
    s._api_code_review_run_result(q)

# ── regression（add-test-regression-tab）──────────────────────────

def _get_regression_result(s, p, q, m):
    s._api_regression_result(q)

def _get_regression_config(s, p, q, m):
    s._api_regression_config(q)

# 回归自动修复判定结果只读（add-regression-auto-fix，GET，无副作用）
def _get_regression_fix_result(s, p, q, m):
    s._api_regression_fix_result(q)

# ── architecture（add-project-architecture-tab）──────────────────

def _get_architecture_status(s, p, q, m):
    s._api_architecture_status(q)

# diagram 下发是自含响应 handler：ready 走 _send_file（自写 200），未生成
# 自写 _json(404)——不得再包 _json 双重写响应（keep-alive 下残留第二响应
# 200+null 污染下一请求，同 _get_config 注记）
def _get_architecture_diagram(s, p, q, m):
    s._api_architecture_diagram(q)

# ── knowledge（add-knowledge-atlas）──────────────────────────────

def _get_knowledge_index(s, p, q, m):
    s._api_knowledge_index(q)

def _get_knowledge_file(s, p, q, m):
    s._api_knowledge_file(q)


# ── POST 路由适配函数 ─────────────────────────────────────────────────

def _post_config(s, p, q, m):
    s._api_config_post(q)

def _post_config_sync(s, p, q, m):
    s._api_config_sync_from_user(q)

def _post_config_llm_health_check(s, p, q, m):
    s._api_config_llm_health_check_post(q)

def _post_quality_ocr_install(s, p, q, m):
    s._api_quality_ocr_install_post(q)

def _post_prompts(s, p, q, m):
    s._api_prompts_post(q)

def _post_todo(s, p, q, m):
    s._api_todo_post(q)

def _post_verify_yaml(s, p, q, m):
    s._api_verify_yaml_post(q)

def _post_verify_yaml_autodraft(s, p, q, m):
    s._api_verify_yaml_autodraft_post(q)

def _post_spec_error_clear(s, p, q, m):
    s._api_spec_error_clear(q)

def _post_spec_priority(s, p, q, m):
    s._api_spec_priority(q)

def _post_spec_delete(s, p, q, m):
    s._api_spec_delete(q)

def _post_spec_admin_invoke(s, p, q, m):
    s._api_spec_admin_invoke(q)

def _post_run_cancel(s, p, q, m):
    s._api_run_cancel(q)

def _post_spec_freeze(s, p, q, m):
    s._api_spec_freeze(q)

def _post_spec_unfreeze(s, p, q, m):
    s._api_spec_unfreeze(q)

def _post_spec_start_after(s, p, q, m):
    s._api_spec_start_after(q)

def _post_spec_activate(s, p, q, m):
    s._api_spec_activate(q)

def _post_spec_resume(s, p, q, m):
    s._api_spec_resume(q)

def _post_spec_freeze_config(s, p, q, m):
    s._api_spec_freeze_config(q)

def _post_spec_budget(s, p, q, m):
    s._api_spec_budget(q)

def _post_spec_archive(s, p, q, m):
    s._api_spec_archive(q)

def _post_spec_promote(s, p, q, m):
    s._api_spec_promote(q)

def _post_spec_task_reflow(s, p, q, m):
    s._api_spec_task_reflow(q)

def _post_spec_re_review(s, p, q, m):
    s._api_spec_re_review(q)

def _post_spec_approve_push(s, p, q, m):
    s._api_spec_approve_push(q)

def _post_alerts_clear(s, p, q, m):
    s._api_alerts_clear()

def _post_evolution_accept(s, p, q, m):
    s._api_evolution_accept()

def _post_evolution_reject(s, p, q, m):
    s._api_evolution_reject()

def _post_evolution_delete(s, p, q, m):
    s._api_evolution_delete()

def _post_evolution_clear_todo(s, p, q, m):
    s._api_evolution_clear_todo()

def _post_alert_handled(s, p, q, m):
    alert_id = urllib.parse.unquote(m.group(1))
    s._api_alert_handled(alert_id, q)

def _post_alert_resolve(s, p, q, m):
    s._api_alert_resolve(q)

def _post_run_watch(s, p, q, m):
    # 路由 pattern ^/api/runs/(.+)/watch$ 已消费 /watch 后缀，group(1) 即 run
    # id 本体——不得再剥（code-review item 9d6e8392b667：照搬 GET 适配器的
    # 二次剥离会把 run id 截断，SSE 增量订阅静默失效）；GET 适配器正则
    # ^/api/runs/(.+)$ 的 group(1) 含后缀，那里的剥离才是必要的
    rest = urllib.parse.unquote(m.group(1))
    s._json(s._api_run_watch(rest, q, watch=True))

def _post_project_describe(s, p, q, m):
    s._api_project_describe(q)

def _post_code_review_run(s, p, q, m):
    s._api_code_review_run(q)

def _post_code_review_fix_run(s, p, q, m):
    s._api_code_review_fix_run(q)

def _post_regression_run(s, p, q, m):
    s._api_regression_run(q)

def _post_regression_autodraft(s, p, q, m):
    s._api_regression_autodraft_post(q)

# 回归自动修复触发信号（add-regression-auto-fix，写文件信号，daemon 消费）
def _post_regression_fix(s, p, q, m):
    s._api_regression_fix(q)

# architecture：受理触发生成（add-project-architecture-tab，后台线程，
# 不在 HTTP 线程内同步等待）
def _post_architecture_refresh(s, p, q, m):
    s._api_architecture_refresh(q)

def _post_code_review_generate_spec(s, p, q, m):
    s._api_code_review_generate_spec(q)

def _post_code_review_items_status(s, p, q, m):
    s._api_code_review_items_status(q)

def _post_session_start(s, p, q, m):
    s._api_session_start(q)

def _post_session_send(s, p, q, m):
    s._api_session_send(q)

def _post_session_stop(s, p, q, m):
    s._api_session_stop(q)

def _post_session_watch(s, p, q, m):
    s._api_session_watch(q, watch=True)

# 4 个裸 endswith —— 排在 /api/project/describe 之后（保留顺序陷阱）

def _post_start(s, p, q, m):
    s._api_project_lifecycle("start", p, q)

def _post_stop(s, p, q, m):
    s._api_project_lifecycle("stop", p, q)

def _post_restart(s, p, q, m):
    s._api_project_lifecycle("restart", p, q)

def _post_install_hosting(s, p, q, m):
    s._api_project_lifecycle("install-hosting", p, q)


# ── DELETE 路由适配函数 ───────────────────────────────────────────────

def _del_run_watch(s, p, q, m):
    # 同 _post_run_watch（code-review item 9d6e8392b667）：group(1) 不含
    # /watch 后缀，二次剥离会把 run id 截断致注销错 id
    rest = urllib.parse.unquote(m.group(1))
    s._json(s._api_run_watch(rest, q, watch=False))

def _del_session_watch(s, p, q, m):
    s._api_session_watch(q, watch=False)

def _del_project(s, p, q, m):
    s._api_project_delete(p, q)


# GET 路由表条目：3 元组 (kind, pattern, handler)，或 4 元组第 4 位挂 ETag
# 签名函数（add-dashboard-paging-and-etag 1.2：GET 读端点注册表支持挂签名
# 函数）。_dispatch_table 按 len 容错解包，3 元组条目零改动仍有效。
_API_GET_ROUTES = [
    # 精确路由（原 _handle_api if/elif 顺序保持优先级）
    ("exact", "/api/projects",         _get_projects),
    ("exact", "/api/overview",         _get_overview, _sig_overview),
    ("exact", "/api/specs",            _get_specs, _sig_specs),
    # 参数化前缀（regex）
    ("regex", r"^/api/specs/([^/]+)$", _get_spec_detail, _sig_spec_detail),
    ("regex", r"^/api/runs/(.+)$",     _get_runs_watch),
    ("exact", "/api/events",           _get_events),
    ("exact", "/api/alerts",           _get_alerts, _sig_alerts),
    ("exact", "/api/admin-activities", _get_admin_activities, _sig_admin_activities),
    # config 是自含响应 handler（_api_config_get 自写 _json/_error）——其 304
    # 短路与 200 的 ETag 头同样经适配层（_dispatch_table 短路在 handler 调用
    # 之前；_json 附带 _pending_etag），无需改动 handler 本体
    ("exact", "/api/config",           _get_config, _sig_config),
    ("exact", "/api/hooks/audit",      _get_hooks_audit),
    ("exact", "/api/prompts",          _get_prompts),
    ("exact", "/api/todo",             _get_todo),
    ("exact", "/api/verify-yaml",      _get_verify_yaml),
    ("exact", "/api/verify-yaml-template", _get_verify_yaml_template),
    ("exact", "/api/spec-doc",         _get_spec_doc),
    ("exact", "/api/help/docs",        _get_help_docs),
    ("exact", "/api/help/doc",         _get_help_doc),
    ("exact", "/api/evolution/items",  _get_evolution_items),
    ("exact", "/api/evolution/analysis", _get_evolution_analysis),
    ("exact", "/api/evolution/draft",  _get_evolution_draft),
    ("exact", "/api/session",         _get_session),
    # add-session-composer 1.2/1.3：会话补全数据源（exact，排在本组末尾不动 watch regex 先例）
    ("exact", "/api/session/files",    _get_session_files),
    ("exact", "/api/session/commands", _get_session_commands),
    # 质量页签：open-code-review 安装状态（GET，无副作用）
    ("exact", "/api/quality/ocr-status", _get_quality_ocr_status),
    # code-review（add-code-review-agent-and-quality-tab）：台账与进度（GET，无副作用）
    ("exact", "/api/code-review/items", _get_code_review_items),
    ("exact", "/api/code-review/progress", _get_code_review_progress),
    # code-review 自动修复进度（add-code-review-auto-fix，GET，无副作用）
    ("exact", "/api/code-review/fix-progress", _get_code_review_fix_progress),
    # 手动「立即自动修复」判定结果只读（add-code-fix-manual-trigger，GET，无副作用）
    ("exact", "/api/code-review/fix-run-result", _get_code_review_fix_run_result),
    # 手动触发审查的受理判定结果只读（add-code-review-trigger-ack，GET，无副作用）
    ("exact", "/api/code-review/run-result", _get_code_review_run_result),
    # regression（add-test-regression-tab）：最近一次回归快照（GET，无副作用）
    ("exact", "/api/regression/result", _get_regression_result),
    # regression：verify.yaml regression 段配置状态（GET，无副作用）
    ("exact", "/api/regression/config", _get_regression_config),
    # regression 自动修复判定结果只读（add-regression-auto-fix，GET，无副作用）
    ("exact", "/api/regression/fix-result", _get_regression_fix_result),
    # architecture（add-project-architecture-tab）：生成状态（GET，无副作用）
    ("exact", "/api/architecture/status", _get_architecture_status),
    # architecture：diagram.html 下发（自含响应 handler，未生成回 404 结构化错误）
    ("exact", "/api/architecture/diagram", _get_architecture_diagram),
    # knowledge（add-knowledge-atlas）：真相源只读端点（GET，无副作用；
    # graph 下发端点已随 graphify 功能取消下线）
    ("exact", "/api/knowledge/index", _get_knowledge_index),
    ("exact", "/api/knowledge/file",   _get_knowledge_file),
]

_API_POST_ROUTES = [
    # 精确路由（原顺序保持）
    ("exact", "/api/config",              _post_config),
    ("exact", "/api/config/sync-from-user", _post_config_sync),
    # LLM Provider 健康检测（add-provider-health-check）：daemon 代理探测
    # {baseurl}/v1/messages（纯只读、无副作用、不落盘密钥；探测失败恒 200 业务数据）
    ("exact", "/api/config/llm-health-check", _post_config_llm_health_check),
    # 质量页签：一键安装 open-code-review（POST，同步执行 npm install -g）
    ("exact", "/api/quality/ocr-install", _post_quality_ocr_install),
    ("exact", "/api/prompts",             _post_prompts),
    ("exact", "/api/todo",                _post_todo),
    ("exact", "/api/verify-yaml",         _post_verify_yaml),
    ("exact", "/api/verify-yaml-autodraft", _post_verify_yaml_autodraft),
    ("exact", "/api/spec-error-clear",    _post_spec_error_clear),
    ("exact", "/api/spec-priority",       _post_spec_priority),
    ("exact", "/api/spec-delete",         _post_spec_delete),
    ("exact", "/api/spec-admin-invoke",   _post_spec_admin_invoke),
    ("exact", "/api/run-cancel",          _post_run_cancel),
    ("exact", "/api/spec-freeze",         _post_spec_freeze),
    ("exact", "/api/spec-unfreeze",       _post_spec_unfreeze),
    ("exact", "/api/spec-start-after",    _post_spec_start_after),
    ("exact", "/api/spec-activate",        _post_spec_activate),
    ("exact", "/api/spec-resume",         _post_spec_resume),
    ("exact", "/api/spec-freeze-config",  _post_spec_freeze_config),
    ("exact", "/api/spec-budget",         _post_spec_budget),
    ("exact", "/api/spec-archive",        _post_spec_archive),
    ("exact", "/api/spec-promote",        _post_spec_promote),
    ("exact", "/api/spec-task-reflow",    _post_spec_task_reflow),
    ("exact", "/api/spec-re-review",      _post_spec_re_review),
    ("exact", "/api/spec-approve-push",   _post_spec_approve_push),
    ("exact", "/api/alerts/clear",        _post_alerts_clear),
    # add-human-adjudication-choices 4.1：告警内嵌下拉「选完即闭环」裁决端点
    ("exact", "/api/alert-resolve",       _post_alert_resolve),
    ("exact", "/api/evolution/accept",    _post_evolution_accept),
    ("exact", "/api/evolution/reject",    _post_evolution_reject),
    ("exact", "/api/evolution/delete",    _post_evolution_delete),
    ("exact", "/api/evolution/clear-todo", _post_evolution_clear_todo),
    # 参数化 regex（/handled 和 /watch）
    ("regex", r"^/api/alerts/([^/]+)/handled$", _post_alert_handled),
    ("regex", r"^/api/runs/(.+)/watch$",        _post_run_watch),
    # /api/project/describe（精确，排在 endswith 之前）
    ("exact", "/api/project/describe",   _post_project_describe),
    # code-review（add-code-review-agent-and-quality-tab）：手动触发 / generate-spec / 状态流转
    ("exact", "/api/code-review/run", _post_code_review_run),
    # 手动「立即自动修复」信号（add-code-fix-manual-trigger，写文件信号，daemon 消费）
    ("exact", "/api/code-review/fix-run", _post_code_review_fix_run),
    ("exact", "/api/code-review/generate-spec", _post_code_review_generate_spec),
    ("exact", "/api/code-review/items/status", _post_code_review_items_status),
    # regression（add-test-regression-tab）：手动触发（写文件信号，daemon 消费）
    ("exact", "/api/regression/run", _post_regression_run),
    # regression：AI 补写 regression 段（写 AdminStore 信号，巡检唤起 Administrator）
    ("exact", "/api/regression/autodraft", _post_regression_autodraft),
    # regression 自动修复触发信号（add-regression-auto-fix，写文件信号，daemon 消费）
    ("exact", "/api/regression/fix", _post_regression_fix),
    # architecture：受理触发生成（add-project-architecture-tab，后台线程，
    # 不在 HTTP 线程内同步等待）
    ("exact", "/api/architecture/refresh", _post_architecture_refresh),
    # session 路由（精确，排在裸 endswith 之前，防 /start /stop 误匹配）
    ("exact", "/api/session/start",      _post_session_start),
    ("exact", "/api/session/send",       _post_session_send),
    ("exact", "/api/session/stop",       _post_session_stop),
    ("regex", "^/api/session/watch$",   _post_session_watch),
    # 裸 endswith（4 个，MUST 排最后——保留顺序陷阱）
    ("suffix", "/start",        _post_start),
    ("suffix", "/stop",         _post_stop),
    ("suffix", "/restart",      _post_restart),
    ("suffix", "/install-hosting", _post_install_hosting),
]

_API_DELETE_ROUTES = [
    ("regex",  r"^/api/runs/(.+)/watch$", _del_run_watch),
    ("regex",  "^/api/session/watch$",   _del_session_watch),
    ("regex",  r"^/api/projects/([^/]+)$", _del_project),
]


def _route_match(kind, pattern, path):
    """路由匹配：exact/regex 返回 Match 对象，suffix 返回 True（简单匹配标识），无匹配返回 None。"""
    if kind == "exact":
        return _re.fullmatch(_re.escape(pattern), path)
    elif kind == "regex":
        return _re.fullmatch(pattern, path)
    elif kind == "suffix":
        if path.endswith(pattern):
            return True  # 简单匹配标识
    return None


class H0BaseMixin:
    """H0 HTTP 底座（design D1 表 C H0）。"""

    # 文本类才值得 gzip（图片/字体本身已二进制压缩）；svg mimetypes 给
    # image/*，故按后缀白名单而非 ctype 判断
    _GZIP_EXT = {".js", ".css", ".html", ".htm", ".svg", ".json", ".md", ".txt", ".map"}
    _GZIP_MIN = 860  # 小于阈值的响应不值得压缩

    # ── 服务端分页参数解析单源（add-dashboard-paging-and-etag 2.1/2.2）──

    @staticmethod
    def _parse_page_params(page_raw, size_raw, default_size: int, max_size: int):
        """解析 page/page_size 查询参数，返回 (page | None, page_size)。

        - page **缺席** → page=None：全量兼容路径（响应不带任何分页字段，
          与改造前逐字段一致）。
        - page 在场但非法（非整数/<1）→ 回退 1（分页响应形态保留）。
        - page_size 缺席 → default_size；非法（非整数/<1）→ 回退 default_size；
          超过 max_size → 截到 max_size。
        """
        default_size = min(default_size, max_size)
        page = None
        if page_raw is not None:
            try:
                page = int(str(page_raw).strip())
            except (TypeError, ValueError):
                page = 1
            if page < 1:
                page = 1
        size = default_size
        if size_raw is not None:
            try:
                size = int(str(size_raw).strip())
            except (TypeError, ValueError):
                size = default_size
            else:
                if size < 1:
                    size = default_size
                elif size > max_size:
                    size = max_size
        return page, size

    def _mark_response_started(self):
        """标记本请求已开始写响应（供 _handle 的 500 兜底判断是否可再写）。

        code-review item 9de3d3095e85：`_handle_inner` 的裸 `except Exception`
        会对**响应已开始**的 socket 再写第二个响应（如 body 写中途 BrokenPipe/
        OSError），在 keep-alive 连接上发出第二条状态行/体，污染下一次交换。
        `_json`/`_error`/`_send_file` 响应前调用本方法登记。
        """
        self._response_started = True

    # ── H1 表驱动路由分派（design D1 表 C H1，task 4.5）────────────────

    def _dispatch_table(self, table, path, query):
        """按表遍历匹配并委派（按注册顺序，精确优先）。

        条目容错解包 3/4 元组（第 4 位为 ETag 签名函数，见 _API_GET_ROUTES
        注记）。签名函数在场时先做条件请求协商（add-dashboard-paging-and-etag
        1.2）：If-None-Match 命中 → 在 route handler 调用**之前**写 304 短路
        （兼容 _api_config_get 等自含响应 handler——等返回值再拦截对它们无效）；
        未命中 → 200 全量路径，ETag 经 _pending_etag 由 _json 附带（仅 200
        成功响应携带，错误响应不挂）。
        """
        for entry in table:
            m = _route_match(entry[0], entry[1], path)
            if m is None:
                continue
            handler = entry[2]
            sig_fn = entry[3] if len(entry) > 3 else None
            etag = self._route_etag(sig_fn, query, m) if sig_fn is not None else None
            if etag is not None and _if_none_match_hit(
                self.headers.get("If-None-Match", ""), etag
            ):
                self._write_304(etag)
                return
            # keep-alive 下 handler 实例跨请求复用：_pending_etag 必须 finally
            # 清零，防泄漏到同连接下一请求
            self._pending_etag = etag
            try:
                handler(self, path, query, m)
            finally:
                self._pending_etag = None
            return
        self._error(404, "Not Found")

    def _route_etag(self, sig_fn, query, m) -> str | None:
        """计算路由 ETag；签名函数缺失/抛错/返回空 → None（降级无条件 200 路径）。

        签名失败按「宁缺 304 不假 304」降级：返回 None 则不协商、不挂 ETag 头，
        行为与改造前完全一致。异常经 logger.exception 服务端留痕。
        """
        try:
            etag = sig_fn(self, query, m)
        except Exception:  # noqa: BLE001
            logger.exception("ETag 签名计算失败，本请求降级为无条件 200 路径")
            return None
        if not etag:
            return None
        return f'"{etag}"'

    def _write_304(self, etag: str) -> None:
        """写 304 空体响应（与 _json 同一写出纪律，keep-alive 不污染）。

        304 本身无体且按 RFC 7230 §3.3.3 由头结束界定分帧（不写 wfile，与
        _json 的 HEAD 分支同口径），不发 Content-Length：规范要求其值必须
        等于对应 200 将发送的体长，恒写 0 属协议语义偏差
        （code-review item 06228e8ac652）。Cache-Control 与 _json 一致
        （no-cache：ETag 协商是唯一复用通道，不引入启发式缓存）。
        """
        self._mark_response_started()
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _handle_api(self, path: str, query: dict):
        self._dispatch_table(_API_GET_ROUTES, path, query)

    def _handle_api_post(self, path: str, query: dict):
        self._dispatch_table(_API_POST_ROUTES, path, query)

    def _handle_api_delete(self, path: str, query: dict):
        self._dispatch_table(_API_DELETE_ROUTES, path, query)

    # ── H0 HTTP 底座（原 H0 方法，method body zero-move）─────────────────

    def do_GET(self):
        self._handle(method="GET")

    def do_HEAD(self):
        self._handle(method="HEAD")

    def do_POST(self):
        self._handle(method="POST")

    def do_DELETE(self):
        self._handle(method="DELETE")

    def log_message(self, fmt, *args):
        # 静默访问日志，避免污染运行终端
        pass

    def _handle(self, method: str = "GET"):
        # 拒绝 Transfer-Encoding（chunked）请求体：本模块读体与排空只认
        # Content-Length，分块体既不会被 _read_json_body 消费也不会被排空，
        # 残留的分块字节会在 keep-alive 连接上被下一请求当请求行解析
        # （BUG-01 同类失步）。置 close_connection 回 411，让分块体随连接
        # 关闭作废（与 413 分支处置口径对齐）。
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self._error(411, "Length Required")
            return
        # 线程上限（dashboard-connection-limit D6）
        if not self.server._try_acquire_request_slot():
            # 快速拒绝路径同样处于「新请求」边界，先复位每请求状态再判断排空
            # （code-review item c0cf0404d004）：_request_body_consumed 的常规
            # 复位在 _handle_inner 开头，而本分支在其之前执行——keep-alive 第二
            # 个请求时计数器仍持上一请求的已消费字节数，若该值 ≥ 本请求
            # Content-Length，_drain_remaining_request_body 算得 remaining≤0
            # 跳过读取，重新引入正文失步（残留字节被当下一请求解析）。
            self._request_body_consumed = 0
            # 超大声明 Content-Length 比照 413 处置（code-review item
            # 4f09f474f524，同 _read_json_body 413 分支的无界 read 防御）：
            # 本分支 _request_body_consumed 恒为 0，remaining＝整个声明长度，
            # 对攻击者声明的超大 Content-Length（实际不发数据）盲排会阻塞
            # worker 线程至 socket 超时。超限时置 close_connection=True 跳过
            # 排空（drain 对该标记 no-op），连接关闭后残留作废；仅对合理
            # 大小的残留排空。
            try:
                _declared = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                _declared = 0
                # Content-Length 不可解析时 _drain_remaining_request_body 里同一处
                # int() 同样失败得 remaining=0 而跳过排空，客户端已发出的 body 字节
                # 会残留 keep-alive 连接被下一请求当请求行（BUG-01 同类失步）。
                # 比照 _read_json_body（code-review item 8beb499acc56）置
                # close_connection=True，让残留字节随连接关闭作废。
                self.close_connection = True
            from core.dashboard import server as _server_mod

            if _declared > getattr(_server_mod, "MAX_POST_BODY", 256 * 1024):
                self.close_connection = True
            # 快速拒绝前 MUST 排空请求体（code-review item 265e22d75797）：HTTP/1.1
            # keep-alive 下未读的 body 字节会被当作下一请求的请求行解析——正是
            # POST/DELETE 分支下方小心规避的 BUG-01 失步类。
            self._drain_remaining_request_body()
            self._error(503, "server busy")
            return
        try:
            self._handle_inner(method)
        finally:
            self.server._release_request_slot()

    def _handle_inner(self, method: str = "GET"):
        # 每请求复位 body 消费计数（BUG-01 排空判定基准；keep-alive 下同连接多请求）
        self._request_body_consumed = 0
        # 每请求复位响应已开始标记（code-review item 970c8c0c63b5）：handler
        # 实例在 keep-alive 下跨请求复用，_response_started 若不复位，首个
        # 请求置 True 后后续每个请求的 500 兜底都看到过时 True 而静默跳过
        # ——在写任何字节前失败的请求收不到任何响应。
        self._response_started = False
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path.startswith("/api/"):
                if path == "/api/stream":
                    if method == "GET":
                        self._handle_sse()
                        return
                    # 排空 body 后再回 405（code-review item 265e22d75797）
                    self._drain_remaining_request_body()
                    self._error(405, "Method Not Allowed")
                    return
                if method not in ("GET", "HEAD", "POST", "DELETE"):
                    # 排空 body 后再回 405（code-review item aace0e7e91b6）：
                    # 非 GET/HEAD/POST/DELETE 方法不落入 GET 表分派，与静态
                    # 资源分支的 405 口径对齐。
                    self._drain_remaining_request_body()
                    self._error(405, "Method Not Allowed")
                    return
                if method == "POST":
                    try:
                        self._handle_api_post(path, query)
                    finally:
                        # handler 错误路径提前返回未消费 body 时排空残留字节，
                        # 防 keep-alive 复用下残留体被下一请求当请求行（BUG-01）
                        self._drain_remaining_request_body()
                elif method == "DELETE":
                    try:
                        self._handle_api_delete(path, query)
                    finally:
                        self._drain_remaining_request_body()
                else:
                    try:
                        self._handle_api(path, query)
                    finally:
                        # GET/HEAD 携带 body（curl -X GET -d、部分 GraphQL/代理
                        # 客户端）时同样排空残留字节，防 keep-alive 复用下残留体
                        # 被下一请求当请求行（BUG-01 同类缺口）
                        self._drain_remaining_request_body()
                return

            if method != "GET" and method != "HEAD":
                # 排空 body 后再回 405（code-review item 265e22d75797）
                self._drain_remaining_request_body()
                self._error(405, "Method Not Allowed")
                return

            try:
                if path == "/" or path == "/index.html":
                    self._serve_static("dist/index.html")
                elif path.startswith("/screenshots/"):
                    self._serve_screenshot(path)
                else:
                    self._serve_static(path.lstrip("/"))
            finally:
                # GET/HEAD 静态派发同样在响应后排空残留 body（BUG-01 同类缺口，
                # 常规 GET 无 body 时为 no-op 零开销）
                self._drain_remaining_request_body()
        except BrokenPipeError:
            pass
        except Exception:  # noqa: BLE001
            # 不外泄裸异常文本（code-review item 1a2a0bd78662）：`{e}` 会把
            # 内部路径/存储细节透给 HTTP 客户端，与 code_review_routes 既有
            # 泛化文案策略同款——对外固定文案，详情经 logger.exception
            # （含 traceback）留服务端日志。
            logger.exception("Internal Server Error")
            # 仅在响应尚未开始时才补写 500（code-review item 9de3d3095e85）：
            # handler 已开始写响应（body 中途 BrokenPipe/OSError）时再写第二个
            # 响应会在 keep-alive 连接上发出第二条状态行/体、污染下一次交换。
            if not getattr(self, "_response_started", False):
                try:
                    self._error(500, "Internal Server Error")
                except Exception:
                    pass

    def _read_json_body(self) -> dict | None:
        """读取并解析 JSON 请求体，做大小限制。

        失败路径（Content-Length 不可解析/空体/超限/非法 JSON/非对象体）
        已自行写错误响应（400/413）并返回 None，调用方必须判空后终止。
        """
        from core.dashboard import server as _server_mod
        max_body = getattr(_server_mod, "MAX_POST_BODY", 256 * 1024)
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            # 报文分帧已不可解析，且 _drain_remaining_request_body 里同一处
            # int() 再次失败得 content_length=0 → remaining=0 跳过排空，客户端
            # 若实际发了体字节会在 keep-alive 复用时被当下一个请求的请求行
            # （BUG-01 同类失步）。比照 413 分支置 close_connection=True，让
            # 残留字节随连接关闭作废（code-review item 8beb499acc56）。
            self.close_connection = True
            self._error(400, "Invalid Content-Length")
            return None
        if content_length <= 0:
            self._error(400, "Empty request body")
            return None
        if content_length > max_body:
            # 413 不排空（code-review item 9cbdd2e25696）：残留交 finally 排空
            # 时会对攻击者声明的超大 Content-Length（实际无数据发送）执行无界
            # rfile.read(remaining)，阻塞 worker 线程达 socket 超时、占用请求
            # 槽/连接预算。改为标记连接不可复用（close_connection），排空跳过、
            # 响应后关闭连接让客户端重连，body 残留随之作废。
            self.close_connection = True
            self._error(413, "Request body too large")
            return None
        try:
            raw = self.rfile.read(content_length)
            # BUG-01：标记本请求已消费的 body 字节（POST/DELETE 派发后
            # _drain_remaining_request_body 据此计算残留）
            self._request_body_consumed = content_length
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                self._error(400, "Request body must be a JSON object")
                return None
            return body
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(400, "Invalid JSON body")
            return None

    def _drain_remaining_request_body(self):
        """POST/DELETE 处理后排空未消费的请求体字节（BUG-01 keep-alive 排空）。

        handler 在错误路径（如 project/spec 校验失败）提前返回而未读 body 时，
        残留字节会在 keep-alive 连接复用下被当作下一请求的请求行读取，解析为
        ``{...}POST /api/...`` 之类的非法命令 → 501 Unsupported method。
        排空后连接回到干净状态；已消费（_read_json_body 读满）时为 no-op。
        """
        if getattr(self, "close_connection", False):
            # 连接已标记不可复用（如 413 超大 body，code-review item
            # 9cbdd2e25696）：残留字节随连接关闭作废，不再盲排（无界 read
            # 阻塞 worker 线程）。
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            content_length = 0
        remaining = content_length - getattr(self, "_request_body_consumed", 0)
        if remaining > 0:
            # 残留长度上界（code-review item 5761d9f2f5c3）：handler 走 query
            # 校验早退而未调用 _read_json_body 的 POST/DELETE 路由（如
            # _post_run_watch、_post_alerts_clear 等），Content-Length 从未
            # 做上限校验；对攻击者声明的超大值（实际不发数据）下方
            # rfile.read(remaining) 会盲等阻塞 worker 线程至 socket 超时，
            # 并发打满请求槽后服务整体不可用。与 413 分支（9cbdd2e25696）
            # 及 _handle 快速拒绝分支同口径：超限置 close_connection=True
            # 跳过排空，残留字节随连接关闭作废。
            from core.dashboard import server as _server_mod

            if remaining > getattr(_server_mod, "MAX_POST_BODY", 256 * 1024):
                self.close_connection = True
                return
            try:
                self.rfile.read(remaining)
            except Exception:  # noqa: BLE001 连接已断/异常则放弃排空，不影响主响应
                pass

    def _wants_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "").lower()

    def _maybe_gzip(self, body: bytes) -> bytes:
        if len(body) >= self._GZIP_MIN and self._wants_gzip():
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            return gzip.compress(body, 5)
        return body

    def _json(self, payload, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._mark_response_started()
        self.send_response(status)
        # 条件请求通道（add-dashboard-paging-and-etag 1.2）：200 成功响应附带
        # ETag（_dispatch_table 在 handler 前挂 _pending_etag，此处消费并清零
        # ——自含响应 handler（_api_config_get 内部调 _json）同样命中本路径）。
        # 非 200 状态（错误响应）不挂 ETag：消费即弃，不发送。
        etag = getattr(self, "_pending_etag", None)
        if etag:
            self._pending_etag = None
            if status == 200:
                self.send_header("ETag", etag)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        body = self._maybe_gzip(body)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code: int, msg: str):
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self._mark_response_started()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)