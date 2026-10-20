"""project_routes.py — H2 project management。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。

「项目不存在」状态码的三种变体归属（code-review item ae3374a73d7a，集中
记载防后续端点抄写漂移；前端均按 result.ok/.error 分支，三变体功能等价）：
1) 项目级文件端点统一走 _project_query_or_error——缺参 400、未知/目录缺失
   一律 404 "project not found"（本文件共用口径，新增端点优先抄此）；
2) _api_project_describe 为 400/404 双档（registry 未知 400 "unknown
   project"、目录缺失 404 "project not found"），契约由
   TestProjectDescribeAPI 钉死（见该处 [fenix-ignore:c6597d26ac7c]）；
3) 路径式端点 _api_project_lifecycle / _api_project_delete（经
   _resolve_project_or_400）对未知/未监控项目回 400「项目不存在或未监控」，
   由 test_start_stop_unknown_project_returns_400 /
   test_restart_unknown_project_returns_400 /
   test_install_hosting_unknown_project_400 钉住 400 契约，属既有约定
   不擅改 404。
"""

from __future__ import annotations

import contextlib
import copy
import logging
import threading
import time
import urllib.parse
from pathlib import Path

from core.dashboard import data as dashboard_data
# 单文件数据源签名单点（code-review item c0c4df6ac475）：_overview_project_sig
# 的单文件失效键改用 signature.file_sig 公开名（与原 summary._stat_sig 逐字
# 等价，同为 (mtime_ns, size) / 不可 stat 返回 None），不再跨组消费下划线
# 私有名。模块级导入无环：signature.py 顶部仅 stdlib，其对门面的引用均在
# 函数内延迟解析（与 routes/base.py 的 ETag 签名链路同一模块来源）。
from core.dashboard.data import signature
# add-harness-adapter-layer 4.1：项目简介 describe 一次性 spawn 收编进
# harness/one_shot。env 剔除语义（code-review item 0ea03763257b：HTTP 线程内
# spawn claude 若不传 env，dashboard 进程环境里的 agent-run 专用键——
# FENIX_RUN_PROJECT_ROOT / FENIX_RUN_WORKTREE / CLAUDE_CODE_ENABLE_TODO_TOOLS，
# agent 自测拉起的 dashboard 即携带——会原样进入子进程，其中
# CLAUDE_CODE_ENABLE_TODO_TOOLS 还会实际改变子进程工具面）由 adapter
# build_env 的 ENV_MODE_CLEAN 口径承接（os.environ.copy() 减 banned keys，
# 与原 architecture_routes._build_spawn_env 逐字等价）。
from core.agent_runner.harness import (
    ENV_MODE_CLEAN,
    PROMPT_TRANSPORT_ARGV,
    ClaudeAdapter,
    SpawnRequest,
)
from core.agent_runner.harness.one_shot import run_one_shot

logger = logging.getLogger("fenixd.dashboard.project_routes")

# 同项目简介生成互斥注册表（code-review item 9c8e2c44f682）：_api_project_describe
# 在 HTTP 线程内同步等待 claude CLI 最长 120 秒，同项目并发点击会叠加占用
# base.py 的请求槽位（耗尽时对全部请求返回 503）。锁按项目名缓存复用（项目
# 数量有限，不会无限增长）。
_DESCRIBE_LOCKS: dict[str, threading.Lock] = {}
_DESCRIBE_LOCKS_GUARD = threading.Lock()

# ── /api/overview 结果缓存（add-alerts-archive-and-overview-cache 3.1）──────
# D3「TTL 或 签名」双键取或：TTL 窗口内直接命中；超 TTL 但「项目集合 + 全部
# 项目数据源签名」未变且仍在同一时钟刻度内时直接复用（签名 stat 比聚合便宜
# 1~2 个量级；刻度维度使缓存随时间自然失效，见 _api_overview item
# ce75392d257d 注释）。概览页
# 由 2s SSE 心跳驱动重拉，此前每次请求都冷算 project_summary 聚合（实测稳定
# ~200ms）。D4 单槽即可：overview 响应全局一份（无 project 参数维度）；
# 防写撕裂用简单 threading.Lock（读竞态最坏多算一次，无正确性风险）。
_OVERVIEW_CACHE_TTL = 2.0  # 与 watcher.REFRESH_HEARTBEAT 对齐
_OVERVIEW_CACHE: dict = {}  # 单槽 {sig, projects_key, time_slice, computed_at, payload}
_OVERVIEW_CACHE_LOCK = threading.Lock()


def _overview_project_sig(proot: Path) -> dict:
    """单项目数据源签名（stat-only，不解析内容）。

    复用既有 (path, mtime_ns, size) 失效键模式（signature.file_sig 单文件
    签名单点 + summary 公开别名 runs_by_spec_sigs 的分组扫描，不引入第二套
    扫描）。code-review item c0c4df6ac475 归一：docstring 原悬置的
    「signature.py 落地后归一复用其导出」已兑现——单文件签名与本函数口径
    逐字等价，直接复用其公开名；runs 按 spec 分组签名在 signature.py 无
    等价导出（tree_sigs 为整树相对路径元组集，文件集与返回结构均不同），
    维持 summary 单源、经公开别名引用。覆盖 overview 聚合的文件型数据源：
    STATE.md（spec 清单/状态）、各 spec tasks.md（任务计数）、
    runs 目录（active_runs）、config.yaml（description）。daemon_health /
    hosting_state 等动态源不入签名，陈旧上界由 _api_overview 缓存键的
    60 秒时钟刻度兜底（分钟级，item ce75392d257d）。
    """
    sigs: dict = {}
    for p in (proot / ".fenix" / "STATE.md", proot / ".fenix" / "config.yaml"):
        s = signature.file_sig(p)
        if s is not None:
            sigs[str(p)] = s
    try:
        for p in (proot / "spec" / "changes").glob("*/tasks.md"):
            s = signature.file_sig(p)
            if s is not None:
                sigs[str(p)] = s
    except OSError:
        pass
    for by_spec in dashboard_data.runs_by_spec_sigs(proot).values():
        sigs.update(by_spec)
    return sigs


def _overview_sig(projects: list) -> dict:
    """全部注册项目数据源签名的合并视图（键冠项目名防跨项目撞键）。"""
    merged: dict = {}
    for p in projects:
        if not p.get("exists"):
            continue
        for k, v in _overview_project_sig(Path(p["path"])).items():
            merged[f"{p['name']}::{k}"] = v
    return merged


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
                s = dashboard_data.project_summary(p["name"], p["path"])
                s["discovered"] = p.get("discovered", False)
                s["exists"] = True
                projects.append(s)
            except Exception as exc:  # noqa: BLE001 —— 单项目失败降级，端点仍返回 200
                # 不外泄裸异常文本（code-review item 2a32ba26780c）：str(exc)
                # 可能携带内部路径细节，与 _api_project_describe 的泛化文案
                # 策略同款——细节降级经服务端日志留痕，客户端收固定文案。
                logger.warning(
                    "项目摘要计算降级（project=%s）: %s: %s",
                    p["name"],
                    type(exc).__name__,
                    exc,
                )
                projects.append(dashboard_data.degraded_project(p, "摘要计算失败"))
        return {"projects": projects}


    def _api_overview(self) -> dict:
        projects = self.server.projects()
        # 清单标记并入缓存键（code-review item 651a9ae154ce）：discovered /
        # fixture 与 base.py _sig_overview 的「项目清单标记参与哈希」口径对齐
        # ——否则对已扫描发现的项目 add_project（discovered True→False）或
        # remove_project（False→True）时 name/path/exists 均不变，旧 payload
        # 会被 TTL 快路径与签名复用路径无限期续期（复用还刷新 computed_at），
        # 而 ETag 签名已翻转，客户端持新 ETag 拿到旧内容。
        projects_key = tuple(
            sorted(
                (
                    p["name"],
                    p["path"],
                    bool(p.get("exists")),
                    bool(p.get("discovered")),
                    bool(p.get("fixture")),
                )
                for p in projects
            )
        )
        # 快路径：TTL 窗口内直接命中（免全量签名 stat）
        with _OVERVIEW_CACHE_LOCK:
            cached_ts = _OVERVIEW_CACHE.get("computed_at")
            if (
                cached_ts is not None
                and _OVERVIEW_CACHE.get("projects_key") == projects_key
                and time.monotonic() - cached_ts < _OVERVIEW_CACHE_TTL
            ):
                return copy.deepcopy(_OVERVIEW_CACHE["payload"])

        # TTL 已过：签名未变且仍在同一 60 秒时钟刻度内才复用（D3 双键取或 +
        # 刻度维度，code-review item ce75392d257d）。此前复用即刷新
        # computed_at，TTL 被无限续期：daemon_health / hosting_state 等不入
        # 签名的动态源（第三方 daemon 崩溃不产生任何签名文件变更）与按墙钟
        # 计算的 spec_updated_today/week 跨日后均可无限期滞留陈旧值；混入量化
        # 刻度后，跨刻度的首个 TTL 过期请求即重算，动态字段陈旧上界分钟级。
        now_slice = int(time.time() // 60)
        sig = _overview_sig(projects)
        with _OVERVIEW_CACHE_LOCK:
            if (
                _OVERVIEW_CACHE.get("projects_key") == projects_key
                and _OVERVIEW_CACHE.get("sig") == sig
                and _OVERVIEW_CACHE.get("time_slice") == now_slice
            ):
                _OVERVIEW_CACHE["computed_at"] = time.monotonic()
                return copy.deepcopy(_OVERVIEW_CACHE["payload"])

        payload = dashboard_data.overview(projects)
        with _OVERVIEW_CACHE_LOCK:
            _OVERVIEW_CACHE.clear()
            _OVERVIEW_CACHE.update(
                {
                    "projects_key": projects_key,
                    "sig": sig,
                    # 取重算完成时刻的刻度：payload 与记录刻度同片，跨刻度
                    # 后首个 TTL 过期请求必走重算
                    "time_slice": int(time.time() // 60),
                    "computed_at": time.monotonic(),
                    "payload": payload,
                }
            )
        # 返回前拷贝：命中/写入的缓存 payload 不得被下游原地修改（响应序列化
        # 之外任何持有方改写都会污染缓存）
        return copy.deepcopy(payload)


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


    def _project_or_user_scope(self, query):
        """config 端点共用项目解析（code-review item 1291b3b1f3f1）：三处
        config 端点（_api_config_get / _api_config_post /
        _api_config_sync_from_user）各自内联的「缺参回退用户级、在场但解析
        不到项目 404」判定收敛为行为单源，防端点间漂移。

        判参口径（code-review item 40ec5f6b6c5e，先例 b9e7765dc1de）：
        _project_from_query 把「无 project 查询参数」与「project 名不在
        registry（笔误/项目已删/registry TTL 缓存过期）」折叠成 None——直接
        以 None 判用户级分支会把 ?project=<笔误名> 折进用户级配置。故先看
        参数是否在场：缺席才回退用户级；在场但 project 为 None 或
        not exists → _error(404, "project not found")（资源不存在语义）。

        返回 (project, project_param)，调用方判定：
        - ``project_param and project is None``：404 已由本助手发送，调用方
          直接 return 终止处理；
        - ``project is None``（缺参）：用户级作用域；
        - 其余：project 为有效项目 dict（exists 已核验）。
        （与 _project_query_or_error 的区别：后者缺参即 400，二态返回；
        config 端点缺参是合法用户级作用域，须三态，故独立成助手。）
        """
        project_param = query.get("project", [None])[0]
        project = self._project_from_query(query) if project_param else None
        if project_param and (project is None or not project.get("exists")):
            self._error(404, "project not found")
            return None, project_param
        return project, project_param


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
            self._run_project_lifecycle_locked(action, project)



    def _run_project_lifecycle_locked(self, action: str, project: dict):
        """_api_project_lifecycle 的锁内实现（调用方已持有项目生命周期锁）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙命名空间延迟解析
        try:
            if action == "start":
                result = _server_mod.start_daemon(project["path"])
            elif action == "stop":
                result = _server_mod.stop_daemon(project["path"])
            elif action == "install-hosting":
                result = self._install_hosting_locked(project)
            elif action == "restart":
                # 消费方校验（D8 同源）：unmanaged = 进程在跑但无 supervisor，
                # restart_request 无人消费；拒绝而非写信号后静默滞留。
                # 探测异常（导入失败等）同样不放行：降级 stopped 会绕过校验，
                # 对实际 unmanaged 的 daemon 谎报成功——按 unmanaged 同样拒绝
                try:
                    from core.fenix_session import hosting_state as _hosting_state

                    hosting = _hosting_state(project["path"])
                except Exception:
                    hosting = "unmanaged"
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
                        # 不外泄裸异常文本（code-review item 18e71e70c018）：str(e)
                        # 可能携带 .fenix/restart_request 完整路径与 errno 细节，
                        # 客户端收固定文案，详情经服务端日志留痕（同外层 except 口径）。
                        logger.warning(
                            "写入 restart_request 失败（project=%s）: %s: %s",
                            project["name"],
                            type(e).__name__,
                            e,
                        )
                        result = {"ok": False, "error": "写入 restart_request 失败"}
            else:
                # item 9340641988bd：显式拒绝未知动作，不再裸 else 兜底为
                # restart——路由派发面（base.py 路由表）新增动作而本分发
                # 漏改时，静默写 restart_request 会触发 daemon 排水重启，
                # 故障表现与根因相距很远；两侧失同步在此显式失败可观测。
                result = {"ok": False, "error": f"未知动作 {action}"}
        except Exception as e:  # 环境异常（tmux 不可用等）→ 返回错误对象，不 500
            # 不外泄裸异常文本（code-review item 2a32ba26780c）：环境异常的
            # str(e) 可能携带内部路径/tmux 错误细节，与 _api_project_describe
            # 的泛化文案策略同款——细节降级经服务端日志留痕，客户端收固定文案。
            logger.warning(
                "项目生命周期操作异常（action=%s project=%s）: %s: %s",
                action,
                project["name"],
                type(e).__name__,
                e,
            )
            self._json({"ok": False, "error": "操作失败"})
            return
        if not result.get("ok"):
            if action in ("start", "stop"):
                # 返回值分支同款降级（code-review item 48251584dbe5）：启停函数
                # 返回的 error 内嵌裸 OSError 原文与绝对路径（如 f"写 .fenix/stop
                # 失败: {e}"、tmux stderr），与本文件 _install_hosting_locked /
                # _api_project_delete 的泛化策略对齐——客户端收按动作区分的固定
                # 文案，细节经服务端日志留痕。install-hosting/restart/未知动作
                # 的 error 均为本文件内自造的固定文案（restart 未托管指引须原样
                # 达客户端），维持透传。
                logger.warning(
                    "%s daemon 失败（project=%s）: %s",
                    "启动" if action == "start" else "停止",
                    project["name"],
                    result.get("error", "未知错误"),
                )
                self._json(
                    {
                        "ok": False,
                        "error": (
                            "启动 daemon 失败" if action == "start" else "停止 daemon 失败"
                        ),
                    }
                )
            else:
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



    def _install_hosting_locked(self, project: dict) -> dict:
        """安装 supervisor 托管：停止裸 daemon → 经 supervisor 启动。

        非 HTTP 端点（原 _api_ 前缀为独立端点时代残留，code-review item
        efe9b726c60b）：返回 dict 由 _run_project_lifecycle_locked 的
        install-hosting 分支转发，对外端点是 _api_project_lifecycle。

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
            # 探测异常降级 stopped 并继续执行，与 restart 分支（异常→unmanaged
            # 拒绝）的口径有意不同：restart 只写信号交给既有 daemon 消费，误放行
            # 会信号静默滞留却谎报成功；install-hosting 不依赖信号消费方，直接
            # stop_daemon+start_daemon 真实执行安装，成败由启停函数自报，探测
            # 异常时放行不会假成功。本接口还是 restart 错误文案指定的修复入口，
            # fail-closed 会让探测坏掉时修复路径恰好不可用。代价：瞬时异常叠加
            # 实际 managed 时多做一次停/起（短暂中断，终态仍 managed）。
            hosting = "stopped"
        if hosting == "managed":
            # 不带 hosting 键（code-review item 13088c37c22d）：lifecycle 成功
            # 响应只转发 ok/session/already/was_running，前端也不消费本端点
            # 响应体，透传托管态属死数据；托管态以项目列表轮询为准。
            return {"ok": True, "error": None, "already": True}
        # unmanaged / stopped：先停裸 daemon（幂等），再经 supervisor 启动。
        # 返回值分支同款降级（code-review item d46b9929bb4e）：启停函数返回的
        # error 内嵌裸 OSError 原文与绝对路径（如 f"写 .fenix/stop 失败: {e}"、
        # tmux stderr），与本文件 except 分支的泛化策略对齐——客户端收固定
        # 文案，细节经服务端日志留痕。
        stop_result = _server_mod.stop_daemon(project["path"])
        if not stop_result.get("ok"):
            logger.warning(
                "停止裸 daemon 失败（project=%s）: %s",
                project["name"],
                stop_result.get("error", "未知错误"),
            )
            return {"ok": False, "error": "停止裸 daemon 失败"}
        start_result = _server_mod.start_daemon(project["path"])
        if not start_result.get("ok"):
            logger.warning(
                "经 supervisor 启动失败（project=%s）: %s",
                project["name"],
                start_result.get("error", "未知错误"),
            )
            return {"ok": False, "error": "经 supervisor 启动失败"}
        return {"ok": True, "error": None, "already": False}



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
        # 与启停动作共享生命周期锁：delete 内含 stop_daemon + 注册表移除/忽略
        # 写入，并发 install/stop 时不得绕过串行（fix-supervisor-hosting-chain
        # 验证修复）。移除与忽略写入同置锁内（code-review item d66d3a9f717a）：
        # 若留在锁外，等待同一把锁的 start/install-hosting 会在删除方释放锁后、
        # 忽略写入前抢锁拉起 daemon，删除方随后照常注销+忽略并返回 ok——最终
        # 留下一个对 dashboard 不可见、不再被监控的孤儿 daemon。缺失项目（目录
        # 已不存在）无 daemon 可停，走 nullcontext 跳过锁：锁实现会在缺失目录
        # 创建 .fenix/，不得为已删项目复活目录。
        errors = []
        exists = bool(project.get("exists"))
        lock_cm = (
            _server_mod._project_lifecycle_lock(project["path"])
            if exists
            else contextlib.nullcontext(True)
        )
        with lock_cm as _acquired:
            if not _acquired:
                self._json({"ok": False, "error": "该项目正有另一启停操作进行中，请稍后重试"})
                return
            if exists:
                try:
                    stop_result = _server_mod.stop_daemon(project["path"])
                    if not stop_result.get("ok"):
                        # 返回值分支同款降级（code-review item d46b9929bb4e）：
                        # stop_daemon 返回的 error 内嵌裸异常原文与绝对路径，
                        # 客户端收固定文案，细节经服务端日志留痕。
                        logger.warning(
                            "停止 daemon 失败（project=%s）: %s",
                            project["name"],
                            stop_result.get("error", "未知错误"),
                        )
                        errors.append("停止 daemon 失败")
                except Exception as e:
                    # 不外泄裸异常文本（code-review item 1825f4bcd251）：str(e)
                    # 可能携带内部路径/命令/errno 细节，客户端收固定文案，
                    # 详情经服务端日志留痕（同 _run_project_lifecycle_locked 口径）。
                    logger.warning(
                        "停止 daemon 异常（project=%s）: %s: %s",
                        project["name"],
                        type(e).__name__,
                        e,
                    )
                    errors.append("停止 daemon 失败")
                if errors:
                    self._json({"ok": False, "error": "；".join(errors)})
                    return
            # 2) 移除显式注册项 + 写入忽略列表（忽略优先：即便再次显式注册也被忽略）
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
                    # 返回值分支同款降级（code-review item d46b9929bb4e）：
                    # registry 的 load/save error 内嵌裸异常原文与绝对路径，
                    # 客户端收固定文案，细节经服务端日志留痕。
                    logger.warning(
                        "写入忽略列表失败（path=%s）: %s",
                        project["path"],
                        add_result[1],
                    )
                    errors.append("写入忽略列表失败")
            except Exception as e:
                # 不外泄裸异常文本（code-review item 1825f4bcd251）：同停止 daemon
                # 分支，客户端收固定文案，异常详情经服务端日志留痕。
                logger.warning(
                    "写入忽略列表异常（path=%s）: %s: %s",
                    project["path"],
                    type(e).__name__,
                    e,
                )
                errors.append("写入忽略列表失败")
            if errors:
                self._json({"ok": False, "error": "；".join(errors)})
                return
        # 成功：失效 projects() 缓存（settle 后首次 /api/overview 立即反映真值，
        # 否则 TTL 内的旧缓存让已删项目「消失→重现→10s 后再消失」），再广播 refresh
        try:
            self.server.invalidate_projects_cache()
        except Exception:
            pass
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
        - run_one_shot：claude -p <prompt>（argv 传输），cwd=项目根，timeout=120
        - 成功经 write_config 落盘返回 {ok, description}
        - 非零退出/超时/空输出返回 {error} 且不改 config

        错误契约（code-review item 1063825b9910）：本端点两种错误约定并存
        为有意设计——project 校验失败走 _error(400/404) 状态码；执行失败
        （超时/CLI 失败/写配置失败）走 HTTP 200 + {error} 字典。前端
        regenerateProjectDescription 统一按 result.ok/.error 分支（4xx 会被
        request 层抛异常、反而破坏现约），故执行失败不改用 _error。
        """
        # [fenix-ignore:c6597d26ac7c] 400/404 双档口径是被
        # tests/test_dashboard_api.py::TestProjectDescribeAPI 钉死的既有契约：
        # registry 未知（笔误/已删）→ 400 "unknown project"，已注册但目录
        # 缺失 → 404 "project not found"。与共用助手 _project_query_or_error
        # 的统一口径（未知/不存在一律 404）差异系有意保留，改用共用助手会
        # 破坏 test_describe_unknown_project_returns_400。
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return

        # 同项目互斥去重（code-review item 9c8e2c44f682）：避免并发重复点击
        # 叠加占用 HTTP 请求槽。非阻塞抢锁，已被同项目在途请求持有则立即返回
        # （与执行失败同款契约：HTTP 200 + {error}，前端按 result.error 分支）。
        with _DESCRIBE_LOCKS_GUARD:
            describe_lock = _DESCRIBE_LOCKS.setdefault(project["name"], threading.Lock())
        if not describe_lock.acquire(blocking=False):
            self._json({"error": "该项目简介正在生成中，请稍候再试"})
            return
        try:
            proot = Path(project["path"])
            # 读取项目文件内容
            content = ""
            readme_path = proot / "README.md"
            if readme_path.exists():
                try:
                    raw = readme_path.read_bytes()[:8192]  # ≤8KB 截断
                    # errors="replace" 按设计吞掉坏字节、不会抛 UnicodeDecodeError
                    # （code-review item 61f4c7a973a6），只守卫读取失败的 OSError。
                    content = raw.decode("utf-8", errors="replace")
                except OSError:
                    content = ""
            else:
                # 缺失时改读 package.json/pyproject.toml 前 4KB
                for fallback in ["package.json", "pyproject.toml"]:
                    fallback_path = proot / fallback
                    if fallback_path.exists():
                        try:
                            raw = fallback_path.read_bytes()[:4096]  # 前 4KB
                            # 同上：errors="replace" 不会抛 UnicodeDecodeError
                            # （code-review item 61f4c7a973a6），只守卫 OSError。
                            content = raw.decode("utf-8", errors="replace")
                            break
                        except OSError:
                            continue

            # 拼固定中文指令 prompt（必须携带项目名与路径——README 主题重叠的
            # 项目若无项目身份信息会生成彼此的简介）
            # [fenix-ignore:c43d75c419ec] 本调用点不带 bypassPermissions（异于 knowledge.py/regression_routes 同族），写入类工具默认被拒，输出仅落 description 展示字段，注入面影响有限，维持现约。
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

            # 调用 headless claude CLI——经 harness one_shot 收编（add-harness-
            # adapter-layer 4.1）：argv 传 prompt（prompt_transport=ARGV，紧随
            # -p 的现状形态）、output_format=None（不带 --output-format）、不带
            # permission-mode、clean env 口径（item 0ea03763257b，见模块头注释）、
            # 显式 utf-8/replace 解码（item ee8f460deb54）与非交互 DEVNULL stdin
            # 全部是 SpawnRequest/SpawnSpec 字段；命令构造唯一入口在
            # claude_adapter.build_spawn_spec。
            # [fenix-ignore:c43d75c419ec] 本调用点不带 bypassPermissions（异于
            # knowledge.py/regression_routes 同族），写入类工具默认被拒，输出仅落
            # description 展示字段，注入面影响有限，维持现约。
            # 有意偏差：start_new_session=True（subprocess.run 现状无独立进程组）
            # ——超时收割随之从「杀单进程」升级为「杀整组」，方向更安全，且与其余
            # 四个一次性 spawn 点同构。
            try:
                result = run_one_shot(
                    ClaudeAdapter(),
                    SpawnRequest(
                        prompt,
                        cwd=str(proot),
                        prompt_transport=PROMPT_TRANSPORT_ARGV,
                        output_format=None,
                        env_mode=ENV_MODE_CLEAN,
                    ),
                    timeout=120,
                )
            except Exception as e:
                # 不外泄裸异常文本（code-review item 0936be83135a）：str(e) 可能
                # 携带内部路径/命令细节，与 code_review_routes 的泛化文案策略同款
                # ——细节降级经服务端日志留痕，客户端收通用消息。OneShotCommunicateError
                # 包装的通信期异常解包 original 留真实异常名。
                orig = getattr(e, "original", e)
                logger.warning(
                    "调用 claude CLI 异常（project=%s）: %s: %s",
                    project["name"],
                    type(orig).__name__,
                    orig,
                )
                self._json({"error": "调用 claude CLI 失败"})
                return

            # 检查返回结果
            if result.timed_out:
                # 超时收割（one_shot 内已完成两段式进程组清场）；文案与原
                # subprocess.TimeoutExpired 分支一致
                self._json({"error": "生成超时"})
                return
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

            # 落盘前长度截断（code-review item 654753a47272）：CLI 异常输出（如
            # 误回显全文）无上限，原样写入会把 config.yaml 的 description 撑到
            # 任意大并随 read_effective_config 等读侧传播。与输入侧同量级截
            # 4KB：按字节截断后 errors="replace" 解码，写法与上方 README
            # read_bytes()[:8192]/回退 [:4096] 同款；超限经服务端日志留痕。
            raw_desc = description.encode("utf-8")
            if len(raw_desc) > 4096:
                logger.warning(
                    "生成的简介超 4KB，落盘前截断（project=%s, bytes=%d）",
                    project["name"],
                    len(raw_desc),
                )
                description = raw_desc[:4096].decode("utf-8", errors="replace")

            # 写入配置
            write_result = dashboard_data.write_config(
                proot, {"description": description}, scope="project"
            )
            if not write_result["ok"]:
                # 不外泄裸异常文本：write_result['error'] 可能内嵌 OSError/
                # YAMLError 原文（含服务端绝对路径/errno 细节），与同文件其余
                # 异常分支的泛化文案策略同款——细节降级经服务端日志留痕。
                logger.warning(
                    "配置写入失败（project=%s）: %s",
                    project["name"],
                    write_result.get("error", "未知错误"),
                )
                self._json({"error": "配置写入失败（详见服务端日志）"})
                return

            self._json({"ok": True, "description": description})
        finally:
            describe_lock.release()


    def _project_from_query(self, query):
        name = query.get("project", [None])[0]
        if not name:
            return None
        return self.server.project_by_name(name)


