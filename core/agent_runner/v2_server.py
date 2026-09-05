"""v2_server.py — V2ServerManager：per-run 隔离测试服务器生命周期（add-worktree-test-server）。

状态同迁（design D3 规则 1）：_v2_servers / _v2_used_ports / _v2_run_seq 随组件
迁移；门面经 property 委托保持 `runner._v2_servers` 等路径可用。
"""

from typing import Optional, Dict, Any
from pathlib import Path
from core.v2_dev_server import V2DevServerError, start as v2_start_dev_server, stop as v2_stop_dev_server, base_url as v2_base_url, cleanup_orphans as v2_cleanup_orphans


class V2ServerManager:
    """per-run 隔离测试服务器组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # add-worktree-test-server（design D2/D3）：per-run 隔离测试服务生命周期。
        # _v2_servers: {wt_path(str): (port, proc)}，随 worktree 创建/清理启停；
        # _v2_used_ports: 本 daemon 已分配且占用的端口集合，避免并发派发重复分配；
        # _v2_run_seq: 单调递增运行序号，决定首选端口（确定性分散，design D3）。
        self._v2_servers: Dict[str, Tuple[int, subprocess.Popen]] = {}
        self._v2_used_ports: set = set()
        self._v2_run_seq = 0

    def _v2_ensure_state(self) -> None:
        """惰性初始化 V2 状态（设计容错：部分测试以 ``AgentRunner.__new__`` 绕过
        ``__init__`` 构造实例，此时实例属性未建立；访问前补齐默认值避免 AttributeError，
        行为与 daemon 正常 __init__ 路径一致）。
        """
        if not hasattr(self, "_v2_servers") or self._v2_servers is None:
            self._v2_servers: Dict[str, tuple] = {}
        if not hasattr(self, "_v2_used_ports") or self._v2_used_ports is None:
            self._v2_used_ports: set = set()
        if not hasattr(self, "_v2_run_seq"):
            self._v2_run_seq = 0


    def _v2_launch_for_worktree(self, wt_path: Path) -> None:
        """为某 worktree 启动专属 dev-server 并登记（D2 派发前启动）。

        verify-process-lifecycle（D7 幂等 ensure）：worktree 已有**存活**注册
        条目时不重复启动（幂等）；条目缺失或进程已死时一律补启——修复 repair
        复用载体轮（runner 仅 create 分支启动 dev-server）无注册条目、
        `_v2_inject_env` 返回空、测试静默打主树 8787 的伴生缺陷。

        失败（端口耗尽/启动未就绪）记 WARNING 但**不阻断派发**：测试回退到
        PLAYWRIGHT/默认 8787（config/baseURL 缺省值），仅失去 worktree 隔离——
        比让整条 spec 失败更优。登记成功才写入 _v2_servers，供终态回收。
        """
        self._v2_ensure_state()
        entry = self._v2_servers.get(str(wt_path))
        if entry is not None and entry[1].poll() is None:
            # 存活实例在册：幂等 ensure，不重复启动（同 worktree 双实例互斥）
            return
        if entry is not None:
            # 条目陈旧（进程已死）：释放其端口记账，避免 used_ports 假性占用
            self._v2_used_ports.discard(entry[0])
        try:
            self._v2_run_seq += 1
            port, proc = v2_start_dev_server(
                wt_path, self._v2_run_seq, self._v2_used_ports, self._pm.logger)
            self._v2_servers[str(wt_path)] = (port, proc)
        except V2DevServerError as e:
            self._pm.logger.warning(
                "agent_runner",
                f"V2 dev-server launch failed for {wt_path} (tests fall back to "
                f"8787): {e}",
            )


    def _v2_inject_env(self, wt_path: Path) -> Dict[str, str]:
        """返回该 worktree 的 V2_BASE_URL 注入片段（D1 注入运行环境）。

        未启动 dev-server 时返回空 dict，agent 沿用 config 缺省 8787。
        """
        self._v2_ensure_state()
        entry = self._v2_servers.get(str(wt_path))
        if not entry:
            return {}
        return {"V2_BASE_URL": v2_base_url(entry[0])}


    def _v2_stop_for_worktree(self, wt_path: Path) -> None:
        """回收某 worktree 的 dev-server（D2 终态回收）。"""
        self._v2_ensure_state()
        entry = self._v2_servers.pop(str(wt_path), None)
        if entry is None:
            return
        port, proc = entry
        try:
            v2_stop_dev_server(proc, port, self._v2_used_ports, self._pm.logger)
        except Exception as e:  # 回收失败不阻断主流程
            self._pm.logger.warning(
                "agent_runner", f"V2 dev-server stop failed for {wt_path}: {e}")


    def _v2_stop_all(self) -> None:
        """daemon 关闭 / 异常恢复时回收全部在册 dev-server（D2）。"""
        self._v2_ensure_state()
        for wt_str in list(self._v2_servers.keys()):
            self._v2_stop_for_worktree(Path(wt_str))
