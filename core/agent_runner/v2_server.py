"""v2_server.py — V2ServerManager：per-run 隔离测试服务器生命周期（add-worktree-test-server）。

状态同迁（design D3 规则 1）：_v2_servers / _v2_used_ports / _v2_run_seq 随组件
迁移；门面经 property 委托保持 `runner._v2_servers` 等路径可用。
"""

import subprocess
import threading
from typing import Dict, Tuple
from pathlib import Path
from core.v2_dev_server import (
    V2DevServerError,
    start as v2_start_dev_server,
    stop as v2_stop_dev_server,
    base_url as v2_base_url,
)


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
        # 实例级互斥锁：_v2_servers/_v2_used_ports/_v2_run_seq 的读改写整体纳入
        # 临界区——launch/stop/stop_all 的调用方分布在并行派发车道（repair_lane/
        # fast_track）与多处终态收割点，多步序列无锁时 stop 可在 launch 登记前
        # 弹出条目，泄漏已启动的 dev-server（进程不在册、端口被 used_ports 永久
        # 占用）。慢操作（子进程启动 / terminate·wait）保持在临界区外，只保护
        # 共享结构的读改写。端口记账归属：_v2_used_ports 的 add/discard 全部
        # 发生在本组件临界区内——v2_dev_server.start/stop 拿到的是快照副本或
        # None，其内部记账不触碰共享集合，由本组件在锁内同步记账。
        self._v2_lock = threading.Lock()

    def _v2_ensure_state(self) -> None:
        """惰性初始化 V2 状态（设计容错：部分测试以 ``AgentRunner.__new__`` 绕过
        ``__init__`` 构造实例，此时实例属性未建立；访问前补齐默认值避免 AttributeError，
        行为与 daemon 正常 __init__ 路径一致）。
        """
        if not hasattr(self, "_v2_servers") or self._v2_servers is None:
            self._v2_servers: Dict[str, Tuple] = {}
        if not hasattr(self, "_v2_used_ports") or self._v2_used_ports is None:
            self._v2_used_ports: set = set()
        if not hasattr(self, "_v2_run_seq"):
            self._v2_run_seq = 0
        if not hasattr(self, "_v2_lock") or self._v2_lock is None:
            self._v2_lock = threading.Lock()

    def _v2_launch_for_worktree(self, wt_path: Path) -> None:
        """为某 worktree 启动专属 dev-server 并登记（D2 派发前启动）。

        verify-process-lifecycle（D7 幂等 ensure）：worktree 已有**存活**注册
        条目时不重复启动（幂等）；条目缺失或进程已死时一律补启——修复 repair
        复用载体轮（runner 仅 create 分支启动 dev-server）无注册条目、
        `_v2_inject_env` 返回空、测试静默打主树 8787 的伴生缺陷。

        失败（端口耗尽/启动未就绪）记 WARNING 但**不阻断派发**：测试回退到
        PLAYWRIGHT/默认 8787（config/baseURL 缺省值），仅失去 worktree 隔离——
        比让整条 spec 失败更优。登记成功才写入 _v2_servers，供终态回收。

        launch-vs-launch 竞态封堵：幂等检查与登记分处慢速启动（子进程拉起 +
        就绪等待）两侧，同 worktree 并发 launch 可能双双通过检查各自启动。
        故 run_seq 在锁内预留为局部变量（防锁外读漂移）；启动成功后回锁二次
        复核——窗口期内已出现他者登记的存活条目时让位（锁外停掉自己刚启动的
        进程，不登记、不记账）；失败清理仅按 identity 移除自己确认过的陈旧
        条目，不动他者条目。
        """
        self._v2_ensure_state()
        stale_entry = None
        with self._v2_lock:
            key = str(wt_path)
            entry = self._v2_servers.get(key)
            if entry is not None and entry[1].poll() is None:
                # 存活实例在册：幂等 ensure，不重复启动（同 worktree 双实例互斥）
                return
            if entry is not None:
                # 条目陈旧（进程已死）：释放其端口记账，避免 used_ports 假性占用；
                # 留存条目对象，失败清理路径仅在原样在册时移除（identity 匹配）。
                self._v2_used_ports.discard(entry[0])
                stale_entry = entry
            self._v2_run_seq += 1
            run_seq = self._v2_run_seq  # 序号锁内预留：锁外只读局部变量，防并发漂移
            # 端口记账快照：start 内部的 used_ports.add 只落快照副本，共享集合
            # 的写入收敛到下方临界区（与 _v2_lock 注释声称的覆盖口径一致）。
            used_snapshot = set(self._v2_used_ports)
        loser = None
        try:
            port, proc = v2_start_dev_server(
                wt_path, run_seq, used_snapshot, self._pm.logger
            )
            with self._v2_lock:
                current = self._v2_servers.get(key)
                if current is not None and current[1].poll() is None:
                    # 窗口期内他者已登记存活条目：让位复用，不得覆盖——覆盖会使
                    # 首个实例脱管（进程不在册、端口被 used_ports 永久占用）。
                    # 自己的实例尚未登记、端口未入共享记账（start 只写快照副本），
                    # 锁外停掉即可，无需 discard。
                    loser = (port, proc)
                else:
                    if current is not None:
                        # 覆写窗口期内他者登记的死亡条目：其端口登记时已入共享记账，
                        # 覆写前补 discard 释放，与 launch/inject 侧陈旧条目处理口径
                        # 对齐（discard 对不在集合的端口安全，即使端口与本次相同也
                        # 先释后记无副作用），避免死亡端口滞留 used_ports 缩池。
                        self._v2_used_ports.discard(current[0])
                    self._v2_servers[key] = (port, proc)
                    self._v2_used_ports.add(port)
        except V2DevServerError as e:
            # 启动失败：仅当本线程锁内确认过的陈旧条目原样在册时才移除（identity
            # 匹配），保证 _v2_inject_env 拿不到死端口条目、返回空 dict，测试按
            # 承诺回退 PLAYWRIGHT/缺省 8787，而非向 agent 注入失效端口的
            # V2_BASE_URL 造成假失败；窗口期内他者登记的条目一律不碰。
            with self._v2_lock:
                if stale_entry is not None and self._v2_servers.get(key) is stale_entry:
                    self._v2_servers.pop(key, None)
            self._pm.logger.warning(
                "agent_runner",
                f"V2 dev-server launch failed for {wt_path} (tests fall back to " f"8787): {e}",
            )
        if loser is not None:
            # 让位回收在锁外进行（terminate·wait 慢操作不进临界区，与 _v2_lock
            # 注释口径一致）；回收失败不阻断主流程。
            try:
                v2_stop_dev_server(loser[1], loser[0], None, self._pm.logger)
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner", f"V2 dev-server loser stop failed for {wt_path}: {e}"
                )

    def _v2_inject_env(self, wt_path: Path) -> Dict[str, str]:
        """返回该 worktree 的 V2_BASE_URL 注入片段（D1 注入运行环境）。

        未启动 dev-server 时返回空 dict，agent 沿用 config 缺省 8787。
        """
        self._v2_ensure_state()
        with self._v2_lock:
            entry = self._v2_servers.get(str(wt_path))
            if not entry:
                return {}
            if entry[1].poll() is not None:
                # 条目陈旧（进程已死）：与 launch 侧陈旧条目处理口径对齐——清理条目
                # 并释放端口记账，按未启动处理返回空 dict，绝不向 agent 注入失效端口
                # 的 V2_BASE_URL 造成测试假失败。
                self._v2_servers.pop(str(wt_path), None)
                self._v2_used_ports.discard(entry[0])
                return {}
        return {"V2_BASE_URL": v2_base_url(entry[0])}

    def _v2_stop_for_worktree(self, wt_path: Path) -> None:
        """回收某 worktree 的 dev-server（D2 终态回收）。"""
        self._v2_ensure_state()
        with self._v2_lock:
            entry = self._v2_servers.pop(str(wt_path), None)
        if entry is None:
            return
        port, proc = entry
        try:
            # used_ports 传 None：stop 内部不触碰共享记账，端口释放收敛到下方
            # 临界区（与 _v2_lock 注释声称的覆盖口径一致）。
            v2_stop_dev_server(proc, port, None, self._pm.logger)
            with self._v2_lock:
                self._v2_used_ports.discard(port)
        except Exception as e:  # 回收失败不阻断主流程
            # 条目既已弹出，无论底层进程死活，daemon 都失去了该 server 的全部管理
            # 句柄（_v2_stop_all 与 launch/inject 侧回收均按 _v2_servers 键触达），
            # 端口记账留着只缩池无保护作用：锁内释放，避免失败次数单调缩池；孤儿
            # 真占住端口时由后续 start 绑定失败走 V2DevServerError 降级路径（与
            # launch 侧陈旧条目 discard 口径一致）。
            with self._v2_lock:
                self._v2_used_ports.discard(port)
            self._pm.logger.warning("agent_runner", f"V2 dev-server stop failed for {wt_path}: {e}")

    def _v2_stop_all(self) -> None:
        """daemon 关闭 / 异常恢复时回收全部在册 dev-server（D2）。"""
        self._v2_ensure_state()
        # 条目快照在临界区内取；逐个回收在锁外进行——_v2_stop_for_worktree 内部
        # 会再取同一把非重入锁，临界区内直接调用会自死锁。
        with self._v2_lock:
            wt_keys = list(self._v2_servers.keys())
        for wt_str in wt_keys:
            self._v2_stop_for_worktree(Path(wt_str))
