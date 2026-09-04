"""self_review.py — 每日定时自省（add-daily-self-review spec）。

每晚本地时间 ``admin.self_review.run_at``（缺省 02:00）后，由 Administrator
通道执行一次当日工作回顾：聚合当日数据摘要（STATE 终态 / runs 统计 /
admin 告警与处置 / 日志 ERROR 四源）→ 发起 ``self-review`` run → 追加写入
项目 ``.fenix/todo.md`` → 单文件 commit + push。

调度判定挂在 admin_monitor 巡检循环（design D1，不新增线程/定时器）：
每轮巡检检查「enabled && 本地时间 ≥ run_at && 状态文件 last_run_date <
今天」→ 触发。天然获得补跑（启动后首轮巡检即补）与防重复（状态文件）。
失败当日不重试（也写 last_run_date=今天，防风暴），次日自然重试。

硬约束（spec「禁止自动创建 SPEC」）：本模块及自省链路 MUST NOT 创建
openspec/changes 条目、注册 STATE.md 条目或派发任何 agent——产出仅供用户
阅读判定。token 归账到 cost-observability 独立类目（.fenix/cost/），
不写 STATE（避免混入 spec 状态表）。
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import SELF_REVIEW_DEFAULT_RUN_AT

# 状态文件（.fenix/self_review_state.json，与 admin_alerts.json 同目录同风格）
STATE_FILE = "self_review_state.json"

# review 输出实例文件前缀：每 run 独立 .fenix/self_review_out-<run_id>.json，
# 与 admin_disposition-<run_id>.json 同模式（并行实例互不覆盖）。
REVIEW_OUT_PREFIX = "self_review_out-"

# 秒挂（instant-hang）签名：错误文本命中即归类为秒挂（claude 启动即死）。
_INSTANT_FAIL_PATTERNS = (
    "No conversation found with session ID",
    "unrecognized_model",
)

# run_id 内嵌开始时间戳（int(time.time())）的匹配模式（与 data.get_runs 同口径）。
_RUN_TS_RE = re.compile(r"-(\d{9,10})(?:-a\d+)?$")


def local_today_str() -> str:
    """本地自然日字符串 YYYY-MM-DD（调度与状态文件均按本地时间）。"""
    return datetime.now().date().isoformat()


def _iso_to_local_date(iso_str: Optional[str]) -> Optional[str]:
    """ISO 时间戳（含 Z 后缀）→ 本地自然日字符串；解析失败返回 None。"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone().date().isoformat()


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


def collect_runs_stats(project_root, date_str: str) -> Dict[str, int]:
    """当日 runs 统计（成功/失败/秒挂/超时/丢弃/在跑），排除 self-review run 自身。

    按 run_id 内嵌开始时间戳判定归属自然日（缺失回退文件 mtime），与
    get_runs 的解析口径一致。产物文件只读，不触发任何写操作。
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
        if datetime.fromtimestamp(ts).date().isoformat() != date_str:
            continue
        category, _detail = _classify_run(run_id, _read_run_tail(p, 3))
        counts["total"] += 1
        counts[category] += 1
    return counts


def collect_log_errors(project_root, date_str: str, limit: int = 20) -> Dict[str, Any]:
    """当日 fenixd.log ERROR 聚合：总数 + 最近 limit 条样本（含时间戳/组件/消息）。"""
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
                    if _iso_to_local_date(entry.get("timestamp")) != date_str:
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
        """巡检检查点：enabled && 本地时间 ≥ run_at && 今日未执行 → 触发自省。

        返回结果 dict（触发与否/原因/结果）供测试与审计。enabled=false 时
        全链路零动作（不调度、不执行、不写文件）。
        """
        from .config import ConfigLoader
        sr = ConfigLoader.get_self_review_config(self.config)
        if not sr["enabled"]:
            return {"triggered": False, "reason": "disabled"}

        today = local_today_str()
        if self._load_state().get("last_run_date") == today:
            return {"triggered": False, "reason": "already_run"}

        now = datetime.now()
        if now < _parse_run_at(sr["run_at"], now.date()):
            return {"triggered": False, "reason": "before_run_at"}

        # 触发：成功/失败都写 last_run_date=今天（失败当日不重试，次日自然重试）
        return self._execute_review(today, sr)

    def _execute_review(self, today: str, sr: dict) -> dict:
        """执行一次自省：聚合数据 → 发起 run → 追加 todo.md → 提交。"""
        if self.agent_runner is None:
            self._record_failure_alert(
                f"{today}: agent_runner 不可用（未装配），无法执行自省")
            self._save_state(today)
            return {"triggered": True, "ok": False, "reason": "no_runner", "date": today}

        daily_summary = self.collect_daily_summary(today)
        todo_md = self._read_todo() if sr.get("read_todo") else None

        try:
            result = self.agent_runner.run_self_review(today, daily_summary, todo_md)
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
            written = self._append_todo(today, result)
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

    # ── 四源数据摘要（spec 场景锁定数据源清单） ───────────────

    def collect_daily_summary(self, date_str: str) -> str:
        """聚合当日数据摘要：STATE 终态 / runs 统计 / admin 告警与处置 / 日志 ERROR。

        输出 markdown 文本块，作为自省 prompt 的「当日数据摘要」注入（与人工
        复盘同源）。任一源读取失败降级为空段（不阻断自省）。
        """
        lines = ["# 当日数据摘要", f"日期: {date_str}", ""]

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
        lines.append("## 2. runs 统计（当日）")
        stats = collect_runs_stats(self.project_root, date_str)
        lines.append(f"- 总 run 数: {stats['total']}")
        lines.append(f"- 成功: {stats['succeeded']}")
        lines.append(f"- 失败: {stats['failed']}")
        lines.append(f"- 秒挂: {stats['instant_hang']}")
        lines.append(f"- 超时: {stats['timeout']}")
        lines.append(f"- 丢弃/空: {stats['dropped']}")
        lines.append(f"- 在跑/无终态: {stats['running']}")
        lines.append("")

        # 3. admin 告警与处置记录
        lines.append("## 3. admin 告警与处置记录（当日）")
        lines.extend(self._collect_admin_summary(date_str))
        lines.append("")

        # 4. 日志 ERROR 聚合
        lines.append("## 4. 日志 ERROR 聚合（当日）")
        err = collect_log_errors(self.project_root, date_str)
        lines.append(f"- ERROR 总数: {err['error_count']}")
        if err["samples"]:
            lines.append("- 最近样本:")
            for s in err["samples"]:
                lines.append(f"  - {s}")
        else:
            lines.append("- （当日无 ERROR）")
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

    def _collect_admin_summary(self, date_str: str) -> List[str]:
        try:
            records = self.store.read_all()
        except Exception:
            return ["- （admin store 读取失败）"]
        today_records = [
            r for r in records
            if _iso_to_local_date(r.get("created")) == date_str
        ]
        signals = [r for r in today_records if r.get("kind") == "signal"]
        escalations = [r for r in today_records if r.get("kind") == "escalation"]
        dispositions = [r for r in today_records if r.get("kind") == "disposition"]
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
        if not today_records:
            return ["- （当日无 admin 记录）"]
        return lines

    def _read_todo(self) -> Optional[str]:
        """读取 .fenix/todo.md 全文（read_todo=true 时注入 prompt 用）。"""
        todo = self.project_root / ".fenix" / "todo.md"
        if not todo.is_file():
            return None
        try:
            return todo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    # ── todo.md 结构化追加（spec「todo.md 结构化追加」） ────────

    def _append_todo(self, date_str: str, result) -> Path:
        """把自省结果按固定结构追加到 .fenix/todo.md（首次写入创建文件）。

        结构：``## YYYY-MM-DD`` 分节 + 「浪费」「失误」「可改进」三个小节，
        每条含证据与建议（Agent 已在条目文本中嵌入）。历史分节不变（追加
        在尾部）。返回 todo.md 路径。
        """
        todo = self.project_root / ".fenix" / "todo.md"
        sections: List[str] = []
        for title, items in (
            ("浪费", result.waste or []),
            ("失误", result.mistakes or []),
            ("可改进", result.improvements or []),
        ):
            sections.append(f"### {title}")
            if items:
                for item in items:
                    item_str = str(item).strip()
                    if item_str:
                        sections.append(f"- {item_str}")
            if len(sections) == 0 or sections[-1] == f"### {title}":
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
        if not isinstance(data, dict) or not isinstance(data.get("last_run_date"), str):
            return {}
        return data

    def _save_state(self, date_str: str) -> None:
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "last_run_date": date_str,
                    "updated_at": datetime.now().astimezone().isoformat(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.logger.error("self_review", f"状态文件写入失败: {e}")

    # ── 失败处理（design D5：静默降级为告警，当日不重试） ───────

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
                    "次日将自然重试；如需立即执行可检查 admin.self_review 配置后重启 daemon"
                ),
            })
            try:
                self.store.mark_handled(rec["id"])
            except Exception:
                pass
        except Exception as e:
            self.logger.error("self_review", f"失败告警落盘失败: {e}")
        self.logger.warning("self_review", f"每日自省失败：{message}")
