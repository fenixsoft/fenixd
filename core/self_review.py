"""self_review.py — 每日定时自省（add-daily-self-review spec）。

每晚本地时间 ``admin.self_review.run_at``（缺省 02:00）后，由 Administrator
通道执行一次工作回顾：聚合执行前 24 小时的数据摘要（STATE 终态 / runs 统计 /
admin 告警与处置 / 日志 ERROR / 近 3 日 git 提交五源）→ 发起 ``self-review``
run → 按 resolved 移除已闭环历史条目 + 追加写入项目 ``.fenix/todo.md``
→ 单文件 commit + push。

调度判定挂在 admin_monitor 巡检循环（design D1，不新增线程/定时器）：
每轮巡检检查「enabled && 本地时间 ≥ run_at && 今日未执行」→ 触发。天然
获得补跑（run_at 后首轮巡检即跑）与同日防重复（状态文件 last_run_date）。
失败当日不重试（也写 last_run_date，防风暴），次日 run_at 后自然重试。

自然日触发 + 增量窗口（2026-09-08 用户决策，原地修改）：调度防重复回归
「last_run_date == 今天」，数据聚合与活动判定窗口 = [last_run_at, now]
增量——每天 run_at 检查上次执行以来是否有 SPEC 活动，有则在 run_at 执行，
审查范围即该窗口内产生的 spec/告警/运维记录。取代 24h 滚动窗口（09-08
事故：一次迟到补跑把 24h 锚点拖到白天，此后 02:00 永久失效——滚动窗口
与「每晚 run_at」意图冲突）。无 last_run_at（首跑/旧格式状态文件）回退
24h 窗口；手动触发通道 = 删除状态文件（或把 last_run_date 改为昨日）。

零活动防护（2026-09-05 用户决策，窗口 09-08 起为增量窗口）：窗口内无任何
SPEC run（``review-`` 前缀自省 run 已排除）→ 不发起 run、不唤醒 admin，
仅在 todo.md 记一句「自上次自省以来无 SPEC 活动，跳过自省。」占位（裸
bullet，不进闭环判定条目），照常提交与写状态文件。

硬约束（spec「禁止自动创建 SPEC」）：本模块及自省链路 MUST NOT 创建
spec/changes 条目、注册 STATE.md 条目或派发任何 agent——产出仅供用户
阅读判定。token 归账到 cost-observability 独立类目（.fenix/cost/），
不写 STATE（避免混入 spec 状态表）。
"""

import ast
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.config import SELF_REVIEW_DEFAULT_RUN_AT

# 状态文件（.fenix/self_review_state.json，与 admin_alerts.json 同目录同风格）
STATE_FILE = "self_review_state.json"

# review 输出实例文件前缀：每 run 独立 .fenix/self_review_out-<run_id>.json，
# 与 admin_disposition-<run_id>.json 同模式（并行实例互不覆盖）。
REVIEW_OUT_PREFIX = "self_review_out-"

# 闭环移除窗口（自省启动时处理「前面 3 天」的记录）：只收集/移除运行日
# D-1..D-3 的条目，更早的历史日期节保留不动。模块常量而非配置键。
CLEANUP_WINDOW_DAYS = 3

# todo.md 结构标题正则：## YYYY-MM-DD 日期节 / ### 小节。
_TODO_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
_TODO_SECTION_RE = re.compile(r"^### (.+?)\s*$")

# 空小节占位（_append_todo 写入）；收集闭环判定条目时排除。
_EMPTY_MARKER = "（当日无）"

# 秒挂（instant-hang）签名：错误文本命中即归类为秒挂（claude 启动即死）。
_INSTANT_FAIL_PATTERNS = (
    "No conversation found with session ID",
    "unrecognized_model",
)

# run_id 内嵌开始时间戳（int(time.time())）的匹配模式（与 data.get_runs 同口径）。
_RUN_TS_RE = re.compile(r"-(\d{9,10})(?:-a\d+)?$")


# 结构化条目契约键（_rescue_structured_entry 判定 + dict 渲染共用）。
_STRUCTURED_ENTRY_KEYS = {"impact", "evidence", "analysis", "suggestion"}


def _rescue_structured_entry(text: str) -> Optional[dict]:
    """dict-repr 字符串 → 结构化条目 dict（仅当解析结果含契约键）。

    历史解析层（09-08 前）把 agent 合规输出的 dict 无差别 str() 成
    dict-repr 字符串，渲染层按旧字符串透传退化为机器形态。此处在渲染
    入口做纵深防御：ast.literal_eval 只接受字面量、不执行代码，解析失败
    或结果非含任一契约键的 dict → None（调用方按旧字符串透传）。
    """
    try:
        obj = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    if isinstance(obj, dict) and _STRUCTURED_ENTRY_KEYS & obj.keys():
        return obj
    return None


def local_today_str() -> str:
    """本地自然日字符串 YYYY-MM-DD（todo 日期节与状态文件均按本地时间）。"""
    return datetime.now().date().isoformat()


def _iso_to_local_dt(iso_str: Optional[str]) -> Optional[datetime]:
    """ISO 时间戳（含 Z 后缀）→ 本地 naive datetime；解析失败返回 None。"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _in_window(dt: Optional[datetime], window_start: datetime) -> bool:
    """naive 本地 datetime 是否落在 [window_start, now] 窗口内。"""
    if dt is None:
        return False
    return window_start <= dt <= datetime.now()


def _parse_run_at(run_at: str, today) -> datetime:
    """把 'HH:MM' 解析为 today（date 对象）当日的本地 datetime；非法回退缺省
    （单源自 core.config.SELF_REVIEW_DEFAULT_RUN_AT）。"""
    try:
        hh, mm = str(run_at).split(":")
        return datetime(today.year, today.month, today.day, int(hh), int(mm), 0)
    except (ValueError, AttributeError):
        hh, mm = SELF_REVIEW_DEFAULT_RUN_AT.split(":")
        return datetime(today.year, today.month, today.day, int(hh), int(mm), 0)


def _run_start_ts(run_id: str) -> Optional[int]:
    """从 run_id 提取内嵌开始时间戳（unix 秒）；无法解析返回 None（回退文件 mtime）。"""
    m = _RUN_TS_RE.search(run_id)
    return int(m.group(1)) if m else None


def _read_run_tail(path: Path, max_lines: int = 3) -> list:
    """读取 run 产物文件末尾若干行并逐行 JSON 解析（跳过噪声行）。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    lines = []
    for line in raw[-max_lines:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            lines.append(parsed)
    return lines


def _classify_run(run_id: str, lines: list) -> tuple:
    """按产物终态分类一条 run：返回 (category, detail)。

    category ∈ {succeeded, failed, instant_hang, timeout, dropped, running}。
    - succeeded: 终态 result
    - timeout:   终态 error 且文本含超时信号
    - instant_hang: 终态 error 且文本命中秒挂签名
    - failed:    其余终态 error
    - dropped:   空文件 / 无任何事件
    - running:   有事件但无终态（在跑或异常残留）
    """
    if not lines:
        return "dropped", "empty"
    last = lines[-1]
    if not isinstance(last, dict):
        return "running", "no-terminal"
    t = last.get("type")
    if t == "result":
        return "succeeded", ""
    if t != "error":
        return "running", "no-terminal"
    text = str(last.get("error") or "")
    if "Timeout after" in text or "run timeout" in text:
        return "timeout", text[:140]
    if any(p in text for p in _INSTANT_FAIL_PATTERNS):
        return "instant_hang", text[:140]
    return "failed", text[:140]


def collect_runs_stats(project_root, window_start: datetime) -> Dict[str, int]:
    """近 24 小时窗口 runs 统计（成功/失败/秒挂/超时/丢弃/在跑），排除
    self-review run 自身。

    窗口 = [window_start, now]，按 run_id 内嵌开始时间戳判定归属（缺失回退
    文件 mtime），与 get_runs 的解析口径一致。产物文件只读，不触发任何写操作。
    """
    counts = {"total": 0, "succeeded": 0, "failed": 0, "instant_hang": 0,
              "timeout": 0, "dropped": 0, "running": 0}
    runs_dir = Path(project_root) / ".fenix" / "runs"
    if not runs_dir.is_dir():
        return counts
    try:
        files = list(runs_dir.glob("*.jsonl"))
    except OSError:
        return counts
    for p in files:
        run_id = p.stem
        if run_id.startswith("review-"):
            continue  # 自省 run 不审视自身
        try:
            stat = p.stat()
        except OSError:
            continue
        start_ts = _run_start_ts(run_id)
        ts = start_ts if start_ts is not None else int(stat.st_mtime)
        if not _in_window(datetime.fromtimestamp(ts), window_start):
            continue
        category, _detail = _classify_run(run_id, _read_run_tail(p, 3))
        counts["total"] += 1
        counts[category] += 1
    return counts


def collect_log_errors(project_root, window_start: datetime,
                       limit: int = 20) -> Dict[str, Any]:
    """近 24 小时窗口 fenixd.log ERROR 聚合：总数 + 最近 limit 条样本
    （含时间戳/组件/消息）。"""
    log_path = Path(project_root) / ".fenix" / "logs" / "fenixd.log"
    errors: List[dict] = []
    if log_path.is_file():
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("level") != "ERROR":
                        continue
                    if not _in_window(_iso_to_local_dt(entry.get("timestamp")),
                                      window_start):
                        continue
                    errors.append(entry)
        except OSError:
            pass
    samples = [
        f"{e.get('timestamp', '')} [{e.get('component', '')}] "
        f"{str(e.get('message', ''))[:200]}"
        for e in errors[-limit:]
    ]
    return {"error_count": len(errors), "samples": samples}


def parse_todo_blocks(text: str) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    """todo.md 全文 → (前置行, [(日期, 节体行), ...])。

    日期节以 ``## YYYY-MM-DD`` 起，节体不含该标题行；非日期的 ``##`` 行
    原样并入所在块（或首个日期节之前的前置区），保证重组时逐字保留。
    条目收集与闭环移除共用同一解析口径。
    """
    preamble: List[str] = []
    blocks: List[Tuple[str, List[str]]] = []
    cur_date: Optional[str] = None
    cur_lines: List[str] = []
    for line in text.splitlines():
        m = _TODO_DATE_RE.match(line)
        if m:
            if cur_date is not None:
                blocks.append((cur_date, cur_lines))
            cur_date, cur_lines = m.group(1), []
        elif cur_date is None:
            preamble.append(line)
        else:
            cur_lines.append(line)
    if cur_date is not None:
        blocks.append((cur_date, cur_lines))
    return preamble, blocks


def render_todo_entries(entries: List[Dict[str, str]]) -> str:
    """把闭环判定条目渲染为 ID 标注清单（注入 self-review prompt 用）。"""
    if not entries:
        return "（近3日窗口内无既有条目）"
    lines: List[str] = []
    last_date: Optional[str] = None
    last_section: Optional[str] = None
    for e in entries:
        if e["date"] != last_date:
            lines.append(f"## {e['date']}")
            last_date, last_section = e["date"], None
        if e["section"] != last_section:
            lines.append(f"### {e['section']}")
            last_section = e["section"]
        lines.append(f"- [{e['id']}] {e['text']}")
    return "\n".join(lines)


class SelfReviewScheduler:
    """每日自省调度器：调度判定 + 数据聚合 + todo.md 产物 + 自动提交。

    由 admin_monitor 巡检循环每轮调用 ``check_and_run()``；``agent_runner``
    提供 ``run_self_review``（None 时只判定、不执行并把失败记告警）。
    """

    def __init__(self, config: dict, project_root, logger, state_machine,
                 agent_runner=None, store=None):
        from .config import ConfigLoader
        self.config = config
        self.project_root = Path(project_root)
        self.logger = logger
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        # admin store（记失败告警）；None 时用默认路径构造
        if store is not None:
            self.store = store
        else:
            from .admin_store import AdminStore
            self.store = AdminStore(self.project_root, logger)
        self._sr_cfg = None  # 每次 check_and_run 时经 ConfigLoader 重读（热更新生效）

    # ── 调度判定（design D1） ──────────────────────────────────

    def check_and_run(self) -> dict:
        """巡检检查点：enabled && 本地时间 ≥ run_at && 今日未执行 → 触发。

        数据聚合与活动判定窗口 = [last_run_at, now] 增量（2026-09-08 用户
        决策：自然日触发取代 24h 滚动窗口——run_at 是当日触发点，审查范围
        是上次执行以来的增量；成功/失败/占位跳过都写 last_run_date=today，
        当日不再重试，失败次日 run_at 自然重试）。返回结果 dict（触发与否/
        原因/结果）供测试与审计。enabled=false 时全链路零动作（不调度、不
        执行、不写文件）。无 last_run_at（首跑/旧格式状态文件）回退 24h
        窗口；手动触发通道 = 删除状态文件或把 last_run_date 改为昨日。
        """
        from .config import ConfigLoader
        sr = ConfigLoader.get_self_review_config(self.config)
        if not sr["enabled"]:
            return {"triggered": False, "reason": "disabled"}

        now = datetime.now()
        if now < _parse_run_at(sr["run_at"], now.date()):
            return {"triggered": False, "reason": "before_run_at"}

        # 同日防重复：成功/失败/占位跳过都写 last_run_date=today
        if self._load_state().get("last_run_date") == local_today_str():
            return {"triggered": False, "reason": "already_ran_today"}

        # 增量窗口锚点：上次执行时刻；无（首跑/旧格式）回退 24h
        last_run_at = self._load_last_run_at()
        window_start = (last_run_at if last_run_at is not None
                        else now - timedelta(hours=24))

        # 触发：成功/失败都写 last_run_date=today（失败当日不重试，次日
        # run_at 自然重试）
        return self._execute_review(local_today_str(), now, sr, window_start)

    def _execute_review(self, today: str, now: datetime, sr: dict,
                        window_start: datetime) -> dict:
        """执行一次自省：聚合窗口数据 → 发起 run → 追加 todo.md → 提交。"""
        if self.agent_runner is None:
            self._record_failure_alert(
                f"{today}: agent_runner 不可用（未装配），无法执行自省")
            self._save_state(today)
            return {"triggered": True, "ok": False, "reason": "no_runner", "date": today}

        # 零活动防护：窗口 [last_run_at, now] 内无任何 SPEC run（review-
        # 自省 run 已排除）→ 不唤醒 admin，仅在 todo.md 记一句占位并跳过
        # （2026-09-05 用户决策，窗口 2026-09-08 起为增量窗口）。
        if collect_runs_stats(self.project_root, window_start)["total"] == 0:
            return self._skip_review(today)

        daily_summary = self.collect_daily_summary(window_start)
        # 闭环判定条目（read_todo=true 时收集窗口内既有条目并 ID 标注注入）
        cleanup_entries: List[Dict[str, str]] = []
        todo_md = None
        todo_entries = None
        if sr.get("read_todo"):
            todo_md = self._read_todo()
            cleanup_entries = self._collect_recent_entries(today)
            todo_entries = render_todo_entries(cleanup_entries)

        try:
            result = self.agent_runner.run_self_review(
                today, daily_summary, todo_md, todo_entries)
        except Exception as e:
            self._record_failure_alert(f"{today}: run_self_review 异常: {e}")
            self._save_state(today)
            return {"triggered": True, "ok": False, "reason": f"exception: {e}",
                    "date": today}

        if not result.success:
            self._record_failure_alert(
                f"{today}: 自省 run 失败（run_id={result.run_id}）: {result.error}")
            self._save_state(today)
            return {"triggered": True, "ok": False, "reason": "run_failed",
                    "date": today, "run_id": result.run_id}

        try:
            written = self._apply_todo_update(today, result, cleanup_entries)
        except Exception as e:
            self._record_failure_alert(f"{today}: todo.md 追加失败: {e}")
            self._save_state(today)
            return {"triggered": True, "ok": False, "reason": f"append_error: {e}",
                    "date": today}

        committed = self._commit_todo(today)
        self._save_state(today)
        self.logger.info(
            "self_review",
            f"每日自省完成 {today}（todo.md 已追加：{written}，"
            f"commit: {'ok' if committed else 'skipped/failed'}）",
        )
        return {"triggered": True, "ok": True, "date": today,
                "todo_written": str(written), "committed": committed}

    # ── 零活动防护（2026-09-05 用户决策） ─────────────────────

    def _skip_review(self, today: str) -> dict:
        """窗口零 SPEC 活动跳过：不发起 run（不唤醒 admin），仅在 todo.md
        记一句占位，照常提交 + 写状态文件（当日不再重试）。

        占位写为日期节下的裸 bullet（无小节）——_collect_recent_entries 只
        收小节下条目，故不进闭环判定清单、也不参与闭环移除，作为「当天执行
        过调度但无可回顾内容」的痕迹保留。当日节已存在（状态文件丢失重跑）
        时不重复追加。占位写入失败仅记 WARNING，不影响跳过语义。
        """
        todo = self.project_root / ".fenix" / "todo.md"
        try:
            existing = ""
            if todo.is_file():
                existing = todo.read_text(encoding="utf-8", errors="replace")
            if not re.search(rf"(?m)^## {re.escape(today)}\s*$", existing):
                block = f"## {today}\n\n- 自上次自省以来无 SPEC 活动，跳过自省。\n"
                if existing.strip():
                    todo.write_text(
                        existing.rstrip("\n") + "\n\n" + block, encoding="utf-8")
                else:
                    todo.parent.mkdir(parents=True, exist_ok=True)
                    todo.write_text(block, encoding="utf-8")
        except OSError as e:
            self.logger.warning(
                "self_review", f"{today}: 零活动占位写入 todo.md 失败: {e}")
        self._commit_todo(today)
        self._save_state(today)
        self.logger.info(
            "self_review",
            f"{today}: 自上次自省以来无 SPEC 活动（0 run），跳过自省（未唤醒 admin）")
        return {"triggered": True, "ok": True, "date": today,
                "skipped": True, "reason": "no_spec_activity"}

    # ── 四源数据摘要（spec 场景锁定数据源清单） ───────────────

    def collect_daily_summary(self, window_start: datetime) -> str:
        """聚合窗口数据摘要：STATE 终态 / runs 统计 / admin 告警与处置 /
        日志 ERROR / 近 3 日 git 提交五源。

        窗口 = [window_start, now]（调度器传上次执行时刻，增量窗口）。输出
        markdown 文本块，作为自省 prompt 的「数据摘要」注入（与人工复盘同
        源）。任一源读取失败降级为空段（不阻断自省）。
        """
        lines = [
            "# 数据摘要",
            f"窗口: {window_start:%Y-%m-%d %H:%M} ~ "
            f"{datetime.now():%Y-%m-%d %H:%M}（本地时间，自上次自省以来）",
            "",
        ]

        # 1. STATE 终态分布
        lines.append("## 1. STATE 终态分布")
        dist = self._collect_state_distribution()
        if dist:
            for status in sorted(dist):
                lines.append(f"- {status}: {dist[status]}")
        else:
            lines.append("- （无 spec 记录）")
        lines.append("")

        # 2. runs 统计
        lines.append("## 2. runs 统计（窗口内）")
        stats = collect_runs_stats(self.project_root, window_start)
        lines.append(f"- 总 run 数: {stats['total']}")
        lines.append(f"- 成功: {stats['succeeded']}")
        lines.append(f"- 失败: {stats['failed']}")
        lines.append(f"- 秒挂: {stats['instant_hang']}")
        lines.append(f"- 超时: {stats['timeout']}")
        lines.append(f"- 丢弃/空: {stats['dropped']}")
        lines.append(f"- 在跑/无终态: {stats['running']}")
        lines.append("")

        # 3. admin 告警与处置记录
        lines.append("## 3. admin 告警与处置记录（窗口内）")
        lines.extend(self._collect_admin_summary(window_start))
        lines.append("")

        # 4. 日志 ERROR 聚合
        lines.append("## 4. 日志 ERROR 聚合（窗口内）")
        err = collect_log_errors(self.project_root, window_start)
        lines.append(f"- ERROR 总数: {err['error_count']}")
        if err["samples"]:
            lines.append("- 最近样本:")
            for s in err["samples"]:
                lines.append(f"  - {s}")
        else:
            lines.append("- （窗口内无 ERROR）")
        lines.append("")

        # 5. 近 3 日 git 提交（闭环判定硬证据：问题是否已有对应修复落地）
        lines.append("## 5. 近 3 日 git 提交")
        lines.extend(self._collect_recent_commits())
        lines.append("")

        return "\n".join(lines)

    def _collect_state_distribution(self) -> Dict[str, int]:
        dist: Dict[str, int] = {}
        try:
            specs = self.state_machine.read_all() or {}
        except Exception:
            return dist
        if not isinstance(specs, dict):
            return dist
        for entry in specs.values():
            status = (entry.get("status") or "unknown") if isinstance(entry, dict) else "unknown"
            dist[status] = dist.get(status, 0) + 1
        return dist

    def _collect_admin_summary(self, window_start: datetime) -> List[str]:
        try:
            records = self.store.read_all()
        except Exception:
            return ["- （admin store 读取失败）"]
        window_records = [
            r for r in records
            if _in_window(_iso_to_local_dt(r.get("created")), window_start)
        ]
        signals = [r for r in window_records if r.get("kind") == "signal"]
        escalations = [r for r in window_records if r.get("kind") == "escalation"]
        dispositions = [r for r in window_records if r.get("kind") == "disposition"]
        unhandled = [r for r in escalations if not r.get("handled")]
        lines = [
            f"- 信号: {len(signals)} 条",
            f"- 升级告警: {len(escalations)} 条（未处理 {len(unhandled)} 条）",
            f"- 处置记录: {len(dispositions)} 条",
        ]
        # 未处理升级告警明细（最高价值的待办证据）
        for u in unhandled[:5]:
            lines.append(
                f"  - 未处理升级 [{u.get('signal_type')}] spec={u.get('spec')}: "
                f"{str(u.get('description') or '')[:160]}"
            )
        if not window_records:
            return ["- （窗口内无 admin 记录）"]
        return lines

    def _collect_recent_commits(self, days: int = CLEANUP_WINDOW_DAYS,
                                limit: int = 100) -> List[str]:
        """近 N 日 git 提交清单（hash + 本地时间 + 标题），闭环判定的硬证据源。

        非 git 目录 / 无提交 / 命令失败均降级为占位行，不阻断自省。
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.project_root), "log",
                 f"--since={since}", "-n", str(limit),
                 "--pretty=%h %ad %s", "--date=format-local:%m-%d %H:%M"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return [f"- （git log 读取失败）"]
        if proc.returncode != 0:
            return [f"- （git log 读取失败）"]
        commits = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
        if not commits:
            return [f"- （近 {days} 日无提交）"]
        return [f"- {c}" for c in commits]

    def _read_todo(self) -> Optional[str]:
        """读取 .fenix/todo.md 全文（read_todo=true 时注入 prompt 用）。"""
        todo = self.project_root / ".fenix" / "todo.md"
        if not todo.is_file():
            return None
        try:
            return todo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    # ── 闭环移除（自省启动时处理前 CLEANUP_WINDOW_DAYS 天记录） ──

    def _collect_recent_entries(self, today: str) -> List[Dict[str, str]]:
        """收集运行日前 CLEANUP_WINDOW_DAYS 天窗口内的既有条目（闭环判定对象）。

        返回 ``[{id, date, section, text}]``：id 形如 ``2026-09-04#失误#2``
        （日期#小节#节内序号），text 为条目原文快照（去除 ``- `` 前缀后
        strip）——移除时按 (日期, 小节, 原文) 三元组匹配，防运行期间文件被
        并发编辑（如 dashboard /api/todo）后按序号错删。「（当日无）」占位
        与窗口外日期节不收集。
        """
        todo = self.project_root / ".fenix" / "todo.md"
        if not todo.is_file():
            return []
        try:
            text = todo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        base = datetime.strptime(today, "%Y-%m-%d").date()
        window = {
            (base - timedelta(days=k)).isoformat()
            for k in range(1, CLEANUP_WINDOW_DAYS + 1)
        }
        _preamble, blocks = parse_todo_blocks(text)
        entries: List[Dict[str, str]] = []
        for date, body in blocks:
            if date not in window:
                continue
            section: Optional[str] = None
            counters: Dict[str, int] = {}
            for line in body:
                m = _TODO_SECTION_RE.match(line)
                if m:
                    section = m.group(1)
                    continue
                if section is None or not line.startswith("- "):
                    continue
                item = line[2:].strip()
                if not item or item == _EMPTY_MARKER:
                    continue
                counters[section] = counters.get(section, 0) + 1
                entries.append({
                    "id": f"{date}#{section}#{counters[section]}",
                    "date": date, "section": section, "text": item,
                })
        return entries

    def _remove_resolved(self, entries: List[Dict[str, str]],
                         resolved: list) -> List[Dict[str, str]]:
        """按 resolved 清单从 todo.md 移除已闭环条目；返回实际移除清单。

        只处理注入清单（entries）内的 id；命中条件为 (日期, 小节, 原文快照)
        逐字一致——不一致（运行期间文件被并发编辑）跳过该条并记 WARNING，
        绝不按序号盲删。条目移除后空小节剔除，小节全空的日期节整体剔除；
        未涉及的日期节逐字保留（涉及块按机器格式规范化重渲染）。
        """
        todo = self.project_root / ".fenix" / "todo.md"
        if not todo.is_file() or not resolved or not entries:
            return []
        by_id = {e["id"]: e for e in entries}
        targets: Dict[str, str] = {}  # id -> reason（畸形/未知 id 忽略）
        for item in resolved:
            if (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and item["id"] in by_id):
                targets[item["id"]] = str(item.get("reason") or "")
        if not targets:
            return []
        try:
            text = todo.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.logger.warning("self_review", f"闭环移除读取 todo.md 失败: {e}")
            return []
        match_key = {
            (e["date"], e["section"], e["text"]): eid
            for eid, e in by_id.items() if eid in targets
        }
        target_dates = {by_id[eid]["date"] for eid in targets}
        preamble, blocks = parse_todo_blocks(text)
        matched_ids: set = set()
        new_blocks: List[Tuple[str, List[str]]] = []
        for date, body in blocks:
            if date not in target_dates:
                new_blocks.append((date, body))  # 未涉及 → 逐字保留
                continue
            sections: List[Dict[str, Any]] = []
            cur: Optional[Dict[str, Any]] = None
            head: List[str] = []
            tail: List[str] = []
            pending: Optional[List[str]] = None  # 未决 bullet 块（原文行，含续行）
            skip_block = False  # 上一 bullet 块被移除 → 其缩进续行一并吞掉
            for line in body:
                is_new_bullet = line.startswith("- ")
                is_cont = line[:1] in (" ", "\t")
                if skip_block:
                    if is_cont:
                        continue  # 已删块的续行随块消失
                    skip_block = False
                if pending is not None:
                    if is_cont:
                        pending.append(line)  # 多行条目的 证据/建议 续行随块
                        continue
                    cur["bullets"].append(pending)  # 非续行 → 块落盘
                    pending = None
                m = _TODO_SECTION_RE.match(line)
                if m:
                    cur = {"title": m.group(1), "bullets": []}
                    sections.append(cur)
                    continue
                if cur is None:
                    head.append(line)  # 日期节标题下的游离内容（备注等）保留
                    continue
                if is_new_bullet:
                    item = line[2:].strip()
                    eid = match_key.get((date, cur["title"], item))
                    if eid and eid not in matched_ids:
                        matched_ids.add(eid)
                        skip_block = True  # 命中快照 → 整块移除
                        continue
                    pending = [line]
                    continue
                if line.strip():
                    tail.append(line)
                # 空行不落 tail：重组按 2026-09-08 格式（条目间空行）结构化补
            if pending is not None and cur is not None:
                cur["bullets"].append(pending)
            kept = [s for s in sections if s["bullets"]]
            if not kept and not any(l.strip() for l in head + tail):
                continue  # 小节全空且无游离内容 → 日期节整体剔除
            out: List[str] = []
            out.extend(head)
            for s in kept:
                out.append(f"### {s['title']}")
                for blk in s["bullets"]:
                    out.extend(blk)  # 保留块逐字回写（含续行）
                    out.append("")  # 条目间空行（2026-09-08 格式）
            out.extend(tail)
            new_blocks.append((date, out))
        skipped = [eid for eid in sorted(targets) if eid not in matched_ids]
        if skipped:
            self.logger.warning(
                "self_review",
                f"闭环移除跳过 {len(skipped)} 条（快照不匹配或日期节已不存在）: "
                + ", ".join(skipped))
        if not matched_ids:
            return []  # 无实际移除 → 文件不动
        parts: List[str] = []
        if any(l.strip() for l in preamble):
            parts.append("\n".join(preamble).strip("\n"))
        for date, body in new_blocks:
            parts.append(f"## {date}\n\n" + "\n".join(body).strip("\n"))
        try:
            todo.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        except OSError as e:
            self.logger.warning("self_review", f"闭环移除写回 todo.md 失败: {e}")
            return []
        return [{"id": eid, "reason": targets[eid]} for eid in sorted(matched_ids)]

    def _apply_todo_update(self, today: str, result,
                           entries: List[Dict[str, str]]) -> Path:
        """闭环移除 + 结构化追加（同一次执行，同一 commit 内留痕）。"""
        resolved = getattr(result, "resolved", None) or []
        removed = self._remove_resolved(entries, resolved)
        if removed:
            detail = "；".join(f"{r['id']}（{r['reason'][:60]}）" for r in removed)
            self.logger.info(
                "self_review", f"闭环移除 {len(removed)} 条: {detail}")
        return self._append_todo(today, result)

    # ── todo.md 结构化追加（spec「todo.md 结构化追加」） ────────

    @staticmethod
    def _render_entry_lines(item) -> List[str]:
        """单条目 → 渲染行列表（2026-09-08 用户改版：短标题 + 嵌套明细）。

        dict 条目（结构化契约 {title, impact, evidence, analysis?, suggestion}）
        渲染为「- **标题**」+ 嵌套「  - 影响：…／  - 证据：…／  - 调查评估：…／
  - 建议：…」bullet 块；title 缺省省略标题行（历史输出兼容），空字段
        跳行；str 条目先经 dict-repr 抢救（_rescue_structured_entry，旧解析
        层产物兼容），未命中则按旧行内格式单行透传。空渲染返回 []。条目间
        空行由 _append_todo 负责（同小节块间 join 空行）。
        """
        if isinstance(item, str):
            item = _rescue_structured_entry(item) or item
        if isinstance(item, dict):
            lines: List[str] = []
            title = str(item.get("title") or "").strip()
            if title:
                lines.append(f"- **{title}**")
            for label, key in (("影响", "impact"), ("证据", "evidence"),
                               ("调查评估", "analysis"), ("建议", "suggestion")):
                val = str(item.get(key) or "").strip()
                if val:
                    lines.append(f"  - {label}：{val}")
            return lines
        item_str = str(item).strip()
        return [f"- {item_str}"] if item_str else []

    def _append_todo(self, date_str: str, result) -> Path:
        """把自省结果按固定结构追加到 .fenix/todo.md（首次写入创建文件）。

        结构：``## YYYY-MM-DD`` 分节 + 「浪费」「失误」「可改进」三个小节。
        结构化条目每条渲染为「短标题 + 嵌套明细」bullet 块（2026-09-08 用户
        改版），同小节条目块之间空行（markdown 松列表）；字符串条目单行透传
        （历史格式兼容）。历史分节不变（追加在尾部）。返回 todo.md 路径。
        """
        todo = self.project_root / ".fenix" / "todo.md"
        sections: List[str] = []
        for title, items in (
            ("浪费", result.waste or []),
            ("失误", result.mistakes or []),
            ("可改进", result.improvements or []),
        ):
            sections.append(f"### {title}")
            blocks = []
            for item in (items or []):
                entry_lines = self._render_entry_lines(item)
                if entry_lines:
                    blocks.append("\n".join(entry_lines))
            if blocks:
                sections.append("\n\n".join(blocks))
            else:
                sections.append("- （当日无）")
            sections.append("")
        block = "\n".join(sections).rstrip()
        content = f"## {date_str}\n\n{block}\n"

        existing = ""
        if todo.is_file():
            try:
                existing = todo.read_text(encoding="utf-8", errors="replace")
            except OSError:
                existing = ""
        if existing and existing.strip():
            content = "\n\n" + content
        todo.parent.mkdir(parents=True, exist_ok=True)
        todo.write_text(existing + content, encoding="utf-8")
        return todo

    def _commit_todo(self, date_str: str) -> bool:
        """git add（仅 todo.md）→ commit → push；push 失败降级 WARNING。

        D4：worktree 从 main 分出，未提交文件对后续 agent 不可见——「新 agent
        据此提出 spec」要求条目入库。提交仅含 todo.md 路径。push 失败降级
        WARNING（与归档自动提交同策略，不影响下次追加）。返回是否完成 commit。
        """
        git = ["git", "-C", str(self.project_root)]
        try:
            add = subprocess.run(
                git + ["add", "--", ".fenix/todo.md"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            self.logger.warning("self_review", f"git add todo.md 失败: {e}")
            return False
        if add.returncode != 0:
            self.logger.warning(
                "self_review", f"git add todo.md 失败: {add.stderr.strip()[:200]}")
            return False
        try:
            commit = subprocess.run(
                git + ["commit", "-m", f"[fenix] daily self-review: {date_str}"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            self.logger.warning("self_review", f"git commit todo.md 失败: {e}")
            return False
        if commit.returncode != 0:
            # 无变更可提交（内容重复等）不视为失败
            self.logger.info(
                "self_review",
                f"git commit todo.md 未产生提交: {commit.stderr.strip()[:200]}",
            )
            return False
        try:
            push = subprocess.run(
                git + ["push"],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            self.logger.warning("self_review", f"git push 失败（降级 WARNING）: {e}")
            return True
        if push.returncode != 0:
            self.logger.warning(
                "self_review",
                f"git push 失败（降级 WARNING，commit 已产生）: {push.stderr.strip()[:200]}",
            )
        return True

    # ── 状态文件（.fenix/self_review_state.json） ──────────────

    def _state_path(self) -> Path:
        return self.project_root / ".fenix" / STATE_FILE

    def _load_state(self) -> dict:
        path = self._state_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load_last_run_at(self) -> Optional[datetime]:
        """状态文件 last_run_at → 本地 naive datetime；缺失/畸形返回 None。

        仅作增量窗口锚点使用（2026-09-08 起）；同日防重复由 last_run_date
        承担。旧格式状态文件（仅 last_run_date）返回 None → 回退 24h 窗口。
        """
        raw = self._load_state().get("last_run_at")
        if not isinstance(raw, str) or not raw:
            return None
        return _iso_to_local_dt(raw)

    def _save_state(self, date_str: str) -> None:
        """记录执行日（last_run_date，同日防重复判定基准）与执行时刻。

        last_run_at 保留写入：下次执行的增量窗口锚点（数据聚合与活动判定
        从该时刻起算）；调度防重复只看 last_run_date。
        """
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "last_run_date": date_str,
                    "last_run_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().astimezone().isoformat(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.logger.error("self_review", f"状态文件写入失败: {e}")

    # ── 失败处理（design D5：静默降级为告警，24h 内不重试） ───────

    def _record_failure_alert(self, message: str) -> None:
        """自省失败记 admin WARNING 告警（含原因）。

        warning 级不进人工待处理队列（与 token_budget 告警同策略：写入即标记
        handled，仅留历史记录），避免自省失败刷屏人工队列。
        """
        try:
            from .admin_store import ESCALATION
            rec = self.store.append({
                "kind": ESCALATION,
                "signal_type": "self_review_failed",
                "spec": None,
                "severity": "warning",
                "description": f"每日自省失败：{message}",
                "evidence": f"date={local_today_str()}",
                "recommended_action": (
                    "次日 run_at 后自然重试；如需当日立即重试，删除 "
                    ".fenix/self_review_state.json 后等下一轮巡检"
                ),
            })
            try:
                self.store.mark_handled(rec["id"])
            except Exception:
                pass
        except Exception as e:
            self.logger.error("self_review", f"失败告警落盘失败: {e}")
        self.logger.warning("self_review", f"每日自省失败：{message}")
