"""
watcher.py — Dashboard 数据源文件变更监听（VuePress 式推送的前端数据侧）。

把前端从「2 秒轮询」改为「服务端监听 + SSE 推送」：本模块轮询各受管项目
的 Dashboard 数据源文件（STATE.md / tasks.md / 验证产物 / run 产物 / 日志），
检测到变化后重组对应视图数据并交给 SSE Hub 广播。纯标准库，思路与
daemon 侧 event_bus.py 的 checksum 轮询一致。

事件类型（SSE Hub 广播的 payload 统一带 project 字段）：
- {type: "state",   overview, specs, details}  —— STATE.md / 日志变化
- {type: "detail",  spec, data}                —— 单个 SPEC 自己的文件变化
- {type: "run_meta", run_id, status}           —— run 状态转换（running→done/error）
- {type: "run_events", run_id, status, events[, reset]} —— 被订阅 run 的增量事件
"""

import threading
import time
from pathlib import Path

from . import data as dashboard_data

SCAN_INTERVAL = 1.0       # 数据源文件轮询周期（秒）
REFRESH_HEARTBEAT = 2.0   # 周期性刷新心跳（秒）：daemon 状态/新项目发现不产生文件变更，需周期推送


class FileWatcher:
    def __init__(self, projects_fn, hub, interval: float = SCAN_INTERVAL,
                 heartbeat: float | None = None):
        """projects_fn: 无参可调用，返回 [{"name", "path", "exists", ...}]。"""
        self.projects_fn = projects_fn
        self.hub = hub
        self.interval = interval
        self.heartbeat = heartbeat if heartbeat is not None else REFRESH_HEARTBEAT

        self._running = False
        self._thread = None
        self._sigs = {}        # project -> {str(path): (mtime_ns, size)}
        self._states = {}      # project -> parse_state() 快照（用于 STATE.md diff）
        self._run_base = {}    # (project, run_id) -> {"size": int, "status": str}

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="fenixd-dashboard-watcher",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        tick = 0
        while self._running:
            try:
                self.scan_once()
            except Exception:
                pass  # 监听绝不崩溃：单轮失败下轮重试
            # 周期性心跳：daemon 健康状态 / 新项目发现等变化不产生数据源文件变更，
            # scan_once 感知不到，需周期广播 refresh 让前端在 2s 自动刷新周期内反映
            tick += 1
            if tick * self.interval >= self.heartbeat:
                tick = 0
                try:
                    self.hub.broadcast({"type": "refresh"})
                except Exception:
                    pass
            time.sleep(self.interval)

    # ── 主扫描 ───────────────────────────────────────────────

    def scan_once(self):
        for proj in self.projects_fn():
            if not proj.get("exists"):
                continue
            try:
                self._scan_project(proj["name"], Path(proj["path"]))
            except Exception:
                continue

    def _scan_project(self, name: str, proot: Path):
        sigs = self._sigs.setdefault(name, {})
        seen = set()
        state_changed = False
        logs_changed = False
        spec_changed = set()
        run_changed = set()

        for kind, key, path in self._iter_project_files(proot):
            pkey = str(path)
            seen.add(pkey)
            try:
                st = path.stat()
                sig = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            if sigs.get(pkey) != sig:
                sigs[pkey] = sig
                if kind == "state":
                    state_changed = True
                elif kind == "logs":
                    logs_changed = True
                elif kind == "spec":
                    spec_changed.add(key)
                elif kind == "run":
                    run_changed.add(key)
        # 清理已删除文件
        for stale in [k for k in sigs if k not in seen]:
            del sigs[stale]

        if state_changed or logs_changed:
            self._handle_state_change(name, proot)
        for spec in spec_changed:
            self._handle_spec_change(name, proot, spec)
        for run_id in run_changed:
            self._handle_run_change(name, proot, run_id)

    # ── 数据源文件枚举 ───────────────────────────────────────

    @staticmethod
    def _iter_project_files(proot: Path):
        """产出 (kind, key, Path)。kind: state/spec/run/logs。"""
        state = proot / "STATE.md"
        if state.is_file():
            yield ("state", None, state)

        changes = proot / "openspec" / "changes"
        if changes.is_dir():
            for spec_dir in changes.iterdir():
                if not spec_dir.is_dir():
                    continue
                sname = spec_dir.name
                for fname in ("tasks.md", "verification-report.md"):
                    p = spec_dir / fname
                    if p.is_file():
                        yield ("spec", sname, p)
                specs_dir = spec_dir / "specs"
                if specs_dir.is_dir():
                    for p in specs_dir.rglob("*.md"):
                        if p.is_file():
                            yield ("spec", sname, p)

        vp = proot / ".fenix" / "verify-progress"
        if vp.is_dir():
            for p in vp.glob("*.json"):
                if p.is_file():
                    yield ("spec", p.stem, p)
            for d in vp.iterdir():
                if not d.is_dir():
                    continue
                sname = d.name
                for fname in ("report.json", "test_scenarios.json"):
                    p = d / fname
                    if p.is_file():
                        yield ("spec", sname, p)
                ss = d / "screenshots"
                if ss.is_dir():
                    for p in ss.iterdir():
                        if p.is_file():
                            yield ("spec", sname, p)

        runs = proot / ".fenix" / "runs"
        if runs.is_dir():
            for p in runs.glob("*.jsonl"):
                if p.is_file():
                    yield ("run", p.stem, p)

        logs = proot / ".fenix" / "logs"
        if logs.is_dir():
            for p in logs.glob("fenixd*.log"):
                if p.is_file():
                    yield ("logs", None, p)

    # ── 变化处理 ─────────────────────────────────────────────

    def _handle_state_change(self, name: str, proot: Path):
        """STATE.md / 日志变化：重组概览 + SPEC 列表 + 变更 SPEC 的详情。"""
        overview = dashboard_data.overview(self.projects_fn())
        cur = dashboard_data.parse_state(proot)
        prev = self._states.get(name, {})
        details = {}
        for spec, entry in cur.items():
            if prev.get(spec) != entry:
                try:
                    d = dashboard_data.spec_detail(proot, spec, entry)
                    d["project"] = name
                    details[spec] = d
                except Exception:
                    pass
        self._states[name] = cur

        specs = sorted(
            (dashboard_data.spec_summary(proot, n, e) for n, e in cur.items()),
            key=lambda s: s.get("created") or "", reverse=True,
        )
        # specs 必须与 GET /api/specs 同形（数组）：app.js 把 msg.specs 直接
        # 喂给 renderProject 的 data.specs，嵌套对象会令 specs.filter 抛 TypeError、
        # 视图停在旧 DOM（清障按钮等写操作因此看似"无效"）
        self.hub.broadcast({
            "project": name,
            "type": "state",
            "overview": overview,
            "specs": specs,
            "details": details,
        })

    def _handle_spec_change(self, name: str, proot: Path, spec: str):
        """单个 SPEC 自己的文件（tasks/验证产物/截图）变化：推送该 SPEC 详情。"""
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
        key = (name, run_id)
        prev = self._run_base.get(key)

        if prev is None:
            # 首次见到：仅建立基线（含状态），不推送（弹窗初始已通过 REST 拉到尾部）
            self._run_base[key] = {"size": size, "status": self._classify(run_file)}
            return

        if size == prev["size"]:
            return
        if size < prev["size"]:
            # 文件被截断/轮转：重置基线；订阅方收到 reset 后应重新拉取尾部
            status = self._classify(run_file)
            self._run_base[key] = {"size": size, "status": status}
            if self.hub.is_watched(run_id):
                self.hub.broadcast({
                    "project": name, "type": "run_events", "run_id": run_id,
                    "status": status, "reset": True,
                })
            return

        # 正常增长：读取新增字节
        new_events = dashboard_data.read_run_events_between(proot, run_id, prev["size"])
        status = self._classify(run_file)
        self._run_base[key] = {"size": size, "status": status}

        if new_events and self.hub.is_watched(run_id):
            self.hub.broadcast({
                "project": name, "type": "run_events", "run_id": run_id,
                "status": status, "events": new_events,
            })
        if status != prev["status"]:
            # 状态转换（running→done/error）：run 元数据/时间轴需刷新
            self.hub.broadcast({
                "project": name, "type": "run_meta", "run_id": run_id, "status": status,
            })

    @staticmethod
    def _classify(run_file: Path) -> str:
        """按产物最后几行判定运行终态（与 data.get_runs 一致，只读尾部 4KB）。"""
        lines = dashboard_data._read_run_lines(run_file, max_lines=3)
        return dashboard_data.classify_run(lines)
