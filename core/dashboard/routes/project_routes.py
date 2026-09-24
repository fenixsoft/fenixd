"""project_routes.py — H2 project management。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import logging
import urllib.parse
from pathlib import Path

from core.dashboard import data as dashboard_data

logger = logging.getLogger("fenixd.dashboard.project_routes")


class H2ProjectRoutesMixin:
    """H2 project management。"""

    def _api_projects(self) -> dict:
        projects = []
        for p in self.server.projects():
            if not p.get("exists"):
                projects.append(
                    {
                        "name": p["name"],
                        "path": p["path"],
                        "discovered": p.get("discovered", False),
                        "exists": False,
                        "daemon": "stopped",
                        "hosting": "stopped",
                        "error": "项目路径不存在",
                    }
                )
                continue
            try:
                s = dashboard_data.project_summary(p["path"], p["name"], p["path"])
                s["discovered"] = p.get("discovered", False)
                s["exists"] = True
                projects.append(s)
            except Exception as exc:  # noqa: BLE001 —— 单项目失败降级，端点仍返回 200
                projects.append(dashboard_data._degraded_project(p, f"摘要计算失败: {exc}"))
        return {"projects": projects}


    def _api_overview(self) -> dict:
        return dashboard_data.overview(self.server.projects())


    def _project_query_or_error(self, query, what: str):
        """文件级项目端点共用校验：缺 project 400、项目未知/不存在 404。

        通过返回项目 dict；失败已发送错误响应并返回 None。
        """
        name = query.get("project", [None])[0]
        if not name:
            self._error(400, f"缺少 project 参数（{what}为项目级文件）")
            return None
        project = self.server.project_by_name(name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return None
        return project


    def _resolve_project_or_400(self, path: str, prefix: str, require_exists: bool = True):
        """从 /api/projects/<name>[/start|/stop|/restart|/install-hosting] 或
        /api/projects/<name> 解析项目名。

        路径可能带动作后缀，先剥离再按项目名匹配。
        项目不存在（不在监控列表）返回 None；require_exists 时目录不存在也返回 None，
        调用方发 400。删除接口传 require_exists=False 以支持移除缺失项目。
        """
        if not path.startswith(prefix):
            return None
        name = urllib.parse.unquote(path[len(prefix) :])
        # 剥离可能的动作后缀（/start、/stop、/restart、/install-hosting）
        for suffix in ("/start", "/stop", "/restart", "/install-hosting"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if not name:
            return None
        project = self.server.project_by_name(name)
        if project is None or (require_exists and not project.get("exists")):
            return None
        return project


    def _api_project_lifecycle(self, action: str, path: str, query: dict):
        """POST /api/projects/<name>/start|stop|restart|install-hosting。成功广播 refresh。

        restart 走 supervisor 优雅重启协议（写 .fenix/restart_request，与
        hook restart-daemon 同构）：daemon 自行排水退出后由 supervisor 拉起，
        dashboard 进程不直接杀/拉 daemon。fix-supervisor-hosting-chain 5.2：
        restart 前校验托管态，unmanaged（裸 daemon）时拒绝——写信号无人消费
        会静默滞留，MUST NOT 视作成功。

        install-hosting（5.2）：对 unmanaged 项目执行「停止裸 daemon → 经
        supervisor 启动」转入 managed；对 managed 幂等返回已托管（不重启）；
        对 stopped 等价于启动。复用 stop_daemon/start_daemon，不绕过它们
        直接操作进程或 tmux。

        并发串行（fix-supervisor-hosting-chain 验证修复 BUG-01）：同一项目的
        全部生命周期动作经 .fenix/lifecycle.lock 串行——验证实证并发的
        install/stop 互踩会让一路的 SIGKILL 兜底误杀另一路刚拉起的 supervisor，
        致托管永远无法成立。锁超时返回可读错误，不挂死 HTTP 线程。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙命名空间延迟解析
        project = self._resolve_project_or_400(path, "/api/projects/")
        if project is None:
            self._error(400, "项目不存在或未监控")
            return
        with _server_mod._project_lifecycle_lock(project["path"]) as _acquired:
            if not _acquired:
                self._json({"ok": False, "error": "该项目正有另一启停操作进行中，请稍后重试"})
                return
            self._run_project_lifecycle_locked(action, project, path)



    def _run_project_lifecycle_locked(self, action: str, project: dict, path: str):
        """_api_project_lifecycle 的锁内实现（调用方已持有项目生命周期锁）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙命名空间延迟解析
        try:
            if action == "start":
                result = _server_mod.start_daemon(project["path"])
            elif action == "stop":
                result = _server_mod.stop_daemon(project["path"])
            elif action == "install-hosting":
                result = self._api_project_install_hosting(project)
            else:  # restart
                # 消费方校验（D8 同源）：unmanaged = 进程在跑但无 supervisor，
                # restart_request 无人消费；拒绝而非写信号后静默滞留
                try:
                    from core.fenix_session import hosting_state as _hosting_state

                    hosting = _hosting_state(project["path"])
                except Exception:
                    hosting = "stopped"
                if hosting == "unmanaged":
                    result = {
                        "ok": False,
                        "error": (
                            "本项目 daemon 未受 supervisor 托管，重启请求"
                            "不会被消费。经 Dashboard 项目页「安装托管」"
                            "或 /fenix-setup 恢复 supervisor 托管后重试"
                        ),
                    }
                else:
                    req_path = Path(project["path"]) / ".fenix" / "restart_request"
                    try:
                        req_path.parent.mkdir(parents=True, exist_ok=True)
                        req_path.touch()
                        result = {"ok": True, "error": None, "requested": True, "session": None}
                    except OSError as e:
                        result = {"ok": False, "error": f"写入 restart_request 失败: {e}"}
        except Exception as e:  # 环境异常（tmux 不可用等）→ 返回错误对象，不 500
            self._json({"ok": False, "error": f"操作失败: {e}"})
            return
        if not result.get("ok"):
            self._json({"ok": False, "error": result.get("error", "未知错误")})
            return
        # 成功：广播 refresh，概览在自动刷新周期内跟随更新 daemon 状态
        try:
            self.server.sse_hub.broadcast({"type": "refresh"})
        except Exception:
            pass
        self._json(
            {
                "ok": True,
                "session": result.get("session"),
                "already": result.get("already", False),
                "was_running": result.get("was_running", False),
            }
        )



    def _api_project_install_hosting(self, project: dict) -> dict:
        """安装 supervisor 托管：停止裸 daemon → 经 supervisor 启动。

        fix-supervisor-hosting-chain D6：存量项目（fenix-server、scheduling-
        showcase）的托管修复路径。对 managed 幂等返回已托管（不重启）；对
        stopped 等价于启动；对 unmanaged 停裸 daemon 后经 supervisor 拉起。
        复用 stop_daemon/start_daemon，强制走同一对已被测试覆盖的启停函数，
        不出现第三套启停实现。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙命名空间延迟解析
        try:
            from core.fenix_session import hosting_state as _hosting_state

            hosting = _hosting_state(project["path"])
        except Exception:
            hosting = "stopped"
        if hosting == "managed":
            return {"ok": True, "error": None, "already": True, "hosting": "managed"}
        # unmanaged / stopped：先停裸 daemon（幂等），再经 supervisor 启动
        stop_result = _server_mod.stop_daemon(project["path"])
        if not stop_result.get("ok"):
            return {"ok": False, "error": f"停止裸 daemon 失败: {stop_result.get('error')}"}
        start_result = _server_mod.start_daemon(project["path"])
        if not start_result.get("ok"):
            return {"ok": False, "error": f"经 supervisor 启动失败: {start_result.get('error')}"}
        return {"ok": True, "error": None, "already": False, "hosting": "managed"}



    def _api_project_delete(self, path: str, query: dict):
        """DELETE /api/projects/<name> —— 软删除：停止 daemon + 写入忽略列表。

        缺失项目（目录已不存在，exists=false）也允许删除：跳过停止 daemon，
        仅从监控列表移除并写入忽略列表。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙命名空间延迟解析
        project = self._resolve_project_or_400(path, "/api/projects/", require_exists=False)
        if project is None:
            self._error(400, "项目不存在或未监控")
            return
        # 与启停动作共享生命周期锁：delete 内含 stop_daemon，并发 install/stop
        # 时不得绕过串行（fix-supervisor-hosting-chain 验证修复）
        if project.get("exists"):
            with _server_mod._project_lifecycle_lock(project["path"]) as _acquired:
                if not _acquired:
                    self._json({"ok": False, "error": "该项目正有另一启停操作进行中，请稍后重试"})
                    return
                errors = []
                try:
                    stop_result = _server_mod.stop_daemon(project["path"])
                    if not stop_result.get("ok"):
                        errors.append(stop_result.get("error", "停止 daemon 失败"))
                except Exception as e:
                    errors.append(f"停止 daemon 失败: {e}")
                if errors:
                    self._json({"ok": False, "error": "；".join(errors)})
                    return
        else:
            errors = []
        # 2) 停止显式注册项 + 写入忽略列表（忽略优先：即便再次显式注册也被忽略）
        try:
            self.server.registry.remove_project(project["path"])
        except Exception as e:
            # 移除失败留痕（code-review item de01de91d3a7）：忽略优先语义下
            # 不阻断删除，但项目可能残留于显式注册列表，须可追查。
            logger.warning(
                "移除显式注册项失败（path=%s）: %s: %s",
                project["path"],
                type(e).__name__,
                e,
            )
        try:
            add_result = self.server.registry.add_ignored(project["path"])
            if not add_result[0]:
                errors.append(add_result[1])
        except Exception as e:
            errors.append(f"写入忽略列表失败: {e}")
        if errors:
            self._json({"ok": False, "error": "；".join(errors)})
            return
        # 成功：广播 refresh，概览不再返回该项目
        try:
            self.server.sse_hub.broadcast({"type": "refresh"})
        except Exception:
            pass
        self._json({"ok": True, "path": project["path"]})

    # ── 项目简介生成端点 ────────────────────────────────────────



    def _api_project_describe(self, query):
        """POST /api/project/describe?project=<name>

        由后端调用 headless claude CLI 生成项目简介。
        - 读项目根 README.md（≤8KB 截断，缺失时改读 package.json/pyproject.toml 前 4KB）
        - 拼固定中文指令 prompt
        - subprocess.run(["claude", "-p", prompt], cwd=项目根, timeout=120, shell=False)
        - 成功经 write_config 落盘返回 {ok, description}
        - 非零退出/超时/空输出返回 {error} 且不改 config

        错误契约（code-review item 1063825b9910）：本端点两种错误约定并存
        为有意设计——project 校验失败走 _error(400/404) 状态码；执行失败
        （超时/CLI 失败/写配置失败）走 HTTP 200 + {error} 字典。前端
        regenerateProjectDescription 统一按 result.ok/.error 分支（4xx 会被
        request 层抛异常、反而破坏现约），故执行失败不改用 _error。
        """
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return

        proot = Path(project["path"])
        # 读取项目文件内容
        content = ""
        readme_path = proot / "README.md"
        if readme_path.exists():
            try:
                raw = readme_path.read_bytes()[:8192]  # ≤8KB 截断
                content = raw.decode("utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                content = ""
        else:
            # 缺失时改读 package.json/pyproject.toml 前 4KB
            for fallback in ["package.json", "pyproject.toml"]:
                fallback_path = proot / fallback
                if fallback_path.exists():
                    try:
                        raw = fallback_path.read_bytes()[:4096]  # 前 4KB
                        content = raw.decode("utf-8", errors="replace")
                        break
                    except (OSError, UnicodeDecodeError):
                        continue

        # 拼固定中文指令 prompt（必须携带项目名与路径——README 主题重叠的
        # 项目若无项目身份信息会生成彼此的简介）
        prompt = f"""你是一个项目简介生成器。请为项目「{project["name"]}」（位于 {proot}）生成一句约100字的中文项目简介。

以下是该项目说明文件的内容：
{content}

要求：
1. 生成的简介必须围绕项目「{project["name"]}」本身，是纯文本，不要包含任何标记语言
2. 说明文件内容可能与同生态其他项目相似甚至过时：若它无法体现本项目的独特功能，
   请查看项目目录中的实际文件（如 package.json 的 name/description、pyproject.toml、
   主要源码结构）来确认项目定位，简介以项目实际功能为准
3. 简介应该概括该项目的主要用途和特点，注意区分于同生态下的其他项目
4. 简介长度控制在100字左右
5. 只输出简介文本，不要有其他内容"""

        # 调用 headless claude CLI
        import subprocess

        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                cwd=str(proot),
                timeout=120,
                shell=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            self._json({"error": "生成超时"})
            return
        except Exception as e:
            # 不外泄裸异常文本（code-review item 0936be83135a）：str(e) 可能
            # 携带内部路径/命令细节，与 code_review_routes 的泛化文案策略同款
            # ——细节降级经服务端日志留痕，客户端收通用消息。
            logger.warning(
                "调用 claude CLI 异常（project=%s）: %s: %s",
                project["name"],
                type(e).__name__,
                e,
            )
            self._json({"error": "调用 claude CLI 失败"})
            return

        # 检查返回结果
        if result.returncode != 0:
            logger.warning(
                "claude CLI 非零退出码（project=%s）: %s",
                project["name"],
                result.returncode,
            )
            self._json({"error": "调用 claude CLI 失败"})
            return

        description = result.stdout.strip()
        if not description:
            self._json({"error": "生成的简介为空"})
            return

        # 写入配置
        write_result = dashboard_data.write_config(
            proot, {"description": description}, scope="project"
        )
        if not write_result["ok"]:
            self._json({"error": f"配置写入失败: {write_result.get('error', '未知错误')}"})
            return

        self._json({"ok": True, "description": description})


    def _project_from_query(self, query):
        name = query.get("project", [None])[0]
        if not name:
            return None
        return self.server.project_by_name(name)


