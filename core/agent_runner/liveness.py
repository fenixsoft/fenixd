"""liveness.py — LivenessSupervisor：attempt 存活探测/活性快照/LLM 判活/超时监督/优雅等待（refactor-core-packages 阶段 3）。

状态同迁（design D3 规则 1）：_extension_baselines 随组件迁移；门面经 property 委托保持原路径可用。

"""

from pathlib import Path
from core.agent_runner.run_files import append_run_error, append_run_line
from datetime import datetime, timezone
import json
import subprocess
import time


# 优雅退出时对每个在跑 agent 的 SIGTERM 缓冲窗口（秒）。daemon 收到关闭信号后对所有
# 在跑 agent 发 SIGTERM，等此窗口让其收尾（关会话/flush 输出）；窗口结束仍未退出的
# 用 SIGKILL 兜底。取 claude 收尾所需量级，模块级常量便于测试注入短值。
# 见 spec agent-shutdown-interrupt：总关闭时长需压到 ≪ supervisor 60s SIGKILL 窗口。
AGENT_TERMINATE_GRACE_SECONDS = 10

# ── attempt 存活探测 / 超时活性监督（improve-run-lifecycle-governance）──────
# 进程扫描不可用时，run 流文件 mtime 在该窗口内视为 attempt 仍在活动（D4 回退判据）。
LIVE_ATTEMPT_STREAM_WINDOW_SECONDS = 120
# 超时监督默认值（D3）。单次续期 extension_seconds、次数上限 max_extensions、
# 总墙钟上限 absolute_max_seconds（命中即无条件终止，封闭续期的成本风险）、
# 活性判定窗口 judge_window（秒）。
SUPERVISION_DEFAULTS = {
    "enabled": True,
    "extension_seconds": 1800,
    "max_extensions": 2,
    "absolute_max_seconds": 7200,
    "judge_window": 600,
}
# 活性判定 LLM 单轮调用的超时秒数（D2）：judge 卡死不能拖住监督循环
JUDGE_TIMEOUT_SECONDS = 120
# 活性快照 last_output 片段截断字符数（D1）
LIVENESS_SNIPPET_CHARS = 400

# ── 启动终态补写扫描（fix-daemon-lifecycle-races D1）──────────────────────
# run jsonl 的终态事件类型（对齐 runner.py _run_was_interrupted 与
# admin_monitor.py _run_has_interrupted_marker 的判定口径）：
# result=自然完成, interrupted=daemon shutdown, error=进程异常终止,
# cancelled=人工取消。任一类型出现即视为 run 已终结。
RUN_TERMINAL_EVENT_TYPES = frozenset({
    "result", "interrupted", "error", "cancelled",
})


def _file_has_terminal_event(run_file: Path) -> bool:
    """读 run jsonl 逐行判定尾部是否已有终态事件（运行期/启动清扫共享口径）。

    终态口径 = ``RUN_TERMINAL_EVENT_TYPES``（result/interrupted/error/cancelled），
    两种清扫 MUST 复用本 helper，不得各自实现解析逻辑（runtime-run-sweep
    「与启动清扫口径一致」Requirement）。损坏 JSON 行跳过不阻断；
    文件不可读（OSError）视为无终态事件。
    """
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (isinstance(entry, dict)
                        and entry.get("type") in RUN_TERMINAL_EVENT_TYPES):
                    return True
    except OSError:
        return False
    return False


def sweep_runs_without_terminal_state(runs_dir: Path) -> list:
    """启动终态补写扫描：扫描 runs_dir 顶层 *.jsonl，对尾部无终态事件的
    run 文件追加 ``{"type": "interrupted", "reason": "startup terminal-state
    sweep"}`` 终态事件。

    仅在 daemon 启动期调用一次（AgentRunner 初始化后、任何派发前）；
    孤儿 claude 进程存活不阻塞补写——run 文件由 daemon 侧转写，孤儿
    进程不会再产生新事件。

    Returns: 被补写的文件列表 ``[(run_file_name_stem, Path), ...]``。
    """
    if not runs_dir.is_dir():
        return []
    patched = []
    try:
        files = list(runs_dir.glob("*.jsonl"))
    except OSError:
        return []
    for run_file in files:
        if _file_has_terminal_event(run_file):
            continue
        # 无终态事件——追加 interrupted 终态（O_APPEND 单行原子追加）
        try:
            append_run_line(run_file, {
                "type": "interrupted",
                "reason": "startup terminal-state sweep",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            patched.append((run_file.stem, run_file))
        except OSError:
            pass
    return patched


class LivenessSupervisor:
    """LivenessSupervisor组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 超时监督续期基准注册表（improve-run-lifecycle-governance 3.2 / D3）：
        # {spec_name: {"baseline": epoch, "run_id": str, "extension": int,
        #              "deadline": epoch}}。agent_runner 每次超时续期时把 baseline
        # 顺延到续期时刻，pm_engine 的 stuck 检测读取该基准而非 STATE.md 的固定
        # updated 起点——否则刚被续期的长任务下一轮就被误判 stuck。
        # 无显式回收：get_extension_baseline 按流文件新鲜度自清理（run 结束后
        # 流停止增长即失效）。
        self._extension_baselines: Dict[str, dict] = {}

    def has_live_attempt(self, spec_name: str) -> bool:
        """探测某 SPEC 是否仍有存活的 attempt 子进程（恢复一致性 D4 接口）。

        判定顺序：
          1. pgrep 进程表：cmdline 含该 spec 的 worktree 目录字面量
             （``worktrees/{impl,verify}-<spec>-<ts>``）→ 存活；
          2. 进程扫描不可用/未命中时，回退 run 流文件新鲜度：
             该 spec 任一 run jsonl 的 mtime < LIVE_ATTEMPT_STREAM_WINDOW_SECONDS
             视为仍在活动（resume 孤儿进程通常持续写流）。

        供 pm_engine auto-recovery 与 event_bus 孤儿 ready 白名单调用——
        有存活子进程时 MUST NOT 重置状态/清空跟踪字段。
        """
        try:
            # 经门面回引（design D3 规则 3）：测试在门面实例上替换
            # runner._pgrep_live_attempt 的补丁缝保持有效。
            if self._pm._pgrep_live_attempt(spec_name):
                return True
        except Exception as e:  # 扫描器异常一律走流新鲜度回退，不向上抛
            self._pm.logger.debug(
                "agent_runner",
                f"has_live_attempt process scan failed for '{spec_name}': {e}",
            )
        return self._stream_recent(spec_name, LIVE_ATTEMPT_STREAM_WINDOW_SECONDS)


    def _pgrep_live_attempt(self, spec_name: str) -> bool:
        """pgrep 匹配 cmdline 含该 spec worktree 目录字面量的进程。

        pgrep 不可用（缺失/超时/OSError）时返回 False，由流新鲜度回退判定。
        """
        for prefix in ("impl", "verify"):
            pattern = f"worktrees/{prefix}-{spec_name}-"
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.SubprocessError, OSError):
                return False
            if res.returncode == 0 and res.stdout.strip():
                return True
        return False


    def _stream_recent(self, spec_name: str, seconds: int) -> bool:
        """该 spec 最新 run 流文件的 mtime 是否在 seconds 内（不可用 → False）。"""
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        cutoff = time.time() - seconds
        for prefix in ("impl", "verify"):
            try:
                paths = list(runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"))
            except OSError:
                return False
            for p in paths:
                try:
                    if p.stat().st_mtime >= cutoff:
                        return True
                except OSError:
                    continue
        return False


    def note_run_extension(self, spec_name: str, run_id: str,
                           extension_index: int, new_deadline: float) -> None:
        """超时续期时登记该 spec 的新 stuck 检测基准（续期时刻）。

        pm_engine.check_blockers 的 stuck 计算通过 ``get_extension_baseline``
        读取该基准，使 stuck 起点随续期同步顺延——否则刚续期的长任务立刻被
        误判 stuck 并触发 auto-recovery（等于绕过整个监督机制）。
        """
        self._extension_baselines[spec_name] = {
            "baseline": time.time(),
            "run_id": run_id,
            "extension": int(extension_index),
            "deadline": float(new_deadline),
        }
        self._pm.logger.info(
            "agent_runner",
            f"Extension #{extension_index} noted for '{spec_name}' (run {run_id}) — "
            f"stuck baseline reset, new deadline "
            f"{datetime.fromtimestamp(new_deadline, timezone.utc).isoformat()}",
        )


    def get_extension_baseline(self, spec_name: str) -> float | None:
        """返回该 spec 的续期基准（epoch 秒）；无条目或 run 已结束返回 None。

        新鲜度自清理：关联 run 流文件已停止增长（超过 LIVE_ATTEMPT_STREAM_
        WINDOW_SECONDS）说明 run 已结束——基准随即失效并移除，调用方回退到
        既有 updated 起点（行为与无注册表时一致）。
        """
        entry = self._extension_baselines.get(spec_name)
        if not entry:
            return None
        run_id = entry.get("run_id") or ""
        run_file = self._pm.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
        try:
            mtime = run_file.stat().st_mtime
        except OSError:
            self._extension_baselines.pop(spec_name, None)
            return None
        if time.time() - mtime > LIVE_ATTEMPT_STREAM_WINDOW_SECONDS:
            self._extension_baselines.pop(spec_name, None)
            return None
        return float(entry.get("baseline") or 0.0)


    def _liveness_snapshot(self, run_file: Path, window_seconds: float,
                           now: float | None = None) -> dict:
        """run jsonl 活性快照（D1）：窗口内事件数、tool_use 数、最后事件距今。

        判定要素（tasks 4.1）：
        - ``events_in_window``：带可解析时间戳且落在窗口内的事件数；
        - ``tool_use`` / ``tool_counts``：assistant 消息中的工具调用计数；
        - ``last_event_age``：最后一个事件距今秒数（事件无时间戳时回退文件 mtime）；
        - ``last_output``：最后的 assistant 文本 / result 文本片段（截断）。

        无时间戳的行（stderr 兜底行等）按「文件 mtime 在窗口内即计入」的口径
        处理，保证纯 stderr 流不会被误判为死流。
        """
        now = time.time() if now is None else now
        snapshot = {
            "run_file": str(run_file),
            "window_seconds": float(window_seconds),
            "total_events": 0,
            "events_in_window": 0,
            "tool_use": 0,
            "tool_counts": {},
            "last_event_age": None,
            "last_output": "",
            "stream_available": True,
        }
        cutoff = now - max(0.0, window_seconds)
        try:
            with run_file.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    snapshot["total_events"] += 1
                    ts = self._pm._parse_event_timestamp(entry)
                    if ts is None:
                        # 无时间戳：只有文件本身仍在窗口内才计入
                        try:
                            if run_file.stat().st_mtime >= cutoff:
                                snapshot["events_in_window"] += 1
                        except OSError:
                            pass
                    else:
                        if ts >= cutoff:
                            snapshot["events_in_window"] += 1
                        if (snapshot["last_event_age"] is None
                                or (now - ts) < snapshot["last_event_age"]):
                            snapshot["last_event_age"] = max(0.0, now - ts)
                    if entry.get("type") == "assistant":
                        msg = entry.get("message") or {}
                        for block in (msg.get("content") or []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                snapshot["tool_use"] += 1
                                name = str(block.get("name") or "unknown")
                                snapshot["tool_counts"][name] = (
                                    snapshot["tool_counts"].get(name, 0) + 1)
                            elif block.get("type") == "text":
                                text = str(block.get("text") or "").strip()
                                if text:
                                    snapshot["last_output"] = text
                    elif entry.get("type") == "result":
                        text = str(entry.get("result") or "").strip()
                        if text:
                            snapshot["last_output"] = text
        except OSError:
            snapshot["stream_available"] = False
            return snapshot

        if snapshot["last_event_age"] is None:
            # 全部事件无时间戳：以文件 mtime 作为最后活动时刻
            try:
                snapshot["last_event_age"] = max(0.0, now - run_file.stat().st_mtime)
            except OSError:
                snapshot["last_event_age"] = None
        snapshot["last_output"] = snapshot["last_output"][:LIVENESS_SNIPPET_CHARS]
        return snapshot


    @staticmethod
    def _summarize_snapshot(snapshot: dict) -> str:
        """活性快照的证据摘要（供终止证据与日志，短小可读）。"""
        tools = snapshot.get("tool_counts") or {}
        tool_str = ",".join(f"{k}x{v}" for k, v in sorted(tools.items())) or "none"
        age = snapshot.get("last_event_age")
        return (
            f"events_in_window={snapshot.get('events_in_window')}, "
            f"total_events={snapshot.get('total_events')}, "
            f"tool_use={snapshot.get('tool_use')} ({tool_str}), "
            f"last_event_age={'n/a' if age is None else f'{age:.0f}s'}, "
            f"last_output={(snapshot.get('last_output') or '')[:160]}"
        )


    def _judge_liveness(self, snapshot: dict, spec_name: str | None,
                        run_id: str) -> dict:
        """轻量 LLM 活性判定（D2）：单轮调用，输出 {verdict, evidence}。

        模型路由复用 Administrator 的兜底通道（DEFAULT_GATEWAY_MODEL），不落
        .fenix/runs 正式 run 文件——判定结论写回被监督 run 的 jsonl 与 daemon 日志。
        任何解析失败 / 异常都按 ``stagnant`` 处理，evidence 以
        ``liveness judge unavailable`` 开头（tasks 4.2 要求的可辨识证据）。

        per-agent-timeout-override 3.3：judge 子进程超时经
        ``agents.timeout_overrides.supervision-judge`` 配置（缺省回退 120s 常量），
        该值不参与 absolute_max 派生。
        """
        timeout = self._supervision_judge_timeout()
        prompt = (
            "你是长时运行 agent 的活性监督判定器。根据以下 run 流统计快照，判断该"
            " agent 是在真实推进任务，还是已陷入停滞（空转、卡死、重复循环、无输出）。\n\n"
            f"SPEC: {spec_name or 'unknown'}\nRUN: {run_id}\n\n快照：\n"
            f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
            "只输出一个 JSON 对象，不要其它文字：\n"
            '{"verdict": "advancing|stagnant", "evidence": "简短判定依据（<=200字）"}\n'
            "判定口径：窗口内有新事件且工具调用在推进/产出新内容 → advancing；"
            "零事件、同参数工具调用反复失败、长时间无新输出 → stagnant。"
        )
        try:
            cmd = ["claude", "-p", prompt, "--output-format", "json"]
            model = self._pm._get_admin_model()
            if model:
                cmd += ["--model", model]
            res = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=str(self._pm.project_root),
            )
            text = res.stdout or ""
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and payload.get("result"):
                    text = str(payload["result"])
            except json.JSONDecodeError:
                pass
            verdict = self._parse_verdict_json(text)
            if verdict:
                return {
                    "verdict": verdict["verdict"],
                    "evidence": str(verdict.get("evidence") or "")[:400],
                }
            return {
                "verdict": "stagnant",
                "evidence": (f"liveness judge unavailable: unparseable output "
                             f"(rc={res.returncode}) {(res.stderr or '')[:160]}"),
            }
        except Exception as e:
            return {"verdict": "stagnant", "evidence": f"liveness judge unavailable: {e}"}


    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        """从模型输出中提取 ``{"verdict": ...}`` JSON 对象；找不到返回 None。"""
        if not text:
            return None
        start = text.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
                        if (isinstance(obj, dict)
                                and obj.get("verdict") in ("advancing", "stagnant")):
                            return obj
                        break
            start = text.find("{", start + 1)
        return None


    def _supervision_judge_timeout(self) -> float:
        """活性判定 judge 子进程超时（per-agent-timeout-override 3.3）。

        读取 ``agents.timeout_overrides.supervision-judge``（缺省回退 120 秒常量），
        该值不参与 absolute_max 派生。
        """
        from core.config import ConfigLoader
        return ConfigLoader.judge_timeout_seconds(self._pm.config)

    def _supervision_settings(self) -> dict:
        """超时监督配置（D3）：canonical ``agents.timeout_supervision``，回退旧顶层键。

        缺省取 SUPERVISION_DEFAULTS（enabled=true）；旧版顶层 ``timeout_supervision``
        （fix-stuck-threshold-unify 引入，enabled=false）作为回退开关仍然生效。
        """
        cfg = dict(SUPERVISION_DEFAULTS)
        sup = self._pm._get_config("agents.timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = self._pm._get_config("timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = {}
        for key, default in cfg.items():
            value = sup.get(key)
            if value is None:
                continue
            if isinstance(default, bool):
                cfg[key] = bool(value)
                continue
            try:
                cfg[key] = type(default)(value)
            except (TypeError, ValueError):
                self._pm.logger.warning(
                    "agent_runner",
                    f"Invalid timeout_supervision.{key}={value!r} — keeping default "
                    f"{default}",
                )
        return cfg


    def _supervision_deadline_action(self, run_file: Path, spec_name: str | None,
                                     run_id: str, started_at: float,
                                     extensions_used: int,
                                     judge=None,
                                     agent_type: str | None = None) -> dict:
        """deadline 到点后的监督决策（D3）：续期 or 终止，封闭矩阵。

        判定顺序（先硬上限后活性）：
          1. supervision 未启用 → 纯墙钟终止（现状行为）；
          2. 总墙钟 ≥ absolute_max_seconds（不低于 run_timeout + 续期总额，
             保证续期预算完整可用）→ 无条件终止；
          3. 已用满 max_extensions → 终止；
          4. judge_window 内零事件 → 跳过 LLM、直接判停滞终止；
          5. LLM 判定 advancing → 续期 extension_seconds；
          6. LLM 判定 stagnant（含 judge 不可用）→ 终止并保留证据。

        Returns: {"action": "extend"|"kill", "reason", "extension_seconds"?,
                  "extension_index"?, "evidence", "settings"}
        """
        sup = self._supervision_settings()
        evidence = ""
        if not sup["enabled"]:
            return {
                "action": "kill",
                "reason": "run timeout reached (supervision disabled)",
                "evidence": evidence,
                "settings": sup,
            }
        # per-agent-timeout-override 3.2：supervision 的 extension 总额与 absolute_max
        # 护栏按该 agent type 的生效超时派生（覆盖值参与），stuck 阈值派生保持全局默认
        # 值语义（见 effective_stuck_threshold_seconds，不随覆盖变化）。
        run_timeout = float(self._pm._effective_run_timeout(agent_type))
        max_extensions = max(0, int(sup["max_extensions"]))
        extension_seconds = max(1.0, float(sup["extension_seconds"]))
        # absolute_max 是总墙钟上限；配置偏小时抬到 run_timeout + 续期总额，
        # 否则续期预算会被总上限截断（语义矛盾）。
        floor_absolute_max = run_timeout + max_extensions * extension_seconds
        configured_abs_max = float(sup["absolute_max_seconds"])
        absolute_max = max(configured_abs_max, floor_absolute_max)
        if configured_abs_max < floor_absolute_max:
            # per-agent-timeout-override 3.2：生效超时（覆盖后）抬高 absolute_max 兜底时
            # ERROR 留痕（守护配置告警），每次 deadline 判定至多几次（续期轮次有界）。
            self._pm.logger.error(
                "agent_runner",
                f"supervision absolute_max_seconds({int(configured_abs_max)}s) 低于 "
                f"生效超时 {int(run_timeout)}s + 续期总额 {int(max_extensions)}×"
                f"{int(extension_seconds)}s = {int(floor_absolute_max)}s，"
                f"按 {int(floor_absolute_max)}s 兜底生效（agent_type={agent_type or 'default'}）",
            )
        now = time.time()
        if now - started_at >= absolute_max:
            return {
                "action": "kill",
                "reason": (f"absolute_max_seconds cap reached ({int(absolute_max)}s, "
                           f"extensions_used={extensions_used})"),
                "evidence": evidence,
                "settings": sup,
            }
        if extensions_used >= max_extensions:
            return {
                "action": "kill",
                "reason": (f"extension budget exhausted "
                           f"({extensions_used}/{max_extensions})"),
                "evidence": evidence,
                "settings": sup,
            }
        window = max(30.0, float(sup["judge_window"]))
        snapshot = self._liveness_snapshot(run_file, window)
        evidence = self._summarize_snapshot(snapshot)
        if (not snapshot.get("stream_available")
                or snapshot.get("last_event_age") is None
                or snapshot["last_event_age"] > window
                or snapshot.get("events_in_window", 0) == 0):
            return {
                "action": "kill",
                "reason": "stagnant: zero run events within judge window",
                "evidence": evidence,
                "settings": sup,
            }
        verdict = (judge or self._judge_liveness)(snapshot, spec_name, run_id)
        if verdict.get("verdict") == "advancing":
            return {
                "action": "extend",
                "extension_seconds": extension_seconds,
                "extension_index": extensions_used + 1,
                "reason": "judged advancing",
                "evidence": str(verdict.get("evidence") or "")[:400],
                "settings": sup,
            }
        return {
            "action": "kill",
            "reason": "judged stagnant",
            "evidence": str(verdict.get("evidence") or "")[:400],
            "settings": sup,
        }


    def wait_for_running_agents(self, timeout: int = AGENT_TERMINATE_GRACE_SECONDS):
        """优雅退出时终止全部在跑 agent（terminate 流程），不再逐 agent 等待完成。

        fix-graceful-shutdown-agents：原实现每 agent 最多等待 timeout（300s）串行叠加，
        叠加 supervisor 固定 60s SIGKILL 窗口必触发 kill -9，丢失在跑 agent 的 run 结果。

        新流程（D5 并行终止）：
          1. 对所有在跑 agent 立即发 SIGTERM（不等待完成）；
          2. 同步向各自 run 文件追加 interrupted 标记（标记 daemon 侧已知中断，
             与"疑似崩溃"区分，且不影响已 finalize 的完成 run）；
          3. 统一等待 ≤ grace 缓冲窗口（默认 10s），让 claude 收尾；
          4. 窗口结束仍未退出的 agent 用 SIGKILL 兜底。

        总终止时长恒 ≲ grace，不随 agent 数量线性增长，确保 daemon 在 supervisor 60s
        窗口内退出。

        Args:
            timeout: 缓冲窗口秒数（子类/测试可覆写短值避免真实等待）。
        """
        grace = max(0, timeout)
        running = list(self._pm._running_agents.items())
        if not running:
            return

        # 第一步：统一 SIGTERM，并行通知所有在跑 agent 收尾
        for name, proc in running:
            try:
                proc.terminate()  # SIGTERM：让 claude 关会话/flush 输出
                self._pm.logger.info("agent_runner", f"Sent SIGTERM to running agent: {name}")
            except ProcessLookupError:
                # 进程已退出（竞态），标记清理后跳过
                self._pm._running_agents.pop(name, None)
            except Exception as e:  # pragma: no cover - 防御性
                self._pm.logger.warning("agent_runner", f"SIGTERM failed for agent {name}: {e}")

        # 第二步：同步写入 interrupted 标记。running 快照只含未完成 agent（完成的已
        # finalize 并移除），不会误标已完成 run。对每个被终止 agent 都写标记——无论其
        # 是否已在 SIGTERM 后快速退出（design D2：标记由 daemon 侧同步写入，不依赖
        # agent 优雅退出，保证"已知中断"证据完整）。读线程以 append 模式单行写入，
        # O_APPEND 原子追加不破坏 JSONL 结构。
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        for name, proc in running:
            run_file = runs_dir / f"{name}.jsonl"
            try:
                append_run_line(run_file, {
                    "type": "interrupted",
                    "reason": "daemon shutdown",
                    "by": "agent_runner",
                })
            except Exception as e:  # pragma: no cover - run 文件写入失败不影响退出
                self._pm.logger.warning(
                    "agent_runner", f"Failed to write interrupted marker for {name}: {e}"
                )

        # 第三步 + 第四步：统一缓冲窗口，窗口内未退出者 SIGKILL 兜底
        if grace > 0:
            deadline = time.time() + grace
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                alive = [n for n, p in self._pm._running_agents.items() if p.poll() is None]
                if not alive:
                    break
                time.sleep(min(0.2, remaining))
            # 缓冲窗口结束仍未退出的，强制 SIGKILL（标记已写入，不依赖优雅退出）
            for name, proc in list(self._pm._running_agents.items()):
                if proc.poll() is None:
                    self._pm.logger.warning(
                        "agent_runner", f"Agent did not exit within {grace}s, SIGKILL: {name}"
                    )
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    except Exception as e:  # pragma: no cover - 防御性
                        self._pm.logger.warning("agent_runner", f"SIGKILL failed for {name}: {e}")
        else:
            # grace=0：直接 SIGKILL 兜底
            for name, proc in list(self._pm._running_agents.items()):
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

        # 收割所有子进程，避免僵尸进程
        for name, proc in list(self._pm._running_agents.items()):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            except Exception:  # pragma: no cover - 防御性
                pass
            self._pm._running_agents.pop(name, None)
