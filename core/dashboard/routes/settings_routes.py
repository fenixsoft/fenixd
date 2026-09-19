"""settings_routes.py — H5 settings/prompts/todo/verify-yaml。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from core.dashboard import data as dashboard_data
from core.dashboard.ocr_status import check_ocr_installed, install_ocr
from core.admin_store import AdminStore, SIGNAL  # noqa: E402
from core.dashboard.registry import Registry
from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_DIR,
    AGENT_PROMPT_FILES,
    project_agents_dir,
)


class H5SettingsRoutesMixin:
    """H5 settings/prompts/todo/verify-yaml。"""

    def _api_config_get(self, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            # 无项目 → 用户级配置（scope=user，不再返回 unknown project）
            return dashboard_data.read_config(None, scope="user")
        if not project.get("exists"):
            return {"error": "project not found"}
        config = dashboard_data.read_effective_config(project["path"])
        config["project"] = project["name"]
        return config


    def _api_config_post(self, query):
        body = self._read_json_body()
        if body is None:
            return

        project = self._project_from_query(query)
        if project is None:
            # 用户模式：写 ~/.fenix/config.yaml
            result = dashboard_data.write_config(None, body, scope="user")
        else:
            if not project.get("exists"):
                self._error(400, "project not found")
                return
            result = dashboard_data.write_config(project["path"], body, scope="project")

        if not result["ok"]:
            self._error(400, result["error"] or "配置写入失败")
            return

        # 成功后返回最新配置（读回以确认）+ scope / 写入路径
        if project is None:
            config = dashboard_data.read_config(None, scope="user")
        else:
            config = dashboard_data.read_effective_config(project["path"])
            config["project"] = project["name"]
        config["saved"] = True
        config["scope"] = result["scope"]
        config["path"] = result["path"]
        self._json(config)


    def _api_config_sync_from_user(self, query):
        """POST /api/config/sync-from-user?project=<name>  body: {"page": "<页标识>"}

        把用户级 config.yaml 中 page 页签对应的受管键覆盖写入项目级配置
        （设置页项目级「同步用户级设置」按钮）。page 白名单见
        data._SYNC_PAGE_KEYS；成功返回最新项目级生效配置（读回以确认）。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(400, "project not found")
            return
        page = body.get("page")
        if not isinstance(page, str) or not page:
            self._error(400, "body.page 必须为页面标识字符串")
            return
        result = dashboard_data.sync_config_from_user(project["path"], page)
        if not result["ok"]:
            self._error(400, result.get("error") or "同步失败")
            return
        config = dashboard_data.read_effective_config(project["path"])
        config["project"] = project["name"]
        config["saved"] = True
        config["synced"] = result["synced"]
        self._json(config)


    def _api_prompts_get(self, query) -> dict:
        """GET /api/prompts[?project=<name>] — agent 提示词读取。

        缺省 → 仅通用层六文件（用户级只读视图）；带 project → 追加项目级
        .fenix/agents/ 附加内容。通用层一律只读，端点不提供通用层写入。
        """
        agents = []
        for atype, fname in AGENT_PROMPT_FILES.items():
            path = AGENT_PROMPT_DIR / fname
            try:
                content = path.read_text(encoding="utf-8") if path.is_file() else ""
            except OSError:
                content = ""
            agents.append({"type": atype, "file": fname, "content": content})
        out: dict = {"agents": agents}
        project = self._project_from_query(query)
        if project is None:
            return out
        if not project.get("exists"):
            return {"error": "project not found"}
        proot = Path(project["path"])
        out["project"] = {
            "name": project["name"],
            "path": project["path"],
            # 所有项目一视同仁（含 fenixd 自身）；仅废弃软链布局 extras 为空串
            "extras": {
                atype: self._read_project_extra(proot, atype) for atype in AGENT_PROMPT_FILES
            },
        }
        return out


    @staticmethod
    def _read_project_extra(proot: Path, agent_type: str) -> str:
        agents_dir = project_agents_dir(proot)
        if agents_dir is None:
            return ""
        path = agents_dir / AGENT_PROMPT_FILES[agent_type]
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""


    def _api_prompts_post(self, query):
        """POST /api/prompts?project=<name> — 保存项目附加提示词。

        body: {"agent_type": <白名单键>, "content": <自由 Markdown>}。
        写入 <项目根>/.fenix/agents/<agent-type>.md（该目录唯一写入口，
        框架运行时代码不写项目级目录）；.fenix/agents 解析为通用层目录的
        废弃软链布局拒绝（403，项目通道永不触碰通用层）。
        """
        body = self._read_json_body()
        if body is None:
            return
        name = query.get("project", [None])[0]
        if not name:
            self._error(400, "缺少 project 参数（项目附加提示词必须挂到具体项目）")
            return
        project = self.server.project_by_name(name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        agent_type = body.get("agent_type")
        if not isinstance(agent_type, str) or agent_type not in AGENT_PROMPT_FILES:
            self._error(400, f"非法 agent_type（白名单外）: {agent_type}")
            return
        proot = Path(project["path"])
        agents_dir = project_agents_dir(proot)
        if agents_dir is None:
            self._error(
                403,
                "项目 .fenix/agents 解析为框架通用层 agents/（废弃自引用软链布局），"
                "项目通道禁止写入通用提示词",
            )
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 Markdown，不做 schema 校验）")
            return
        target = agents_dir / AGENT_PROMPT_FILES[agent_type]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._json({"ok": True, "agent_type": agent_type, "path": str(target)})


    def _api_todo_get(self, query) -> None:
        """GET /api/todo?project=<name> — 项目 todo.md 读取（设置页「自省」面板）。

        路径固定为 <项目根>/.fenix/todo.md，不接受任意路径参数。
        文件尚不存在（自省未运行过）返回空串 + exists=false。
        """
        project = self._project_query_or_error(query, "todo.md")
        if project is None:
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "todo.md"
        exists = target.is_file()
        content = ""
        try:
            if exists:
                content = target.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"todo.md 读取失败: {e}")
            return
        self._json(
            {"project": project["name"], "path": str(target), "exists": exists, "content": content}
        )


    def _api_todo_post(self, query):
        """POST /api/todo?project=<name> — 保存项目 todo.md（整文件覆写）。

        body: {"content": <自由 Markdown>}。文件不存在时自动创建；
        daemon 自省会追加写入此文件，覆写保存以 UI 提交内容为准。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "todo.md")
        if project is None:
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 Markdown，不做 schema 校验）")
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "todo.md"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            self._error(500, f"todo.md 保存失败: {e}")
            return
        self._json({"ok": True, "project": project["name"], "path": str(target)})


    def _api_verify_yaml_get(self, query) -> None:
        """GET /api/verify-yaml?project=<name> — 验证契约文件读取（设置页「项目简介」面板）。

        路径固定为 <项目根>/.fenix/verify.yaml，不接受任意路径参数。
        文件尚不存在返回空串 + exists=false（前端提示可从模板创建）。
        """
        project = self._project_query_or_error(query, "verify.yaml")
        if project is None:
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "verify.yaml"
        exists = target.is_file()
        content = ""
        try:
            if exists:
                content = target.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"verify.yaml 读取失败: {e}")
            return
        self._json(
            {"project": project["name"], "path": str(target), "exists": exists, "content": content}
        )


    def _api_verify_yaml_post(self, query):
        """POST /api/verify-yaml?project=<name> — 保存验证契约（整文件覆写）。

        body: {"content": <自由 YAML>}。与 todo.md 的关键差异：保存前做校验——
        1. YAML 语法必须可解析（坏 YAML 会被 load_verify_contract 按「无契约」
           静默回退，用户以为契约生效了实则没有，编辑器必须当场拦截）；
        2. 顶层必须为字段映射或空（列表/标量同样静默失效）。
        不做字段级 schema 校验：加载器对未知字段宽容，字段语义在模板注释里。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "verify.yaml")
        if project is None:
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 YAML，不做字段级 schema 校验）")
            return
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            self._error(
                400, f"YAML 语法错误，拒绝保存（坏契约会被框架按「无契约」" f"静默回退）: {e}"
            )
            return
        if data is not None and not isinstance(data, dict):
            self._error(
                400,
                f"verify.yaml 顶层必须是字段映射（prepare/serve/ready），"
                f"当前为 {type(data).__name__}——非映射契约会被框架静默失效",
            )
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "verify.yaml"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            self._error(500, f"verify.yaml 保存失败: {e}")
            return
        self._json({"ok": True, "project": project["name"], "path": str(target)})


    def _api_verify_yaml_template(self) -> None:
        """GET /api/verify-yaml-template — 契约模板原文（设置页「插入模板」按钮）。

        模板单一来源 = core/verify_contract_template.yaml（fenix-init 生成、
        setup skill 复制均引用同一文件）；全部配置行注释 = 惰性 YAML。
        """
        template = Path(__file__).resolve().parents[2] / "verify_contract_template.yaml"
        try:
            content = template.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"契约模板读取失败: {e}")
            return
        self._json({"path": str(template), "template": content})


    def _api_verify_yaml_autodraft_post(self, query: dict):
        """POST /api/verify-yaml-autodraft?project=<name> — 触发 AI 起草验证契约。

        项目解析复用现有 verify-yaml 端点路径（未知项目 404）；
        load_verify_contract 轻量判定——契约缺失/解析失败（contract is None）写
        verify_contract_missing SIGNAL；契约可解析且带覆盖确认（overwrite=true）改写
        verify_contract_redraft SIGNAL（fix-verify-contract-signal-semantics B：
        语义拆分，missing 回归纯缺失语义，覆盖重起草不再旁路 missing）。
        两者均为 AdminStore.append，source=ui-manual、overwrite 标记、spec 字段留空、
        项目名入 evidence，响应 dispatched；
        契约有效且无 overwrite 响应 skipped（附「契约已有效」文案）不写信号；
        写前在途去重（D2）：同项目同 signal_type 未消费信号已存在则不重复写，
        响应仍 dispatched 且 message 注明已有在途请求。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "verify-yaml-autodraft")
        if project is None:
            return
        proot = Path(project["path"])
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=None)
        overwrite = bool(body.get("overwrite"))
        if contract is not None and not overwrite:
            # 有效契约且无覆盖确认 → skipped
            self._json(
                {
                    "ok": True,
                    "project": project["name"],
                    "status": "skipped",
                    "message": "契约已有效，无需自动起草。如需覆盖，请确认覆盖意图后重试。",
                }
            )
            return
        # 契约缺失/解析失败 → verify_contract_missing；契约有效且带覆盖确认 → verify_contract_redraft
        signal_type = "verify_contract_missing" if contract is None else "verify_contract_redraft"
        store = AdminStore(proot, logger=None)
        evidence_detail = f"项目名={project['name']}"
        if overwrite:
            evidence_detail += "; 覆盖确认=是"
        # 在途去重（D2）：同项目同 signal_type 未消费信号已存在 → 不重复写。
        # 异类型互不抑制（missing 在途不挡 redraft——契约被修正后确认覆盖是新意图）；
        # 已 handled 的历史信号不抑制（用户可再次请求）。
        inflight = [
            r
            for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == signal_type
            and not r.get("handled")
            and f"项目名={project['name']}" in (r.get("evidence") or "")
        ]
        if inflight:
            self._json(
                {
                    "ok": True,
                    "project": project["name"],
                    "status": "dispatched",
                    "message": "已有在途的验证契约处理请求，无需重复触发；Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录。",
                }
            )
            return
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": signal_type,
                "spec": None,
                "severity": "major",
                "description": "AI 起草验证契约请求（UI 手动触发）",
                "evidence": evidence_detail,
                "source": "ui-manual",
                "overwrite": overwrite,
                "recommended_action": "Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点重新加载查看新契约。",
            }
        )
        self._json(
            {
                "ok": True,
                "project": project["name"],
                "status": "dispatched",
                "message": "已提交 AI 起草请求，Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点重新加载查看新契约。",
            }
        )


    # ── 质量页签：open-code-review 安装探测与一键安装 ──────────────────

    def _api_quality_ocr_status_get(self, query) -> dict:
        """GET /api/quality/ocr-status — ocr 安装状态（质量页签门控）。

        返回 {"installed", "bin", "version"}；探测口径见 core.dashboard.ocr_status
        （shutil.which("ocr")，与 bin/ocr_review.py 包装器的 PATH 解析同源）。
        无项目参数依赖——ocr 是机器级环境，与作用域/项目无关。
        """
        return check_ocr_installed()

    def _api_quality_ocr_install_post(self, query) -> None:
        """POST /api/quality/ocr-install — 一键安装 open-code-review。

        执行 `npm install -g @alibaba-group/open-code-review`（固定字面量，
        无用户输入拼接）。失败（含权限不足）返回 400 + 可读错误与 npm 输出尾部，
        由用户自行 sudo 安装（不做提权）。成功返回最新版本串供 UI 立即刷新。
        """
        result = install_ocr()
        if not result["ok"]:
            # npm 原始报错（如 EACCES 权限不足）尾部并入错误文案透出，
            # 便于用户自行 sudo 安装；错误体仍是单行可读字符串。
            msg = result["error"] or "安装失败"
            tail = (result.get("output") or "").strip()
            if tail:
                last_line = tail.splitlines()[-1].strip()
                if last_line and last_line not in msg:
                    msg = f"{msg}：{last_line}"
            self._error(400, msg)
            return
        self._json({"ok": True, "version": result["version"], "output": result["output"]})
