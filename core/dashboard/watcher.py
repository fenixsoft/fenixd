"""
watcher.py — Dashboard 数据源文件变更监听（VuePress 式推送的前端数据侧）。

把前端从「2 秒轮询」改为「服务端监听 + SSE 推送」：本模块轮询各受管项目
的 Dashboard 数据源文件（STATE.md / tasks.md / 验证产物 / run 产物 / 日志），
检测到变化后重组对应视图数据并交给 SSE Hub 广播。纯标准库，思路与
daemon 侧 event_bus.py 的 checksum 轮询一致。

事件类型（SSE Hub 广播的 payload 统一带 project 字段）：
- {type: "state",   project, specs, details, overview: null}  —— 增量形态
  （dashboard-incremental-watcher D2）：specs 仅列变更 spec 的摘要
  （新增/变更带 summary，删除以 summary:null 标记），details 仅含变更 spec 的详情，
  overview 恒为 null（D3：前端本地归并统计，30s 心跳校准）
- {type: "detail",  spec, data}    —— 单个 SPEC 自己的文件变化（保留，兼容详情弹窗）
- {type: "run_meta", run_id, status}           —— run 状态转换（running→done/error）
- {type: "run_events", run_id, status, events[, reset]} —— 被订阅 run 的增量事件
- {type: "admin_activities", project}          —— .fenix/admin_alerts.json 变化
  （add-admin-invoke-dialog：弹窗打开时前端据此重新拉取该 SPEC 的处置记录）

监视模型（dashboard-incremental-watcher D7，两级签名跳层 + 索引兜底）：
- **一级（顶层源）**：每项目 stat 固定集合（STATE.md、spec/changes、
  .fenix/verify-progress、.fenix/admin_alerts.json），签名变化进入子树枚举。
- **二级（spec 目录）**：每轮对 changes/ 下全部 spec 目录做目录级 stat
  （O(N) 目录 stat，10000 spec ≈ 10ms 页缓存）；目录签名未变则跳过该 spec。
  目录签名含 ctime，能捕获 spec 目录新增/删除/原子替换（os.replace 会更新
  父目录 mtime）。
- **索引兜底（文件级）**：一旦任何粗粒度信号触发，`_handle_state_change` 经
  `SummaryIndex.get()` 做文件级签名比对——未变 spec 直返缓存、变化 spec 只重算，
  再与上次广播基线 diff，specs 只列新增/变更/删除。这覆盖目录级签名对
  write_text 纯净内容改写不敏感的场景（Linux 上 write_text 不更新父目录 mtime，
  但 pm_engine/verify 报告写入与 STATE.md 原子替换会更新目录签名）。
- run/logs 属小集合（活跃 runs 有界性由「终态即移出」保证——daemon 周期保留
  清理移入归档、归档受 runs.keep 上限约束缺省 50；日志数只 1~3 个），逐文件
  stat 成本恒定；
  spec 树才是 10000 规模下 stat 的大头。
"""

import logging
import threading
import time
from pathlib import Path

from . import data as dashboard_data

# 可传播到 fenixd 已挂载 handler 的结构化日志器（同 registry.py：收敛旁路裸
# getLogger(__name__)，保证 WARNING 落盘）
logger = logging.getLogger("fenixd.dashboard.watcher")

SCAN_INTERVAL = 1.0  # 数据源文件轮询周期（秒）
REFRESH_HEARTBEAT = 2.0  # 周期性刷新心跳（秒）：daemon 状态/新项目发现不产生文件变更，需周期推送


def _dir_sig(p: Path):
    """目录签名 (mtime_ns, size, ctime_ns)；缺失返回 None。"""
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ctime_ns)


def _file_sig(p: Path):
    """文件签名 (mtime_ns, size)；缺失返回 None。"""
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class FileWatcher:
    def __init__(
        self,
        projects_fn,
        hub,
        interval: float = SCAN_INTERVAL,
        heartbeat: float | None = None,
        summary_index=None,
    ):
        """projects_fn: 无参可调用，返回 [{"name", "path", "exists", ...}]。
        summary_index: 可选，共享的 SummaryIndex（与 server 同实例）；缺省自建。
        """
        self.projects_fn = projects_fn
        self.hub = hub
        self.interval = interval
        self.heartbeat = heartbeat if heartbeat is not None else REFRESH_HEARTBEAT
        self.summary_index = summary_index or dashboard_data.SummaryIndex()

        self._running = False
        self._thread = None
        # 项目级缓存统一以项目路径（proot.as_posix()）为键，见 _prune_stale_caches
        self._top_sigs = {}  # project path -> {kind: sig}（state/vp/admin）
        self._spec_dirs = {}  # project path -> {spec_name: 目录签名}
        self._last_summaries = {}  # project path -> {spec_name: summary dict}（增量 diff 基线）
        self._run_base = {}  # (project path, run_id) -> {"size": int, "status": str}
        self._log_sigs = {}  # project path -> {log_path: (mtime_ns, size)}
        self._proj_scan_warn = {}  # project -> 上次扫描失败告警时刻（monotonic 秒，5 分钟节流）

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="fenixd-dashboard-watcher", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        tick = 0
        last_scan_warn = 0.0  # scan_once 持续失败告警节流（monotonic 秒）
        last_hb_warn = 0.0  # 心跳广播失败告警节流（monotonic 秒）
        while self._running:
            try:
                self.scan_once()
            except Exception as e:  # 监听绝不崩溃：单轮失败下轮重试
                now = time.monotonic()
                if now - last_scan_warn >= 300:  # 低频节流：持续失败约 5 分钟记一条
                    last_scan_warn = now
                    logger.warning(
                        "dashboard watcher scan_once 失败: %s: %s", type(e).__name__, e
                    )
            # 周期性心跳：daemon 健康状态 / 新项目发现等变化不产生数据源文件变更，
            # scan_once 感知不到，需周期广播 refresh 让前端在心跳周期内反映
            tick += 1
            if tick * self.interval >= self.heartbeat:
                tick = 0
                try:
                    self.hub.broadcast({"type": "refresh"})
                except Exception as e:
                    now = time.monotonic()
                    if now - last_hb_warn >= 300:
                        last_hb_warn = now
                        logger.warning(
                            "dashboard watcher 心跳广播失败: %s: %s",
                            type(e).__name__,
                            e,
                        )
            time.sleep(self.interval)

    # ── 主扫描 ───────────────────────────────────────────────

    def scan_once(self):
        projects = self.projects_fn()
        for proj in projects:
            if not proj.get("exists"):
                continue
            try:
                self._scan_project(proj["name"], Path(proj["path"]))
            except Exception as e:  # 单项目失败不拖垮整轮；低频节流告警（同 _loop 5 分钟纪律）
                now = time.monotonic()
                key = proj.get("path") or proj["name"]
                if now - self._proj_scan_warn.get(key, 0.0) >= 300:
                    self._proj_scan_warn[key] = now
                    logger.warning(
                        "dashboard watcher 扫描项目 %s 失败: %s: %s",
                        proj["name"],
                        type(e).__name__,
                        e,
                    )
                continue
        # 项目集变化后剔除消失项目的缓存（长驻进程防无界累积）
        self._prune_stale_caches(projects)

    def _prune_stale_caches(self, projects: list):
        """projects_fn 返回集变化后，剔除已消失项目的全部缓存条目。

        全部项目级缓存统一以项目路径为键：项目从 registry 删除或更名（路径
        变化）后旧键不再残留，同目录更名也不会导致基线失效重建。仍在 registry
        但 exists=False 的项目保留缓存，路径恢复后基线继续有效。
        """
        live = {Path(p["path"]).as_posix() for p in projects if p.get("path")}
        for cache in (self._top_sigs, self._spec_dirs, self._last_summaries, self._log_sigs):
            for k in [k for k in cache if k not in live]:
                del cache[k]
        for k in [k for k in self._run_base if k[0] not in live]:
            del self._run_base[k]

    def _scan_project(self, name: str, proot: Path):
        top_sigs = self._top_sigs.setdefault(proot.as_posix(), {})
        admin_changed = False

        # ── 第一级：顶层数据源签名（O(少数) stat） ──
        state_path = proot / ".fenix" / "STATE.md"
        sig = _file_sig(state_path)
        state_changed = sig != top_sigs.get("state")
        top_sigs["state"] = sig

        vp_changed = False
        vp_path = proot / ".fenix" / "verify-progress"
        vsig = _dir_sig(vp_path)
        if vsig != top_sigs.get("vp"):
            vp_changed = True
            top_sigs["vp"] = vsig

        admin_path = proot / ".fenix" / "admin_alerts.json"
        asig = _file_sig(admin_path)
        if asig != top_sigs.get("admin"):
            admin_changed = True
            top_sigs["admin"] = asig

        # 日志追加：fenixd.log append-only，目录签名不变但文件签名变，逐文件比对
        logs_changed = self._scan_logs(proot)

        # run 产物：小集合逐文件 size 比对（增量推送基线）
        run_changed = self._scan_runs(proot)

        # ── 第二级：spec 目录级签名（每轮 O(N) 目录 stat，不做文件级） ──
        spec_dir_changed, spec_removed = self._scan_spec_dirs(proot)

        # 汇总分发
        #   spec 内容/存在相关信号 → SummaryIndex 文件级 diff（新增/变更/删除）
        if state_changed or vp_changed or spec_dir_changed or spec_removed:
            self._handle_state_change(name, proot, removed=spec_removed)
        #   仅日志变化 → 轻量空增量（前端不刷新列表；跑马灯等靠心跳校准）
        elif logs_changed:
            self.hub.broadcast(
                {
                    "project": name,
                    "type": "state",
                    "specs": [],
                    "details": {},
                    "overview": None,
                }
            )
        # spec 目录变化额外推详情（列表摘要归 state 事件；详情供详情弹窗刷新）
        for spec in spec_dir_changed:
            self._handle_spec_change(name, proot, spec)
        for run_id in run_changed:
            self._handle_run_change(name, proot, run_id)
        if admin_changed:
            self._handle_admin_change(name)

    # ── 第二级：spec 目录签名跳层 ────────────────────────────

    def _scan_spec_dirs(self, proot: Path) -> tuple:
        """枚举 changes/ 下全部 spec 目录，目录级签名跳层。

        返回 (changed: set[str], removed: set[str])。目录签名未变 → 跳过该 spec
        的文件级 stat（跳层核心）。文件级最终判定交给 _handle_state_change 经
        SummaryIndex 完成（文件级签名 + 只重算变化 spec）。
        """
        changes = proot / "spec" / "changes"
        spec_dirs = self._spec_dirs.setdefault(proot.as_posix(), {})
        changed = set()
        removed = set()

        seen = set()
        if changes.is_dir():
            try:
                entries = list(changes.iterdir())
            except OSError:
                entries = []
            for d in entries:
                if not d.is_dir():
                    continue
                sname = d.name
                seen.add(sname)
                dsig = _dir_sig(d)
                if dsig is None:
                    continue
                prev_dsig = spec_dirs.get(sname)
                spec_dirs[sname] = dsig
                if prev_dsig is None or prev_dsig != dsig:
                    changed.add(sname)
        for stale in [k for k in spec_dirs if k not in seen]:
            del spec_dirs[stale]
            removed.add(stale)
        return changed, removed

    # ── runs / logs / admin（小集合逐文件比对） ──────────────

    def _scan_runs(self, proot: Path) -> set:
        """run 产物：沿用既有 size 基线机制，返回应触发 _handle_run_change 的 run_id。

        活跃 runs 目录有界性由「终态即移出」保证（daemon 周期保留清理把终态
        移入归档），归档目录受 runs.keep 上限约束（缺省 50）——逐文件 stat
        成本恒定。
        """
        runs_dir = proot / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return set()
        run_changed = set()
        try:
            run_files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return set()
        active = set()
        for p in run_files:
            run_id = p.stem
            active.add(run_id)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            key = (proot.as_posix(), run_id)
            prev = self._run_base.get(key)
            if prev is None or size != prev["size"]:
                run_changed.add(run_id)
        for k in [k for k in self._run_base if k[0] == proot.as_posix() and k[1] not in active]:
            del self._run_base[k]
        return run_changed

    def _scan_logs(self, proot: Path) -> bool:
        """fenixd*.log 文件签名比对；任一变化（追加/轮转）返回 True。"""
        logs_dir = proot / ".fenix" / "logs"
        if not logs_dir.is_dir():
            return False
        cache = self._log_sigs.setdefault(proot.as_posix(), {})
        changed = False
        try:
            log_files = list(logs_dir.glob("fenixd*.log"))
        except OSError:
            return False
        seen = set()
        for p in log_files:
            pkey = str(p)
            seen.add(pkey)
            sig = _file_sig(p)
            if sig is None:
                continue
            if cache.get(pkey) != sig:
                cache[pkey] = sig
                changed = True
        for stale in [k for k in cache if k not in seen]:
            del cache[stale]
            changed = True
        return changed

    # ── 变化处理 ─────────────────────────────────────────────

    def _handle_state_change(self, name: str, proot: Path, removed: set = None):
        """增量 state 事件（dashboard-incremental-watcher D2/D3）。

        变化发生后经 SummaryIndex.get() 做文件级签名比对（未变直返缓存、变化只
        重算），再把新摘要与上次广播基线 diff——specs 只列新增/变更/删除。
        overview 不再由 watcher 计算下发（D3：前端本地归并统计，30s 心跳校准）。
        """
        removed = removed or set()
        cur = dashboard_data.parse_state(proot)

        state_sig = _file_sig(proot / ".fenix" / "STATE.md")
        try:
            summaries = self.summary_index.get(proot, cur, state_sig=state_sig)
        except Exception:
            summaries = [dashboard_data.spec_summary(proot, s, e) for s, e in cur.items()]
        new_map = {s.get("name"): s for s in summaries}
        prev_map = self._last_summaries.get(proot.as_posix(), {})

        specs_out = []
        details = {}
        # 变更/新增：specs 只列与上次基线不同的 spec（携带实时摘要），
        # details 仅含变更 spec 的详情（D2：只带变更 spec）
        for spec in sorted(new_map):
            if prev_map.get(spec) == new_map[spec]:
                continue  # 未变：不推
            specs_out.append({"spec": spec, "summary": new_map[spec]})
            entry = cur.get(spec)
            if entry is not None:
                try:
                    d = dashboard_data.spec_detail(proot, spec, entry)
                    d["project"] = name
                    details[spec] = d
                except Exception:
                    pass
        # 删除：STATE.md 移除或 spec 目录删除 → summary:null 标记。
        # 目录删除但 STATE.md 仍保留条目时，索引仍返回 archived 摘要——按目录级
        # 信号优先，推 null 让前端本地表删除该行。
        deleted = (set(prev_map) - set(new_map)) | removed
        for spec in sorted(deleted):
            specs_out.append({"spec": spec, "summary": None})

        self._last_summaries[proot.as_posix()] = new_map
        self.hub.broadcast(
            {
                "project": name,
                "type": "state",
                "specs": specs_out,
                "details": details,
                "overview": None,
            }
        )

    def _handle_spec_change(self, name: str, proot: Path, spec: str):
        """单个 SPEC 自己的文件变化：推送该 SPEC 详情（detail 事件）。"""
        entry = dashboard_data.parse_state(proot).get(spec)
        if entry is None:
            return
        try:
            d = dashboard_data.spec_detail(proot, spec, entry)
        except Exception:
            return
        d["project"] = name
        self.hub.broadcast({"project": name, "type": "detail", "spec": spec, "data": d})

    def _handle_run_change(self, name: str, proot: Path, run_id: str):
        """run 产物文件变化：状态转换推 run_meta；被订阅的 run 推增量事件。"""
        run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        try:
            size = run_file.stat().st_size
        except OSError:
            return
        key = (proot.as_posix(), run_id)
        prev = self._run_base.get(key)

        if prev is None:
            # 首次见到：仅建立基线（含状态），不推送（弹窗初始已通过 REST 拉到尾部）
            self._run_base[key] = {"size": size, "status": self._classify(run_file)}
            return

        prev_size = prev["size"]
        if size == prev_size:
            return
        if size < prev_size:
            # 文件被截断/轮转：重置基线；订阅方收到 reset 后应重新拉取尾部
            status = self._classify(run_file)
            self._run_base[key] = {"size": size, "status": status}
            if self.hub.is_watched(run_id):
                self.hub.broadcast(
                    {
                        "project": name,
                        "type": "run_events",
                        "run_id": run_id,
                        "status": status,
                        "reset": True,
                    }
                )
            return

        # 正常增长：基线对所有活跃 run 持续维护（status 转换广播不依赖订阅，
        # 且未订阅 run 也需跟踪 size，保证订阅后首轮增量起点正确）
        status = self._classify(run_file)

        if self.hub.is_watched(run_id):
            # 仅被订阅的 run 才读取新增字节并解析事件。先读增量、成功后才推进
            # 基线：read_run_events_between 读失败（并发归档/移除等 OSError）
            # 返回 None 区别于「无新增」的 []，此时保留旧基线，下一轮扫描
            # 重读同一区间，避免这段事件被永久跳过（item 522789f55ab8）。
            new_events = dashboard_data.read_run_events_between(proot, run_id, prev_size)
            if new_events is not None:
                self._run_base[key] = {"size": size, "status": status}
        else:
            new_events = []
            self._run_base[key] = {"size": size, "status": status}

        if new_events:
            self.hub.broadcast(
                {
                    "project": name,
                    "type": "run_events",
                    "run_id": run_id,
                    "status": status,
                    "events": new_events,
                }
            )
        if status != prev["status"]:
            # 状态转换（running→done/error）：run 元数据/时间轴需刷新
            self.hub.broadcast(
                {
                    "project": name,
                    "type": "run_meta",
                    "run_id": run_id,
                    "status": status,
                }
            )

    def _handle_admin_change(self, name: str):
        """admin_alerts.json 变化（add-admin-invoke-dialog）：广播轻量通知。"""
        self.hub.broadcast({"project": name, "type": "admin_activities"})

    @staticmethod
    def _classify(run_file: Path) -> str:
        """按产物最后几行判定运行终态（与 data.get_runs 一致，只读尾部 4KB）。"""
        lines = dashboard_data._read_run_lines(run_file, max_lines=3)
        return dashboard_data.classify_run(lines)
